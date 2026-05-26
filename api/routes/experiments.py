"""
api/routes/experiments.py

Read-only experiment lineage endpoints (Phase 24).

Two endpoints only:
    GET  /experiments         — list all experiment_runs rows
    GET  /experiments/{id}    — single row + compute_summary output

No POST.  No trigger-via-API.  The experiment layer is a CLI/Python
concern; the API is a read-only lineage window.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import require_db
from core.experiments import Experiment

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.get("")
def list_experiments_endpoint(db: str = Depends(require_db)) -> dict:
    """Return all experiment_runs rows, newest first.

    Response shape::

        {
            "experiments": [
                {
                    "experiment_run_id": "...",
                    "experiment_name":   "scale_sweep",
                    "status":            "completed",
                    "started_at":        "2026-05-26T...",
                    "completed_at":      "2026-05-26T..."
                },
                ...
            ]
        }
    """
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT experiment_run_id, experiment_name, status,
                   started_at, completed_at
              FROM experiment_runs
             ORDER BY started_at DESC
            """
        ).fetchall()
    finally:
        conn.close()

    return {
        "experiments": [
            {
                "experiment_run_id": r[0],
                "experiment_name":   r[1],
                "status":            r[2],
                "started_at":        r[3],
                "completed_at":      r[4],
            }
            for r in rows
        ]
    }


@router.get("/{experiment_run_id}")
def get_experiment_endpoint(
    experiment_run_id: str,
    db: str = Depends(require_db),
) -> dict:
    """Return one experiment_runs row plus its compute_summary output.

    Response shape::

        {
            "experiment_run_id": "...",
            "experiment_name":   "full_grid",
            "status":            "completed",
            "started_at":        "...",
            "completed_at":      "...",
            "definition":        {...},
            "summary": {
                "experiment_run_id": "...",
                "profiles": [
                    {
                        "scenario_name":        "suburban_standard",
                        "domain_name":          "food_delivery",
                        "scale_model_name":     "urban_dense_fleet",
                        "avg_effective_profit": 4.21,
                        "avg_overhead":         1.96,
                        "avg_revenue":          22.38,
                        "break_even_rate":      0.8,
                        "trip_count":           10
                    },
                    ...
                ]
            }
        }

    Returns 404 if the experiment_run_id is not found.
    """
    import json

    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            """
            SELECT experiment_run_id, experiment_name, status,
                   started_at, completed_at, definition_json, error
              FROM experiment_runs
             WHERE experiment_run_id = ?
            """,
            (experiment_run_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"experiment_run_id {experiment_run_id!r} not found",
        )

    exp_id, exp_name, status, started_at, completed_at, defn_json, error = row

    result: dict = {
        "experiment_run_id": exp_id,
        "experiment_name":   exp_name,
        "status":            status,
        "started_at":        started_at,
        "completed_at":      completed_at,
        "definition":        json.loads(defn_json) if defn_json else None,
    }
    if error:
        result["error"] = error

    # Attach compute_summary output for completed experiments.
    if status == "completed":
        result["summary"] = Experiment.compute_summary_for(db, exp_id)
    else:
        result["summary"] = {"experiment_run_id": exp_id, "profiles": []}

    return result
