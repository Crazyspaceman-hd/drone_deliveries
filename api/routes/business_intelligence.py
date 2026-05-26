"""GET /business-intelligence{,/{run_id}}."""

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_db
from core.business_intelligence import (
    compute_scenario_metrics, generate_feasibility_report,
    generate_scenario_rankings,
)
from core.runs import get_run

router = APIRouter(prefix="/business-intelligence", tags=["bi"])


@router.get("")
def bi_overall(db: str = Depends(require_db)) -> dict:
    return generate_feasibility_report(db)


@router.get("/{run_id}")
def bi_for_run(run_id: str, db: str = Depends(require_db)) -> dict:
    """The Phase 11 BI layer aggregates by scenario across all runs in the
    DB.  This endpoint scopes to the scenario of the requested run.
    """
    run = get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    rankings = generate_scenario_rankings(db)
    for r in rankings:
        if r["scenario_name"] == run["scenario_names"]:
            return {"run_id": run_id, "scenario_ranking": r}
    raise HTTPException(
        status_code=404,
        detail=f"no BI ranking found for scenario {run['scenario_names']}",
    )
