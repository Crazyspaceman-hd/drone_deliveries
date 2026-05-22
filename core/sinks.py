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
    "scenario_name",
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
