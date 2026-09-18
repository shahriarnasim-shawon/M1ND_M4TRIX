import os
import json
import time
from typing import List, Dict, Any
from google import genai
from google.genai import types
from schemas import DirectiveInterpretationEntry

api_key = os.getenv("GEMINI_API_KEY", "")
client = genai.Client(api_key=api_key)

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

# In-memory cache for repeated calls
NOTE_CACHE = {}

SYSTEM_PROMPT = """You are an expert energy operations parser for the BUP Smart Campus Energy Challenge.
Your task is to interpret human operator notes into a machine-checkable structured directive array.

DIRECTIVE SPECIFICATIONS:
1. "solar_reduction":
   Use when usable solar generation is reduced or impaired.
   structured_adjustment: {"hours": [int...], "factor": float}
   - factor is the usable fraction remaining (e.g. 80% reduction means factor = 0.2; drop to 20% means factor = 0.2).
2. "minimum_battery_reserve":
   Use when a required battery storage reserve must be preserved.
   structured_adjustment: {"hours": [int...], "minimum_energy_kwh": float}
   - If expressed as percentage of battery capacity, compute absolute kWh (e.g. 50% of 200 kWh = 100.0).
3. "no_charge_window":
   Use when battery charging is disabled/isolated.
   structured_adjustment: {"hours": [int...]}
4. "no_discharge_window":
   Use when battery discharging is prohibited.
   structured_adjustment: {"hours": [int...]}
5. "max_grid_window":
   Use when grid import is capped/restricted.
   structured_adjustment: {"hours": [int...], "max_grid_kwh": float}
6. "no_op":
   Use for distractors, irrelevant notices, or operations not affecting today's 24-hour schedule.
   applies: false
   structured_adjustment: null

CANONICAL TIME CONVENTIONS:
- Hours 0 through 23.
- Windows are START-INCLUSIVE and END-EXCLUSIVE:
  - "1 PM to 3 PM" -> [13, 14]
  - "noon until 2 PM" -> [12, 13]
  - "6 PM until 9 PM" -> [18, 19, 20]
  - "11 AM until 1 PM" -> [11, 12]
- Hours must be unique integers in ascending order.
- Applies flag: applies = true for all directives EXCEPT no_op, where applies = false.
- You must return exactly one entry per note in note_index order (0..N-1).
"""


def _execute_gemini_request(user_prompt: str) -> List[Dict[str, Any]]:
    """Helper to call Gemini with minimal thinking to prevent latency spikes."""
    config_args = {
        "system_instruction": SYSTEM_PROMPT,
        "response_mime_type": "application/json",
        "temperature": 0.0,
    }

    # Attempt to set minimal thinking configuration for Gemini 3
    try:
        config_args["thinking_config"] = types.ThinkingConfig(
            thinking_level="MINIMAL")
    except Exception:
        try:
            config_args["thinking_config"] = types.ThinkingConfig(
                thinking_budget=0)
        except Exception:
            pass

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=user_prompt,
        config=types.GenerateContentConfig(**config_args)
    )

    parsed = json.loads(response.text)

    if isinstance(parsed, list):
        return parsed
    elif isinstance(parsed, dict):
        for k in ("directives", "directive_interpretation", "results", "interpretations"):
            if k in parsed and isinstance(parsed[k], list):
                return parsed[k]
        for v in parsed.values():
            if isinstance(v, list):
                return v
    return None


def call_gemini(notes: List[str], battery_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Check cache first
    cache_key = (tuple(notes), battery_info.get("capacity_kwh", 0))
    if cache_key in NOTE_CACHE:
        return NOTE_CACHE[cache_key]

    capacity = battery_info.get("capacity_kwh", 0.0)
    user_prompt = f"Battery Capacity: {capacity} kWh\n\nOperator Notes to interpret:\n"
    for idx, note in enumerate(notes):
        user_prompt += f"Note {idx}: \"{note}\"\n"

    user_prompt += (
        "\nReturn a valid JSON array of objects with fields: "
        "note_index (int), applies (bool), directive_type (string), "
        "structured_adjustment (object or null), explanation (string)."
    )

    # Try up to 2 times (with 0.5s backoff) to protect against transient network jitter
    for attempt in range(2):
        try:
            result = _execute_gemini_request(user_prompt)
            if result and len(result) == len(notes):
                # Only cache successful, non-fallback results
                NOTE_CACHE[cache_key] = result
                return result
        except Exception as e:
            print(f"[Gemini Call Attempt {attempt + 1} Failed]: {e}")
            time.sleep(0.5)

    # Safe fallback if both attempts fail
    return [
        {
            "note_index": i,
            "applies": False,
            "directive_type": "no_op",
            "structured_adjustment": None,
            "explanation": "Safe fallback due to parsing exception."
        }
        for i in range(len(notes))
    ]


def guardrail_and_validate(
    raw_directives: List[Dict[str, Any]],
    notes: List[str],
    battery_capacity: float
) -> List[DirectiveInterpretationEntry]:
    validated: List[DirectiveInterpretationEntry] = []

    for idx in range(len(notes)):
        entry = next(
            (d for d in raw_directives if d.get("note_index") == idx), None)
        if not entry:
            entry = {
                "note_index": idx,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "Missing note index defaulted to no_op."
            }

        dtype = entry.get("directive_type", "no_op")
        adj = entry.get("structured_adjustment")
        applies = entry.get("applies", True)

        # 1. Allowed Types Guardrail
        if dtype not in [
            "solar_reduction", "minimum_battery_reserve", "no_charge_window",
            "no_discharge_window", "max_grid_window", "no_op"
        ]:
            dtype = "no_op"

        # 2. Applies Semantics Guardrail
        if dtype == "no_op":
            applies = False
            adj = None
        else:
            applies = True
            if not isinstance(adj, dict):
                adj = {}

            # 3. Hours Array Normalization (unique, sorted integers 0..23)
            raw_hours = adj.get("hours", [])
            clean_hours = sorted(list({int(h) for h in raw_hours if isinstance(
                h, (int, float, str)) and 0 <= int(h) <= 23}))
            adj["hours"] = clean_hours

            # 4. Numeric Bounds Guardrails
            if dtype == "solar_reduction":
                factor = float(adj.get("factor", 1.0))
                adj["factor"] = round(max(0.0, min(1.0, factor)), 4)
            elif dtype == "minimum_battery_reserve":
                val = float(adj.get("minimum_energy_kwh", 0.0))
                adj["minimum_energy_kwh"] = round(
                    max(0.0, min(battery_capacity, val)), 2)
            elif dtype == "max_grid_window":
                val = float(adj.get("max_grid_kwh", 0.0))
                adj["max_grid_kwh"] = round(max(0.0, val), 2)

        validated.append(
            DirectiveInterpretationEntry(
                note_index=idx,
                applies=applies,
                directive_type=dtype,
                structured_adjustment=adj,
                explanation=str(
                    entry.get("explanation", "Directive interpreted successfully."))
            )
        )

    return validated
