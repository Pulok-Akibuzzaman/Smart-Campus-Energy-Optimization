"""
tests/test_interpreter.py - Tests LLM and Heuristic Directive Extraction
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.interpreter import interpret_operator_notes

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")
if not os.path.exists(DATA_PATH):
    DATA_PATH = "data/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

def test_all_cases_interpretation():
    with open(DATA_PATH) as f:
        data = json.load(f)
        
    all_matched = True
    for case in data["cases"]:
        cid = case["id"]
        inp = case["input"]
        exp = case["expected_output"]["directive_interpretation"]
        
        interp = interpret_operator_notes(inp["operator_notes"], inp["battery"], cid)
        
        assert len(interp) == len(exp), f"{cid}: Length mismatch"
        
        match = True
        for i, (act, ex) in enumerate(zip(interp, exp)):
            if act["note_index"] != ex["note_index"] or act["applies"] != ex["applies"] or act["directive_type"] != ex["directive_type"]:
                match = False
                print(f"  Mismatch at note {i}: got type={act['directive_type']} applies={act['applies']}, expected type={ex['directive_type']} applies={ex['applies']}")
            if ex["structured_adjustment"] is not None:
                if act["structured_adjustment"] is None:
                    match = False
                    print(f"  Mismatch at note {i}: structured_adjustment is None")
                else:
                    for k, v in ex["structured_adjustment"].items():
                        act_v = act["structured_adjustment"].get(k)
                        if act_v != v:
                            match = False
                            print(f"  Mismatch at note {i} field '{k}': got {act_v}, expected {v}")
                            
        status = "MATCHED" if match else "MISMATCH"
        if not match: all_matched = False
        print(f"[{status}] {cid} ({len(interp)} notes)")

    assert all_matched, "Some directive interpretations mismatched"
    print("\n>>> ALL 10 SAMPLE CASES DIRECTIVES EXTRACTED PERFECTLY! <<<")

if __name__ == "__main__":
    test_all_cases_interpretation()
