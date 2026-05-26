"""
transforms/runs.py

CRUD over ``transformation_runs`` — the analytical-lineage table.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.runs import capture_git_commit


def record_transform_run(
    db_path: str,
    *,
    source_run_id:     Optional[str],
    transform_name:    str,
    transform_version: str,
    parameters_json:   Optional[str]  = None,
    row_count:         Optional[int]  = None,
    notes:             Optional[str]  = None,
    git_commit:        Optional[str]  = None,
    transform_run_id:  Optional[str]  = None,
    experiment_run_id: Optional[str]  = None,
) -> str:
    """Insert one row into ``transformation_runs`` and return its id.

    ``git_commit`` is captured automatically when ``None`` is passed (same
    convention as ``core.runs.create_simulation_run``).  Pass an explicit
    empty string to skip capture.

    ``transform_run_id`` may be pre-allocated by the caller so that other
    rows written during the same transform pass (e.g. Phase 22's
    trip_economics_snapshots) can reference it before this row exists.

    ``experiment_run_id`` (Phase 24) links this row back to the
    ``experiment_runs`` record that triggered the transform.  Leave ``None``
    for direct ``transforms/*.run()`` calls outside an experiment.
    """
    if transform_run_id is None:
        transform_run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    if git_commit is None:
        git_commit = capture_git_commit()
    elif git_commit == "":
        git_commit = None

    # Dict-driven INSERT: adding a future column is a single dict entry.
    # Column order matches the table definition but is not load-bearing —
    # we build the SQL from the dict keys at call time.
    fields: dict = {
        "transform_run_id":  transform_run_id,
        "source_run_id":     source_run_id,
        "transform_name":    transform_name,
        "transform_version": transform_version,
        "created_at":        created_at,
        "parameters_json":   parameters_json,
        "git_commit":        git_commit,
        "row_count":         row_count,
        "notes":             notes,
        "experiment_run_id": experiment_run_id,
    }
    cols         = ", ".join(fields.keys())
    placeholders = ", ".join("?" * len(fields))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"INSERT INTO transformation_runs ({cols}) VALUES ({placeholders})",
            tuple(fields.values()),
        )
        conn.commit()
    finally:
        conn.close()
    return transform_run_id


def list_transform_runs(db_path: str, limit: int = 50) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM transformation_runs "
            " ORDER BY created_at DESC, transform_run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def list_source_run_ids(db_path: str) -> list[str]:
    """All simulation_runs.run_id values currently present in the DB."""
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute(
            "SELECT run_id FROM simulation_runs ORDER BY created_at ASC"
        ).fetchall()]
    finally:
        conn.close()
