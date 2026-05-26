"""
core/runs.py

Lightweight experiment-tracking layer.

Every call to ``core.simulator.run_simulation`` inserts one row into
``simulation_runs`` and stamps every event/trip/order it emits with the
resulting ``run_id``.  Outside callers can use this module directly to
record runs of their own simulator variants (manual experiments, parameter
sweeps, etc.).

What we deliberately do *not* do here
─────────────────────────────────────
- No orchestration / scheduler.
- No artifact registry (just text columns).
- No automatic uploads anywhere.
- No JSON schema validation.

This is just enough lineage to make outputs attributable and runs
queryable.  Heavier metadata tooling (MLflow, Weights & Biases, etc.) is
a Phase 16+ decision and would replace, not extend, this module.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Optional


# Manual version strings — bump when the simulator's semantics change in a
# way you want runs to be distinguishable by.
SIMULATOR_VERSION  = "phase21"
ASSUMPTION_VERSION = "phase14_calibrated"


# ─────────────────────────────────────────────────────────────────────────────
# git hash capture (best-effort)
# ─────────────────────────────────────────────────────────────────────────────

def capture_git_commit(repo_path: Optional[str] = None) -> Optional[str]:
    """Return the short HEAD commit hash, or None if git is unavailable.

    Failure modes handled:
      - git not on PATH      (FileNotFoundError)
      - not a git working dir (non-zero exit)
      - timeout              (TimeoutExpired)
      - anything else        (OSError / generic Exception)
    Never raises.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_path or os.getcwd(),
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    except Exception:  # noqa: BLE001 — best-effort capture
        return None
    if result.returncode != 0:
        return None
    out = (result.stdout or "").strip()
    return out or None


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_simulation_run(
    db_path: str,
    *,
    seed: Optional[int]              = None,
    scenario_names: Optional[str]    = None,
    trip_count: Optional[int]        = None,
    drone_count: Optional[int]       = None,
    notes: Optional[str]             = None,
    git_commit: Optional[str]        = None,
    assumption_version: str          = ASSUMPTION_VERSION,
    simulator_version: str           = SIMULATOR_VERSION,
    run_id: Optional[str]            = None,
    created_at: Optional[str]        = None,
) -> str:
    """Insert one ``simulation_runs`` row and return the ``run_id``.

    ``run_id`` and ``created_at`` are auto-generated when not provided.
    ``git_commit`` is auto-captured (best-effort) if None is passed; pass
    an explicit empty string ``""`` if you want to skip capture entirely.
    """
    if run_id is None:
        run_id = str(uuid.uuid4())
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    if git_commit is None:
        git_commit = capture_git_commit()
    elif git_commit == "":
        git_commit = None

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO simulation_runs (
                run_id, created_at, seed, scenario_names,
                trip_count, drone_count, notes,
                git_commit, assumption_version, simulator_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, created_at, seed, scenario_names,
                trip_count, drone_count, notes,
                git_commit, assumption_version, simulator_version,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def get_run(db_path: str, run_id: str) -> Optional[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM simulation_runs WHERE run_id = ?", (run_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_runs(db_path: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM simulation_runs "
            "ORDER BY created_at DESC, run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
