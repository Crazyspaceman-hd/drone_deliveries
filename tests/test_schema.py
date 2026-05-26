"""Schema creation: every expected table + delivery_events columns."""

import sqlite3
from pathlib import Path


EXPECTED_TABLES = {
    "depots", "drones", "orders", "trips", "trip_legs", "delivery_events",
}

EXPECTED_EVENT_COLUMNS = {
    "event_id", "event_time", "ingested_at",
    "drone_id", "trip_id", "leg_id", "event_type",
    "latitude", "longitude", "battery_pct", "payload_json",
}


def test_tables_created(empty_db: Path):
    conn = sqlite3.connect(str(empty_db))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        conn.close()
    tables = {r[0] for r in rows}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"missing tables: {missing}"


def test_delivery_events_columns(empty_db: Path):
    conn = sqlite3.connect(str(empty_db))
    try:
        rows = conn.execute("PRAGMA table_info(delivery_events)").fetchall()
    finally:
        conn.close()
    cols = {r[1] for r in rows}
    missing = EXPECTED_EVENT_COLUMNS - cols
    assert not missing, f"missing columns on delivery_events: {missing}"
