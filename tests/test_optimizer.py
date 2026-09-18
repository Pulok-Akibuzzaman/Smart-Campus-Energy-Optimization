"""
tests/test_optimizer.py - Comprehensive Unit & Constraint Validation Tests
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.optimizer import solve_energy_schedule

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")
if not os.path.exists(DATA_PATH):
    DATA_PATH = "data/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

def validate_plan(hours_data, battery_data, directives, result):
    """
    Independently verifies all constraints per Section 09 & 11 of the Problem Statement.
    """
    T = 24
    plan = result["hourly_plan"]
    assert len(plan) == T, "Must have exactly 24 hours"
    
    cap = float(battery_data["capacity_kwh"])
    init_e = float(battery_data["initial_energy_kwh"])
    base_min = float(battery_data["minimum_energy_kwh"])
    max_charge = float(battery_data["max_charge_kwh_per_hour"])
    max_discharge = float(battery_data["max_discharge_kwh_per_hour"])
    
    effective_solar = [float(h["solar_kwh"]) for h in hours_data]
    min_reserve = [base_min for _ in range(T)]
    no_charge = set()
    no_discharge = set()
    grid_caps = {}
    
    for d in directives:
        if not d.get("applies", False): continue
        dtype = d.get("directive_type")
        adj = d.get("structured_adjustment") or {}
        for h in adj.get("hours", []):
            if dtype == "solar_reduction":
                effective_solar[h] *= float(adj.get("factor", 1.0))
            elif dtype == "minimum_battery_reserve":
                min_reserve[h] = max(min_reserve[h], float(adj.get("minimum_energy_kwh", base_min)))
            elif dtype == "no_charge_window":
                no_charge.add(h)
            elif dtype == "no_discharge_window":
                no_discharge.add(h)
            elif dtype == "max_grid_window":
                grid_caps[h] = min(grid_caps.get(h, 1e9), float(adj.get("max_grid_kwh", 1e9)))
                
    curr_e = init_e
    calc_grid_sum = 0.0
    calc_cost_sum = 0.0
    calc_peak_grid = 0.0
    
    for h in range(T):
        p = plan[h]
        assert p["hour"] == h, f"Hour index mismatch at {h}"
        g = p["grid_kwh"]
        s = p["solar_used_kwh"]
        act = p["battery_action"]
        b_kwh = p["battery_kwh"]
        e_after = p["battery_energy_after_kwh"]
        demand = float(hours_data[h]["demand_kwh"])
        tariff = float(hours_data[h]["tariff_bdt_per_kwh"])
        
        # 1. Non-negative
        assert g >= -1e-5 and s >= -1e-5 and b_kwh >= -1e-5, f"Negative value at hour {h}"
        # 2. Solar usage <= effective solar
        assert s <= effective_solar[h] + 1e-4, f"Overuse solar at hour {h}: {s} > {effective_solar[h]}"
        # 3. Action check
        assert act in ["charge", "discharge", "idle"], f"Invalid action {act} at hour {h}"
        if act == "idle":
            assert b_kwh == 0, f"Idle but non-zero battery_kwh at hour {h}"
            c_val, d_val = 0.0, 0.0
        elif act == "charge":
            assert b_kwh <= max_charge + 1e-4, f"Charge rate exceeded at hour {h}"
            assert h not in no_charge, f"Charged during no_charge window at hour {h}"
            c_val, d_val = b_kwh, 0.0
        else: # discharge
            assert b_kwh <= max_discharge + 1e-4, f"Discharge rate exceeded at hour {h}"
            assert h not in no_discharge, f"Discharged during no_discharge window at hour {h}"
            c_val, d_val = 0.0, b_kwh
            
        # 4. Energy balance: grid + solar + discharge = demand + charge
        balance_diff = abs((g + s + d_val) - (demand + c_val))
        assert balance_diff <= 0.01, f"Energy balance violated at hour {h}: diff={balance_diff}"
        
        # 5. Grid cap
        if h in grid_caps:
            assert g <= grid_caps[h] + 0.01, f"Grid cap violated at hour {h}: {g} > {grid_caps[h]}"
            
        # 6. Battery transition & bounds
        expected_e = curr_e + c_val - d_val
        assert abs(e_after - expected_e) <= 0.01, f"Battery transition mismatch at hour {h}: {e_after} vs {expected_e}"
        assert min_reserve[h] - 0.01 <= e_after <= cap + 0.01, f"Battery reserve violated at hour {h}: {e_after} not in [{min_reserve[h]}, {cap}]"
        curr_e = e_after
        
        calc_grid_sum += g
        calc_cost_sum += g * tariff
        if g > calc_peak_grid: calc_peak_grid = g
        
    # 7. End of day neutrality
    assert abs(curr_e - init_e) <= 0.01, f"Neutrality violated: final {curr_e} != initial {init_e}"
    
    # 8. Recalculated totals
    assert abs(result["total_grid_kwh"] - calc_grid_sum) <= 0.01, "total_grid_kwh mismatch"
    assert abs(result["total_cost_bdt"] - calc_cost_sum) <= 0.01, "total_cost_bdt mismatch"
    assert abs(result["peak_grid_kwh"] - calc_peak_grid) <= 0.01, "peak_grid_kwh mismatch"
    return True

def test_all_cases_optimizer():
    with open(DATA_PATH) as f:
        data = json.load(f)
    for case in data["cases"]:
        cid = case["id"]
        inp = case["input"]
        exp = case["expected_output"]
        res = solve_energy_schedule(inp["hours"], inp["battery"], exp["directive_interpretation"])
        validate_plan(inp["hours"], inp["battery"], exp["directive_interpretation"], res)
        cost_diff = abs(res["total_cost_bdt"] - exp["total_cost_bdt"])
        assert cost_diff <= 0.05, f"{cid} cost diff too large: {cost_diff}"
        print(f"Verified all physical and directive constraints for {cid}: PERFECT!")

if __name__ == "__main__":
    test_all_cases_optimizer()
