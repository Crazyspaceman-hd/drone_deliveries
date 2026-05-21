"""JSONL export round-trip."""

import json
import sqlite3
from pathlib import Path

from core.sinks import export_events_to_jsonl


REQUIRED_KEYS = {"event_id", "event_time", "ingested_at", "event_type", "payload_json"}


def test_export_matches_table(seed42_db: Path, tmp_path: Path):
    out = tmp_path / "events.jsonl"
    exported = export_events_to_jsonl(str(seed42_db), str(out))

    conn = sqlite3.connect(str(seed42_db))
    try:
        table_count = conn.execute(
            "SELECT COUNT(*) FROM delivery_events"
        ).fetchone()[0]
    finally:
        conn.close()

    assert exported == table_count

    with out.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
    assert len(lines) == table_count

    first = json.loads(lines[0])
    missing = REQUIRED_KEYS - set(first.keys())
    assert not missing, f"first JSONL event missing keys: {missing}"
