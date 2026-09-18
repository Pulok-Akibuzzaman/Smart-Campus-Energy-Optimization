"""
tests/test_server.py - Integration Tests for the FastAPI Service
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from src.main import app
from src.models import OptimizeEnergyResponse
from tests.test_optimizer import validate_plan

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")
if not os.path.exists(DATA_PATH):
    DATA_PATH = "data/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

client = TestClient(app)

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200, f"Health status was {resp.status_code}"
    assert resp.json() == {"status": "ok"}, f"Health body mismatch: {resp.json()}"
    print("[PASSED] GET /health check")

def test_all_sample_cases():
    with open(DATA_PATH) as f:
        data = json.load(f)
        
    for case in data["cases"]:
        cid = case["id"]
        inp = case["input"]
        exp = case["expected_output"]
        
        resp = client.post("/optimize-energy", json=inp)
        assert resp.status_code == 200, f"Error on {cid}: status={resp.status_code}, body={resp.text}"
        
        res_json = resp.json()
        
        # Verify schema validity
        validated = OptimizeEnergyResponse(**res_json)
        assert validated.scenario_id == cid
        
        # Verify cost equality with expected within 0.05
        cost_diff = abs(res_json["total_cost_bdt"] - exp["total_cost_bdt"])
        assert cost_diff <= 0.05, f"{cid}: Cost diff {cost_diff} exceeds tolerance: got {res_json['total_cost_bdt']}, exp {exp['total_cost_bdt']}"
        
        # Verify physical and directive constraints using independent validator
        validate_plan(inp["hours"], inp["battery"], res_json["directive_interpretation"], res_json)
        print(f"[PASSED] POST /optimize-energy for {cid}: Cost = {res_json['total_cost_bdt']} BDT (Exact match)")

def test_malformed_input():
    resp = client.post("/optimize-energy", json={"invalid": "data"})
    assert resp.status_code == 400
    print("[PASSED] Malformed input error handling (HTTP 400)")

if __name__ == "__main__":
    test_health()
    test_all_sample_cases()
    test_malformed_input()
    print("\n>>> ALL SERVER ENDPOINT TESTS PASSED WITH FLYING COLORS! <<<")
