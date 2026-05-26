"""
core/sinks.py

Portable event exports.

The operational store is SQLite (see core.events, core.setup_db).  This
module turns the same event rows into JSONL — one JSON object per line —
which is the format most cloud lakehouse loaders (S3 + Athena, BigQuery
external tables, DuckDB, Snowflake stages, Iceberg via Trino) accept
directly.

Kept deliberately small.  No abstract Sink base class; if a second sink
shape is ever needed, copy the JsonlSink and rename it.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional, Union

from core.models import DeliveryEvent


class JsonlSink:
    """Append-only JSONL writer for DeliveryEvent rows.

    One JSON object per line.  Field order matches the delivery_events
    table column order so the output is also easy to read by eye.

    Usage::

        sink = JsonlSink("data/events.jsonl")
        for ev in events:
            sink.write(ev)
        sink.close()

    Or as a context manager::

        with JsonlSink("data/events.jsonl") as sink:
            sink.write(event)
    """

    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # utf-8 + newline="" so the file is identical on Windows and POSIX.
        self._fh = open(path, "w", encoding="utf-8", newline="")
        self.count = 0

    def write(self, event: Union[DeliveryEvent, dict]) -> None:
        row = event.to_dict() if isinstance(event, DeliveryEvent) else dict(event)
        # payload_json is already a JSON string; keep it as-is so consumers
        # can choose whether to re-parse it.
        self._fh.write(json.dumps(row, separators=(",", ":")))
        self._fh.write("\n")
        self.count += 1

    # Alias for callers that prefer the longer name.
    write_event = write

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> "JsonlSink":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# ─────────────────────────────────────────────────────────────────────────────
# Convenience helper
# ─────────────────────────────────────────────────────────────────────────────

# Column order matches setup_db.py delivery_events DDL.
_EVENT_COLUMNS = (
    "event_id", "event_time", "ingested_at",
    "drone_id", "trip_id", "leg_id", "event_type",
    "latitude", "longitude", "battery_pct", "payload_json",
    "scenario_name", "run_id",
)


def export_events_to_jsonl(
    db_path: str,
    out_path: str,
    where: Optional[str] = None,
) -> int:
    """Dump every delivery_events row in chronological order to JSONL.

    Args:
        db_path:  Source SQLite database.
        out_path: Target JSONL path; parent directories auto-created.
        where:    Optional SQL fragment (without leading WHERE) to filter rows.

    Returns:
        Number of rows written.
    """
    cols = ", ".join(_EVENT_COLUMNS)
    sql = f"SELECT {cols} FROM delivery_events"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY event_time ASC, event_id ASC"

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()

    with JsonlSink(out_path) as sink:
        for row in rows:
            sink.write(dict(zip(_EVENT_COLUMNS, row)))
        return sink.count


# ─────────────────────────────────────────────────────────────────────────────
# Run-aware output path helper (Phase 15)
# ─────────────────────────────────────────────────────────────────────────────

def run_output_dir(run_id: str, base: str = "outputs/runs") -> str:
    """Return (and create) the per-run output directory.

    Format: ``<base>/run_id=<run_id>/`` (Hive-style key=value so glob tools
    and lakehouse loaders pick the partition up automatically).
    """
    path = os.path.join(base, f"run_id={run_id}")
    os.makedirs(path, exist_ok=True)
    return path


def export_run_events_to_jsonl(
    db_path: str, run_id: str, out_path: Optional[str] = None,
) -> tuple[int, str]:
    """Export just one run's events to JSONL.

    Returns (row_count, output_path).  If ``out_path`` is None, writes to
    ``outputs/runs/run_id=<run_id>/events.jsonl``.
    """
    if out_path is None:
        out_path = os.path.join(run_output_dir(run_id), "events.jsonl")
    n = export_events_to_jsonl(db_path, out_path, where=f"run_id = '{run_id}'")
    return n, out_path


# ─────────────────────────────────────────────────────────────────────────────
# Parquet export (Phase 16)
# ─────────────────────────────────────────────────────────────────────────────
#
# Parquet is the analytical-portability layer.  SQLite stays the operational
# source of truth; Parquet is what an analyst or downstream OLAP engine
# (DuckDB, BigQuery external tables, Athena, Snowflake stages) consumes.
#
# We use pandas + pyarrow because it is the simplest two-line round trip
# from a sqlite cursor to a Parquet file.  Both deps are optional from the
# project's perspective — if missing, the helpers raise a clear ImportError
# rather than crashing somewhere deeper.

# Tables we export per run.  Order matters only for predictability in the
# returned summary dict.
_RUN_PARQUET_TABLES = (
    "delivery_events",
    "trips",
    "orders",
    "simulation_runs",
)


def _require_parquet_stack():
    """Raise a clear ImportError if pandas/pyarrow aren't available."""
    try:
        import pandas        # noqa: F401
        import pyarrow       # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "Parquet export requires `pandas` and `pyarrow`. "
            "Install them via `pip install -r requirements.txt`."
        ) from exc


def _export_table_to_parquet(
    db_path: str, table: str, out_path: str, *, where: Optional[str] = None,
) -> int:
    """Pull one table (optionally filtered) into a Parquet file.

    Returns the number of rows written.
    """
    import pandas as pd  # local import: keeps module load light
    conn = sqlite3.connect(db_path)
    try:
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        df = pd.read_sql_query(sql, conn)
    finally:
        conn.close()

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    df.to_parquet(out_path, engine="pyarrow", index=False)
    return len(df)


def export_run_to_parquet(
    db_path: str,
    run_id: str,
    out_dir: Optional[str] = None,
) -> dict:
    """Dump every table for ``run_id`` to a per-run Parquet directory.

    Output layout::

        <out_dir or outputs/runs/run_id=<id>>/parquet/
            delivery_events.parquet
            trips.parquet
            orders.parquet
            simulation_runs.parquet

    Returns a dict like::

        {"run_id":   "...",
         "out_dir":  "outputs/runs/run_id=.../parquet",
         "rows":     {"delivery_events": 156, "trips": 10, ...},
         "files":    {"delivery_events": "...delivery_events.parquet", ...}}

    Raises ImportError if pandas/pyarrow aren't installed.  No SQLite
    schema is altered; this is a pure export.
    """
    _require_parquet_stack()
    if out_dir is None:
        out_dir = os.path.join(run_output_dir(run_id), "parquet")
    os.makedirs(out_dir, exist_ok=True)

    rows:  dict[str, int] = {}
    files: dict[str, str] = {}
    for table in _RUN_PARQUET_TABLES:
        out_path = os.path.join(out_dir, f"{table}.parquet")
        where = (f"run_id = '{run_id}'" if table != "simulation_runs"
                 else f"run_id = '{run_id}'")
        # simulation_runs has run_id as its PK, so the filter is also safe
        # there and gives the analyst a one-row provenance block.
        rows[table]  = _export_table_to_parquet(db_path, table, out_path, where=where)
        files[table] = out_path

    return {"run_id": run_id, "out_dir": out_dir, "rows": rows, "files": files}


def export_all_runs_to_parquet(
    db_path: str, base_dir: str = "outputs/runs",
) -> list[dict]:
    """Convenience: export every simulation_runs row in db_path."""
    conn = sqlite3.connect(db_path)
    try:
        run_ids = [r[0] for r in conn.execute(
            "SELECT run_id FROM simulation_runs ORDER BY created_at ASC"
        ).fetchall()]
    finally:
        conn.close()
    return [export_run_to_parquet(db_path, rid) for rid in run_ids]
