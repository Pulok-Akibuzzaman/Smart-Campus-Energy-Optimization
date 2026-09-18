import json
import pulp

def solve_energy_schedule(hours_data, battery_data, directives):
    prob = pulp.LpProblem("Campus_Energy_Optimization", pulp.LpMinimize)
    T = 24
    
    cap = float(battery_data["capacity_kwh"])
    init_e = float(battery_data["initial_energy_kwh"])
    base_min_e = float(battery_data["minimum_energy_kwh"])
    max_charge = float(battery_data["max_charge_kwh_per_hour"])
    max_discharge = float(battery_data["max_discharge_kwh_per_hour"])
    
    effective_solar = [float(h["solar_kwh"]) for h in hours_data]
    min_reserve = [base_min_e for _ in range(T)]
    no_charge = [False for _ in range(T)]
    no_discharge = [False for _ in range(T)]
    grid_max_cap = [None for _ in range(T)]
    
    for d in directives:
        if not d.get("applies", False):
            continue
        dtype = d.get("directive_type")
        adj = d.get("structured_adjustment") or {}
        hours = adj.get("hours", [])
        
        if dtype == "solar_reduction":
            factor = float(adj.get("factor", 1.0))
            for h in hours:
                if 0 <= h < T:
                    effective_solar[h] = effective_solar[h] * factor
        elif dtype == "minimum_battery_reserve":
            req_min = float(adj.get("minimum_energy_kwh", base_min_e))
            for h in hours:
                if 0 <= h < T:
                    min_reserve[h] = max(min_reserve[h], req_min)
        elif dtype == "no_charge_window":
            for h in hours:
                if 0 <= h < T:
                    no_charge[h] = True
        elif dtype == "no_discharge_window":
            for h in hours:
                if 0 <= h < T:
                    no_discharge[h] = True
        elif dtype == "max_grid_window":
            cap_val = float(adj.get("max_grid_kwh", 1e9))
            for h in hours:
                if 0 <= h < T:
                    if grid_max_cap[h] is None:
                        grid_max_cap[h] = cap_val
                    else:
                        grid_max_cap[h] = min(grid_max_cap[h], cap_val)

    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0) for h in range(T)]
    solar_used = [pulp.LpVariable(f"solar_used_{h}", lowBound=0, upBound=effective_solar[h]) for h in range(T)]
    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=max_charge) for h in range(T)]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=max_discharge) for h in range(T)]
    is_charging = [pulp.LpVariable(f"is_charging_{h}", cat=pulp.LpBinary) for h in range(T)]
    battery_energy = [pulp.LpVariable(f"battery_energy_{h}", lowBound=min_reserve[h], upBound=cap) for h in range(T)]
    peak_g = pulp.LpVariable("peak_grid", lowBound=0)
    
    cost_expr = pulp.lpSum([grid[h] * float(hours_data[h]["tariff_bdt_per_kwh"]) for h in range(T)])
    prob += cost_expr + 1e-6 * peak_g
    
    for h in range(T):
        demand_h = float(hours_data[h]["demand_kwh"])
        prob += grid[h] + solar_used[h] + discharge[h] == demand_h + charge[h], f"EB_{h}"
        prob += charge[h] <= max_charge * is_charging[h], f"CL_{h}"
        prob += discharge[h] <= max_discharge * (1 - is_charging[h]), f"DL_{h}"
        
        if no_charge[h]:
            prob += charge[h] == 0, f"NC_{h}"
        if no_discharge[h]:
            prob += discharge[h] == 0, f"ND_{h}"
        if grid_max_cap[h] is not None:
            prob += grid[h] <= grid_max_cap[h], f"MG_{h}"
        prob += peak_g >= grid[h], f"PG_{h}"
        
        if h == 0:
            prob += battery_energy[0] == init_e + charge[0] - discharge[0], f"BT_0"
        else:
            prob += battery_energy[h] == battery_energy[h-1] + charge[h] - discharge[h], f"BT_{h}"
            
    prob += battery_energy[T-1] == init_e, "Bat_Neutrality"
    
    try:
        solver = pulp.HiGHS(msg=False)
    except Exception:
        solver = pulp.PULP_CBC_CMD(msg=False)
    prob.solve(solver)
    
    if pulp.LpStatus[prob.status] != "Optimal":
        raise ValueError(f"Solver failed: status = {pulp.LpStatus[prob.status]}")
        
    hourly_plan = []
    total_grid_kwh = 0.0
    total_cost_bdt = 0.0
    peak_grid_kwh = 0.0
    
    for h in range(T):
        g_val = round(float(pulp.value(grid[h])), 6)
        s_val = round(float(pulp.value(solar_used[h])), 6)
        c_val = round(float(pulp.value(charge[h])), 6)
        d_val = round(float(pulp.value(discharge[h])), 6)
        e_val = round(float(pulp.value(battery_energy[h])), 6)
        
        if abs(g_val) < 1e-5: g_val = 0.0
        if abs(s_val) < 1e-5: s_val = 0.0
        if abs(c_val) < 1e-5: c_val = 0.0
        if abs(d_val) < 1e-5: d_val = 0.0
        if abs(e_val - round(e_val)) < 1e-5: e_val = float(round(e_val))
        
        if c_val > 1e-4:
            action = "charge"
            bat_kwh = c_val
        elif d_val > 1e-4:
            action = "discharge"
            bat_kwh = d_val
        else:
            action = "idle"
            bat_kwh = 0.0
            
        hourly_plan.append({
            "hour": h,
            "grid_kwh": g_val,
            "solar_used_kwh": s_val,
            "battery_action": action,
            "battery_kwh": bat_kwh,
            "battery_energy_after_kwh": e_val
        })
        total_grid_kwh += g_val
        total_cost_bdt += g_val * float(hours_data[h]["tariff_bdt_per_kwh"])
        if g_val > peak_grid_kwh:
            peak_grid_kwh = g_val
            
    return {
        "hourly_plan": hourly_plan,
        "total_grid_kwh": round(total_grid_kwh, 4),
        "total_cost_bdt": round(total_cost_bdt, 4),
        "peak_grid_kwh": round(peak_grid_kwh, 4)
    }

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

if __name__ == "__main__":
    with open("BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json") as f:
        data = json.load(f)
    for case in data["cases"]:
        cid = case["id"]
        inp = case["input"]
        exp = case["expected_output"]
        res = solve_energy_schedule(inp["hours"], inp["battery"], exp["directive_interpretation"])
        validate_plan(inp["hours"], inp["battery"], exp["directive_interpretation"], res)
        print(f"Verified all physical and directive constraints for {cid}: PERFECT!")
