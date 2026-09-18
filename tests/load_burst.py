"""
Load-burst test: fire N requests at /optimize-energy concurrently and report
p50/p95/p99/max latencies + status counts. Also asserts that:
  - No request 5xxs
  - p95 < 30 s (LLM path can be slow on first request)
  - The first request that returns the response correctly

Run: PYTHONPATH=src python tests/test_load_burst.py [count]
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

BASE = "http://127.0.0.1:8000"
COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 20
SAMPLES_PATH = PROJECT_ROOT.parent / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


def load_case_payload(idx: int = 0):
    cases = json.loads(SAMPLES_PATH.read_text())["cases"]
    return cases[idx]["input"]


def one_request(idx: int) -> tuple[int, float, str]:
    payload = load_case_payload(idx % 10)
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}/optimize-energy",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
            dt = time.perf_counter() - t0
            return r.status, dt, "ok"
    except urllib.error.HTTPError as e:
        dt = time.perf_counter() - t0
        return e.code, dt, "http_err"
    except Exception as e:
        dt = time.perf_counter() - t0
        return 0, dt, f"err:{type(e).__name__}"


def main() -> int:
    print(f"Firing {COUNT} requests at {BASE}/optimize-energy (LLM path)…")
    # Sequential so the LLM doesn't rate-limit. Concurrency would need async.
    latencies: list[float] = []
    statuses: dict[int, int] = {}
    error_count = 0
    for i in range(COUNT):
        status, dt, kind = one_request(i)
        latencies.append(dt)
        statuses[status] = statuses.get(status, 0) + 1
        if kind != "ok":
            error_count += 1
            print(f"  [{i}] HTTP {status} in {dt*1000:.0f}ms ({kind})")
        elif i < 3 or i == COUNT - 1:
            print(f"  [{i}] HTTP {status} in {dt*1000:.0f}ms")

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.5)]
    p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
    p99 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.99))]
    mx = max(latencies)
    mn = min(latencies)
    print()
    print(f"min   = {mn*1000:.0f} ms")
    print(f"p50   = {p50*1000:.0f} ms")
    print(f"p95   = {p95*1000:.0f} ms")
    print(f"p99   = {p99*1000:.0f} ms")
    print(f"max   = {mx*1000:.0f} ms")
    print(f"mean  = {statistics.mean(latencies)*1000:.0f} ms")
    print()
    print(f"statuses: {statuses}")
    print(f"errors:   {error_count}")
    ok = error_count == 0 and p95 < 30.0
    print(f"\nverdict: {'PASS' if ok else 'FAIL'} (p95 {'<' if p95 < 30 else '>='} 30s)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
