"""
run_history.py — list recent simulation runs, or inspect one by ID.

Examples::

    python run_history.py
    python run_history.py --limit 5
    python run_history.py --run-id abc123ef
"""

import argparse
import os
import sqlite3
import sys

from core.runs import get_run, list_runs


_LIST_COLS = [
    ("run_id",             "run_id",           38),
    ("created_at",         "created_at",       26),
    ("scenario_names",     "scenarios",        20),
    ("seed",               "seed",              6),
    ("trip_count",         "trips",             6),
    ("drone_count",        "drones",            6),
    ("simulator_version",  "sim_ver",          14),
    ("assumption_version", "assumption_ver",   22),
    ("git_commit",         "git",              10),
]


def _print_list(rows: list[dict]) -> None:
    headers = [h for _, h, _ in _LIST_COLS]
    widths  = [w for _, _, w in _LIST_COLS]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        vals = []
        for key, _h, w in _LIST_COLS:
            v = r.get(key)
            s = "" if v is None else str(v)
            if len(s) > w:
                s = s[:w-1] + "…"
            vals.append(s)
        print(fmt.format(*vals))


def _print_detail(db_path: str, run_id: str) -> int:
    run = get_run(db_path, run_id)
    if run is None:
        print(f"No run with id {run_id!r}", file=sys.stderr)
        return 2
    print(f"\nRun {run['run_id']}")
    print("=" * (len(run["run_id"]) + 4))
    for k in ("created_at", "scenario_names", "seed", "trip_count", "drone_count",
              "simulator_version", "assumption_version", "git_commit", "notes"):
        print(f"  {k:<20} {run.get(k) if run.get(k) is not None else '-'}")

    # Per-run metrics from the DB.
    conn = sqlite3.connect(db_path)
    try:
        trips = dict(zip(
            ("trips", "completed", "aborted", "total_profit", "avg_profit"),
            conn.execute(
                """
                SELECT COUNT(*),
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN status='aborted'   THEN 1 ELSE 0 END),
                       COALESCE(SUM(estimated_profit), 0),
                       COALESCE(AVG(estimated_profit), 0)
                  FROM trips WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone(),
        ))
        events = conn.execute(
            "SELECT COUNT(*) FROM delivery_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        per_type = conn.execute(
            "SELECT event_type, COUNT(*) FROM delivery_events "
            "WHERE run_id = ? GROUP BY event_type ORDER BY COUNT(*) DESC",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    print("\n  Metrics")
    print("  -------")
    print(f"    trips           {trips['trips'] or 0}")
    print(f"    completed       {trips['completed'] or 0}")
    print(f"    aborted         {trips['aborted'] or 0}")
    print(f"    total_profit    {round(float(trips['total_profit'] or 0), 2)}")
    print(f"    avg_profit/trip {round(float(trips['avg_profit'] or 0), 2)}")
    print(f"    events          {events}")
    print("    events_by_type:")
    for et, n in per_type:
        print(f"      {et:<24} {n}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List or inspect simulation runs recorded in the local DB."
    )
    parser.add_argument("--db",     default="data/delivery_system.sqlite")
    parser.add_argument("--limit",  type=int, default=20)
    parser.add_argument("--run-id", default=None,
                        help="Show full detail for one run by ID.")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 2

    if args.run_id:
        return _print_detail(args.db, args.run_id)

    rows = list_runs(args.db, limit=args.limit)
    if not rows:
        print("(no simulation runs recorded yet)")
        return 0
    print(f"Recent simulation runs ({len(rows)}):\n")
    _print_list(rows)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
