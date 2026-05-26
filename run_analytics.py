"""
run_analytics.py — execute every *.sql file in analytics/sql/ and print the
result tables.  Intended as a one-stop sanity check after a simulation run.

Usage::

    python run_analytics.py
    python run_analytics.py --db data/delivery_system.sqlite
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path


def _print_table(headers: list[str], rows: list[tuple]) -> None:
    if not rows:
        print("  (no rows)")
        return
    str_rows = [[("" if v is None else str(v)) for v in r] for r in rows]
    widths = [max(len(h), *(len(r[i]) for r in str_rows)) for i, h in enumerate(headers)]
    fmt = "  " + "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in str_rows:
        print(fmt.format(*r))


def run_one(conn: sqlite3.Connection, sql_path: Path) -> None:
    print(f"\n=== {sql_path.name} " + "=" * max(0, 56 - len(sql_path.name)))
    sql = sql_path.read_text(encoding="utf-8")
    cur = conn.execute(sql)
    headers = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    _print_table(headers, rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run analytics/sql/*.sql against the local SQLite database.")
    parser.add_argument("--db",      default="data/delivery_system.sqlite")
    parser.add_argument("--sql-dir", default="analytics/sql")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 2

    sql_dir = Path(args.sql_dir)
    sql_files = sorted(sql_dir.glob("*.sql"))
    if not sql_files:
        print(f"No SQL files in {sql_dir}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(args.db)
    try:
        for path in sql_files:
            run_one(conn, path)
    finally:
        conn.close()

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
