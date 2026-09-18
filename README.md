# GridWise: LLM-Assisted Smart Campus Energy Optimizer
**BUP CSE FEST 2026 Hackathon — Preliminary Round**

---

## 1. System Architecture

The GridWise solution is engineered as an end-to-end decoupled pipeline where human language is interpreted, validated by deterministic guardrails, and fed into an exact mathematical optimizer:

```
[ POST /optimize-energy ]
           │
           ▼
[ 1. LLM Directive Interpreter ]
     • Parses natural-language operator notes into candidate directives:
       (solar_reduction, minimum_battery_reserve, no_charge_window, no_discharge_window, max_grid_window, no_op)
     • Supports Google Gemini (gemini-2.5-flash) and OpenAI / Groq / Local endpoints
     • Zero-crash fallback NLP parser for extreme resilience
           │
           ▼
[ 2. Deterministic Guardrails & Normalizer ]
     • Enforces whole-hour conventions (start-inclusive, end-exclusive)
     • Ensures unique, ascending hours array (0..23)
     • Normalizes reduction factors (e.g. 80% reduction -> 0.20 usable factor)
     • Resolves percentage-based reserve to absolute kWh using battery capacity
     • Enforces strict applies semantics (applies=false and null adjustment only for no_op)
           │
           ▼
[ 3. Mixed-Integer Linear Programming Optimizer (PuLP / HiGHS) ]
     • 24-hour horizon mathematical scheduling minimizing total grid cost:
       min SUM(grid[h] * tariff_bdt_per_kwh[h])
     • Physical constraints:
       - Energy balance: grid[h] + solar_used[h] + discharge[h] == demand[h] + charge[h]
       - Battery rate limits: charge[h] <= max_charge, discharge[h] <= max_discharge
       - Mutual exclusion: charge and discharge never occur simultaneously
       - Battery state transitions & capacity bounds: active_min <= E_after[h] <= capacity
       - End-of-day neutrality: E_after[23] == initial_energy_kwh
       - All operational directive constraints enforced strictly
           │
           ▼
[ 4. Recalculation & API Response Formatter ]
     • Recalculates total_grid_kwh, total_cost_bdt, peak_grid_kwh directly from hourly_plan
     • Generates concise plan_summary and returns exact canonical JSON contract
```

---

## 2. Project Directory Structure

- [**docs/**](./docs/) - Official competition rules & guides
  - [`VIDEO_WALKTHROUGH_SCRIPT.md`](./docs/VIDEO_WALKTHROUGH_SCRIPT.md) - Script for the 3-minute tie-breaker video
- [**data/**](./data/) - Benchmark and sample datasets
  - [`sample_request.json`](./data/sample_request.json) - Sample curl payload
- [**src/**](./src/) - Application source code
  - [`models.py`](./src/models.py) - Pydantic schemas (Section 07 & 10)
  - [`guardrails.py`](./src/guardrails.py) - Deterministic validation & sanitization
  - [`interpreter.py`](./src/interpreter.py) - LLM & fallback directive interpreter
  - [`optimizer.py`](./src/optimizer.py) - PuLP / HiGHS 24h MILP energy solver
  - [`main.py`](./src/main.py) - FastAPI application definition
  - [`static/index.html`](./src/static/index.html) - Interactive Dashboard UI
- [**tests/**](./tests/) - Test and benchmark suites
- [`run_samples.py`](./run_samples.py) - Top-level benchmark runner script
- [`Dockerfile`](./Dockerfile) - Multi-platform container definition
- [`requirements.txt`](./requirements.txt) - Project dependencies
- [`.env.example`](./.env.example) - Environment configuration template

---

## 3. Quickstart (Local Environment)

### Prerequisites
- Python 3.10+
- Git

### Step-by-Step Setup
```bash
# 1. Clone the repository
git clone <repository_url>
cd <repository_folder>

# 2. (Optional) Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the API service
python main.py
# Or with uvicorn:
uvicorn main:app --host 0.0.0.0 --port 8000
```

The service will be listening at `http://localhost:8000`.

---

## 4. Environment Variables & Model Provider Configuration

Create a `.env` file in the root directory (or pass via environment variables):

```bash
# Service Port
PORT=8000

# Primary LLM Option A: Puku.sh AI
PUKU_API_KEY=your_puku_api_key
# PUKU_BASE_URL=https://api-cli.puku.sh
# PUKU_MODEL=puku-ai-2.8

# LLM Option B: Google Gemini
# GEMINI_API_KEY=your_google_gemini_api_key
# GEMINI_MODEL=gemini-2.5-flash

# LLM Option C: OpenAI / Groq / OpenAI-compatible endpoint
# OPENAI_API_KEY=your_openai_or_groq_key
# OPENAI_BASE_URL=https://api.groq.com/openai/v1
# OPENAI_MODEL=llama-3.3-70b-versatile
```

> **Note on Secret Safety**: Never commit `.env` or secrets to git. The service safely redacts all secrets and never exposes API keys, raw prompts with credentials, or internal stack traces in logs or HTTP responses.

---

## 5. API Endpoints & Usage

### 5.1 Interactive Dashboard UI
If you prefer a visual interface to test scenarios instead of curl:
- **[View Dashboard (http://localhost:8000/)](http://localhost:8000/)**

### 5.2 Health Check (Readiness Probe)
- **[Check Status (http://localhost:8000/health)](http://localhost:8000/health)**

```bash
curl -X GET http://localhost:8000/health
```
**Expected Response (HTTP 200)**:
```json
{
  "status": "ok"
}
```

### 5.2 Energy Optimization
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @data/sample_request.json
```

---

## 6. Automated Verification & Public Benchmarks

Run the built-in benchmark script to test all 10 canonical public sample cases:

```bash
# Run local benchmark across all 10 sample cases
python run_samples.py

# Run full integration test suites
python tests/test_optimizer.py
python tests/test_interpreter.py
python tests/test_server.py
```

### Expected Output
```text
===========================================================================
CASE ID      | INTERP   | CALC COST   | EXP COST    | TIME (ms) | STATUS
===========================================================================
SAMPLE-01    | 2 notes  | 38365.00    | 38365.00    | 21.5      | PASS  
SAMPLE-02    | 1 notes  | 42885.00    | 42885.00    | 17.9      | PASS  
SAMPLE-03    | 1 notes  | 35480.00    | 35480.00    | 15.4      | PASS  
SAMPLE-04    | 1 notes  | 40495.00    | 40495.00    | 16.3      | PASS  
SAMPLE-05    | 1 notes  | 33950.00    | 33950.00    | 16.5      | PASS  
SAMPLE-06    | 3 notes  | 34090.00    | 34090.00    | 17.0      | PASS  
SAMPLE-07    | 2 notes  | 38550.00    | 38550.00    | 15.0      | PASS  
SAMPLE-08    | 2 notes  | 37665.00    | 37665.00    | 13.8      | PASS  
SAMPLE-09    | 2 notes  | 34873.00    | 34873.00    | 22.5      | PASS  
SAMPLE-10    | 3 notes  | 41620.00    | 41620.00    | 15.8      | PASS  
===========================================================================
Summary: 10/10 passed | Total Time: 171.7 ms | Avg: 17.2 ms/case
===========================================================================
```

---

## 7. Docker Fallback Execution

The project includes a multi-platform, lightweight container image.

### 7.1 Pull and Run Pre-built Image
```bash
# Pull from registry
docker pull pulokakib/gridwise-solver:v1.0

# Run container binding to port 8000
docker run -d --name gridwise -p 8000:8000 pulokakib/gridwise-solver:v1.0

# Verify health
curl http://localhost:8000/health
```

### 7.2 Build Locally from Source
```bash
docker build -t gridwise-solver:latest .
docker run -p 8000:8000 gridwise-solver:latest
```

---

## 8. Solvers, Libraries & Credits
- **Web Framework**: [FastAPI](https://fastapi.tiangolo.com/) & [Uvicorn](https://www.uvicorn.org/) for async high-performance HTTP service.
- **Data Validation**: [Pydantic v2](https://docs.pydantic.dev/) for strict schema contract enforcement.
- **Optimization Solver**: [PuLP](https://coin-or.github.io/pulp/) with [HiGHS](https://highs.dev/) / COIN-OR CBC for global-optimal MILP solving.
- **UI & Analytics**: [Chart.js](https://www.chartjs.org/) for the dynamic 24-hour dashboard visualization.
- **Language Model (LLM)**: Google **Gemini 2.5 Flash** is our primary LLM for operator note interpretation due to its high speed, massive context window, and robust structured JSON capability. The architecture is fully compatible with OpenAI **GPT-4o** / **GPT-4o-mini** out of the box.
- **AI Coding Assistant**: Development was heavily accelerated using **Google Antigravity** (Advanced Agentic Coding AI) which helped us architect the pipeline, verify edge-case mathematical constraints against the rulebook, and design the interactive UI dashboard.
---

## 9. Known Limitations
- The optimizer operates on a fixed 24-hour discrete horizon ($h \in [0, 23]$).
- Floating-point calculations adhere to standard IEEE-754 precision, verified well within the competition tolerance of 0.01 kWh and 0.01 BDT.
