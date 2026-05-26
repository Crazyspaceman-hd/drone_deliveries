"""GET /runs, GET /runs/{run_id}, GET /runs/{run_id}/transforms.

Read-only wrappers over core.runs plus a small lineage helper that lets
the workbench show transformation_runs filtered to one source run.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_db
from core.runs import get_run, list_runs

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("")
def runs_list(limit: int = 20, db: str = Depends(require_db)) -> dict:
    return {"runs": list_runs(db, limit=limit)}


@router.get("/{run_id}")
def runs_get(run_id: str, db: str = Depends(require_db)) -> dict:
    run = get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    return run


@router.get("/{run_id}/transforms")
def runs_transforms(run_id: str, db: str = Depends(require_db)) -> dict:
    """Flat lineage table: every ``transformation_runs`` row whose
    ``source_run_id`` matches *run_id*, oldest first.

    Used by the workbench RunExplorer to render transform lineage as a
    plain table (no graph viz).
    """
    if get_run(db, run_id) is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT transform_run_id, transform_name, transform_version,
                   created_at, row_count, parameters_json,
                   experiment_run_id, notes
              FROM transformation_runs
             WHERE source_run_id = ?
             ORDER BY created_at ASC, transform_run_id ASC
            """,
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    return {"run_id": run_id, "transforms": [dict(r) for r in rows]}
