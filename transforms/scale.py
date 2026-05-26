"""
transforms/scale.py

Fleet-scale amortization overlay (Phase 23).

Reads economics snapshots and writes one row per trip to
``trip_scale_snapshots`` carrying the amortized overhead and
utilization-adjusted ``effective_profit`` under the chosen
``ScaleModel``.  Source events are never touched.

Pipeline position
─────────────────
    economics (10) → scale (15) → hybrid (20) → telemetry (30)

scale runs AFTER economics (needs the snapshot to amortize over) and
BEFORE hybrid+telemetry (which are independent and don't read scale).

What this transform MUST NOT write to
──────────────────────────────────────
- trips
- delivery_events
- trip_economics_snapshots   (Phase 22's table; immutable to scale)
- telemetry_observations
- orders

Enforced by ``tests/test_scale_models.py`` separation invariants.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.scale_models import (
    SCALE_MODEL_REGISTRY_VERSION, ScaleModel, get_scale_model,
)
from transforms.runs import record_transform_run


TRANSFORM_NAME    = "scale"
TRANSFORM_VERSION = "scale.v1"
RUN_ORDER         = 15   # between economics (10) and hybrid (20)


def _effective_profit(
    *, source_profit: float, source_op_cost: float, sm: ScaleModel,
) -> float:
    """Combine amortized overhead with a utilization rebate.

    effective_profit = source_profit
                     - amortized_overhead_per_trip
                     + utilization_efficiency * idle_reduction_factor
                       * source_operational_cost

    The rebate captures "better utilization recovers part of the
    per-trip operational cost"; without it, large fleets would look
    strictly worse than small ones because of the overhead floor.
    """
    overhead = sm.amortized_overhead_per_trip()
    rebate   = sm.utilization_efficiency * sm.idle_reduction_factor * source_op_cost
    return source_profit - overhead + rebate


def _select_source_snapshots(
    conn: sqlite3.Connection,
    *,
    run_id:                 Optional[str],
    source_snapshot_run_id: Optional[str],
) -> list[tuple]:
    """Return (trip_id, transform_run_id, estimated_profit,
                estimated_operational_cost) for each trip's source
    economics snapshot.

    When ``source_snapshot_run_id`` is given, restrict to that one
    economics-recompute pass.  Otherwise pick the most recent
    economics snapshot per trip (matches the default-pipeline
    auto-run).  Optional ``run_id`` further scopes by simulation run.
    """
    if source_snapshot_run_id is not None:
        sql = """
            SELECT s.trip_id, s.transform_run_id,
                   s.estimated_profit, s.estimated_operational_cost
              FROM trip_economics_snapshots s
              JOIN trips t ON t.trip_id = s.trip_id
             WHERE s.transform_run_id = ?
        """
        params: tuple = (source_snapshot_run_id,)
        if run_id is not None:
            sql   += " AND t.run_id = ?"
            params = params + (run_id,)
        return conn.execute(sql, params).fetchall()

    # Otherwise: latest economics snapshot per trip.
    sql = """
        WITH ranked AS (
            SELECT s.trip_id, s.transform_run_id,
                   s.estimated_profit, s.estimated_operational_cost,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.trip_id ORDER BY s.created_at DESC
                   ) AS rk
              FROM trip_economics_snapshots s
              JOIN trips t ON t.trip_id = s.trip_id
             WHERE 1=1
    """
    params2: tuple = ()
    if run_id is not None:
        sql    += " AND t.run_id = ?"
        params2 = (run_id,)
    sql += """
        )
        SELECT trip_id, transform_run_id, estimated_profit,
               estimated_operational_cost
          FROM ranked WHERE rk = 1
    """
    return conn.execute(sql, params2).fetchall()


def run(
    db_path: str,
    *,
    run_id:                 Optional[str] = None,
    scale_model:            Optional[ScaleModel | str] = None,
    source_snapshot_run_id: Optional[str] = None,
    experiment_run_id:      Optional[str] = None,
) -> dict:
    """Compute amortized overhead + effective profit for every trip and
    INSERT one row per trip into ``trip_scale_snapshots``.

    Args:
        db_path:                SQLite file.
        run_id:                 Limit to one simulation run.  None = every
                                trip in the DB.
        scale_model:            Override ScaleModel (name, instance, or
                                None for default = pilot_program).
        source_snapshot_run_id: Pin the economics snapshot to amortize
                                over.  None = each trip's most-recent
                                economics snapshot.

    Side effects:
        * INSERT one row per trip into ``trip_scale_snapshots``,
          keyed by (trip_id, transform_run_id).  PK collision is
          impossible per call because ``transform_run_id`` is fresh.
        * INSERT one row into ``transformation_runs`` with
          parameters_json = {scale_model, source_snapshot_run_id,
                             registry_versions}.

    Returns a small summary dict.
    """
    sm = get_scale_model(scale_model)
    transform_run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        sources = _select_source_snapshots(
            conn, run_id=run_id, source_snapshot_run_id=source_snapshot_run_id,
        )
        cur = conn.cursor()
        rows_written = 0
        for trip_id, src_tx_id, src_profit, src_op_cost in sources:
            src_profit  = float(src_profit  or 0.0)
            src_op_cost = float(src_op_cost or 0.0)
            overhead    = round(sm.amortized_overhead_per_trip(), 4)
            effective   = round(
                _effective_profit(
                    source_profit=src_profit,
                    source_op_cost=src_op_cost,
                    sm=sm,
                ),
                4,
            )
            cur.execute(
                """
                INSERT OR REPLACE INTO trip_scale_snapshots (
                    trip_id, transform_run_id, source_snapshot_run_id,
                    scale_model_name, amortized_overhead_per_trip,
                    effective_profit, utilization_efficiency, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trip_id, transform_run_id, src_tx_id,
                    sm.name, overhead, effective,
                    sm.utilization_efficiency, created_at,
                ),
            )
            rows_written += 1
        conn.commit()
    finally:
        conn.close()

    params_json = json.dumps(
        {
            "scale_model":            sm.name,
            "source_snapshot_run_id": source_snapshot_run_id,
            "registry_versions":      {"scale_model": SCALE_MODEL_REGISTRY_VERSION},
        },
        separators=(",", ":"), sort_keys=True,
    )
    record_transform_run(
        db_path,
        source_run_id     = run_id,
        transform_name    = TRANSFORM_NAME,
        transform_version = TRANSFORM_VERSION,
        parameters_json   = params_json,
        row_count         = rows_written,
        notes             = f"scale_model={sm.name}",
        transform_run_id  = transform_run_id,
        experiment_run_id = experiment_run_id,   # Phase 24: FK to experiment_runs
    )
    return {
        "transform_run_id":       transform_run_id,
        "transform_name":         TRANSFORM_NAME,
        "transform_version":      TRANSFORM_VERSION,
        "source_run_id":          run_id,
        "scale_model":            sm.name,
        # Use the same key name as the other transforms so the CLI's
        # summary loop ("Ran N transforms:") can iterate over results
        # uniformly without per-module casing.
        "rows_updated":           rows_written,
        "source_snapshot_run_id": source_snapshot_run_id,
    }
