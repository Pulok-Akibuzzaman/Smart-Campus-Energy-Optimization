"""
run_samples.py - Benchmark and Verification Script
Runs all 10 public sample cases against the GridWise pipeline and validates all metrics.
"""

import time
import json
from optimizer import solve_energy_schedule
from interpreter import interpret_operator_notes
from test_optimizer import validate_plan

def run_benchmark():
    with open("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json") as f:
        data = json.load(f)
        
    cases = data["cases"]
    print(f"\n{'='*75}")
    print(f"{'CASE ID':<12} | {'INTERP':<8} | {'CALC COST':<11} | {'EXP COST':<11} | {'TIME (ms)':<9} | {'STATUS':<6}")
    print(f"{'='*75}")
    
    total_time = 0.0
    passed_count = 0
    
    for case in cases:
        cid = case["id"]
        inp = case["input"]
        exp = case["expected_output"]
        
        t0 = time.perf_counter()
        
        # 1. Interpret
        directives = interpret_operator_notes(inp["operator_notes"], inp["battery"], cid)
        
        # 2. Optimize
        res = solve_energy_schedule(inp["hours"], inp["battery"], directives)
        
        elapsed_ms = (time.perf_counter() - t0) * 1000
        total_time += elapsed_ms
        
        # 3. Validate
        validate_plan(inp["hours"], inp["battery"], directives, res)
        
        cost_diff = abs(res["total_cost_bdt"] - exp["total_cost_bdt"])
        status = "PASS" if cost_diff <= 0.05 else "FAIL"
        if status == "PASS":
            passed_count += 1
            
        print(f"{cid:<12} | {len(directives)} notes  | {res['total_cost_bdt']:<11.2f} | {exp['total_cost_bdt']:<11.2f} | {elapsed_ms:<9.1f} | {status:<6}")
        
    print(f"{'='*75}")
    print(f"Summary: {passed_count}/{len(cases)} passed | Total Time: {total_time:.1f} ms | Avg: {total_time/len(cases):.1f} ms/case")
    print(f"{'='*75}\n")

if __name__ == "__main__":
    run_benchmark()
