"""GET /validation and GET /validation/{run_id}."""

from fastapi import APIRouter, Depends

from api.dependencies import require_db
from core.validation import generate_validation_summary

router = APIRouter(prefix="/validation", tags=["validation"])


@router.get("")
def validation_global(db: str = Depends(require_db)) -> dict:
    return generate_validation_summary(db)


@router.get("/{run_id}")
def validation_one_run(run_id: str, db: str = Depends(require_db)) -> dict:
    return generate_validation_summary(db, run_id=run_id)
