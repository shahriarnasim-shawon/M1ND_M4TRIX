# M1ND_M4TR1X — Smart Campus Energy Optimization Engine

## BUP CSE Fest 2026 · Hackathon · Preliminary Round

An automated, low-latency, and mathematically verified energy scheduling API. The service parses unstructured, natural-language campus operator notes into machine-checkable operational directives, validates them through deterministic guardrails, and solves the 24-hour campus energy scheduling problem to global cost optimality using Mixed-Integer Linear Programming (MILP).

---

# 1. System Architecture & Flow

```text
┌─────────────────┐    ┌─────────────────────────┐    ┌──────────────────────┐    ┌────────────────────┐    ┌──────────────┐
│  Request JSON   │ ──>│  Gemini 3.1 Flash-Lite  │ ──>│   Deterministic      │ ──>│  HiGHS MILP Solver │ ──>│ JSON Output  │
│  (Data + Notes) │    │  (Directive Interpreter)│    │  Guardrail Validator │    │   (SciPy milp)     │    │ Plan & Costs │
└─────────────────┘    └─────────────────────────┘    └──────────────────────┘    └────────────────────┘    └──────────────┘
```

## 1.1 LLM Interpreter (gemini-3.1-flash-lite)

- Parses 1–3 natural-language notes into structured directives in exact `note_index` order.
- Standardizes time intervals using start-inclusive, end-exclusive whole-hour indexing (`[start, end)`).
- Translates relative reserves (e.g., "50% capacity") to absolute kWh and calculates usable solar remaining factors.
- Accurately filters out distractors and unrelated campus announcements as `no_op` (`applies = false`, `structured_adjustment = null`).
- Uses `ThinkingLevel.MINIMAL` to eliminate reasoning delays, keeping LLM generation under 1.5 seconds.

## 1.2 Deterministic Guardrails (llm_interpreter.py)

- Untrusted model output is verified against canonical contract rules before entering the optimizer.
- Enforces supported directive enums, unique ascending hour sequences (0..23), bounded factors (`0.0 <= factor <= 1.0`), and capacity-capped reserve levels.
- Never crashes on malformed LLM responses; safely defaults unparseable notes to non-breaking `no_op`.

## 1.3 Mathematical Optimizer (optimizer.py via SciPy HiGHS)

- Formulated as a Mixed-Integer Linear Program (MILP) solved in < 10 ms.
- Strictly satisfies all GridWise physical constraints: hourly demand balance, solar availability/curtailment, battery capacity/reserve bounds, and charge/discharge rate limits.
- Implements binary exclusivity variables (`u_h ∈ {0, 1}`) to guarantee the battery never charges and discharges within the same hour.
- Enforces strict end-of-day battery neutrality: `battery_energy_after_kwh[23] == initial_energy_kwh`.

## 1.4 Exact Re-accounting Validator

- Recalculates `total_grid_kwh`, `total_cost_bdt`, and `peak_grid_kwh` directly from the discrete rounded hourly plan to eliminate floating-point drift against judge replay harnesses.

# 2. Dependencies & Tech Stack

- **Runtime:** Python 3.11+
- **API Framework:** FastAPI & Uvicorn (async HTTP server with threadpool dispatch)
- **Data Validation:** Pydantic v2 (strict JSON schemas)
- **Language Model SDK:** google-genai (Google Gemini API client)
- **Mathematical Solver:** scipy.optimize.milp (HiGHS solver engine)
- **Numerical Computing:** NumPy

# 3. Environment Variables

| Variable Name    | Required | Default                 | Description                                                  |
| ---------------- | -------- | ----------------------- | ------------------------------------------------------------ |
| `GEMINI_API_KEY` | Yes      | None                    | Google Gemini API key used for directive parsing.            |
| `GEMINI_MODEL`   | No       | `gemini-3.1-flash-lite` | Model identifier for natural language interpretation.        |
| `PORT`           | No       | `8000`                  | HTTP service port (automatically mapped in cloud platforms). |

**Security Note:** Never commit `.env` files or hardcode API keys. Keys must only be injected via environment variables at runtime.

# 4. Local Quickstart (Clean Environment Reproduction)

```bash
# 1. Clone the repository
git clone https://github.com/shahriarnasimshawon/<your-repo-name>.git
cd <your-repo-name>

# 2. Create and activate a clean virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configure environment variables (replace with your key)
export GEMINI_API_KEY="your-gemini-api-key-here"

# 5. Start the HTTP API service
uvicorn main:app --host 0.0.0.0 --port 8000
```

# 5. Endpoints & API Verification

## 5.1 Health Check (GET /health)

```bash
curl -i -X GET http://localhost:8000/health
```

Expected Response (HTTP 200 OK):

```json
{
  "status": "ok"
}
```

## 5.2 Optimize Energy (POST /optimize-energy)

```bash
curl -X POST http://localhost:8000/optimize-energy \
     -H "Content-Type: application/json" \
     -d '{
       "scenario_id": "SAMPLE-01",
       "operator_notes": [
         "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
         "The sports office moved next month'\''s registration deadline."
       ],
       "hours": [
         {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
         {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
         {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
         {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
         {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
         {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
         {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
         {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
         {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
         {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
         {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
         {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
         {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
         {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
         {"hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
         {"hour": 15, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
         {"hour": 16, "demand_kwh": 170, "solar_kwh": 45, "tariff_bdt_per_kwh": 18},
         {"hour": 17, "demand_kwh": 185, "solar_kwh": 10, "tariff_bdt_per_kwh": 22},
         {"hour": 18, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 28},
         {"hour": 19, "demand_kwh": 215, "solar_kwh": 0, "tariff_bdt_per_kwh": 30},
         {"hour": 20, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 26},
         {"hour": 21, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
         {"hour": 22, "demand_kwh": 135, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
         {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}
       ],
       "battery": {
         "capacity_kwh": 220,
         "initial_energy_kwh": 110,
         "minimum_energy_kwh": 40,
         "max_charge_kwh_per_hour": 50,
         "max_discharge_kwh_per_hour": 50
       }
     }'
```

**Expected Outcome:** HTTP 200 OK, `total_grid_kwh = 2692.5`, `total_cost_bdt = 38365.0`.

## 5.3 Automated Validation Test

Run the test suite across all 10 canonical public sample cases:

```bash
python validate_all_samples.py
```

**Expected Output:** 10/10 cases passed with exact cost and directive matching.

# 6. Docker Fallback Execution

A pre-built container image (linux/amd64) is available on Docker Hub for judge fallback execution:

```bash
# 1. Pull the image
docker pull shahriarnasimshawon/gridwise:latest

# 2. Run the container binding to 0.0.0.0:8000 with runtime secret injection
docker run -d -p 8000:8000 \
  -e GEMINI_API_KEY="your-gemini-api-key-here" \
  --name gridwise_service \
  shahriarnasimshawon/gridwise:latest

# 3. Verify readiness
curl -s http://localhost:8000/health
# Output: {"status":"ok"}
```

# 7. Known Limitations & Edge-Case Handling

- **Sub-Hour Directives:** The Problem Statement establishes whole-hour intervals (0..23). Directives with fractional minutes round to the nearest encompassing whole-hour window.
- **Upstream LLM Latency & Retries:** If external network jitter occurs during an LLM API call, the client automatically retries once with backoff before falling back to a safe, non-crashing `no_op` response to guarantee uptime.
- **Infeasible Directives:** Organizers guaranteed feasible test cases. If contradictory hard constraints are received, the solver rejects impossible physical states and returns a controlled HTTP 500 error without exposing internal stack traces.
