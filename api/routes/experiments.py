"""
api/routes/experiments.py

Experiment lineage endpoints (Phase 24) + what-if launcher (Phase 32).

    GET  /experiments           — list all experiment_runs rows
    GET  /experiments/{id}      — single row + compute_summary output
    POST /experiments/what-if   — launch a controlled parameter sweep

The what-if launcher is the only write path; it reuses the existing
``Experiment`` runner so there's a single execution code path.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from api.dependencies import require_db
from core.experiments import Experiment

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.post("/what-if")
def what_if_endpoint(
    body: dict = Body(...),
    db: str = Depends(require_db),
) -> dict:
    """Launch a controlled parameter sweep from the workbench.

    Request body::

        {
            "dimension": "capacity_model",     # or "delivery_domain"
            "base":      "pilot_capacity",
            "parameter": "operator_to_drone_ratio",
            "values":    [0.60, 0.45, 0.30, 0.20],
            "run_ids":   ["..."]               # optional
        }

    Reuses the existing ``Experiment`` runner — no second execution
    path.  ``delivery_domain`` sweeps write economics snapshots with
    synthetic domain names; ``capacity_model`` sweeps are read-side and
    record their synthetic names in the experiment definition for
    discovery by the viability readers (they write no new snapshots).

    Response includes the synthetic names created and a hint to refresh
    the viability grid.
    """
    from datetime import datetime, timezone
    from core.experiments import ExperimentDefinition, ParameterSweep

    dimension = body.get("dimension")
    base      = body.get("base")
    parameter = body.get("parameter")
    values    = body.get("values")
    run_ids   = body.get("run_ids") or []

    if not (dimension and base and parameter and isinstance(values, list) and values):
        raise HTTPException(
            status_code=422,
            detail="what-if requires non-empty 'dimension', 'base', "
                   "'parameter', and a non-empty 'values' list.",
        )

    try:
        sweep = ParameterSweep(
            dimension = dimension,
            base_name = base,
            parameter = parameter,
            values    = list(values),
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # Mirror the CLI: capacity base must NOT go into delivery_domains.
    domains = [base] if dimension == "delivery_domain" else ["retail_package"]
    defn = ExperimentDefinition(
        name             = f"_whatif_{ts}",
        run_ids          = list(run_ids),
        scenarios        = [],
        economic_models  = ["suburban_standard"],
        delivery_domains = domains,
        scale_models     = ["pilot_program"],
        parameter_sweeps = [sweep],
    )
    result = Experiment(defn, db).run()
    if result["status"] != "completed":
        raise HTTPException(
            status_code=500,
            detail=f"experiment failed: {result.get('error', 'unknown')}",
        )

    return {
        "experiment_name":   defn.name,
        "experiment_run_id": result["experiment_run_id"],
        "dimension":         dimension,
        "synthetic_names":   sweep.synthetic_names(),
        "run_ids_used":      run_ids,
        "combinations":      result.get("combinations", 0),
        "next_step":         (
            "Refresh the viability grid (GET /analytics/viability-summary) "
            "— the synthetic variants now appear alongside registered profiles."
        ),
    }


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
