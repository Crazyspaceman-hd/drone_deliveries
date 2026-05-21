"""Every analytics/sql/*.sql file runs without error and returns at least one row."""

import sqlite3
from pathlib import Path

import pytest


SQL_DIR = Path(__file__).resolve().parent.parent / "analytics" / "sql"


def _sql_files():
    return sorted(SQL_DIR.glob("*.sql"))


@pytest.mark.parametrize("sql_path", _sql_files(), ids=lambda p: p.name)
def test_query_returns_rows(seed42_db: Path, sql_path: Path):
    sql = sql_path.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(seed42_db))
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    assert rows, f"{sql_path.name} returned no rows"


def test_at_least_one_sql_file_exists():
    # Guard against the parametrize collapsing to zero cases if the dir
    # is empty for some reason.
    assert _sql_files(), "no .sql files found in analytics/sql/"
