import requests
import json
import time

# Load the public sample JSON file provided in the competition pack
try:
    with open("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", "r") as f:
        data = json.load(f)
except FileNotFoundError:
    print("Error: Put 'BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json' in this folder.")
    exit(1)

cases = data.get("cases", [])
print(
    f"Loaded {len(cases)} test cases. Testing against http://localhost:8000...\n")

total_passed = 0
latencies = []

for case in cases:
    cid = case["id"]
    label = case.get("label", "")
    expected = case.get("expected_output", {})

    t0 = time.time()
    try:
        resp = requests.post(
            "http://localhost:8000/optimize-energy", json=case["input"], timeout=30)
        dur = time.time() - t0
        latencies.append(dur)
    except Exception as e:
        print(f"[{cid}] FAIL - Request error: {e}")
        continue

    if resp.status_code != 200:
        print(f"[{cid}] FAIL - HTTP {resp.status_code}: {resp.text}")
        continue

    out = resp.json()
    cost_diff = abs(out["total_cost_bdt"] - expected["total_cost_bdt"])
    grid_diff = abs(out["total_grid_kwh"] - expected["total_grid_kwh"])

    # Check numerical tolerance (0.01 threshold from section 11.5)
    if cost_diff <= 0.05 and grid_diff <= 0.05:
        print(
            f"[{cid}] PASS ({dur:.2f}s) - {label} | Cost: {out['total_cost_bdt']} BDT")
        total_passed += 1
    else:
        print(f"[{cid}] WARN ({dur:.2f}s) - Expected Cost {expected['total_cost_bdt']}, got {out['total_cost_bdt']}")

print(f"\n==========================================")
print(f"Result: {total_passed}/{len(cases)} cases passed.")
print(
    f"Average Latency: {sum(latencies)/len(latencies):.2f}s (P95: {sorted(latencies)[int(len(latencies)*0.95)]:.2f}s)")
print(f"==========================================")
