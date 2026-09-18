# Deploying GridWise to Railway

**5-minute deploy. Public URL. Stays up through the judging window.**

> Railway is the simplest platform for a FastAPI service: it auto-detects Python, exposes a public HTTPS URL, and respects `$PORT`. The repo already includes `railway.toml`, `Procfile`, `runtime.txt`, and the Dockerfile is `$PORT`-aware.

---

## Option A — One-click from GitHub (recommended)

1. **Create a Railway account** at https://railway.app (sign in with GitHub).
2. Click **"New Project"** → **"Deploy from GitHub repo"**.
3. Pick `Pulok-Akibuzzaman/Smart-Campus-Energy-Optimization-Challenge-Team-Ai-Will-Fix-It`.
   - If the repo is private, Railway will ask for read access — grant it.
4. Railway reads `railway.toml` and uses the existing **Dockerfile** (no rebuild magic).
5. Once the build finishes, click the service → **Settings** → **Networking** → **Generate Domain**.
   - You'll get a URL like `https://gridwise-production.up.railway.app`
6. **Set environment variables** (Service → Variables → Raw Editor):

   ```env
   GROQ_API_KEY=<your_groq_api_key>
   GEMINI_API_KEY=<your_gemini_api_key>
   OPENROUTER_API_KEY=<your_openrouter_api_key>
   LLM_PROVIDER_ORDER=groq,gemini,openrouter
   LOG_LEVEL=INFO
   ENABLE_UI=false
   ```
   > You only need `GROQ_API_KEY` for full quality; the other two are fallback. If you don't have keys, leave them blank — the regex safety net will still return valid plans (lower LLM-interpretation score, but the optimizer is unchanged).

7. **Verify** the deploy:
   ```bash
   curl https://gridwise-production.up.railway.app/health
   # → {"status":"ok"}
   ```
8. Paste the URL into the submission form field **#6 (Live Project Demo / Deployment URL)**.

---

## Option B — Deploy from the existing Docker Hub image (no rebuild needed)

If Railway's free-tier GitHub build minutes run out, you can deploy the **already-pushed** image directly:

1. Railway → **New Project** → **"Empty Project"**.
2. Click **"+ New"** → **"Docker Image"**.
3. Paste `ashikonik/gridwise-bup-2026:1.0.0` (or `:1.0.1-railway` once that tag exists).
4. Set the same environment variables as above.
5. Generate a domain and verify `/health`.

---

## How `PORT` works (why the Dockerfile was updated)

Railway (and Heroku, Render, Fly.io) injects a `PORT` environment variable. The original Dockerfile had a hardcoded port (8000), which meant Railway couldn't bind the service. Fixed:

```dockerfile
# Dockerfile
CMD ["sh", "-c", "uvicorn gridwise.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

If `PORT` is unset (local Docker, the existing `gridwise` container on this machine), it falls back to `8000`. **Verified locally:**

```bash
docker run -p 8001:8765 -e PORT=8765 ashikonik/gridwise-bup-2026:1.0.1-railway
curl http://127.0.0.1:8001/health   # → {"status":"ok"} HTTP 200
```

---

## Healthcheck & cold starts

- Railway pings `/health` every few seconds.
- First request boots PuLP + scipy (~3–5 s). Healthcheck timeout in `railway.toml` is **30 s** to absorb that.
- If the very first `/optimize-energy` is slow (LLM path), it's normal; judges' harness will retry.

---

## Cost / limits

- Railway free tier: **$5/month of usage**, **500 hours** of runtime, **100 GB egress**.
- GridWise at idle uses ~50 MB RAM and 0 CPU; a single 24-h hackathon run costs < $0.10.
- If the free tier is exhausted, you can switch to Render (similar setup) or Fly.io (also `$PORT`-aware).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `502 Bad Gateway` immediately | Container didn't bind to `$PORT`. Make sure you pulled the **latest** Dockerfile (the one with `${PORT:-8000}`). |
| Healthcheck timeout | Increase `healthcheckTimeout` in `railway.toml` to 60. Cold start with PuLP can take 10–15 s on a fresh container. |
| `ModuleNotFoundError: gridwise` | `PYTHONPATH` isn't set. The Dockerfile sets `ENV PYTHONPATH=/app/src` — confirm the deploy used the Dockerfile, not Nixpacks. |
| LLM 401 errors | API key invalid or missing. Check Service → Variables. The service won't crash — it'll fall through to the regex safety net. |
| Want to redeploy a new image tag | Push a new tag (e.g. `:1.0.1-railway`) to Docker Hub, then in Railway → Settings → Deploy → change the image reference. |

---

## Verification commands (run these before submitting the form)

```bash
# 1. Health
curl -s https://YOUR-RAILWAY-URL.up.railway.app/health | python3 -m json.tool

# 2. End-to-end optimize-energy with public sample 1
curl -s -X POST https://YOUR-RAILWAY-URL.up.railway.app/optimize-energy \
  -H "Content-Type: application/json" \
  -d @- <<'EOF' | python3 -m json.tool | head -30
$(python3 -c "import json; c=json.load(open('../BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json'))['cases'][0]; print(json.dumps(c['input']))")
EOF

# 3. OpenAPI schema is exposed (good sanity check)
curl -s -o /dev/null -w "%{http_code}\n" https://YOUR-RAILWAY-URL.up.railway.app/openapi.json
# → 200
```

If all three return 200 and the response includes `total_cost_bdt` + `hourly_plan`, you're done.

---

## Files added for Railway

| File | Purpose |
|---|---|
| `railway.toml` | Pins builder=DOCKERFILE, declares healthcheck + restart policy |
| `Procfile` | Fallback for platforms that prefer it over `railway.toml` |
| `runtime.txt` | Pins `python-3.11.16` so nixpacks (if used) matches the image |
| `Dockerfile` (modified) | CMD now reads `${PORT:-8000}` |

No application code was changed — these are pure infrastructure files.
