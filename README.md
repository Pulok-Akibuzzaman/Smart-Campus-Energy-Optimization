# GridWise: LLM-Assisted Smart Campus Energy Optimizer
**BUP CSE FEST 2026 Hackathon — Preliminary Round**  
*Team: Ai-Will-Fix-It*

---

## 1. Project Overview & What Has Been Done

GridWise is an end-to-end, resilient energy scheduling and optimization service designed for a smart university campus microgrid. The system ingests 24-hour forecasts of solar generation, campus energy demand, and time-of-use tariffs alongside unstructured natural-language operator directives. It parses, validates, and mathematically optimizes hourly battery charge/discharge and grid intake to minimize total campus electricity cost while strictly respecting physical, operational, and directive constraints.

### Key Milestones & Completed Features

- [x] **Multi-Tier LLM Directive Interpretation**:
  - **Puku.sh AI Integration**: Primary high-throughput inference engine utilizing `puku-ai-2.8` via Anthropic-compatible messages API (`https://api-cli.puku.sh`).
  - **Google Gemini Integration**: Native support for `gemini-2.5-flash` / `gemini-1.5-pro` with structured JSON output mode.
  - **OpenAI / Groq Compatibility**: Flexible adapter for OpenAI-compatible endpoints (`gpt-4o-mini`, `llama-3.3-70b-versatile`).
  - **Deterministic NLP Heuristic Fallback Engine**: Fully offline, regex-based semantic parser capable of extracting all 6 directive types, parsing whole-hour intervals (start-inclusive, end-exclusive), resolving reduction factors/percentages, and filtering non-operational distractors with zero external network dependency.

- [x] **Deterministic Safety Guardrails & Sanitizer** ([`src/guardrails.py`](./src/guardrails.py)):
  - Canonical time-window validation guaranteeing unique, ascending hour arrays in `[0..23]`.
  - Normalization of reduction factors (e.g., 80% reduction $\rightarrow$ 0.20 usable factor).
  - Absolute energy conversion for percentage reserves using physical battery capacity.
  - Strict enforcement of competition schema semantics (`applies: false` $\iff$ `directive_type: "no_op"`).
  - Zero-crash guarantee against malformed, incomplete, or adversarial LLM outputs.

- [x] **Mixed-Integer Linear Programming (MILP) Optimizer** ([`src/optimizer.py`](./src/optimizer.py)):
  - Mathematical 24-hour horizon solver built on **PuLP** with **HiGHS / CBC**.
  - Objective: $\min \sum_{h=0}^{23} (\text{grid}[h] \times \text{tariff}[h])$.
  - Exact enforcement of hourly energy balance, battery rate constraints, mutual exclusion of simultaneous charge/discharge, storage capacity bounds, and end-of-day neutrality ($E_{23} = E_{\text{initial}}$).
  - High performance: Solves 24-hour schedules in **~16 ms** per scenario with 100% exact ground-truth cost match.

- [x] **Production FastAPI HTTP Service & Live Dashboard** ([`src/main.py`](./src/main.py)):
  - `GET /health`: Fast readiness probe returning service metadata (HTTP 200).
  - `POST /optimize-energy`: Canonical solver endpoint accepting scenario JSON and outputting the official `OptimizeEnergyResponse` contract with recomputed totals and human-readable plan summaries.
  - `GET /`: Interactive web dashboard powered by Chart.js featuring real-time scenario benchmarking, hourly energy flow graphs, and battery state-of-charge tracking.

- [x] **Comprehensive Testing & Benchmark Suite**:
  - 10/10 official public sample cases verified with $0.00$ BDT cost discrepancy.
  - Automated test suites for interpreter parsing, physical constraint validation, and API HTTP error handling.

- [x] **Deployment & Containerization**:
  - Dockerized with a lightweight multi-platform image ready for immediate cloud deployment.

---

## 2. System Architecture

```
[ POST /optimize-energy ]
           │
           ▼
[ 1. Multi-Tier LLM Directive Interpreter ]
     • 1st Priority: Puku.sh AI (puku-ai-2.8)
     • 2nd Priority: Google Gemini (gemini-2.5-flash)
     • 3rd Priority: OpenAI / Groq / Local endpoints
     • Safety Tier: Deterministic Heuristic NLP Fallback
           │
           ▼
[ 2. Deterministic Guardrails & Normalizer ]
     • Enforces whole-hour conventions (start-inclusive, end-exclusive)
     • Validates & canonicalizes time windows from note text
     • Clamps reduction factors, reserve thresholds, and grid caps
     • Guarantees 1-to-1 directive-to-note mapping and schema integrity
           │
           ▼
[ 3. Mixed-Integer Linear Programming Optimizer (PuLP / HiGHS) ]
     • 24-hour horizon mathematical scheduling minimizing total grid cost:
       min SUM(grid[h] * tariff_bdt_per_kwh[h])
     • Physical constraints:
       - Energy balance: grid[h] + solar_used[h] + discharge[h] == demand[h] + charge[h]
       - Battery rate limits: charge[h] <= max_charge, discharge[h] <= max_discharge
       - Mutual exclusion: charge[h] and discharge[h] cannot be active simultaneously
       - Storage bounds: active_min <= E_after[h] <= capacity
       - Neutrality: E_after[23] == initial_energy_kwh
       - All operational directive constraints enforced strictly
           │
           ▼
[ 4. Recalculation & API Response Formatter ]
     • Recomputes total_grid_kwh, total_cost_bdt, peak_grid_kwh directly from hourly_plan
     • Generates concise plan_summary and returns exact canonical JSON contract
```

---

## 3. Project Directory Structure

```
├── .dockerignore
├── .env.example          <- Environment configuration template
├── .gitignore            <- Secures keys, virtualenvs, logs, and caches
├── Dockerfile            <- Multi-platform production container definition
├── README.md             <- Architecture, API documentation, and credits
├── requirements.txt      <- Core dependencies (fastapi, uvicorn, pulp, requests, pydantic)
├── main.py               <- Root execution entrypoint (python main.py / uvicorn)
├── run_samples.py        <- Automated benchmark verification runner
│
├── src/                  <- Application source code
│   ├── __init__.py
│   ├── main.py           <- FastAPI app: GET /health, POST /optimize-energy, GET /
│   ├── models.py         <- Pydantic schemas (Section 07 & 10)
│   ├── interpreter.py    <- LLM & heuristic directive interpreter
│   ├── guardrails.py     <- Deterministic validation, sanitization & time parsing
│   ├── optimizer.py      <- 24-hour MILP energy solver (PuLP / HiGHS)
│   └── static/
│       └── index.html    <- Interactive Campus Energy Management Dashboard UI
│
├── data/                 <- Benchmark and sample datasets
│   ├── BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json
│   └── sample_request.json
│
├── docs/                 <- Guidelines, scripts, and documentation
│   ├── BUP_CSE_FEST_2026_Participant_Guide_&_Evaluation_Rubric_GridWise_LLM.pdf
│   ├── BUP_CSE_FEST_2026_Preliminary_Problem_Statement_GridWise_LLM.pdf
│   ├── FINAL_SUBMISSION_DOCUMENTATION.md / .pdf
│   └── VIDEO_WALKTHROUGH_SCRIPT.md
│
└── tests/                <- Automated test and validation suites
    ├── __init__.py
    ├── test_interpreter.py  <- 10/10 scenario directive parsing tests
    ├── test_optimizer.py    <- Physical battery & microgrid constraint tests
    └── test_server.py       <- API endpoint tests & error handling
```

---

## 4. Step-by-Step Guide: How to Run

### Step 1: Clone the Repository
```bash
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It.git
cd Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It
```

### Step 2: Set Up Virtual Environment (Recommended)
**On Windows (PowerShell / Command Prompt):**
```powershell
python -m venv .venv
.venv\Scripts\activate
```
**On Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Step 3: Install Required Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables
Copy `.env.example` to create your `.env` file:
```bash
# On Windows (PowerShell):
Copy-Item .env.example .env

# On Linux / macOS:
cp .env.example .env
```
*(Optional)* Open `.env` in a text editor to configure your preferred LLM API keys (Puku.sh, Google Gemini, or OpenAI/Groq). If no API key is provided, the service runs completely offline using the built-in deterministic heuristic fallback engine.

### Step 5: Start the API Service
Run the service using either of the following commands:

**Option A — Direct Python Runner:**
```bash
python main.py
```

**Option B — Uvicorn Server:**
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

The service will start listening at: `http://localhost:8000`

---

### Step 6: Verify the Running Service

#### 1. Open the Interactive Web Dashboard
Open your web browser and navigate to:
- **Interactive UI Dashboard**: [http://localhost:8000/](http://localhost:8000/)
- **Swagger / OpenAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)

#### 2. Test the Health Endpoint (`GET /health`)
```bash
curl -X GET http://localhost:8000/health
```
*Expected Response (HTTP 200):*
```json
{
  "status": "healthy",
  "service": "GridWise",
  "version": "2.0.0"
}
```

#### 3. Test Energy Optimization (`POST /optimize-energy`)
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @data/sample_request.json
```

---

### Step 7: Run Automated Verification Benchmarks
To run the automated benchmark runner against all 10 official public scenarios:
```bash
python run_samples.py
```

To run individual test suites:
```bash
python tests/test_optimizer.py
python tests/test_interpreter.py
python tests/test_server.py
```

---

### Step 8: Expose Publicly for Evaluation (Hackathon Submission)
If you need a live public URL for the hackathon evaluation:

- **Using ngrok**:
  ```bash
  ngrok http 8000
  ```
- **Using localtunnel**:
  ```bash
  npx localtunnel --port 8000
  ```
- **Using Docker**:
  ```bash
  docker build -t gridwise-solver:latest .
  docker run -p 8000:8000 gridwise-solver:latest
  ```

---

## 5. Environment Variables & Model Provider Configuration

Create a `.env` file in the root directory (or configure system environment variables):

```bash
# Service Port
PORT=8000

# Primary LLM Option A: Puku.sh AI
PUKU_API_KEY=your_puku_api_key
PUKU_BASE_URL=https://api-cli.puku.sh
PUKU_MODEL=puku-ai-2.8
PUKU_TIMEOUT=25

# LLM Option B: Google Gemini
# GEMINI_API_KEY=your_google_gemini_api_key
# GEMINI_MODEL=gemini-2.5-flash

# LLM Option C: OpenAI / Groq / OpenAI-compatible endpoint
# OPENAI_API_KEY=your_openai_or_groq_key
# OPENAI_BASE_URL=https://api.groq.com/openai/v1
# OPENAI_MODEL=llama-3.3-70b-versatile
```

> **Security Note**: Never commit `.env` or sensitive API keys to git. The service redacts credentials and never logs or exposes internal keys or stack traces in HTTP responses.

---

## 6. API Endpoints & Usage

### 6.1 Interactive Dashboard UI
Visit `http://localhost:8000/` in any browser to inspect hourly dispatch schedules, test operator note scenarios, and view live interactive Chart.js microgrid diagrams.

### 6.2 Health Check (Readiness Probe)
```bash
curl -X GET http://localhost:8000/health
```
**Response (HTTP 200)**:
```json
{
  "status": "healthy",
  "service": "GridWise",
  "version": "2.0.0"
}
```

### 6.3 Energy Optimization Endpoint
```bash
curl -X POST http://localhost:8000/optimize-energy \
  -H "Content-Type: application/json" \
  -d @data/sample_request.json
```

---

## 7. Verification & Benchmark Results

Run the automated benchmark runner to evaluate all 10 canonical public sample cases:

```bash
python run_samples.py
```

### Official Benchmark Verification Output
```text
===========================================================================
CASE ID      | INTERP   | CALC COST   | EXP COST    | TIME (ms) | STATUS
===========================================================================
SAMPLE-01    | 2 notes  | 38365.00    | 38365.00    | 20.4      | PASS  
SAMPLE-02    | 1 notes  | 42885.00    | 42885.00    | 17.6      | PASS  
SAMPLE-03    | 1 notes  | 35480.00    | 35480.00    | 15.0      | PASS  
SAMPLE-04    | 1 notes  | 40495.00    | 40495.00    | 15.5      | PASS  
SAMPLE-05    | 1 notes  | 33950.00    | 33950.00    | 16.1      | PASS  
SAMPLE-06    | 3 notes  | 34090.00    | 34090.00    | 15.4      | PASS  
SAMPLE-07    | 2 notes  | 38550.00    | 38550.00    | 14.4      | PASS  
SAMPLE-08    | 2 notes  | 37665.00    | 37665.00    | 12.7      | PASS  
SAMPLE-09    | 2 notes  | 34873.00    | 34873.00    | 21.9      | PASS  
SAMPLE-10    | 3 notes  | 41620.00    | 41620.00    | 15.5      | PASS  
===========================================================================
Summary: 10/10 passed | Total Time: 164.4 ms | Avg: 16.4 ms/case
===========================================================================
```

---

## 8. Docker Deployment

### 8.1 Build Locally from Source
```bash
docker build -t gridwise-solver:latest .
docker run -p 8000:8000 gridwise-solver:latest
```

### 8.2 Pull and Run Pre-built Image
```bash
docker pull pulokakib/gridwise-solver:v1.0
docker run -d --name gridwise -p 8000:8000 pulokakib/gridwise-solver:v1.0
```

---

## 9. Credits & Acknowledgments

- **Team**: **Ai-Will-Fix-It**

### Technology & Tool Credits
- **LLM Platforms**:
  - **[Puku.sh](https://puku.sh/)**: High-performance AI inference engine providing the fast `puku-ai-2.8` model backend.
  - **[Google Gemini](https://ai.google.dev/)**: State-of-the-art multi-modal language model providing structured JSON directive interpretation.
  - **[OpenAI](https://platform.openai.com/) / [Groq](https://groq.com/)**: High-speed secondary LLM inference support.
- **AI Coding Assistant**:
  - **Google Antigravity**: Advanced Agentic Coding AI from Google DeepMind, instrumental in architecting the decoupled pipeline, verifying complex microgrid constraints against competition rubrics, and rapid engineering.
- **Mathematical Optimization & Web Stack**:
  - **[FastAPI](https://fastapi.tiangolo.com/) & [Uvicorn](https://www.uvicorn.org/)**: Asynchronous, high-throughput microservice framework.
  - **[PuLP](https://coin-or.github.io/pulp/) & [HiGHS](https://highs.dev/)**: High-performance open-source Mixed-Integer Linear Programming solvers.
  - **[Pydantic v2](https://docs.pydantic.dev/)**: Robust data parsing and strict schema validation.
  - **[Chart.js](https://www.chartjs.org/)**: Visualizations for 24-hour campus energy scheduling.
