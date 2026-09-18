"""
run_samples.py - Top-Level Benchmark and Verification Runner
Executes all 10 canonical public sample cases and prints a clean performance summary table.
"""

import os
import sys
import time
import json

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.optimizer import solve_energy_schedule
from src.interpreter import interpret_operator_notes
from tests.test_optimizer import validate_plan

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")
if not os.path.exists(DATA_PATH):
    DATA_PATH = "data/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

def run_benchmark():
    with open(DATA_PATH) as f:
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
