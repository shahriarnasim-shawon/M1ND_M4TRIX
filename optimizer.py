import numpy as np
from scipy.optimize import milp, LinearConstraint, Bounds
from typing import List, Dict, Any, Tuple
from schemas import DirectiveInterpretationEntry, HourlyPlanEntry


def solve_energy_schedule(
    hours_data: List[Dict[str, Any]],
    battery_data: Dict[str, Any],
    directives: List[DirectiveInterpretationEntry]
) -> Tuple[List[HourlyPlanEntry], float, float, float]:
    """
    Solves the 24-hour campus energy schedule via SciPy HiGHS MILP in <10ms.
    Variables for each hour h (0..23):
      0: g_h (grid import >= 0)
      1: s_h (solar used >= 0)
      2: c_h (charge >= 0)
      3: d_h (discharge >= 0)
      4: E_h (battery energy after hour h)
      5: u_h in {0,1} (1 if charging, 0 if discharging; prevents simultaneous action)
    """
    N = 24
    demand = np.array([h["demand_kwh"] for h in hours_data], dtype=float)
    solar = np.array([h["solar_kwh"] for h in hours_data], dtype=float)
    tariff = np.array([h["tariff_bdt_per_kwh"]
                      for h in hours_data], dtype=float)

    cap = float(battery_data["capacity_kwh"])
    init_E = float(battery_data["initial_energy_kwh"])
    min_E = float(battery_data["minimum_energy_kwh"])
    max_c = float(battery_data["max_charge_kwh_per_hour"])
    max_d = float(battery_data["max_discharge_kwh_per_hour"])

    # 1. Apply Directives Deterministically
    effective_solar = solar.copy()
    hourly_min_reserve = np.full(N, min_E, dtype=float)
    no_charge_mask = np.zeros(N, dtype=bool)
    no_discharge_mask = np.zeros(N, dtype=bool)
    grid_cap = np.full(N, np.inf, dtype=float)

    for d in directives:
        if not d.applies or not d.structured_adjustment:
            continue
        dtype = d.directive_type
        adj = d.structured_adjustment.model_dump() if hasattr(
            d.structured_adjustment, "model_dump") else d.structured_adjustment
        hours = adj.get("hours", [])

        if dtype == "solar_reduction":
            factor = float(adj.get("factor", 1.0))
            for h in hours:
                if 0 <= h < N:
                    effective_solar[h] = solar[h] * factor
        elif dtype == "minimum_battery_reserve":
            req_min = float(adj.get("minimum_energy_kwh", min_E))
            for h in hours:
                if 0 <= h < N:
                    hourly_min_reserve[h] = max(hourly_min_reserve[h], req_min)
        elif dtype == "no_charge_window":
            for h in hours:
                if 0 <= h < N:
                    no_charge_mask[h] = True
        elif dtype == "no_discharge_window":
            for h in hours:
                if 0 <= h < N:
                    no_discharge_mask[h] = True
        elif dtype == "max_grid_window":
            cap_val = float(adj.get("max_grid_kwh", np.inf))
            for h in hours:
                if 0 <= h < N:
                    grid_cap[h] = min(grid_cap[h], cap_val)

    def idx_g(h): return 6 * h + 0
    def idx_s(h): return 6 * h + 1
    def idx_c(h): return 6 * h + 2
    def idx_d(h): return 6 * h + 3
    def idx_E(h): return 6 * h + 4
    def idx_u(h): return 6 * h + 5

    num_vars = 6 * N

    # Cost objective: sum(tariff[h] * g_h) + tiny epsilon to prevent unnecessary micro-cycles
    c = np.zeros(num_vars)
    for h in range(N):
        c[idx_g(h)] = tariff[h]
        c[idx_c(h)] = 1e-6
        c[idx_d(h)] = 1e-6

    integrality = np.zeros(num_vars)
    for h in range(N):
        integrality[idx_u(h)] = 1  # binary

    lb = np.zeros(num_vars)
    ub = np.zeros(num_vars)
    for h in range(N):
        lb[idx_g(h)] = 0.0
        ub[idx_g(h)] = grid_cap[h]

        lb[idx_s(h)] = 0.0
        ub[idx_s(h)] = effective_solar[h]

        lb[idx_c(h)] = 0.0
        ub[idx_c(h)] = 0.0 if no_charge_mask[h] else max_c

        lb[idx_d(h)] = 0.0
        ub[idx_d(h)] = 0.0 if no_discharge_mask[h] else max_d

        lb[idx_E(h)] = hourly_min_reserve[h]
        ub[idx_E(h)] = cap

        lb[idx_u(h)] = 0.0
        ub[idx_u(h)] = 1.0

    bounds = Bounds(lb, ub)

    A_rows, lhs, rhs = [], [], []
    for h in range(N):
        # Energy balance: g_h + s_h + d_h - c_h = demand_h
        row = np.zeros(num_vars)
        row[idx_g(h)] = 1.0
        row[idx_s(h)] = 1.0
        row[idx_d(h)] = 1.0
        row[idx_c(h)] = -1.0
        A_rows.append(row)
        lhs.append(demand[h])
        rhs.append(demand[h])

        # Battery state transition: E_h - E_{h-1} - c_h + d_h = 0
        row = np.zeros(num_vars)
        row[idx_E(h)] = 1.0
        row[idx_c(h)] = -1.0
        row[idx_d(h)] = 1.0
        if h == 0:
            A_rows.append(row)
            lhs.append(init_E)
            rhs.append(init_E)
        else:
            row[idx_E(h - 1)] = -1.0
            A_rows.append(row)
            lhs.append(0.0)
            rhs.append(0.0)

        # Exclusivity: c_h - max_c * u_h <= 0
        row = np.zeros(num_vars)
        row[idx_c(h)] = 1.0
        row[idx_u(h)] = -max_c
        A_rows.append(row)
        lhs.append(-np.inf)
        rhs.append(0.0)

        # Exclusivity: d_h + max_d * u_h <= max_d
        row = np.zeros(num_vars)
        row[idx_d(h)] = 1.0
        row[idx_u(h)] = max_d
        A_rows.append(row)
        lhs.append(-np.inf)
        rhs.append(max_d)

    # End-of-day neutrality: E_23 = init_E
    row = np.zeros(num_vars)
    row[idx_E(N - 1)] = 1.0
    A_rows.append(row)
    lhs.append(init_E)
    rhs.append(init_E)

    A = np.array(A_rows)
    constraints = LinearConstraint(A, lhs, rhs)

    res = milp(c=c, integrality=integrality,
               bounds=bounds, constraints=constraints)
    if not res.success:
        raise RuntimeError(f"MILP solver failed: {res.status}")

    sol = res.x
    hourly_plan: List[HourlyPlanEntry] = []

    for h in range(N):
        g = float(sol[idx_g(h)])
        s = float(sol[idx_s(h)])
        ch = float(sol[idx_c(h)])
        di = float(sol[idx_d(h)])
        e = float(sol[idx_E(h)])

        if ch > 1e-4:
            action = "charge"
            b_kwh = ch
        elif di > 1e-4:
            action = "discharge"
            b_kwh = di
        else:
            action = "idle"
            b_kwh = 0.0

        hourly_plan.append(
            HourlyPlanEntry(
                hour=h,
                grid_kwh=round(g, 2),
                solar_used_kwh=round(s, 2),
                battery_action=action,
                battery_kwh=round(b_kwh, 2),
                battery_energy_after_kwh=round(e, 2)
            )
        )

    # Recalculate totals directly from plan to eliminate floating discrepancies
    total_grid = sum(entry.grid_kwh for entry in hourly_plan)
    total_cost = sum(entry.grid_kwh *
                     tariff[entry.hour] for entry in hourly_plan)
    peak_grid = max(entry.grid_kwh for entry in hourly_plan)

    return hourly_plan, round(total_grid, 2), round(total_cost, 2), round(peak_grid, 2)
