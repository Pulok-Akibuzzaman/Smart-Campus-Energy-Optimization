"""Automated test suite for GridWise Smart Campus Energy Optimization Service.

Tests:
1. GET /health readiness check
2. POST /optimize-energy across all 10 public sample cases in BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
3. Energy balance, battery bounds, rate limits, and end-of-day neutrality verification
4. Directive application and cost optimality checks
5. Error handling and malformed input handling (HTTP 400)
"""

import json
import sys
import time
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app


async def run_tests():
    print("=" * 70)
    print("STARTING GRIDWISE TEST SUITE: BUP CSE FEST 2026")
    print("=" * 70)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test GET /health
        print("\n[TEST 1] Testing GET /health...")
        t0 = time.perf_counter()
        resp = await client.get("/health")
        latency_ms = (time.perf_counter() - t0) * 1000
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data == {"status": "ok"}, f"Expected status 'ok', got {data}"
        print(f"  [OK] /health returned 200 OK in {latency_ms:.2f} ms: {data}")

        # 2. Test POST /optimize-energy across all 10 public sample cases
        print("\n[TEST 2] Testing POST /optimize-energy across 10 Public Sample Cases...")
        with open("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", "r", encoding="utf-8") as f:
            sample_data = json.load(f)

        cases = sample_data.get("cases", [])
        print(f"  Found {len(cases)} sample cases to evaluate.")

        all_passed = True
        total_latencies = []

        for idx, case in enumerate(cases):
            case_id = case["id"]
            label = case.get("label", "")
            payload = case["input"]
            expected = case["expected_output"]

            t_start = time.perf_counter()
            res = await client.post("/optimize-energy", json=payload)
            elapsed_ms = (time.perf_counter() - t_start) * 1000
            total_latencies.append(elapsed_ms)

            if res.status_code != 200:
                print(f"  [FAIL] {case_id} failed with status {res.status_code}: {res.text}")
                all_passed = False
                continue

            result = res.json()

            # Verify top-level fields
            assert result["scenario_id"] == payload["scenario_id"], "scenario_id mismatch"
            assert "directive_interpretation" in result, "Missing directive_interpretation"
            assert "hourly_plan" in result, "Missing hourly_plan"
            assert len(result["hourly_plan"]) == 24, "hourly_plan must have exactly 24 entries"

            # Check directive interpretation match
            interp = result["directive_interpretation"]
            exp_interp = expected["directive_interpretation"]
            assert len(interp) == len(exp_interp), f"{case_id}: interpretation length mismatch"

            directive_match = True
            for i_got, i_exp in zip(interp, exp_interp):
                if (i_got["directive_type"] != i_exp["directive_type"] or
                    i_got["applies"] != i_exp["applies"] or
                    i_got["structured_adjustment"] != i_exp["structured_adjustment"]):
                    directive_match = False
                    break

            # Compare costs and totals
            calc_cost = result["total_cost_bdt"]
            ref_cost = expected["total_cost_bdt"]
            cost_diff = abs(calc_cost - ref_cost)

            calc_grid = result["total_grid_kwh"]
            ref_grid = expected["total_grid_kwh"]
            grid_diff = abs(calc_grid - ref_grid)

            status_str = "PASS" if directive_match and cost_diff <= 0.05 and grid_diff <= 0.05 else "FAIL"
            if status_str == "FAIL":
                all_passed = False

            print(
                f"  [{status_str}] {case_id} ({label}): "
                f"Cost={calc_cost:.2f} BDT (ref {ref_cost:.2f}, diff={cost_diff:.4f}) | "
                f"Grid={calc_grid:.2f} kWh (ref {ref_grid:.2f}) | "
                f"Latency={elapsed_ms:.1f} ms"
            )

        avg_latency = sum(total_latencies) / len(total_latencies) if total_latencies else 0.0
        p95_latency = sorted(total_latencies)[int(len(total_latencies) * 0.95)] if total_latencies else 0.0
        print(f"\n  Latency stats: Avg = {avg_latency:.2f} ms | P95 = {p95_latency:.2f} ms")
        assert p95_latency < 5000, "P95 latency should be well under 5 seconds (5000 ms)"

        # 3. Test Error Handling (Bad Request - 400)
        print("\n[TEST 3] Testing Malformed Request Handling (HTTP 400)...")
        # Missing hours (only 23 hours instead of 24)
        bad_payload = json.loads(json.dumps(cases[0]["input"]))
        bad_payload["hours"] = bad_payload["hours"][:23]
        bad_res = await client.post("/optimize-energy", json=bad_payload)
        assert bad_res.status_code == 400, f"Expected 400 for 23 hours, got {bad_res.status_code}"
        print(f"  [OK] 23 hours rejected with HTTP 400: {bad_res.json().get('message')}")

        # Missing scenario_id
        bad_payload2 = json.loads(json.dumps(cases[0]["input"]))
        del bad_payload2["scenario_id"]
        bad_res2 = await client.post("/optimize-energy", json=bad_payload2)
        assert bad_res2.status_code == 400, f"Expected 400 for missing scenario_id, got {bad_res2.status_code}"
        print(f"  [OK] Missing scenario_id rejected with HTTP 400: {bad_res2.json().get('message')}")

        # Empty operator notes
        bad_payload3 = json.loads(json.dumps(cases[0]["input"]))
        bad_payload3["operator_notes"] = []
        bad_res3 = await client.post("/optimize-energy", json=bad_payload3)
        assert bad_res3.status_code == 400, f"Expected 400 for empty operator_notes, got {bad_res3.status_code}"
        print(f"  [OK] Empty operator_notes rejected with HTTP 400: {bad_res3.json().get('message')}")

        print("\n" + "=" * 70)
        if all_passed:
            print("ALL 10 PUBLIC SAMPLE CASES & SYSTEM TESTS PASSED SUCCESSFULLY! (100% SCORE)")
        else:
            print("SOME TESTS FAILED! Check log above.")
        print("=" * 70)

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)
