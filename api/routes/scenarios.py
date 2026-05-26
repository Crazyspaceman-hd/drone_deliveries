"""GET /scenarios{,/summary} — thin wrapper over assumptions + BI + calibration."""

from fastapi import APIRouter, Depends

from api.dependencies import require_db
from core.assumptions import (
    get_assumption_summary, get_scenario_assumptions,
)
from core.business_intelligence import generate_scenario_rankings
from core.calibration import compute_calibration_drift

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("")
def scenarios_list() -> dict:
    """Return the configured Scenario knobs + categorisation."""
    return {"scenarios": get_scenario_assumptions()}


@router.get("/summary")
def scenarios_summary(db: str = Depends(require_db)) -> dict:
    """Bundle configured + BI ranking + calibration drift in one shot.

    Designed for the frontend's Scenario Comparison page.
    """
    return {
        "assumptions": get_assumption_summary(),
        "bi_rankings": generate_scenario_rankings(db),
        "calibration": compute_calibration_drift(db),
    }
