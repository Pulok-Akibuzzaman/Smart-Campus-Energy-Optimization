# GridWise — Smart Campus Energy Optimization (LLM-Assisted)

> **BUP CSE Fest 2026 — Hackathon Preliminary · Final Submission**
> **Team:** *Ai-Will-Fix-It*
> **Docker image:** `ashikonik/gridwise-bup-2026:1.0.0`

An LLM-assisted 24-hour energy scheduler. Receives a 24-hour campus energy scenario plus 1–3 free-form operator notes, interprets each note via a 4-provider LLM chain, applies 12 deterministic guardrails, solves a hybrid linear program, and returns a valid minimum-cost battery + grid schedule — matching the reference optimum to the paisa on all 10 public cases.

---

## Why this exists

Every hour, the BUP campus cafeteria buys electricity from the grid — even when the sun is up and the battery is half-empty. **GridWise decides, hour by hour, when to charge from solar, when to discharge to loads, and when to buy from the grid.** The result: same energy, less money, every time.

```
                ┌─────────────────────────────────────────────┐
                │                                             │
                │   Operator Notes → LLM Chain → Validator →  │
                │   LP Optimizer → Hourly Plan → Replay Check │
                │                                             │
                │   37/37 tests · 0.00 BDT diff · ~6 ms solve  │
                │                                             │
                └─────────────────────────────────────────────┘
```

---

## 1. Architecture in one screen

```
         ┌───────────────────────────────────────────────────────┐
         │  POST /optimize-energy  (Pydantic-validated payload)   │
         └─────────────────────────┬─────────────────────────────┘
                                   ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  LLM Interpreter — 4-provider chain + regex safety net      │
   │  ┌──────────┐  ┌──────────┐  ┌─────────────┐  ┌──────────┐  │
   │  │  Groq    │→ │  Gemini  │→ │ OpenRouter  │→ │  Puku    │  │
   │  └────┬─────┘  └────┬─────┘  └──────┬──────┘  └────┬─────┘  │
   │       └─────────────┴───────────────┴──────────────┘        │
   │                              │ all four fail               │
   │                              ▼                              │
   │                  ┌──────────────────────┐                   │
   │                  │  Regex Safety Net    │ (deterministic,    │
   │                  │  always returns ⩾ 1   │  always returns    │
   │                  │  valid directive      │  a parseable plan) │
   │                  └──────────────────────┘                   │
   └─────────────────────────────┬───────────────────────────────┘
                                 ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Validator — 12 strict guardrails (Section 08)               │
   │  → directive_type ∈ {solar_reduction, minimum_battery_reserve,│
   │    no_charge_window, no_discharge_window, max_grid_window, no_op}│
   │  → hours: unique ints 0..23 ascending · factor ∈ [0,1]       │
   │  → bad LLM output → coerced to no_op (smaller loss than     │
   │    inventing an unsupported directive)                      │
   └─────────────────────────────┬───────────────────────────────┘
                                 ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  LP Optimizer — HYBRID (Aurna + Ashik merged)                │
   │  ┌──────────────┐  ┌───────────────────────────────────┐    │
   │  │  PuLP / CBC  │  │  scipy linprog / HiGHS (fallback)  │    │
   │  │  primary     │  │  if PuLP unavailable              │    │
   │  └──────────────┘  └───────────────────────────────────┘    │
   │  120 variables · 49 equality constraints · 1e-6 complementarity│
   │  Stage 1: min Σ grid[h]·tariff[h]  → unique optimum on all 10│
   │           public cases, so stage 2 (peak/total/lex tie-break)│
   │           only fires when stage 1 is ambiguous.             │
   └─────────────────────────────┬───────────────────────────────┘
                                 ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  Replay Validator — re-derives totals from the schedule     │
   │  → returns 200 only when the math matches the schedule       │
   └─────────────────────────────┬───────────────────────────────┘
                                 ▼
         ┌─────────────────────────────────────────────────┐
         │  OptimizeResponse JSON (Pydantic)                │
         │  hourly_plan · total_cost_bdt · solver_used      │
         └─────────────────────────────────────────────────┘
```

The principle from the rubric is mirrored at every layer: **never trust the previous layer's output blindly**. The LLM is untrusted until guardrailed; the optimizer is untrusted until replayed.

---

## 2. Local quickstart

### 2.1 Native Python (development)

```bash
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It.git
cd Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add at least one LLM key (Groq recommended — free + fast)
# GROQ_API_KEY=...

export PYTHONPATH=src
uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
```

### 2.2 Docker (production parity)

```bash
docker pull ashikonik/gridwise-bup-2026:1.0.0
docker run --rm -p 8000:8000 --env-file .env ashikonik/gridwise-bup-2026:1.0.0
```

Or build the image yourself:

```bash
docker build -t gridwise:1.0.0 .
docker run --rm -p 8000:8000 --env-file .env gridwise:1.0.0
```

### 2.3 Verify it works

```bash
# Health check
curl -s http://127.0.0.1:8000/health
# -> {"status":"ok"}

# Run all 10 public sample cases through the optimizer (math path only,
# bypasses the LLM by feeding the expected directive list directly)
PYTHONPATH=src pytest tests/test_hybrid_optimizer.py -v
# Expected: 13/13 pass — 10 cost-diff cases + 2 aggregates + 1 fallback
```

---

## 3. Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe — returns `200 {"status":"ok"}` |
| `/` | GET | 307 redirect to `/docs` |
| `/favicon.ico` | GET | 1×1 transparent PNG (silences browser auto-fetch) |
| `/optimize-energy` | POST | The actual solver. Accepts a scenario JSON, returns a directive interpretation + 24-hour plan + total cost. |
| `/ui` | GET | **Debug console — gated behind `ENABLE_UI=true`.** Not exposed to judges. |

### 3.1 `POST /optimize-energy`

**Example request (truncated):**

```json
{
  "scenario_id": "GRID-101",
  "operator_notes": [
    "Solar output will drop to about 20% from 1 PM to 3 PM.",
    "Do not charge the battery between 2 PM and 4 PM.",
    "The cafeteria menu changes tomorrow."
  ],
  "hours": [
    {"hour": 0, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
    "...22 more hourly entries...",
    {"hour": 23, "demand_kwh": 200, "solar_kwh": 0, "tariff_bdt_per_kwh": 9}
  ],
  "battery": {
    "capacity_kwh": 500,
    "initial_energy_kwh": 200,
    "minimum_energy_kwh": 50,
    "max_charge_kwh_per_hour": 100,
    "max_discharge_kwh_per_hour": 100
  }
}
```

**Example curl:**

```bash
curl -s -X POST http://127.0.0.1:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @request.json | jq .
```

### 3.2 HTTP status codes

| Code | Meaning |
|---|---|
| 200 | Successful response |
| 400 | Malformed JSON or structurally invalid request |
| 500 | Controlled internal error (no secrets / stack traces exposed) |

---

## 4. Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `GROQ_API_KEY` | Groq API key (primary LLM) | unset |
| `GEMINI_API_KEY` | Gemini API key (fallback #1) | unset |
| `OPENROUTER_API_KEY` | OpenRouter API key (fallback #2) | unset |
| `PUKU_API_KEY` | Puku.sh API key (fallback #3; currently browser-session auth) | unset |
| `LLM_PROVIDER_ORDER` | Comma-separated fallback chain | `groq,gemini,openrouter` |
| `GROQ_MODEL` | Groq model | `llama-3.1-8b-instant` |
| `GEMINI_MODEL` | Gemini model | `gemini-1.5-flash` |
| `OPENROUTER_MODEL` | OpenRouter model | `meta-llama/llama-3.1-8b-instruct:free` |
| `PUKU_MODEL` | Puku.sh model | `gpt-oss-20b` |
| `HOST` | Bind host | `0.0.0.0` |
| `PORT` | Bind port | `8000` |
| `LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING`/`ERROR` | `INFO` |
| `LLM_TIMEOUT_SECONDS` | Per-provider timeout | `8` |
| `LLM_MAX_RETRIES` | Per-provider retries | `1` |
| `ENABLE_UI` | Mount `/ui` debug console | unset |

> **Secrets are never committed.** The image does not bake in any keys. Use `.env` (gitignored) or pass keys via `--env-file` / `-e`.

---

## 5. LLM role (mandatory)

Per the rubric, the **language model must sit in the operator-note interpretation path**. This service uses an OpenAI-compatible HTTP API with the following provider chain:

1. **Groq** (`llama-3.1-8b-instant`) — primary, fastest, free tier
2. **Gemini** (`gemini-1.5-flash`) — fallback #1
3. **OpenRouter** (free models) — fallback #2
4. **Puku.sh** — fallback #3 (uses session auth, set `PUKU_API_KEY` to a valid token)
5. **Deterministic regex** — safety net. Only activates if **every** LLM provider fails. Never crashes.

The strict-JSON system prompt lives in `src/gridwise/prompts.py` and:
- Lists every supported directive type and its required shape
- Bakes the time-window rule (`"1 PM to 3 PM" → [13, 14]`)
- Bakes the solar-factor rule (`"80% reduction" → factor 0.2`)
- Forbids inventing unsupported directive types
- Forces distractors (cafeteria menu, registration deadlines, drills) to `no_op`

The validator re-checks every directive against the 12 guardrails before it can influence the optimizer. Any malformed LLM output is coerced to `no_op` rather than crashing.

---

## 6. Optimizer — the HYBRID

This codebase merges two optimizer approaches:

- **Aurna's exact cost objective**: `Σ grid[h] · tariff[h]` with a `1e-6` complementarity penalty on `(charge + discharge)` so simultaneous charging and discharging is broken when the LP is ambiguous.
- **Ashik's 2-stage tie-break**: stage 1 minimizes cost; stage 2 pins cost to that optimum and minimizes peak grid, then total grid, then hour-by-hour lexicographic — fires only when stage 1 is ambiguous.

Primary: **PuLP** with the bundled **CBC** solver (pure Python, free, solves the 24-hour LP in milliseconds).
Fallback: **scipy.optimize.linprog** with the **HiGHS** solver. A dedicated test (`tests/test_solver_fallback.py`) blocks PuLP via `monkeypatch` and asserts scipy takes over.

Decision variables per hour: `grid_kwh`, `solar_used_kwh`, `battery_charge_kwh`, `battery_discharge_kwh`, `battery_energy_after_kwh`.

Constraints: energy balance, battery dynamics (`E[h] = E[h-1] + charge − discharge`), battery bounds (with raised minimum in `minimum_battery_reserve` windows), charge/discharge rate limits, charge/discharge disabled in their respective window directives, `grid_kwh ≤ max_grid_kwh` in `max_grid_window` hours, `solar_used ≤ effective_solar`, and explicit end-of-day battery neutrality (`E[23] = initial`).

**Quality on the 10 public cases:** `+0.00 BDT` total diff. Average solve: `~6 ms`.

---

## 7. Testing

The merged test suite runs with pytest:

```bash
PYTHONPATH=src pytest tests/ -v
```

| Test file | What it covers | Count |
|---|---|---|
| `tests/test_hybrid_optimizer.py` | Asserts `+0.00 BDT` diff on all 10 public cases; aggregate quality_ratio ≥ 0.999; all replay-valid | 12 |
| `tests/test_solver_fallback.py` | Defence-in-depth: scipy fallback works when PuLP is unavailable | 1 |
| `tests/test_validator.py` | 17 hand-rolled malformed inputs must coerce to no_op without crashing | 17 |
| `tests/test_provider_chain.py` | 7 mocked failover scenarios across the LLM provider chain | 7 |
| `tests/public_samples.py` | CLI: full determinism harness across all 10 public cases (cost-compare, replay-validate) | (script) |
| `tests/load_burst.py` | CLI: 20-request latency burst against a running service | (script) |

**Total: 37 deterministic pytest tests + 2 standalone CLI scripts (live API required).**

---

## 8. Project layout

```
gridwise_merged/
├── Dockerfile                  # multi-stage + non-root + urllib healthcheck
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── README.md                   # this file
├── LICENSE
├── pyproject.toml
├── pytest.ini                  # asyncio_mode=auto
├── requirements.txt
├── publish.sh                  # one-shot Docker Hub push (see §10)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── FINAL_SUBMISSION_DOCUMENTATION.md   # one-page rubric checklist
│   ├── VIDEO_SCRIPT.md                     # 3-min demo-day script
│   └── VIDEO_STORYBOARD.md                 # 18-slide outline
├── src/
│   └── gridwise/
│       ├── __init__.py
│       ├── app.py            # FastAPI routes
│       ├── config.py         # env loader + masked_api_key helper (Aurna)
│       ├── constraints.py    # Directive → per-hour arrays (Ashik)
│       ├── interpreter.py    # 4-provider chain + regex safety net (Ashik)
│       ├── optimizer.py      # ★ HYBRID (Aurna objective + Ashik 2-stage)
│       ├── prompts.py        # LLM system prompt (Ashik)
│       ├── replay.py         # Self-validate + total derivation (Ashik)
│       ├── schemas.py        # Pydantic models (Ashik)
│       ├── ui.py             # /ui debug console, gated by ENABLE_UI (Ashik)
│       └── validator.py      # 12 guardrails (Ashik)
└── tests/
    ├── test_hybrid_optimizer.py
    ├── test_solver_fallback.py
    ├── test_validator.py
    ├── test_provider_chain.py
    ├── test_public_samples.py
    └── test_load_burst.py
```

---

## 9. Demo video

3-minute demo-day energetic walkthrough:

- **Script:** [`docs/VIDEO_SCRIPT.md`](./docs/VIDEO_SCRIPT.md) — time-stamped
  speaker notes for cold open, architecture, live demo, math, resilience,
  closing.
- **Storyboard:** [`docs/VIDEO_STORYBOARD.md`](./docs/VIDEO_STORYBOARD.md) —
  18 slides at 10 sec each, with transition cues.

Recording checklist and export-target notes are at the bottom of each
document.

---

## 10. Deployment

### 10.1 Pull from Docker Hub

```bash
docker pull ashikonik/gridwise-bup-2026:1.0.0
docker run -d -p 8000:8000 --env-file .env --name gridwise ashikonik/gridwise-bup-2026:1.0.0
curl -s http://127.0.0.1:8000/health
# -> {"status":"ok"}
```

### 10.2 Publish a new image (one-shot)

Use `publish.sh`:

```bash
export DOCKER_USERNAME=ashikonik
export DOCKER_REPOSITORY=gridwise-bup-2026
export TAG=1.0.0
./publish.sh
```

The script handles `docker login`, build, and push. It expects an
access token to be supplied via `docker login --password-stdin` (or
via `~/.docker/config.json` already populated).

---

## 11. Known limitations

- **LLM interpretation robustness** depends on the chosen provider. If paraphrases are highly unusual, the LLM may misinterpret a note. The deterministic validator coerces bad LLM output to `no_op` (smaller loss than an invented directive).
- **PuLP** is preferred over scipy linprog; if PuLP's bundled CBC fails to install, the service transparently falls back to scipy.
- The regex safety net is intentionally narrow — it covers the public sample patterns only. In production, real LLM providers must be configured.
- **Numeric tolerance** for judge comparisons is **0.01 kWh / 0.01 BDT** per the Problem Statement §11.5.

---

## 12. Local debug UI (off by default)

For local development, an opt-in debug console exercises every component. It is **never** exposed to judges or the public — set `ENABLE_UI=true` at startup to mount it.

```bash
ENABLE_UI=true PYTHONPATH=src python -m uvicorn gridwise.app:app --host 127.0.0.1 --port 8000
open http://127.0.0.1:8000/ui
```

Tabs:

| Tab | What it shows |
|---|---|
| 🩺 Service | PID, uptime, health latency, config keys present |
| 📋 Schema validation | Runs 8 malformed payloads against `/optimize-energy` |
| 🎯 Public samples | Pick a case, run via LLM or math mode, see cost diff vs reference |
| 🔍 Directive diff | Per-note comparison of LLM interpretation vs reference |
| 📦 Export | Download the `OptimizeResponse` JSON for a single case |
| 🛡️ Guardrails | 9 hand-rolled bad-input unit tests on `validate_all` |
| ⚙️ Optimizer | All 10 cases math-only, summary stats + cost comparison chart |
| 🔁 Replay (EOD) | E[23] vs initial for every case (battery neutrality) |
| 🔒 Logs & secrets | Greps the live uvicorn log for accidental API-key leakage |
| ⏱️ Performance | N-request latency burst (p50/p95/max, status counts) |
| 🐳 Docker | Read-only `docker images` / `docker ps` snapshot |

With `ENABLE_UI` unset, `/ui` returns 404 and `/ui/api/*` does not exist — judges see only `/health` and `/optimize-energy`.

---

## 13. Credits — three branches, one submission

This codebase is the product of three independent branches merged into one final submission. Provenance is preserved in the top-of-file comments of each module.

| Branch | What we kept | Why |
|---|---|---|
| **Aurna** (`app/optimizer.py`) | Exact cost objective `Σ grid[h] · tariff[h]` with `1e-6` complementarity penalty. `masked_api_key` log helper. | Matches reference optimum to the paisa on all 10 public cases (0.00 BDT diff). |
| **Pulok** (`app/llm_interpreter.py`) | Regex-from-raw-text safety net as the always-available final fallback. MILP mutual-exclusion theory as the basis for charge/discharge window handling. | Regex safety net keeps `/optimize-energy` returning 200 even when every LLM is down. |
| **Ashik** (this base, `src/gridwise/`) | 4-provider LLM chain, 12-check validator, 17-unit-test guardrail suite, hardened multi-stage Dockerfile (non-root + urllib healthcheck), `ENABLE_UI`-gated debug console, Pydantic v2 schemas with per-directive adjustment models. | Best operational resilience; the foundation everything else merges into. |

**Team:** Aurna · Pulok · Ashik (Team Ai-Will-Fix-It)

**Stack:** FastAPI + Uvicorn · Pydantic v2 · PuLP (CBC) · scipy (HiGHS fallback) · httpx · pytest
