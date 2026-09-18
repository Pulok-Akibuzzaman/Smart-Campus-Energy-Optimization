"""FastAPI application for GridWise Smart Campus Energy Optimization."""

import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.schemas import (
    ScenarioRequest,
    OptimizationResponse,
    HealthResponse,
)
from app.llm_interpreter import call_llm_for_interpretation
from app.optimizer import solve_energy_dispatch
from app.validator import replay_and_validate_schedule

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("gridwise.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup verification
    logger.info("Initializing GridWise Energy Optimization Service...")
    logger.info(f"LLM Provider: {settings.llm_provider}")
    logger.info(f"LLM Model: {settings.get_effective_model()}")
    logger.info(f"LLM API Key: {settings.masked_api_key()}")
    yield
    logger.info("Shutting down GridWise service...")


app = FastAPI(
    title="GridWise Smart Campus Energy Optimization Service",
    version="2.0.0",
    description="LLM-assisted energy scheduling and optimization for BUP CSE Fest 2026",
    lifespan=lifespan
)

# CORS support for judge dashboard integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global Exception Handlers (Defense-in-depth, zero secret or stack trace leaks)
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Returns controlled 400 Bad Request on malformed or schema-invalid input."""
    logger.warning(f"Validation error on {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": "Bad Request",
            "message": "Malformed or structurally invalid JSON input schema.",
            "details": [
                {"field": " -> ".join(str(loc) for loc in err.get("loc", [])), "issue": err.get("msg")}
                for err in exc.errors()
            ]
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Controlled 500 handler that intercepts unhandled exceptions without leaking secrets or stack traces."""
    logger.error(f"Controlled internal error on {request.url.path}: {type(exc).__name__} - {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "message": "An unexpected error occurred while processing the energy dispatch scenario."
        }
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

import os
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

# Mount static assets directory
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/dashboard", response_class=HTMLResponse, summary="Visual Demonstration Dashboard")
@app.get("/dashboard/", response_class=HTMLResponse, include_in_schema=False)
@app.get("/", response_class=HTMLResponse, summary="Visual Demonstration Dashboard")
async def dashboard():
    """Serves the interactive GridWise web dashboard for demo and video walkthrough."""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h2>GridWise Service is running. Open /docs for API schema.</h2>")


@app.get("/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json", include_in_schema=False)
async def sample_cases():
    """Serves the official public sample pack for dashboard preset loading."""
    sample_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json")
    if os.path.exists(sample_path):
        return FileResponse(sample_path, media_type="application/json")
    return JSONResponse(status_code=404, content={"error": "File not found"})


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check and service readiness endpoint"
)
async def health_check():
    """Returns HTTP 200 with status='ok' within 60s of startup."""
    return HealthResponse(status="ok")


@app.post(
    "/optimize-energy",
    response_model=OptimizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Optimize 24-hour campus energy schedule based on scenario and operator notes"
)
async def optimize_energy(scenario: ScenarioRequest):
    """
    Main GridWise processing pipeline:
    1. Parse and validate input scenario and operator notes.
    2. Execute LLM interpretation on operator notes.
    3. Run deterministic guardrails on LLM output.
    4. Solve LP energy dispatch using SciPy HiGHS optimizer.
    5. Replay and validate schedule defense-in-depth.
    6. Return complete structured response with scenario_id echo.
    """
    start_time = time.perf_counter()
    logger.info(f"Processing scenario '{scenario.scenario_id}' with {len(scenario.operator_notes)} operator note(s)")

    # 1. Interpret operator notes via LLM with deterministic guardrails
    directives = await call_llm_for_interpretation(scenario.operator_notes, scenario.battery)

    # 2. Solve mathematical LP dispatch
    hourly_plan, raw_grid_kwh, raw_cost_bdt, raw_peak_kwh = solve_energy_dispatch(
        hours=scenario.hours,
        battery=scenario.battery,
        directives=directives
    )

    # 3. Defense-in-depth self-replay and validation
    total_grid_kwh, total_cost_bdt, peak_grid_kwh, plan_summary = replay_and_validate_schedule(
        hours=scenario.hours,
        battery=scenario.battery,
        directives=directives,
        plan=hourly_plan,
        tolerance=settings.tolerance
    )

    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        f"Scenario '{scenario.scenario_id}' completed in {elapsed_ms:.1f} ms: "
        f"Total Cost = {total_cost_bdt:.2f} BDT, Peak Grid = {peak_grid_kwh:.2f} kWh"
    )

    return OptimizationResponse(
        scenario_id=scenario.scenario_id,
        directive_interpretation=directives,
        hourly_plan=hourly_plan,
        total_grid_kwh=total_grid_kwh,
        total_cost_bdt=total_cost_bdt,
        peak_grid_kwh=peak_grid_kwh,
        plan_summary=plan_summary
    )
