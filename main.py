from fastapi import FastAPI
from fastapi.responses import JSONResponse
from schemas import OptimizeEnergyRequest, OptimizeEnergyResponse
from llm_interpreter import call_gemini, guardrail_and_validate
from optimizer import solve_energy_schedule

app = FastAPI(
    title="GridWise Optimization API (Gemini 3.1 Flash-Lite)", version="1.0.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
async def optimize_energy(payload: OptimizeEnergyRequest):
    try:
        # Step 1: LLM Interpretation via Gemini 3.1 Flash-Lite
        raw_directives = call_gemini(
            payload.operator_notes,
            payload.battery.model_dump()
        )

        # Step 2: Deterministic Guardrails
        validated_directives = guardrail_and_validate(
            raw_directives,
            payload.operator_notes,
            payload.battery.capacity_kwh
        )

        # Step 3: HiGHS MILP Mathematical Optimization
        plan, total_grid, total_cost, peak_grid = solve_energy_schedule(
            [h.model_dump() for h in payload.hours],
            payload.battery.model_dump(),
            validated_directives
        )

        summary = (
            f"Scheduled 24 hours under {len(payload.operator_notes)} notes using Gemini 3.1 Flash-Lite "
            f"and HiGHS solver. Total grid: {total_grid} kWh, Total cost: {total_cost} BDT."
        )

        return OptimizeEnergyResponse(
            scenario_id=payload.scenario_id,
            directive_interpretation=validated_directives,
            hourly_plan=plan,
            total_grid_kwh=total_grid,
            total_cost_bdt=total_cost,
            peak_grid_kwh=peak_grid,
            plan_summary=summary
        )
    except Exception as e:
        # Controlled 500 error: Do not expose raw internal secrets or stack traces
        return JSONResponse(
            status_code=500,
            content={
                "error": "Optimization engine encountered an unrecoverable condition."}
        )
