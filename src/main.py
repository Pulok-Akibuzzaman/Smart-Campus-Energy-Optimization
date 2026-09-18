"""
src/main.py - Smart Campus Energy Optimization HTTP API Service
Endpoints:
  - GET /health
  - POST /optimize-energy
"""

import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

try:
    from src.models import OptimizeEnergyRequest, OptimizeEnergyResponse, HealthResponse
    from src.interpreter import interpret_operator_notes
    from src.optimizer import solve_energy_schedule
except ImportError:
    from models import OptimizeEnergyRequest, OptimizeEnergyResponse, HealthResponse
    from interpreter import interpret_operator_notes
    from optimizer import solve_energy_schedule

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("GridWiseService")

app = FastAPI(
    title="GridWise Smart Campus Energy API",
    description="LLM-Assisted Operator Directive Interpretation and 24-Hour Energy Scheduling Service",
    version="2.0.0"
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handles schema validation errors cleanly with HTTP 400."""
    logger.warning(f"Invalid request received: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "Malformed JSON or structurally invalid request", "details": str(exc.errors())}
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handles unexpected server errors cleanly with HTTP 500 without exposing stack traces or keys."""
    logger.error(f"Internal server error: {exc}", exc_info=False)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Controlled internal error processing energy optimization."}
    )

@app.get("/health", response_model=HealthResponse)
def get_health():
    """Readiness probe returning status: ok."""
    return {"status": "ok"}

@app.post("/optimize-energy", response_model=OptimizeEnergyResponse)
def optimize_energy(req: OptimizeEnergyRequest):
    """
    Main endpoint:
    1. Interprets 1-3 operator notes into machine-checkable directives.
    2. Validates directives deterministically through guardrails.
    3. Optimizes 24-hour dispatch using Mixed-Integer Linear Programming.
    4. Recalculates metrics and returns structured plan.
    """
    scenario_id = req.scenario_id
    logger.info(f"Received optimization request for scenario: {scenario_id}")
    
    battery_dict = req.battery.model_dump()
    hours_dict_list = [h.model_dump() for h in req.hours]
    
    # 1. LLM Directive Interpretation & Guardrail validation
    directives = interpret_operator_notes(req.operator_notes, battery_dict, scenario_id)
    logger.info(f"Interpreted {len(directives)} directives for {scenario_id}")
    
    # 2. Mathematical LP Optimization
    try:
        sol = solve_energy_schedule(hours_dict_list, battery_dict, directives)
    except Exception as e:
        logger.error(f"Optimization failure for {scenario_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to solve energy dispatch optimization."
        )
        
    # 3. Generate concise human-readable plan summary
    active_directives = [d["directive_type"] for d in directives if d.get("applies")]
    directive_summary = ", ".join(active_directives) if active_directives else "standard baseline operations"
    
    plan_summary = (
        f"24-hour campus energy schedule for {scenario_id} optimized under {directive_summary}. "
        f"Total grid import: {sol['total_grid_kwh']} kWh, total cost: {sol['total_cost_bdt']} BDT, "
        f"peak grid import: {sol['peak_grid_kwh']} kWh. Battery state of charge satisfies end-of-day neutrality."
    )
    
    return {
        "scenario_id": scenario_id,
        "directive_interpretation": directives,
        "hourly_plan": sol["hourly_plan"],
        "total_grid_kwh": sol["total_grid_kwh"],
        "total_cost_bdt": sol["total_cost_bdt"],
        "peak_grid_kwh": sol["peak_grid_kwh"],
        "plan_summary": plan_summary
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("src.main:app", host="0.0.0.0", port=port, reload=False)
