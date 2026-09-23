# GridWise — Smart Campus Energy Optimization (LLM-Assisted)

> **BUP CSE Fest 2026 — Hackathon Preliminary · Final Submission**
> **Team:** *Ai-Will-Fix-It*
> **Docker image:** `ashikonik/gridwise-bup-2026:1.0.0`
> **Repo:** [`Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization`](https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization)

An LLM-assisted 24-hour energy scheduler. Receives a 24-hour campus energy scenario plus 1–3 free-form operator notes, interprets each note via a 4-provider LLM chain, applies 12 deterministic guardrails, solves a hybrid linear program, and returns a valid minimum-cost battery + grid schedule — matching the reference optimum to the paisa on all 10 public cases.

---

## Table of Contents

0. [Quick start (TL;DR)](#0-quick-start-tldr)
1. [Why this exists](#why-this-exists)
2. [Architecture](#1-architecture-in-one-screen)
3. [Local quickstart — pick your device](#2-local-quickstart-pick-your-device)
   - 2.1 [Cloud IDE (no local install)](#21-cloud-ide-zero-setup)
   - 2.2 [Linux / macOS / WSL](#22-linux-macos-wsl-one-block)
   - 2.3 [Windows native (PowerShell)](#23-windows-native-powershell)
   - 2.4 [Docker](#24-docker-production-parity)
   - 2.5 [Mobile / tablet / Chromebook](#25-mobile-tablet-chromebook)
   - 2.6 [Run as a systemd service](#26-run-as-a-systemd-service-linux)
   - 2.7 [Verify it works](#27-verify-it-works)
   - 2.8 [Common pitfalls](#28-common-pitfalls-any-platform)
4. [Endpoints](#3-endpoints)
5. [Environment variables](#4-environment-variables)
6. [LLM provider chain](#5-llm-provider-chain)
7. [Optimizer (hybrid)](#6-optimizer-the-hybrid)
8. [Testing](#7-testing)
9. [Project layout](#8-project-layout)
10. [Demo video](#9-demo-video)
11. [Deployment](#10-deployment)
12. [Known limitations](#11-known-limitations)
13. [Debug UI](#12-local-debug-ui-off-by-default)
14. [Credits](#13-credits-three-branches-one-submission)

---

## 0. Quick start (TL;DR)

**Already have Python 3.10+?** Three lines:

```bash
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization.git
cd Smart-Campus-Energy-Optimization
pip install -r requirements.txt && PYTHONPATH=src uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
```

Then open <http://127.0.0.1:8000/docs> for the API, or <http://127.0.0.1:8000/ui> for the interactive console (after `echo ENABLE_UI=true >> .env` and restart).

**No Python locally?** Skip to [§2.1 Cloud IDE](#21-cloud-ide-zero-setup) or [§2.4 Docker](#24-docker-production-parity).

**Prerequisites in one line:** Python ≥ 3.10, pip, ~150 MB disk, one free LLM API key (Groq recommended).

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

## 2. Local quickstart — pick your device

The app is pure-Python. The only system requirement is a working Python and pip. CBC (PuLP's bundled solver) and scipy both ship as wheels — **no compiler, no `apt build-dep`, no system CBC install is required** on any platform.

| Platform | Python | Status |
|---|---|---|
| Ubuntu 22.04 / 24.04 LTS | 3.10, 3.11, 3.12 | ✅ |
| Debian 12 (Bookworm) | 3.10, 3.11 | ✅ |
| Fedora 39 / 40 / 41 | 3.11, 3.12, 3.13 | ✅ |
| RHEL 9 / Rocky 9 / AlmaLinux 9 | 3.10, 3.11, 3.12 | ✅ |
| Arch / Manjaro (rolling) | 3.12 | ✅ |
| openSUSE Leap 15.6 / Tumbleweed | 3.11 | ✅ |
| Alpine 3.20+ | 3.11 | ✅ (musl libc; PuLP wheel is pure Python) |
| macOS 13 Ventura / 14 Sonoma / 15 Sequoia | 3.10, 3.11, 3.12, 3.13 | ✅ (Apple Silicon + Intel) |
| Windows 11 native | 3.10, 3.11, 3.12, 3.13 | ✅ (use `venv\Scripts\activate`) |
| Windows 11 + WSL2 (Ubuntu) | 3.10, 3.11, 3.12 | ✅ (recommended) |
| ChromeOS (Linux dev container) | 3.11 | ✅ |
| Cloud IDE (Codespaces / Gitpod / Replit) | 3.11 | ✅ |
| iOS / Android (via cloud IDE + browser) | n/a | ✅ (no local install) |

---

### 2.1 Cloud IDE — zero setup

If you don't want to touch your machine at all, open the repo in a cloud IDE and skip directly to running it.

**GitHub Codespaces** (free 60 hr/month):
1. Go to <https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization>
2. Click **`Code` → `Codespaces` → `Create codespace on main`**
3. Wait ~90 s for the container to build (Python 3.11, all deps pre-installed via `.devcontainer` if present, otherwise just `pip install -r requirements.txt`)
4. In the integrated terminal:
   ```bash
   cp .env.example .env && nano .env   # add GROQ_API_KEY=...
   export PYTHONPATH=src
   uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
   ```
5. Codespaces prompts to forward port 8000 — click **Open in Browser**.

**Gitpod** (<https://gitpod.io/#/https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization>) — same flow, free 50 hr/month.

**Replit** — import the GitHub repo, set `PYTHONPATH=src` in Secrets, run.

> All three expose port 8000 as a public HTTPS URL you can hit from any device, including phones and tablets — see [§2.5](#25-mobile-tablet-chromebook).

---

### 2.2 Linux / macOS / WSL — one block

Works on every Linux distro, macOS, ChromeOS Linux, and WSL.

```bash
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization.git
cd Smart-Campus-Energy-Optimization

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add at least one LLM key (Groq recommended — free + fast)
#   GROQ_API_KEY=gsk_...

export PYTHONPATH=src
uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
```

**Per-distro extras if the block above fails on a stripped system:**

| Distro | If `python3 -m venv` fails | Install command |
|---|---|---|
| Debian / Ubuntu | `ensurepip` not available | `sudo apt install -y python3-venv python3-full` |
| Fedora | pip too old | `sudo dnf install -y python3.11 python3.11-devel` then use `python3.11` |
| RHEL / Rocky 9 | CodeReady Builder needed | `sudo dnf --enablerepo=crb install -y python3-devel` |
| Arch / Manjaro | none typically | `sudo pacman -Syu python python-pip` if missing |
| openSUSE | none typically | `sudo zypper install -y python3 python3-pip python3-virtualenv` |
| Alpine (musl) | none — pip bundled | `sudo apk add --no-cache python3 py3-pip py3-virtualenv git` |
| macOS (no Python) | Homebrew | `brew install python@3.12 git` |
| macOS (no CLT) | Xcode CLT | `xcode-select --install` |

---

### 2.3 Windows native (PowerShell)

Works on Windows 10 (1809+) and Windows 11.

**One-time prerequisites** — install Python if you don't have it:
```powershell
# Pick ONE of these:
winget install Python.Python.3.12      # recommended
# OR download from https://www.python.org/downloads/windows/ (check "Add to PATH")
```

**Run the app** (in PowerShell — not CMD, not Git Bash):

```powershell
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization.git
cd Smart-Campus-Energy-Optimization

python -m venv venv
venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt

copy .env.example .env
# Edit .env with Notepad, VS Code, or:  notepad .env
# Add at least:  GROQ_API_KEY=gsk_...

$env:PYTHONPATH = "src"
uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
```

**Windows CMD** (if you must, though PowerShell is easier):

```bat
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization.git
cd Smart-Campus-Energy-Optimization
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt
copy .env.example .env
set PYTHONPATH=src
uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
```

**If PowerShell blocks the venv activation:**
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**If `uvicorn` is "not recognized":** the venv isn't active. Look at your prompt — it should start with `(venv) `. If it doesn't, re-run `venv\Scripts\Activate.ps1`.

**WSL2 alternative (often smoother):** run `wsl --install -d Ubuntu` then follow [§2.2](#22-linux-macos-wsl-one-block).

---

### 2.4 Docker (production parity)

```bash
docker pull ashikonik/gridwise-bup-2026:1.0.0
docker run --rm -p 8000:8000 --env-file .env ashikonik/gridwise-bup-2026:1.0.0
```

Or build the image yourself (no Docker Hub needed):

```bash
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization.git
cd Smart-Campus-Energy-Optimization
docker build -t gridwise:1.0.0 .
docker run --rm -p 8000:8000 --env-file .env gridwise:1.0.0
```

**docker-compose** (one command):
```bash
docker compose up --build
```

The image is multi-stage, runs as a non-root user, and uses `urllib` for healthchecks — no extra tooling required in the container.

---

### 2.5 Mobile / tablet / Chromebook

You don't need a laptop. Three options, in order of ease:

**Option A — Hit the deployed instance.** If we have a public URL (Railway; see [§10.2](#102-public-host-railway-recommended-for-judges)), open it in your phone/tablet browser. Done.

**Option B — Use a cloud IDE from a tablet browser.** Open <https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization> on your iPad/phone, tap **`Code` → `Codespaces` → `Create codespace`**. Forward port 8000, tap **Open in Browser**. You can edit files in the Codespaces web editor too.

**Option C — Termux on Android** (advanced, no root):
```bash
pkg install python git
git clone https://github.com/Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization.git
cd Smart-Campus-Energy-Optimization
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # Termux has its own nano
export PYTHONPATH=src
uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
```
Then visit `http://<your-phone-ip>:8000/ui` from any device on the same Wi-Fi.

**iOS (iSH shell)** — same flow as Termux, but `apk add python3 git` and `python3 -m venv` may need extra flags. Tested working, just slower.

> Heads-up: the dev console at `/ui` is desktop-first (Tailwind responsive layout). On a phone in portrait it works but is cramped. **Landscape mode recommended.**

---

### 2.6 Run as a systemd service (Linux)

For a Linux box that should keep the API running 24/7:

```ini
# /etc/systemd/system/gridwise.service
[Unit]
Description=GridWise BUP Energy Optimizer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=gridwise
WorkingDirectory=/opt/gridwise
Environment="PYTHONPATH=/opt/gridwise/src"
EnvironmentFile=/opt/gridwise/.env
ExecStart=/opt/gridwise/venv/bin/uvicorn gridwise.app:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd --system --home /opt/gridwise --shell /usr/sbin/nologin gridwise
sudo cp -r . /opt/gridwise/
sudo chown -R gridwise:gridwise /opt/gridwise
sudo systemctl daemon-reload
sudo systemctl enable --now gridwise
sudo systemctl status gridwise
curl -s http://127.0.0.1:8000/health
```

---

### 2.7 Verify it works

**Health check** (works on any shell, any device with `curl`):

```bash
curl -s http://127.0.0.1:8000/health
# -> {"status":"ok"}
```

**Run the full test suite** (math path + provider chain + validator + solver fallback):

```bash
PYTHONPATH=src pytest -q
# Expected: 37/37 pass
```

**Run just the public-case regression:**

```bash
PYTHONPATH=src pytest tests/test_hybrid_optimizer.py -v
# Expected: 12 pass — 10 cost-diff cases + 2 aggregate checks
```

> The 10 public sample cases are loaded from
> `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` at the repo root. If you
> checked out a tree state from before this file was committed, copy it there
> manually.

---

### 2.8 Common pitfalls (any platform)

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: No matching distribution found for fastapi` | pip linked to Python 2.7 | `python3 -m pip install -r requirements.txt` |
| `pulp` install fails with "no module named distutils" | Python 3.12+ removed distutils | already fixed in PuLP ≥ 2.7; `pip install -U pulp` |
| `Address already in use` on `:8000` | another process holds the port | `PORT=8001 uvicorn gridwise.app:app --port 8001` or `lsof -i :8000` (Win: `netstat -ano \| findstr :8000`) |
| `ModuleNotFoundError: No module named 'gridwise'` | forgot `PYTHONPATH=src` | bash/zsh: `export PYTHONPATH=src` · CMD: `set PYTHONPATH=src` · PowerShell: `$env:PYTHONPATH = "src"` — must match the shell you're actually in |
| `groq: 404 Not Found` | default model retired on Groq | `GROQ_MODEL=openai/gpt-oss-20b` in `.env` |
| UI returns 404 on `/ui` | gated behind `ENABLE_UI=true` | `echo "ENABLE_UI=true" >> .env` and restart |
| WSL: `bash: uvicorn: not found` after activation | activation didn't actually run | `source venv/bin/activate && which uvicorn` |
| Windows: `'uvicorn' is not recognized` | venv not active in this shell | re-run `venv\Scripts\Activate.ps1` — prompt must start with `(venv)` |
| Tests crash with `samples not found` | JSON fixture missing at repo root | pull latest main, or copy `BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json` into the repo root |
| PuLP `DeprecationWarning` in test output | PuLP 3.x deprecates direct `LpVariable`/`PULP_CBC_CMD` | informational only; will be addressed in PuLP 4.0 |
| Codespaces: port 8000 not reachable | port not forwarded | Codespaces panel → Ports tab → right-click 8000 → Port Visibility → Public |

---

## 3. Endpoints

### 3.0 Public endpoints (always exposed)

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness probe — returns `200 {"status":"ok"}` |
| `/` | GET | 307 redirect to `/docs` |
| `/favicon.ico` | GET | 1×1 transparent PNG (silences browser auto-fetch) |
| `/docs` | GET | Swagger UI (auto-generated from the OpenAPI schema) |
| `/redoc` | GET | ReDoc API reference |
| `/openapi.json` | GET | Raw OpenAPI 3.x schema |
| `/optimize-energy` | POST | The actual solver. Accepts a scenario JSON, returns a directive interpretation + 24-hour plan + total cost. |

### 3.0b Debug endpoints (only when `ENABLE_UI=true`)

| Endpoint | Method | Purpose |
|---|---|---|
| `/ui` | GET | Interactive debug console (HTML) |
| `/ui/api/service-info` | GET | PID, uptime, provider chain, config snapshot |
| `/ui/api/schema-tests` | GET | Runs 8 malformed payloads against `/optimize-energy` |
| `/ui/api/sample/{case_id}` | POST | Run a single public case via LLM or math mode |
| `/ui/api/run-all-samples` | POST | Run all 10 public cases |
| `/ui/api/perf-burst` | POST | 20-request latency burst (p50/p95/max) |
| `/ui/api/cold-start` | POST | Uptime snapshot (restart server to re-measure) |
| `/ui/api/directive-diff/{case_id}` | POST | Per-note LLM interpretation vs reference |
| `/ui/api/export-response/{case_id}` | POST | Download the `OptimizeResponse` JSON |
| `/ui/api/guardrail-tests` | GET | 9 bad-input unit tests on the validator |
| `/ui/api/replay-checks` | GET | E[23] vs initial battery neutrality for all 10 cases |
| `/ui/api/log-scan` | GET | Greps the live uvicorn log for API-key leakage |
| `/ui/api/docker-status` | GET | Read-only `docker images` / `docker ps` snapshot |

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

### 4.0 Where to get API keys (all free tiers available)

| Provider | Sign-up URL | Free tier | Time to key |
|---|---|---|---|
| **Groq** (recommended) | <https://console.groq.com> | Generous free tier, very fast | ~30 s |
| **Gemini** | <https://aistudio.google.com/apikey> | 15 RPM, 1M TPM | ~30 s |
| **OpenRouter** | <https://openrouter.ai/keys> | Many `:free` models | ~30 s |
| **Puku.sh** | <https://puku.sh> | Browser-session auth required | ~2 min |

You only need **one** key — the chain falls back automatically.

### 4.1 Configuration variables

| Variable | Purpose | Default |
|---|---|---|
| `GROQ_API_KEY` | Groq API key (primary LLM) | unset |
| `GEMINI_API_KEY` | Gemini API key (fallback #1) | unset |
| `OPENROUTER_API_KEY` | OpenRouter API key (fallback #2) | unset |
| `PUKU_API_KEY` | Puku.sh API key (fallback #3; currently browser-session auth) | unset |
| `LLM_PROVIDER_ORDER` | Comma-separated fallback chain | `groq,gemini,openrouter,puku` |
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

## 5. LLM provider chain

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

If **no LLM key is set**, the regex safety net still produces a valid plan — `/optimize-energy` will return 200, just without semantic interpretation of free-text notes.

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
Smart-Campus-Energy-Optimization/
├── Dockerfile                  # multi-stage + non-root + urllib healthcheck
├── docker-compose.yml
├── .dockerignore
├── .env.example                # template — copy to .env and fill in keys
├── .gitignore
├── README.md                   # this file
├── Procfile                    # Railway / Heroku entry
├── pyproject.toml              # PEP 621 metadata + pip-installable source
├── pytest.ini                  # asyncio_mode=auto
├── railway.toml                # Railway deploy config (PORT-aware CMD)
├── runtime.txt                 # Python version pin for Railway
├── requirements.txt            # pip mirror of pyproject deps
├── publish.sh                  # one-shot Docker Hub push (see §10.3)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── FINAL_SUBMISSION_DOCUMENTATION.md   # one-page rubric checklist
│   ├── RAILWAY_DEPLOY.md
│   ├── VIDEO_SCRIPT.md                     # 3-min demo-day script
│   └── VIDEO_STORYBOARD.md                 # 18-slide outline
├── src/
│   └── gridwise/
│       ├── __init__.py
│       ├── app.py            # FastAPI routes (public + /ui debug)
│       ├── config.py         # env loader + masked_api_key helper (Aurna)
│       ├── constraints.py    # Directive → per-hour arrays (Ashik)
│       ├── interpreter.py    # 4-provider chain + regex safety net (Ashik)
│       ├── optimizer.py      # ★ HYBRID (Aurna objective + Ashik 2-stage)
│       ├── prompts.py        # LLM system prompt (Ashik)
│       ├── replay.py         # Self-validate + total derivation (Ashik)
│       ├── schemas.py        # Pydantic models (Ashik)
│       ├── ui.py             # /ui debug console, gated by ENABLE_UI (Ashik)
│       └── validator.py      # 12 guardrails (Ashik)
├── tests/
│   ├── test_hybrid_optimizer.py    # 10 public cases + 2 aggregates
│   ├── test_solver_fallback.py     # scipy fallback defence-in-depth
│   ├── test_validator.py           # 17 malformed-input cases
│   ├── test_provider_chain.py      # 7 mocked LLM failover scenarios
│   ├── public_samples.py           # CLI: 10-case determinism harness
│   └── load_burst.py               # CLI: 20-request latency burst
└── BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json   # 10-case fixture
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

### 10.2 Public host (Railway — recommended for judges)

```bash
# One-time: sign in at https://railway.app with GitHub, then:
# 1. New Project → Deploy from GitHub repo → pick this repo
# 2. Service → Variables, paste: GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY
# 3. Settings → Networking → Generate Domain
# Full guide: docs/RAILWAY_DEPLOY.md
```

The Dockerfile and `railway.toml` are already configured for Railway:
- `CMD` reads `$PORT` so Railway's auto-injected port works.
- `railway.toml` declares `/health` as the healthcheck with a 30 s timeout
  (covers PuLP + scipy cold-start).

### 10.2b Render / Fly.io / Heroku alternatives

Same Docker image works on any platform that runs containers:

| Platform | Free tier | One-click deploy |
|---|---|---|
| **Render** | 750 hr/month web service | "New Web Service" → connect this repo → Render reads the Dockerfile automatically |
| **Fly.io** | 3 shared VMs | `fly launch --dockerfile` |
| **Heroku** | Eco dyno (~$5/mo, no free) | `heroku container:push web -a your-app` |
| **DigitalOcean App Platform** | $0 basic tier | "Deploy from GitHub" → picks the Dockerfile |

All four honor `$PORT` — no code changes needed.

### 10.3 Publish a new image (one-shot)

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
- **PuLP 3.x deprecation warnings** appear in test output (`PULP_CBC_CMD is deprecated`, `Constructing LpVariable(name, ...) directly is deprecated`). They are informational — the LP still solves correctly. Plan to migrate to PuLP 4.0's `add_variable` API before that release ships.
- The `/ui` debug console is desktop-first (Tailwind responsive layout). It works on tablets in landscape and is barely usable on phones in portrait — judges on small screens should hit `/docs` instead.

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
| **Aurna** | Exact cost objective `Σ grid[h] · tariff[h]` with `1e-6` complementarity penalty. `masked_api_key` log helper. | Matches reference optimum to the paisa on all 10 public cases (0.00 BDT diff). |
| **Pulok** | Regex-from-raw-text safety net as the always-available final fallback. MILP mutual-exclusion theory as the basis for charge/discharge window handling. Public sample fixture file. | Regex safety net keeps `/optimize-energy` returning 200 even when every LLM is down. |
| **Ashik** (base) | 4-provider LLM chain, 12-check validator, 17-unit-test guardrail suite, hardened multi-stage Dockerfile (non-root + urllib healthcheck), `ENABLE_UI`-gated debug console, Pydantic v2 schemas with per-directive adjustment models. | Best operational resilience; the foundation everything else merges into. |

**Team:** Aurna · Pulok · Ashik (Team Ai-Will-Fix-It)

**Stack:** FastAPI + Uvicorn · Pydantic v2 · PuLP (CBC) · scipy (HiGHS fallback) · httpx · pytest
