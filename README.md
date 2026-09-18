# GridWise — Smart Campus Energy Optimization Service

> **BUP CSE Fest 2026 · Hackathon · Online Preliminary Round**  
> **Challenge**: LLM-Assisted Operator Directive Interpretation & 24-Hour Campus Energy Optimization  
> **Canonical Problem Statement Compliant**: Endpoints `GET /health` and `POST /optimize-energy`

---

## 1. Executive Summary & Architecture Overview

GridWise is an end-to-end autonomous energy scheduling service designed for the Bangladesh University of Professionals (BUP) smart campus. It receives a 24-hour campus energy forecast (demand, solar, time-of-use tariffs, battery specs) alongside 1–3 natural-language operator notes, interprets temporary operational directives using a Large Language Model, validates the directives deterministically through strict guardrails, and optimizes the 24-hour dispatch using high-performance linear programming.

```
┌───────────────────────────────────────┐
│ Energy Scenario + 1–3 Operator Notes  │
└──────────────────┬────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────┐
│ 1. LLM Directive Interpreter          │  ◄── Language model extracts structured JSON
│    (OpenAI / Anthropic / Groq / Local)│      (directive_type, hours, factors, reserves, caps)
└──────────────────┬────────────────────┘
                   │ Untrusted output
                   ▼
┌───────────────────────────────────────┐
│ 2. Deterministic Guardrail Validator  │  ◄── Validates 6 canonical types, note mappings,
│    (Zero-crash fallback & repair)     │      bounds, hours 0..23, and applies semantics
└──────────────────┬────────────────────┘
                   │ Verified machine directives
                   ▼
┌───────────────────────────────────────┐
│ 3. Mathematical LP Optimizer          │  ◄── SciPy HiGHS LP Solver (<5 ms solve time):
│    (Linear Programming with HiGHS)    │      Minimizes total BDT cost, satisfies balance,
└──────────────────┬────────────────────┘      rates, battery bounds & end-of-day neutrality
                   │ Candidate 24-hour schedule
                   ▼
┌───────────────────────────────────────┐
│ 4. Defense-in-Depth Self-Replay Engine│  ◄── Verifies energy balance (tol: 0.01),
│    (Re-simulates hourly state)        │      battery neutrality, rate limits, recalc totals
└──────────────────┬────────────────────┘
                   │ Verified optimal schedule
                   ▼
┌───────────────────────────────────────┐
│ 5. API Response (HTTP 200 JSON)       │
└───────────────────────────────────────┘
```

---

## 2. Pipeline Components

### 2.1 LLM Directive Interpreter (Mandatory AI Path)
- **Role**: Generalizes across unseen natural-language operator notes and translates human instructions into machine-checkable directives.
- **Supported Directive Types** (Canonical 6 types only):
  1. `solar_reduction`: `{"hours": [...], "factor": number}` where `factor` is the usable fraction remaining ($80\%\text{ reduction} \to 0.20$).
  2. `minimum_battery_reserve`: `{"hours": [...], "minimum_energy_kwh": number}` (percentage reserves like $50\%$ are resolved using the scenario's battery capacity).
  3. `no_charge_window`: `{"hours": [...]}` disables charging during listed hours.
  4. `no_discharge_window`: `{"hours": [...]}` disables discharging during listed hours.
  5. `max_grid_window`: `{"hours": [...], "max_grid_kwh": number}` enforces grid import cap.
  6. `no_op`: Distractors that do not impact today's schedule (`applies: false`, `structured_adjustment: null`).
- **Prompt Engineering**: System prompt embeds start-inclusive end-exclusive whole-hour conventions (e.g. `1 PM to 3 PM` $\to `[13, 14]`$), remaining factor math, few-shot calibrations, and distractor suppression.
- **Provider Support**: Seamlessly swappable across OpenAI (`gpt-4o-mini`, `gpt-4o`), Anthropic (`claude-3-5-haiku-20241022`), Groq (`llama-3.3-70b-versatile`), and custom OpenAI-compatible local endpoints.
- **Safe Offline Calibrator**: When no API key is provided (`LLM_PROVIDER=offline`), a built-in semantic parser acts as a fail-safe fallback so that `/health` and local reproducibility tests work out-of-the-box without network failure.

### 2.2 Deterministic Guardrails
LLM output is treated as untrusted data before touching the optimizer:
- Rejects any unapproved directive type (falls back safely to `no_op`).
- Enforces strict $1:1$ note mapping for `note_index` $0 \dots N-1$.
- Validates that `hours` are unique integers in $[0, 23]$ in ascending order.
- Bounds `solar_reduction.factor` to $[0.0, 1.0]$.
- Bounds `minimum_battery_reserve` to $[0.0, \text{capacity\_kwh}]$.
- Enforces `applies == false` iff `no_op`.
- Defends against prompt injection or hallucinated attempts to alter base demand, tariffs, or battery constants.

### 2.3 Mathematical Optimizer (SciPy HiGHS LP Solver)
- Formulates a 24-hour Linear Program (120 variables) solved via `scipy.optimize.linprog(method='highs')`.
- **Solve Latency**: $1 \text{ to } 3 \text{ ms}$ (enabling p95 API response times $< 15 \text{ ms}$, far surpassing the $5\text{s}$ scoring threshold).
- **Physical Constraints**:
  - Hourly energy balance: $\text{grid}_h + \text{solar\_used}_h + \text{discharge}_h = \text{demand}_h + \text{charge}_h$.
  - Solar curtailment: $0 \le \text{solar\_used}_h \le \text{effective\_solar}_h$.
  - Battery dynamics: $E_h = E_{h-1} + \text{charge}_h - \text{discharge}_h$, $E_{-1} = \text{initial\_energy}$.
  - State bounds: $\max(\text{min\_energy}, \text{directive\_reserve}_h) \le E_h \le \text{capacity}$.
  - Rate limits: $\text{charge}_h \le \text{max\_charge}$, $\text{discharge}_h \le \text{max\_discharge}$.
  - Grid caps: $\text{grid}_h \le \text{max\_grid}_h$ for active windows.
  - End-of-day neutrality: $E_{23} = \text{initial\_energy}$ (battery cannot be depleted as a free one-time energy source).
  - Complementarity penalty: $10^{-6} \times (\text{charge}_h + \text{discharge}_h)$ prevents simultaneous charge and discharge.

### 2.4 Defense-in-Depth Validator
Replays the schedule step-by-step:
- Verifies every constraint within $0.01 \text{ kWh}$ / $0.01 \text{ BDT}$ tolerance.
- Re-sums `total_grid_kwh`, recalculates `total_cost_bdt`, and checks `peak_grid_kwh`.
- Generates a concise `plan_summary`.

---

## 3. Environment Variables & Configuration

Configure via environment variables or a `.env` file:

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `HOST` | string | `0.0.0.0` | Binding host address |
| `PORT` | int | `8000` | Binding service port |
| `LLM_PROVIDER` | string | `openai` | Model provider: `openai`, `anthropic`, `groq`, `custom`, `offline` |
| `LLM_API_KEY` | string | *None* | Provider API key (automatically masked in logs) |
| `LLM_MODEL` | string | *Auto* | Model name (e.g., `gpt-4o-mini`, `claude-3-5-haiku-20241022`) |
| `LLM_BASE_URL` | string | *None* | Optional custom base URL (e.g. for Ollama / vLLM / Groq) |
| `LLM_TIMEOUT_SECONDS` | float | `8.0` | Request timeout for upstream LLM calls |

*Secret Handling Policy*: API keys are never written to logs or responses. If `LLM_API_KEY` is not set, the service defaults to safe offline semantic parsing.

---

## 4. Local Quickstart (Clean Environment)

### Step 1: Clone & Navigate
```bash
git clone <repository_url>
cd Hackathon
```

### Step 2: Create & Activate Virtual Environment
```bash
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Configure Environment (Optional for Live LLM)
```bash
# To use OpenAI:
export LLM_PROVIDER=openai
export LLM_API_KEY="sk-..."
export LLM_MODEL="gpt-4o-mini"

# Or on Windows PowerShell:
$env:LLM_PROVIDER="openai"
$env:LLM_API_KEY="sk-..."
$env:LLM_MODEL="gpt-4o-mini"
```
*(If no key is configured, GridWise runs with the offline calibrator for instant verification.)*

### Step 5: Start the Service
```bash
python run.py
# Or alternatively:
uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws none
```
The service becomes healthy within $< 2 \text{ seconds}$.

### Step 6: Interactive Dashboard & API Docs (Visual Demo Aid)
Open your web browser:
- **Interactive Visual Dashboard**: `http://localhost:8000/dashboard` (or `http://localhost:8000/`)
  - *Purpose*: Visual demonstration aid for video recording and team testing. Displays the live 5-stage pipeline stepper (**Energy Data $\to$ LLM Interpreter $\to$ Guardrails $\to$ LP Optimizer $\to$ Defense-in-Depth Validator**), note-to-directive mapping cards, paraphrase test chips, and 24-hour Chart.js energy/battery dispatch charts.
  - *Grading Contract Isolation*: Built with pure static frontend files calling `POST /optimize-energy` from the client. It places **zero authentication, zero middleware, and zero latency overhead** on the graded API endpoints.
- **FastAPI Interactive Swagger Docs**: `http://localhost:8000/docs`

---

## 5. Automated Verification & Public Case Testing

Run the included end-to-end test suite that exercises:
- `GET /health` readiness
- `POST /optimize-energy` against all 10 public sample scenarios
- Strict schema validation and error handling (HTTP 400)
- Optimal cost and grid tolerance checks ($< 0.01$)

```bash
python test_solution.py
```

### Expected Output:
```text
======================================================================
STARTING GRIDWISE TEST SUITE: BUP CSE FEST 2026
======================================================================

[TEST 1] Testing GET /health...
  [OK] /health returned 200 OK in 1.60 ms: {'status': 'ok'}

[TEST 2] Testing POST /optimize-energy across 10 Public Sample Cases...
  Found 10 sample cases to evaluate.
  [PASS] SAMPLE-01 (Solar cleaning + distractor): Cost=38365.00 BDT (ref 38365.00, diff=0.0000)
  [PASS] SAMPLE-02 (Battery charging maintenance): Cost=42885.00 BDT (ref 42885.00, diff=0.0000)
  [PASS] SAMPLE-03 (Emergency reserve as percentage): Cost=35480.00 BDT (ref 35480.00, diff=0.0000)
  [PASS] SAMPLE-04 (No-discharge protection test): Cost=40495.00 BDT (ref 40495.00, diff=0.0000)
  [PASS] SAMPLE-05 (Temporary feeder grid cap): Cost=33950.00 BDT (ref 33950.00, diff=0.0000)
  [PASS] SAMPLE-06 (Multiple notes with distractor): Cost=34090.00 BDT (ref 34090.00, diff=0.0000)
  [PASS] SAMPLE-07 (Reserve plus transformer cap): Cost=38550.00 BDT (ref 38550.00, diff=0.0000)
  [PASS] SAMPLE-08 (Separate charge/discharge outages): Cost=37665.00 BDT (ref 37665.00, diff=0.0000)
  [PASS] SAMPLE-09 (Reduction wording normalization): Cost=34873.00 BDT (ref 34873.00, diff=0.0000)
  [PASS] SAMPLE-10 (Multi-constraint evening operation): Cost=41620.00 BDT (ref 41620.00, diff=0.0000)

  Latency stats: Avg = 6.06 ms | P95 = 12.91 ms

[TEST 3] Testing Malformed Request Handling (HTTP 400)...
  [OK] 23 hours rejected with HTTP 400: Malformed or structurally invalid JSON input schema.
  [OK] Missing scenario_id rejected with HTTP 400: Malformed or structurally invalid JSON input schema.
  [OK] Empty operator_notes rejected with HTTP 400: Malformed or structurally invalid JSON input schema.

======================================================================
ALL 10 PUBLIC SAMPLE CASES & SYSTEM TESTS PASSED SUCCESSFULLY! (100% SCORE)
======================================================================
```

---

## 6. API Examples (cURL)

### 6.1 Health Check (`GET /health`)
```bash
curl -X GET http://localhost:8000/health
```
**Response (HTTP 200):**
```json
{
  "status": "ok"
}
```

### 6.2 Energy Optimization (`POST /optimize-energy`)
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "SAMPLE-01",
    "operator_notes": [
      "Facilities will wash the rooftop solar panels from noon until 2 PM. During cleaning, usable solar should be treated as roughly 25% of the forecast.",
      "The sports office moved next months registration deadline."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 90, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 1, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 2, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 3, "demand_kwh": 80, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 4, "demand_kwh": 85, "solar_kwh": 0, "tariff_bdt_per_kwh": 5},
      {"hour": 5, "demand_kwh": 95, "solar_kwh": 0, "tariff_bdt_per_kwh": 6},
      {"hour": 6, "demand_kwh": 110, "solar_kwh": 5, "tariff_bdt_per_kwh": 8},
      {"hour": 7, "demand_kwh": 130, "solar_kwh": 20, "tariff_bdt_per_kwh": 10},
      {"hour": 8, "demand_kwh": 150, "solar_kwh": 50, "tariff_bdt_per_kwh": 12},
      {"hour": 9, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 10, "demand_kwh": 175, "solar_kwh": 130, "tariff_bdt_per_kwh": 16},
      {"hour": 11, "demand_kwh": 180, "solar_kwh": 160, "tariff_bdt_per_kwh": 16},
      {"hour": 12, "demand_kwh": 185, "solar_kwh": 180, "tariff_bdt_per_kwh": 15},
      {"hour": 13, "demand_kwh": 180, "solar_kwh": 170, "tariff_bdt_per_kwh": 14},
      {"hour": 14, "demand_kwh": 170, "solar_kwh": 140, "tariff_bdt_per_kwh": 13},
      {"hour": 15, "demand_kwh": 165, "solar_kwh": 90, "tariff_bdt_per_kwh": 14},
      {"hour": 16, "demand_kwh": 170, "solar_kwh": 45, "tariff_bdt_per_kwh": 18},
      {"hour": 17, "demand_kwh": 185, "solar_kwh": 10, "tariff_bdt_per_kwh": 22},
      {"hour": 18, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 28},
      {"hour": 19, "demand_kwh": 215, "solar_kwh": 0, "tariff_bdt_per_kwh": 30},
      {"hour": 20, "demand_kwh": 205, "solar_kwh": 0, "tariff_bdt_per_kwh": 26},
      {"hour": 21, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 18},
      {"hour": 22, "demand_kwh": 135, "solar_kwh": 0, "tariff_bdt_per_kwh": 10},
      {"hour": 23, "demand_kwh": 105, "solar_kwh": 0, "tariff_bdt_per_kwh": 7}
    ],
    "battery": {
      "capacity_kwh": 220,
      "initial_energy_kwh": 110,
      "minimum_energy_kwh": 40,
      "max_charge_kwh_per_hour": 50,
      "max_discharge_kwh_per_hour": 50
    }
  }'
```

**Response (HTTP 200):**
```json
{
  "scenario_id": "SAMPLE-01",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {
        "hours": [12, 13],
        "factor": 0.25
      },
      "explanation": "Solar availability is reduced to 25% during the panel-cleaning window."
    },
    {
      "note_index": 1,
      "applies": false,
      "directive_type": "no_op",
      "structured_adjustment": null,
      "explanation": "This note does not affect today's 24-hour energy schedule."
    }
  ],
  "hourly_plan": [
    {
      "hour": 0,
      "grid_kwh": 90.0,
      "solar_used_kwh": 0.0,
      "battery_action": "idle",
      "battery_kwh": 0.0,
      "battery_energy_after_kwh": 110.0
    },
    "..."
  ],
  "total_grid_kwh": 2692.5,
  "total_cost_bdt": 38365.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "24-hour optimal dispatch generated successfully..."
}
```

---

## 7. Docker Fallback Instructions

A production-ready Docker container is provided for zero-friction judge evaluation:

### 7.1 Build the Docker Image
```bash
docker build -t gridwise-service:latest .
```

### 7.2 Run the Docker Container
```bash
# Run with exposed port 8000 bound to 0.0.0.0
docker run -d \
  -p 8000:8000 \
  -e LLM_PROVIDER="openai" \
  -e LLM_API_KEY="sk-..." \
  -e LLM_MODEL="gpt-4o-mini" \
  --name gridwise-app \
  gridwise-service:latest
```
*(For offline or self-contained evaluation, simply omit the `LLM_API_KEY` variable.)*

### 7.3 Verify in Docker
```bash
# Check health
curl http://localhost:8000/health

# Run test suite inside container
docker exec gridwise-app python test_solution.py
```

---

## 8. Dependencies & Limitations

### Dependencies
- **FastAPI** (`>=0.110.0`) & **Uvicorn** (`>=0.28.0`): Ultra-low overhead async web server.
- **Pydantic v2** (`>=2.6.0`): Strict, deterministic schema validation.
- **SciPy** (`>=1.11.0`) & **NumPy** (`>=1.26.0`): Built-in C++ HiGHS Linear Programming engine.
- **HTTPX** (`>=0.27.0`): Non-blocking HTTP client.
- **OpenAI** (`>=1.14.0`): Standard client for OpenAI, Groq, and custom gateways.

### Known Limitations & Design Choices
- **Curtailed Solar & Grid Export**: Grid export is strictly disallowed per challenge rules; excess solar above demand and battery charging is automatically curtailed.
- **Time Window Granularity**: All operational directives operate on whole-hour blocks (0..23) with the start-inclusive, end-exclusive convention (e.g., 1 PM to 3 PM is $[13, 14]$).
- **Single-Day Neutrality**: The system strictly restores battery energy to `initial_energy_kwh` at hour 23, ensuring sustained daily cyclic operation.
