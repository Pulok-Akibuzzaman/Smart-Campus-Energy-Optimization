# GridWise — Smart Campus Energy Optimization (LLM-Assisted)

> **BUP CSE Fest 2026 — Hackathon Preliminary**
> **Team:** *Ai-Will-Fix-It*
> **Branch:** `onik`

LLM-assisted 24-hour energy scheduler. Receives a 24-hour campus energy scenario plus 1–3 free-form operator notes, interprets each note via an LLM, applies deterministic guardrails, solves an LP, and returns a valid minimum-cost battery + grid schedule.

---

## 1. What it does

```
POST /optimize-energy
       │
       ▼
  Pydantic schema validation           (Section 07)
       │
       ▼
  LLM interpreter (Groq → Gemini → OpenRouter → regex safety net)
       │
       ▼
  Deterministic guardrails              (Section 08)
       │     ├─ directive_type ∈ {solar_reduction, minimum_battery_reserve,
       │     │                    no_charge_window, no_discharge_window,
       │     │                    max_grid_window, no_op}
       │     ├─ hours: unique ints 0..23 ascending
       │     ├─ factor ∈ [0, 1]
       │     └─ applies = false only for no_op
       ▼
  Constraint translator → per-hour arrays
       ▼
  LP optimizer (PuLP/CBC primary, scipy HiGHS fallback)
       │     minimize Σ grid[h] · tariff[h]
       │     subject to energy balance, battery dynamics, charge/discharge
       │     windows, grid cap, raised reserve, effective solar, EOD neutrality
       ▼
  Replay validator + total derivation   (Section 11.3)
       │
       ▼
  OptimizeResponse JSON
```

The principle from the rubric is mirrored at every layer: **never trust the previous layer's output blindly**. The LLM is untrusted until guardrailed; the optimizer is untrusted until replayed.

---

## 2. Local quickstart

### 2.1 Native Python (recommended for development)

```bash
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It.git
cd Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It
git checkout onik

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add at least one LLM key (Groq recommended — free + fast)
# GROQ_API_KEY=...

export PYTHONPATH=src
uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
```

### 2.2 Docker

```bash
# Build the image
docker build -t ai-will-fix-it/gridwise:latest .

# Run with environment file (recommended)
docker run --rm -p 8000:8000 --env-file .env ai-will-fix-it/gridwise:latest

# Or run with docker-compose
docker compose up --build
```

### 2.3 Verify it works

```bash
# Health check
curl -s http://127.0.0.1:8000/health
# -> {"status":"ok"}

# Run all 10 public sample cases through the optimizer (math path only,
# bypasses the LLM by feeding the expected directive list directly)
PYTHONPATH=src python tests/test_public_samples.py
# Expected: 10/10 valid, avg quality_ratio ≈ 1.000
```

---

## 3. Endpoints

### 3.1 `GET /health`

| Property | Value |
|---|---|
| Purpose | Readiness for the judging harness |
| Response | `200 {"status": "ok"}` |
| Latency target | < 60 s from service start |

### 3.2 `POST /optimize-energy`

Accepts one scenario JSON per the Problem Statement Section 07, returns the directive interpretation plus the optimized 24-hour plan per Section 10.

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

### 3.3 HTTP status codes

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

> **Secrets are never committed.** The image does not bake in any keys. Use `.env` (gitignored) or pass keys via `--env-file` / `-e`.

---

## 5. LLM role (mandatory)

Per the rubric, the **language model must sit in the operator-note interpretation path**. This service uses an OpenAI-compatible HTTP API with the following provider chain:

1. **Groq** (`llama-3.1-8b-instant`) — primary, fastest, free tier
2. **Gemini** (`gemini-1.5-flash`) — fallback #1
3. **OpenRouter** (free models) — fallback #2
4. **Deterministic regex** — safety net. Only activates if **every** LLM provider fails. Never crashes.

The strict-JSON system prompt lives in `src/gridwise/prompts.py` and:
- Lists every supported directive type and its required shape
- Bakes the time-window rule (`"1 PM to 3 PM" → [13, 14]`)
- Bakes the solar-factor rule (`"80% reduction" → factor 0.2`)
- Forbids inventing unsupported directive types
- Forces distractors (cafeteria menu, registration deadlines, drills) to `no_op`

The validator re-checks every directive against the Section 08 guardrails before it can influence the optimizer. Any malformed LLM output is coerced to `no_op` rather than crashing.

---

## 6. Optimizer

Primary: **PuLP** with the bundled **CBC** solver (pure Python, free, solves the 24-hour LP in milliseconds).
Fallback: **scipy.optimize.linprog** with the **HiGHS** solver.

Decision variables per hour: `grid_kwh`, `solar_used_kwh`, `battery_charge_kwh`, `battery_discharge_kwh`, `battery_energy_after_kwh`.

Objective: minimize `Σ grid_kwh[h] · tariff_bdt_per_kwh[h]`.

Constraints: energy balance, battery dynamics (E[h] = E[h−1] + charge − discharge), battery bounds (with raised minimum in `minimum_battery_reserve` windows), charge/discharge rate limits, charge/discharge disabled in their respective window directives, `grid_kwh ≤ max_grid_kwh` in `max_grid_window` hours, `solar_used ≤ effective_solar`, and explicit end-of-day battery neutrality (E[23] = initial).

---

## 7. Testing

```bash
# Math path only — feeds the expected directive list into the optimizer,
# tests correctness + cost quality against the reference.
PYTHONPATH=src python tests/test_public_samples.py
```

Expected output:

```
[OK ] SAMPLE-01  Solar cleaning + distractor
[OK ] SAMPLE-02  Battery charging maintenance
...
Summary: 10/10 cases valid (math only)
         avg quality_ratio: 0.999
```

---

## 8. Project layout

```
ai-will-fix-it/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── requirements.txt
├── docs/
│   └── ARCHITECTURE.md
├── src/
│   └── gridwise/
│       ├── __init__.py
│       ├── app.py            # FastAPI routes
│       ├── schemas.py        # Pydantic models
│       ├── config.py         # Env loader
│       ├── prompts.py        # LLM system prompt
│       ├── interpreter.py    # LLM provider chain + regex fallback
│       ├── validator.py      # Guardrails (Section 08)
│       ├── constraints.py    # Directive → per-hour arrays
│       ├── optimizer.py      # PuLP + scipy LP
│       └── replay.py         # Self-validate + total derivation
└── tests/
    └── test_public_samples.py
```

---

## 9. Known limitations

- **LLM interpretation robustness** depends on the chosen provider. If paraphrases are highly unusual, the LLM may misinterpret a note. The deterministic validator coerces bad LLM output to `no_op` (smaller loss than an invented directive).
- **PuLP** is preferred over scipy linprog; if PuLP's bundled CBC fails to install, the service transparently falls back to scipy.
- The regex safety net is intentionally narrow — it covers the public sample patterns only. In production, real LLM providers must be configured.
- **Numeric tolerance** for judge comparisons is **0.01 kWh / 0.01 BDT** per the Problem Statement §11.5.

---

## 9.5 Local debug UI (off by default)

For local development, an opt-in debug console exercises every component. It is **never** exposed to judges or the public — set `ENABLE_UI=true` at startup to mount it.

```bash
# Boot with UI enabled
ENABLE_UI=true PYTHONPATH=src python -m uvicorn gridwise.app:app --host 127.0.0.1 --port 8000

# Open in browser
open http://127.0.0.1:8000/ui
```

Tabs:

| Tab | What it shows |
|---|---|
| 🩺 **Service** | PID, uptime, health latency, config keys present |
| 📋 **Schema validation** | Runs 8 malformed payloads against `/optimize-energy` |
| 🎯 **Public samples** | Pick a case, run via LLM or math mode, see cost diff vs reference |
| 🛡️ **Guardrails** | 9 hand-rolled bad-input unit tests on `validate_all` |
| ⚙️ **Optimizer** | All 10 cases math-only, summary stats + cost comparison chart |
| 🔁 **Replay (EOD)** | E[23] vs initial for every case (battery neutrality) |
| 🔒 **Logs & secrets** | Greps the live uvicorn log for accidental API-key leakage |
| ⏱️ **Performance** | N-request latency burst (p50/p95/max, status counts) |
| 🐳 **Docker** | Read-only `docker images` / `docker ps` snapshot |

With `ENABLE_UI` unset, `/ui` returns 404 and `/ui/api/*` does not exist — judges see only `/health` and `/optimize-energy`.

---

## 10. Credits

- **Optimizer:** PuLP (LP modeling) with CBC solver; scipy HiGHS fallback
- **Web framework:** FastAPI + Uvicorn
- **Validation:** Pydantic v2
- **LLM provider SDKs:** httpx (OpenAI-compatible REST)
- **Repo pipeline:** `/ecc` plan-and-build conventions (see `ECC/CLAUDE.md`)
