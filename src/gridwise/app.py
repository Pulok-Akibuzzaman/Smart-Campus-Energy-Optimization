"""
FastAPI service for BUP CSE Fest 2026 GridWise preliminary.

Endpoints:
  GET  /health           -> {"status": "ok"}
  POST /optimize-energy  -> full LLM → guardrails → LP → replay pipeline
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import CFG
from .constraints import build_constraints
from .interpreter import interpret_notes
from .optimizer import optimize_schedule
from .replay import build_hourly_plan, replay
from .schemas import (
    DirectiveInterpretationEntry,
    HealthResponse,
    OptimizeRequest,
    OptimizeResponse,
)
from .validator import validate_all

logging.basicConfig(
    level=CFG.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("gridwise")


# ──────────── Lifespan: log config (no secrets) at startup ───────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    CFG.log_summary()
    log.info("GridWise API ready on %s:%s", CFG.HOST, CFG.PORT)
    yield


app = FastAPI(
    title="GridWise — Smart Campus Energy Optimization",
    description="LLM-assisted 24-hour energy scheduler for BUP CSE Fest 2026",
    version="0.1.0",
    lifespan=lifespan,
)


# ──────────── Global exception handlers ───────────


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    log.info("400 validation: %s", exc.errors())
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed or invalid request body."},
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_handler(request: Request, exc: ValidationError):
    log.info("400 pydantic validation: %s", exc.errors())
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Malformed or invalid request body."},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.exception("500 internal error")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error."},
    )


# ──────────── Routes ───────────


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post(
    "/optimize-energy",
    response_model=OptimizeResponse,
    tags=["optimize"],
)
async def optimize_energy(req: OptimizeRequest) -> OptimizeResponse:
    """Main endpoint: LLM interprets notes, LP optimizes, replay validates."""
    log.info("optimize-energy start scenario=%s notes=%d", req.scenario_id, len(req.operator_notes))

    # 1) LLM interpretation (provider chain → regex fallback).
    raw_llm, provider_used = await interpret_notes(
        operator_notes=req.operator_notes,
        battery_capacity_kwh=req.battery.capacity_kwh,
    )

    # 2) Guardrails validation.
    directives: List[DirectiveInterpretationEntry] = validate_all(
        raw_entries=raw_llm.get("directives", []),
        operator_notes=req.operator_notes,
        battery=req.battery,
    )

    # 3) Translate directives into per-hour constraints.
    cons = build_constraints(req.hours, req.battery, directives)

    # 4) Solve LP (PuLP primary, scipy fallback).
    opt_result = optimize_schedule(req.hours, req.battery, cons)

    # 5) Replay-validate and derive totals.
    report = replay(req.hours, req.battery, cons, opt_result)
    if not report.valid:
        log.warning(
            "Replay flagged %d violations for scenario=%s: %s",
            len(report.violations),
            req.scenario_id,
            report.violations[:5],
        )

    # 6) Build response.
    plan = build_hourly_plan(req.hours, opt_result)
    summary = _build_plan_summary(req, directives, cons, report, provider_used)

    response = OptimizeResponse(
        scenario_id=req.scenario_id,
        directive_interpretation=directives,
        hourly_plan=plan,
        total_grid_kwh=round(report.total_grid_kwh, 4),
        total_cost_bdt=round(report.total_cost_bdt, 4),
        peak_grid_kwh=round(report.peak_grid_kwh, 4),
        plan_summary=summary,
    )
    log.info(
        "optimize-energy done scenario=%s total_cost=%.2f BDT provider=%s",
        req.scenario_id,
        report.total_cost_bdt,
        provider_used,
    )
    return response


# ──────────── Helpers ───────────


def _build_plan_summary(
    req: OptimizeRequest,
    directives: List[DirectiveInterpretationEntry],
    cons,
    report,
    provider_used: str,
) -> str:
    applied = [d for d in directives if d.applies]
    applied_descs = [d.directive_type.value for d in applied]
    if applied_descs:
        rules = ", ".join(applied_descs)
        summary = (
            f"Applied {len(applied)} directive(s): {rules}. "
            f"Total grid energy {report.total_grid_kwh:.1f} kWh, "
            f"cost {report.total_cost_bdt:.0f} BDT, "
            f"peak {report.peak_grid_kwh:.0f} kWh."
        )
    else:
        summary = (
            f"No applicable operator directives. "
            f"Total grid energy {report.total_grid_kwh:.1f} kWh, "
            f"cost {report.total_cost_bdt:.0f} BDT, "
            f"peak {report.peak_grid_kwh:.0f} kWh."
        )
    # Do not include provider name in user-facing summary; it can leak internal state.
    return summary


# ──────────── Optional local debug UI (gated by ENABLE_UI) ───────────


if CFG.ENABLE_UI:
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse

    from .ui import router as ui_router
    from pathlib import Path

    _STATIC_DIR = Path(__file__).parent / "static"

    @app.get("/ui", include_in_schema=False)
    async def _ui_index():
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount("/ui/static", StaticFiles(directory=str(_STATIC_DIR)), name="ui-static")
    app.include_router(ui_router, prefix="/ui/api")

    log.info("Debug UI mounted at /ui (ENABLE_UI=true)")
