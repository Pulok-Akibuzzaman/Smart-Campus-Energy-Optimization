"""
optimizer.py - 24-Hour Smart Campus Energy Optimization Engine (PuLP / HiGHS)
Compliant with BUP CSE FEST 2026 Hackathon Problem Statement specifications.
"""

from typing import List, Dict, Any
import pulp

def solve_energy_schedule(hours_data: List[Dict[str, Any]], battery_data: Dict[str, Any], directives: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Solves the 24-hour smart campus energy schedule using Mixed-Integer Linear Programming.
    
    Variables:
      - grid[h] >= 0: Grid energy purchased in hour h (kWh)
      - solar_used[h] >= 0: Rooftop solar energy consumed in hour h (kWh)
      - charge[h] >= 0: Battery charging rate in hour h (kWh)
      - discharge[h] >= 0: Battery discharging rate in hour h (kWh)
      - is_charging[h] in {0, 1}: Binary flag ensuring charge & discharge are mutually exclusive
      - battery_energy[h]: State of charge at the end of hour h (kWh)
      
    Constraints:
      1. Energy Balance: grid[h] + solar_used[h] + discharge[h] == demand[h] + charge[h]
      2. Solar Usage: 0 <= solar_used[h] <= effective_solar[h]
      3. Battery Rates: charge[h] <= max_charge * is_charging[h], discharge[h] <= max_discharge * (1 - is_charging[h])
      4. Battery Capacity & Reserve: active_min_reserve[h] <= battery_energy[h] <= capacity_kwh
      5. Battery Transitions:
         - battery_energy[0] == initial_energy_kwh + charge[0] - discharge[0]
         - battery_energy[h] == battery_energy[h-1] + charge[h] - discharge[h] (for h > 0)
      6. End-of-Day Neutrality: battery_energy[23] == initial_energy_kwh
      7. Directive Constraints:
         - no_charge_window: charge[h] == 0 for h in hours
         - no_discharge_window: discharge[h] == 0 for h in hours
         - max_grid_window: grid[h] <= max_grid_kwh for h in hours
         
    Objective:
      Minimize SUM(grid[h] * tariff_bdt_per_kwh[h]) over h = 0..23
    """
    T = 24
    if len(hours_data) != T:
        raise ValueError(f"Expected exactly 24 hours of data, received {len(hours_data)}")
        
    cap = float(battery_data["capacity_kwh"])
    init_e = float(battery_data["initial_energy_kwh"])
    base_min_e = float(battery_data["minimum_energy_kwh"])
    max_charge = float(battery_data["max_charge_kwh_per_hour"])
    max_discharge = float(battery_data["max_discharge_kwh_per_hour"])
    
    # Pre-process hourly baseline and apply directives
    effective_solar = [float(hours_data[h]["solar_kwh"]) for h in range(T)]
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
                    effective_solar[h] *= factor
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

    # Initialize optimization model
    prob = pulp.LpProblem("Smart_Campus_Energy_Optimizer", pulp.LpMinimize)
    
    # Decision variables
    grid = [pulp.LpVariable(f"grid_{h}", lowBound=0) for h in range(T)]
    solar_used = [pulp.LpVariable(f"solar_used_{h}", lowBound=0, upBound=effective_solar[h]) for h in range(T)]
    charge = [pulp.LpVariable(f"charge_{h}", lowBound=0, upBound=max_charge) for h in range(T)]
    discharge = [pulp.LpVariable(f"discharge_{h}", lowBound=0, upBound=max_discharge) for h in range(T)]
    is_charging = [pulp.LpVariable(f"is_charging_{h}", cat=pulp.LpBinary) for h in range(T)]
    battery_energy = [pulp.LpVariable(f"battery_energy_{h}", lowBound=min_reserve[h], upBound=cap) for h in range(T)]
    peak_grid = pulp.LpVariable("peak_grid", lowBound=0)
    
    # Primary objective: Total grid cost (BDT)
    cost_expr = pulp.lpSum([grid[h] * float(hours_data[h]["tariff_bdt_per_kwh"]) for h in range(T)])
    # Add minimal tie-breaker for peak grid
    prob += cost_expr + 1e-6 * peak_grid
    
    # Constraints
    for h in range(T):
        demand_h = float(hours_data[h]["demand_kwh"])
        
        # 1. Energy balance
        prob += grid[h] + solar_used[h] + discharge[h] == demand_h + charge[h], f"EB_{h}"
        
        # 2. Charge/discharge rate bounds with binary mutual exclusivity
        prob += charge[h] <= max_charge * is_charging[h], f"CL_{h}"
        prob += discharge[h] <= max_discharge * (1 - is_charging[h]), f"DL_{h}"
        
        # 3. Directives for charge/discharge
        if no_charge[h]:
            prob += charge[h] == 0, f"NC_{h}"
        if no_discharge[h]:
            prob += discharge[h] == 0, f"ND_{h}"
            
        # 4. Directive for max grid import
        if grid_max_cap[h] is not None:
            prob += grid[h] <= grid_max_cap[h], f"MG_{h}"
            
        # 5. Peak grid tracking
        prob += peak_grid >= grid[h], f"PG_{h}"
        
        # 6. Battery state transition
        if h == 0:
            prob += battery_energy[0] == init_e + charge[0] - discharge[0], "BT_0"
        else:
            prob += battery_energy[h] == battery_energy[h-1] + charge[h] - discharge[h], f"BT_{h}"
            
    # 7. End-of-day battery neutrality
    prob += battery_energy[T-1] == init_e, "Bat_Neutrality"
    
    # Solve with HiGHS or CBC
    try:
        solver = pulp.HiGHS(msg=False)
    except Exception:
        solver = pulp.PULP_CBC_CMD(msg=False)
    prob.solve(solver)
    
    status_str = pulp.LpStatus[prob.status]
    if status_str != "Optimal":
        raise ValueError(f"Solver failed to find optimal schedule: status = {status_str}")
        
    # Extract hourly plan and recalculate metrics
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
        
        # Clean up microscopic floating noise
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
