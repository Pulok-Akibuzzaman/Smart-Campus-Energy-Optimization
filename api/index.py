"""Vercel serverless entrypoint for GridWise.

Vercel expects an ASGI callable named `app` at `api/index.py`. Our FastAPI
app lives at `src/gridwise/app.py`, so this shim wires the import path and
re-exports the FastAPI instance.

Notes for Vercel:
- The Hobby tier caps serverless functions at 300s and 2 GB RAM. The
  optimize-energy solver takes <100 ms in practice, so this is comfortable.
- PuLP's bundled CBC binary is shipped as a wheel and runs as a subprocess;
  Lambda-style runtimes permit subprocess so this works on Vercel.
- scipy ships precompiled wheels (Linux x86_64, manylinux) so the HiGHS
  fallback is always available.
- ENABLE_UI is forced ON on Vercel so the root URL `/` redirects to the
  interactive `/ui` debug console. The only UI feature that won't work is
  the docker-status tab (no `docker` CLI in the serverless runtime); every
  other tab works fine. To disable the UI on Vercel, set ENABLE_UI=false
  in the project's Environment Variables.
- LLM provider keys are read from Vercel's environment variables — set them
  in the project's Settings → Environment Variables tab. The chain
  (Groq → Gemini → OpenRouter → Puku) is unchanged.
"""
from __future__ import annotations

import os
import sys

# Vercel's working directory is the project root, not src/. The package is
# laid out under src/, so prepend src to sys.path before importing.
_SRC = os.path.join(os.path.dirname(__file__), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# Mount the /ui debug console on Vercel so the root URL lands on the
# interactive dashboard. Only the docker-status sub-tab won't work (no
# docker CLI serverless).
os.environ.setdefault("ENABLE_UI", "true")

# Importing gridwise.app triggers Pydantic v2 model build + PuLP solver
# discovery; both are needed for the first cold start but cached after.
from gridwise.app import app  # noqa: E402  (sys.path manipulation above)

