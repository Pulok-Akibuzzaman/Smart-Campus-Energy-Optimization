"""
Local debug UI backend.

All routes here are mounted ONLY when ENABLE_UI=true. They are intentionally
verbose and read-only against public endpoints — they re-run the same
pipeline that the judge-facing endpoint runs, plus a few unit tests.

Originally from Ashik/src/gridwise/ui.py (a942e15).
Aurna and Pulok both ship a static dashboard at `/` and `/dashboard` but
neither is gated behind an env flag. Ashik's ENABLE_UI=true gate keeps
the debug surface off judges' default view — important for production
hygiene.

Reuses every public function in the package. Never raises: every endpoint
returns a JSON dict, even on error, so the UI can render a meaningful card.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Query

from .config import CFG
from .schemas import BatterySpec

log = logging.getLogger(__name__)

router = APIRouter()

# ─────────────────────────── Path resolution ─────────────────────────

# /home/biloi/Hackathon/ai-will-fix-it/src/gridwise/ui.py
#   └── (3 levels up) ──┘       └── (4 levels up) ──┘
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # ai-will-fix-it
REPO_PARENT = PROJECT_ROOT.parent  # /home/biloi/Hackathon
SAMPLES_PATH = REPO_PARENT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def _load_samples() -> Optional[List[Dict[str, Any]]]:
    if not SAMPLES_PATH.exists():
        log.warning("Public samples file not found at %s", SAMPLES_PATH)
        return None
    try:
        with SAMPLES_PATH.open() as f:
            return json.load(f)["cases"]
    except Exception as e:
        log.warning("Failed to load samples: %s", e)
        return None


# ─────────────────────────── Service info ────────────────────────────

_START_TIME = time.time()


@router.get("/service-info")
async def service_info() -> Dict[str, Any]:
    """Quick status snapshot for the sidebar."""
    t0 = time.time()
    health_ms = None
    health_status = None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"http://127.0.0.1:{CFG.PORT}/health")
        health_status = r.status_code
        health_ms = round((time.time() - t0) * 1000, 2)
    except Exception as e:
        health_status = f"error: {e}"

    return {
        "pid": os.getpid(),
        "uptime_s": round(time.time() - _START_TIME, 1),
        "ui_enabled": CFG.ENABLE_UI,
        "config": CFG.summary(),
        "health": {
            "status_code": health_status,
            "latency_ms": health_ms,
        },
    }


# ─────────────────────────── Schema validation tests ─────────────────


def _battery_dict(case_input: Dict[str, Any]) -> Dict[str, float]:
    return case_input.get("battery", {})


@router.get("/schema-tests")
async def schema_tests() -> Dict[str, Any]:
    """Run a battery of malformed/edge inputs against /optimize-energy."""
    samples = _load_samples()
    if not samples:
        return {"error": "samples not found"}
    base = samples[0]["input"]

    tests: List[Tuple[str, Dict[str, Any]]] = [
        ("B1_empty_body", {}),
        ("B2_malformed_json", {"_raw": "{not valid json"}),
        ("B3_empty_operator_notes", {**base, "operator_notes": []}),
        ("B4_too_few_hours", {**base, "hours": base["hours"][:23]}),
        ("B5_duplicate_hour", {
            **base,
            "hours": [{**base["hours"][0], "hour": 0}] + base["hours"][1:],
        }),
        ("B6_missing_battery", {**base, "battery": {}}),
        ("B7_negative_demand", {
            **base,
            "hours": [{**base["hours"][0], "demand_kwh": -5}] + base["hours"][1:],
        }),
        ("B8_unknown_field_ignored", {**base, "foo": "bar"}),
    ]

    results: List[Dict[str, Any]] = []
    base_url = f"http://127.0.0.1:{CFG.PORT}/optimize-energy"

    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, payload in tests:
            t0 = time.time()
            try:
                if name == "B2_malformed_json":
                    r = await client.post(
                        base_url,
                        content="{not valid json",
                        headers={"Content-Type": "application/json"},
                    )
                else:
                    r = await client.post(base_url, json=payload)
                elapsed_ms = round((time.time() - t0) * 1000, 2)
                try:
                    body = r.json()
                except Exception:
                    body = {"raw": r.text[:200]}
                results.append(
                    {
                        "test": name,
                        "status": r.status_code,
                        "elapsed_ms": elapsed_ms,
                        "expected": 400 if name != "B8_unknown_field_ignored" else 200,
                        "passed": (
                            r.status_code == 400
                            if name != "B8_unknown_field_ignored"
                            else r.status_code == 200
                        ),
                        "response_preview": body,
                    }
                )
            except Exception as e:
                results.append(
                    {
                        "test": name,
                        "status": "error",
                        "elapsed_ms": round((time.time() - t0) * 1000, 2),
                        "expected": 400,
                        "passed": False,
                        "error": str(e),
                    }
                )

    return {"results": results, "base_url": base_url}


# ─────────────────────────── Single sample ───────────────────────────


@router.post("/sample/{case_id}")
async def run_sample(case_id: str, mode: str = Query("llm")) -> Dict[str, Any]:
    """Run a single public sample case and return response + diff vs reference.

    mode: 'llm' uses the live endpoint (default). 'math' bypasses the LLM by
    passing the expected directive list directly to validate_all → optimizer.
    """
    samples = _load_samples()
    if not samples:
        return {"error": "samples not found"}
    case = next((c for c in samples if c["id"] == case_id), None)
    if not case:
        return {"error": f"case {case_id} not found", "available": [c["id"] for c in samples]}

    expected = case["expected_output"]
    base_url = f"http://127.0.0.1:{CFG.PORT}/optimize-energy"
    t0 = time.time()

    if mode == "math":
        # Direct math path — reuse the test harness.
        sys.path.insert(0, str(PROJECT_ROOT))
        try:
            from tests.test_public_samples import run_case  # type: ignore

            ok, msg, totals = run_case(case)
        except Exception as e:
            return {"error": f"math path failed: {e}", "case_id": case_id}
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        return {
            "case_id": case_id,
            "mode": "math",
            "valid": ok,
            "msg": msg,
            "totals": totals,
            "expected_totals": {
                "total_grid_kwh": expected["total_grid_kwh"],
                "total_cost_bdt": expected["total_cost_bdt"],
                "peak_grid_kwh": expected["peak_grid_kwh"],
            },
            "elapsed_ms": elapsed_ms,
            "expected_directives": [
                {"note_index": d["note_index"], "directive_type": d["directive_type"], "applies": d["applies"]}
                for d in expected["directive_interpretation"]
            ],
        }

    # mode == "llm" (default): live call through the public endpoint.
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(base_url, json=case["input"])
        elapsed_ms = round((time.time() - t0) * 1000, 2)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
        diff = None
        if r.status_code == 200 and isinstance(body, dict):
            diff = {
                "grid_diff": round(body.get("total_grid_kwh", 0) - expected["total_grid_kwh"], 2),
                "cost_diff": round(body.get("total_cost_bdt", 0) - expected["total_cost_bdt"], 2),
                "peak_diff": round(body.get("peak_grid_kwh", 0) - expected["peak_grid_kwh"], 2),
            }
        return {
            "case_id": case_id,
            "mode": "llm",
            "status": r.status_code,
            "elapsed_ms": elapsed_ms,
            "response": body,
            "expected": {
                "directive_types": [d["directive_type"] for d in expected["directive_interpretation"]],
                "total_cost_bdt": expected["total_cost_bdt"],
                "total_grid_kwh": expected["total_grid_kwh"],
                "peak_grid_kwh": expected["peak_grid_kwh"],
            },
            "diff": diff,
        }
    except Exception as e:
        return {"error": str(e), "case_id": case_id, "mode": mode}


# ─────────────────────────── All samples ────────────────────────────


@router.post("/run-all-samples")
async def run_all_samples(mode: str = Query("llm")) -> Dict[str, Any]:
    """Run all 10 public cases and return a summary table."""
    samples = _load_samples()
    if not samples:
        return {"error": "samples not found"}

    sys.path.insert(0, str(PROJECT_ROOT))
    rows: List[Dict[str, Any]] = []

    if mode == "math":
        try:
            from tests.test_public_samples import run_case  # type: ignore
        except Exception as e:
            return {"error": f"could not import test harness: {e}"}
        for case in samples:
            tid = f"{case['id']}__{mode}"
            t0 = time.time()
            try:
                ok, msg, totals = run_case(case)
                elapsed_ms = round((time.time() - t0) * 1000, 2)
                org_cost = totals.get("exp_cost", 0) or 0
                team_cost = totals.get("cost", 0) or 0
                ratio = min(1.0, org_cost / team_cost) if team_cost > 0.01 else (1.0 if org_cost <= 0.01 else 0.0)
                rows.append(
                    {
                        "case_id": case["id"],
                        "label": case.get("label", ""),
                        "valid": ok,
                        "elapsed_ms": elapsed_ms,
                        "team_cost": totals.get("cost"),
                        "expected_cost": totals.get("exp_cost"),
                        "cost_diff": round(totals.get("cost", 0) - totals.get("exp_cost", 0), 2),
                        "team_grid": totals.get("grid"),
                        "expected_grid": totals.get("exp_grid"),
                        "quality_ratio": round(ratio, 4),
                    }
                )
            except Exception as e:
                rows.append({"case_id": case["id"], "error": str(e)})
    else:
        base_url = f"http://127.0.0.1:{CFG.PORT}/optimize-energy"
        async with httpx.AsyncClient(timeout=30.0) as client:
            for case in samples:
                t0 = time.time()
                try:
                    r = await client.post(base_url, json=case["input"])
                    elapsed_ms = round((time.time() - t0) * 1000, 2)
                    body = r.json()
                    expected = case["expected_output"]
                    team_cost = body.get("total_cost_bdt", 0)
                    org_cost = expected["total_cost_bdt"]
                    ratio = min(1.0, org_cost / team_cost) if team_cost > 0.01 else (1.0 if org_cost <= 0.01 else 0.0)
                    rows.append(
                        {
                            "case_id": case["id"],
                            "label": case.get("label", ""),
                            "status": r.status_code,
                            "elapsed_ms": elapsed_ms,
                            "team_cost": team_cost,
                            "expected_cost": org_cost,
                            "cost_diff": round(team_cost - org_cost, 2),
                            "team_grid": body.get("total_grid_kwh"),
                            "expected_grid": expected["total_grid_kwh"],
                            "directive_types": [
                                d["directive_type"]
                                for d in body.get("directive_interpretation", [])
                            ],
                            "quality_ratio": round(ratio, 4),
                        }
                    )
                except Exception as e:
                    rows.append({"case_id": case["id"], "error": str(e)})

    valid_count = sum(1 for r in rows if r.get("valid") is True or (r.get("status") == 200))
    avg_ratio = 0.0
    ratio_rows = [r for r in rows if "quality_ratio" in r]
    if ratio_rows:
        avg_ratio = round(sum(r["quality_ratio"] for r in ratio_rows) / len(ratio_rows), 4)

    return {
        "mode": mode,
        "rows": rows,
        "summary": {
            "total": len(rows),
            "valid_or_200": valid_count,
            "avg_quality_ratio": avg_ratio,
        },
    }


# ─────────────────────────── Guardrail unit tests ────────────────────


@router.get("/guardrail-tests")
async def guardrail_tests() -> Dict[str, Any]:
    """Hand-rolled bad input → validate_all. Verifies the validator coerces to no_op."""
    from .validator import validate_all

    battery = BatterySpec(
        capacity_kwh=200,
        initial_energy_kwh=100,
        minimum_energy_kwh=20,
        max_charge_kwh_per_hour=50,
        max_discharge_kwh_per_hour=50,
    )
    notes = ["note_a", "note_b", "note_c"]

    cases = [
        (
            "D1_valid_solar_reduction",
            [
                {"note_index": 0, "applies": True, "directive_type": "solar_reduction",
                 "structured_adjustment": {"hours": [12, 13], "factor": 0.25},
                 "explanation": "ok"},
            ] + [
                {"note_index": i, "applies": False, "directive_type": "no_op",
                 "structured_adjustment": None, "explanation": "noop"}
                for i in (1, 2)
            ],
            [(0, "solar_reduction", True), (1, "no_op", False), (2, "no_op", False)],
        ),
        (
            "D2_unsupported_type",
            [{"note_index": 0, "applies": True, "directive_type": "charge_now",
              "structured_adjustment": {}, "explanation": "invented"}]
            + [
                {"note_index": i, "applies": False, "directive_type": "no_op",
                 "structured_adjustment": None, "explanation": "x"}
                for i in (1, 2)
            ],
            [(0, "no_op", False), (1, "no_op", False), (2, "no_op", False)],
        ),
        (
            "D3_factor_out_of_range",
            [{"note_index": 0, "applies": True, "directive_type": "solar_reduction",
              "structured_adjustment": {"hours": [12], "factor": 1.5},
              "explanation": "bad"}]
            + [
                {"note_index": i, "applies": False, "directive_type": "no_op",
                 "structured_adjustment": None, "explanation": "x"}
                for i in (1, 2)
            ],
            [(0, "no_op", False), (1, "no_op", False), (2, "no_op", False)],
        ),
        (
            "D4_duplicate_hours",
            [{"note_index": 0, "applies": True, "directive_type": "solar_reduction",
              "structured_adjustment": {"hours": [12, 12, 13], "factor": 0.3},
              "explanation": "dup"}]
            + [
                {"note_index": i, "applies": False, "directive_type": "no_op",
                 "structured_adjustment": None, "explanation": "x"}
                for i in (1, 2)
            ],
            [(0, "no_op", False), (1, "no_op", False), (2, "no_op", False)],
        ),
        (
            "D5_no_op_with_applies_true",
            [{"note_index": 0, "applies": True, "directive_type": "no_op",
              "structured_adjustment": None, "explanation": "wrong"}]
            + [
                {"note_index": i, "applies": False, "directive_type": "no_op",
                 "structured_adjustment": None, "explanation": "x"}
                for i in (1, 2)
            ],
            [(0, "no_op", False), (1, "no_op", False), (2, "no_op", False)],
        ),
        (
            "L1_absurd_factor_hours",
            [{"note_index": 0, "applies": True, "directive_type": "solar_reduction",
              "structured_adjustment": {"hours": [99, 100], "factor": 100.0},
              "explanation": "absurd"}]
            + [
                {"note_index": i, "applies": False, "directive_type": "no_op",
                 "structured_adjustment": None, "explanation": "x"}
                for i in (1, 2)
            ],
            [(0, "no_op", False), (1, "no_op", False), (2, "no_op", False)],
        ),
        (
            "L2_sql_injection_style",
            [{"note_index": 0, "applies": True, "directive_type": "solar_reduction",
              "structured_adjustment": {"hours": [12], "factor": "0.5; DROP TABLE demand; --"},
              "explanation": "injection"}]
            + [
                {"note_index": i, "applies": False, "directive_type": "no_op",
                 "structured_adjustment": None, "explanation": "x"}
                for i in (1, 2)
            ],
            [(0, "no_op", False), (1, "no_op", False), (2, "no_op", False)],
        ),
        (
            "L3_minute_30_hour",
            [{"note_index": 0, "applies": True, "directive_type": "no_discharge_window",
              "structured_adjustment": {"hours": [30]}, "explanation": "weird hour"}]
            + [
                {"note_index": i, "applies": False, "directive_type": "no_op",
                 "structured_adjustment": None, "explanation": "x"}
                for i in (1, 2)
            ],
            [(0, "no_op", False), (1, "no_op", False), (2, "no_op", False)],
        ),
        (
            "L4_mixed_valid_and_nonsense",
            [{"note_index": 0, "applies": True, "directive_type": "no_charge_window",
              "structured_adjustment": {"hours": [2, 3, 4]}, "explanation": "valid"},
             {"note_index": 1, "applies": True, "directive_type": "solar_reduction_pow",  # invented
              "structured_adjustment": {"hours": [10], "factor": 0.5}, "explanation": "nonsense"},
             {"note_index": 2, "applies": True, "directive_type": "no_op",  # applies must be false
              "structured_adjustment": None, "explanation": "wrong"}],
            [(0, "no_charge_window", True), (1, "no_op", False), (2, "no_op", False)],
        ),
    ]

    results = []
    passed = 0
    for name, raw, expected_entries in cases:
        try:
            out = validate_all(raw, notes, battery)
            actual = [(e.note_index, e.directive_type.value, e.applies) for e in out]
            ok = actual == expected_entries
            if ok:
                passed += 1
            results.append({
                "test": name,
                "passed": ok,
                "expected": expected_entries,
                "actual": actual,
            })
        except Exception as e:
            results.append({"test": name, "passed": False, "error": str(e)})

    return {"results": results, "passed": passed, "total": len(cases)}


# ─────────────────────────── Replay EOD checks ──────────────────────


@router.get("/replay-checks")
async def replay_checks() -> Dict[str, Any]:
    """For each public case, compute E_initial vs E_final to confirm neutrality."""
    samples = _load_samples()
    if not samples:
        return {"error": "samples not found"}

    sys.path.insert(0, str(PROJECT_ROOT))
    try:
        from tests.test_public_samples import run_case  # type: ignore
    except Exception as e:
        return {"error": f"could not import test harness: {e}"}

    rows = []
    for case in samples:
        try:
            ok, msg, totals = run_case(case)
            initial = case["input"]["battery"]["initial_energy_kwh"]
            # Re-run the math to extract E_final — easier: pull from optimizer.
            from .schemas import HourEntry, DirectiveInterpretationEntry
            from .constraints import build_constraints
            from .optimizer import optimize_schedule

            hours = [HourEntry(**h) for h in case["input"]["hours"]]
            battery = BatterySpec(**case["input"]["battery"])

            # Use expected directives (math path).
            from .schemas import (
                DirectiveType,
                MaxGridWindowAdjustment,
                MinimumBatteryReserveAdjustment,
                NoChargeWindowAdjustment,
                NoDischargeWindowAdjustment,
                SolarReductionAdjustment,
            )

            parsers = {
                "solar_reduction": lambda a: SolarReductionAdjustment(hours=a["hours"], factor=a["factor"]),
                "minimum_battery_reserve": lambda a: MinimumBatteryReserveAdjustment(hours=a["hours"], minimum_energy_kwh=a["minimum_energy_kwh"]),
                "no_charge_window": lambda a: NoChargeWindowAdjustment(hours=a["hours"]),
                "no_discharge_window": lambda a: NoDischargeWindowAdjustment(hours=a["hours"]),
                "max_grid_window": lambda a: MaxGridWindowAdjustment(hours=a["hours"], max_grid_kwh=a["max_grid_kwh"]),
            }
            directives = []
            for d in case["expected_output"]["directive_interpretation"]:
                if d["directive_type"] == "no_op":
                    directives.append(
                        DirectiveInterpretationEntry(
                            note_index=d["note_index"],
                            applies=False,
                            directive_type=DirectiveType.NO_OP,
                            structured_adjustment=None,
                            explanation="ref",
                        )
                    )
                else:
                    directives.append(
                        DirectiveInterpretationEntry(
                            note_index=d["note_index"],
                            applies=True,
                            directive_type=DirectiveType(d["directive_type"]),
                            structured_adjustment=parsers[d["directive_type"]](d["structured_adjustment"]),
                            explanation="ref",
                        )
                    )

            cons = build_constraints(hours, battery, directives)
            opt = optimize_schedule(hours, battery, cons)
            e_final = opt.energy_after[23]
            delta = round(e_final - initial, 4)
            rows.append({
                "case_id": case["id"],
                "label": case.get("label", ""),
                "e_initial": initial,
                "e_final": round(e_final, 4),
                "delta": delta,
                "passed": abs(delta) <= 0.01,
                "solver": opt.solver_used,
            })
        except Exception as e:
            rows.append({"case_id": case["id"], "error": str(e)})

    passed = sum(1 for r in rows if r.get("passed"))
    return {"rows": rows, "passed": passed, "total": len(rows)}


# ─────────────────────────── Log / secret scan ──────────────────────


@router.get("/log-scan")
async def log_scan() -> Dict[str, Any]:
    """Grep the live uvicorn log for any leaked API key values."""
    log_path = Path("/tmp/gridwise-live.log")
    if not log_path.exists():
        # Try a few common locations.
        candidates = [
            Path("/tmp/gridwise-live.log"),
            Path("/tmp/uvicorn.log"),
            Path("/tmp/gridwise_boot.log"),
        ]
        for c in candidates:
            if c.exists():
                log_path = c
                break
        else:
            return {"path": str(log_path), "exists": False, "matches": []}

    text = log_path.read_text(errors="replace")
    needles = [
        "GROQ_API_KEY=",
        "GEMINI_API_KEY=",
        "OPENROUTER_API_KEY=",
        "your_groq_api_key_here",
        "your_gemini_api_key_here",
        "your_openrouter_api_key_here",
    ]
    matches = []
    for needle in needles:
        for line in text.splitlines():
            if needle in line and "your_" not in line and "os.getenv" not in line:
                matches.append({"needle": needle, "line": line.strip()[:300]})
                break

    return {
        "path": str(log_path),
        "exists": True,
        "matches": matches,
        "passed": len(matches) == 0,
        "size_bytes": log_path.stat().st_size,
    }


# ─────────────────────────── Performance burst ──────────────────────


@router.post("/perf-burst")
async def perf_burst(count: int = Query(20)) -> Dict[str, Any]:
    """Fire N sequential requests at /optimize-energy and report stats."""
    samples = _load_samples()
    if not samples:
        return {"error": "samples not found"}
    case = samples[0]
    base_url = f"http://127.0.0.1:{CFG.PORT}/optimize-energy"

    statuses: List[int] = []
    latencies: List[float] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(count):
            t0 = time.time()
            try:
                r = await client.post(base_url, json=case["input"])
                statuses.append(r.status_code)
                latencies.append((time.time() - t0) * 1000.0)
            except Exception:
                statuses.append(0)

    if not latencies:
        return {"error": "no successful requests"}

    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[len(latencies_sorted) // 2]
    p95 = latencies_sorted[max(0, int(len(latencies_sorted) * 0.95) - 1)]
    return {
        "count": count,
        "statuses_count": {str(s): statuses.count(s) for s in set(statuses)},
        "min_ms": round(min(latencies), 2),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(max(latencies), 2),
        "mean_ms": round(statistics.mean(latencies), 2),
        "passed": all(s == 200 for s in statuses) and p95 < 5000,
    }


# ─────────────────────────── Cold start ─────────────────────────────


@router.post("/cold-start")
async def cold_start_measure() -> Dict[str, Any]:
    """Best-effort: return process uptime as a proxy for time-to-health."""
    return {
        "uptime_s": round(time.time() - _START_TIME, 2),
        "pid": os.getpid(),
        "note": "service has been up for this many seconds; reload manually to re-measure cold start",
    }


# ─────────────────────────── Docker status ───────────────────────────


@router.get("/docker-status")
async def docker_status() -> Dict[str, Any]:
    """Read-only snapshot of the Docker image and the running container.

    No shell execution. Uses subprocess only to call `docker images`/`docker ps`
    via the safe async subprocess. If docker CLI is unavailable, returns a
    clear error.
    """
    import asyncio

    async def _run(cmd: List[str]) -> Tuple[int, str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")
        except Exception as e:
            return -1, "", str(e)

    rc_img, out_img, err_img = await _run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}", "ai-will-fix-it/gridwise"])
    rc_ps, out_ps, err_ps = await _run(["docker", "ps", "--filter", "ancestor=ai-will-fix-it/gridwise", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"])

    return {
        "images": out_img.strip().splitlines() if rc_img == 0 else [],
        "images_error": err_img.strip() if rc_img != 0 else None,
        "containers": out_ps.strip().splitlines() if rc_ps == 0 else [],
        "containers_error": err_ps.strip() if rc_ps != 0 else None,
    }


# ─────────────────────────── Directive-shape diff ────────────────────


@router.post("/directive-diff/{case_id}")
async def directive_diff(case_id: str, mode: str = Query("llm")) -> Dict[str, Any]:
    """Per-note comparison: LLM-emitted directive vs expected directive.

    Returns one row per note with:
      - expected directive_type / hours / factor / structured_adjustment
      - actual directive_type / hours / factor / structured_adjustment
      - a 'match' flag for the canonical fields
      - a 'severity' tag (exact | partial | mismatch | extra | missing)
    """
    samples = _load_samples()
    if not samples:
        return {"error": "samples not found"}
    case = next((c for c in samples if c["id"] == case_id), None)
    if not case:
        return {"error": f"case {case_id} not found"}

    expected_directives = case["expected_output"]["directive_interpretation"]

    if mode == "math":
        # Math path doesn't run the LLM — assume directives match trivially.
        return {
            "case_id": case_id,
            "mode": "math",
            "rows": [
                {
                    "note_index": d["note_index"],
                    "note": case["input"]["operator_notes"][d["note_index"]],
                    "expected": d,
                    "actual": d,
                    "match": True,
                    "severity": "exact (math path bypasses LLM)",
                }
                for d in expected_directives
            ],
        }

    # LLM path: hit the live endpoint
    base_url = f"http://127.0.0.1:{CFG.PORT}/optimize-energy"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(base_url, json=case["input"])
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        actual_directives = body.get("directive_interpretation", [])
    except Exception as e:
        return {"error": str(e)}

    rows = []
    for d in expected_directives:
        ni = d["note_index"]
        note = case["input"]["operator_notes"][ni]
        actual = next((a for a in actual_directives if a.get("note_index") == ni), None)

        if actual is None:
            rows.append({
                "note_index": ni,
                "note": note,
                "expected": d,
                "actual": None,
                "match": False,
                "severity": "missing",
            })
            continue

        exp_type = d["directive_type"]
        act_type = actual.get("directive_type")
        exp_adj = d.get("structured_adjustment") or {}
        act_adj = actual.get("structured_adjustment") or {}

        # Compare on canonical shape: directive_type + hours + (factor | minimum_energy_kwh | max_grid_kwh)
        same_type = exp_type == act_type
        exp_hours = exp_adj.get("hours") if isinstance(exp_adj, dict) else None
        act_hours = act_adj.get("hours") if isinstance(act_adj, dict) else None
        same_hours = exp_hours == act_hours

        # Scalar field varies by directive type
        scalar_match = True
        if exp_type == "solar_reduction":
            scalar_match = exp_adj.get("factor") == act_adj.get("factor")
        elif exp_type == "minimum_battery_reserve":
            scalar_match = exp_adj.get("minimum_energy_kwh") == act_adj.get("minimum_energy_kwh")
        elif exp_type == "max_grid_window":
            scalar_match = exp_adj.get("max_grid_kwh") == act_adj.get("max_grid_kwh")

        applies_ok = (
            (d["applies"] and actual.get("applies") is True)
            or (not d["applies"] and actual.get("applies") is False)
        )

        severity = (
            "exact" if (same_type and same_hours and scalar_match and applies_ok)
            else "partial" if (same_type and same_hours)
            else "mismatch"
        )
        rows.append({
            "note_index": ni,
            "note": note,
            "expected": d,
            "actual": actual,
            "match": severity == "exact",
            "severity": severity,
        })

    matched = sum(1 for r in rows if r["match"])
    return {
        "case_id": case_id,
        "mode": mode,
        "rows": rows,
        "matched": matched,
        "total": len(rows),
    }


# ─────────────────────────── Export-to-file ──────────────────────────


@router.post("/export-response/{case_id}")
async def export_response(case_id: str, mode: str = Query("llm")) -> Dict[str, Any]:
    """Same as run_sample but returns a downloadable-friendly JSON with
    a timestamped filename suggestion. Used by the UI's Export button.
    """
    samples = _load_samples()
    if not samples:
        return {"error": "samples not found"}
    case = next((c for c in samples if c["id"] == case_id), None)
    if not case:
        return {"error": f"case {case_id} not found"}

    base_url = f"http://127.0.0.1:{CFG.PORT}/optimize-energy"
    if mode == "math":
        return {"error": "math mode does not produce a single OptimizeResponse; use /run-sample/{id}?mode=math"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(base_url, json=case["input"])
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:2000]}
    except Exception as e:
        return {"error": str(e)}

    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return {
        "filename_suggestion": f"gridwise_{case_id}_{mode}_{ts}.json",
        "response": body,
        "status": r.status_code,
        "fetched_at": ts,
    }
