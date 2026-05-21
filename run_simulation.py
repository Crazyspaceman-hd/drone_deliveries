"""
run_simulation.py — CLI entry point for the synthetic event simulator.

Examples::

    python run_simulation.py --drones 3 --trips 10 --seed 42
    python run_simulation.py --reset --trips 20
"""

import argparse
import os
import sys

from core.simulator import run_simulation
from core.sinks import export_events_to_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate synthetic drone-delivery events into a local SQLite database."
    )
    parser.add_argument("--db",     default="data/delivery_system.sqlite",
                        help="SQLite database path (default: data/delivery_system.sqlite)")
    parser.add_argument("--drones", type=int, default=3, help="Fleet size (default: 3)")
    parser.add_argument("--trips",  type=int, default=10, help="Number of trips (default: 10)")
    parser.add_argument("--seed",   type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument("--reset",  action="store_true",
                        help="Delete the SQLite file before running.")
    parser.add_argument("--export-jsonl", dest="export_jsonl", default=None,
                        help="If given, after the run export delivery_events "
                             "to this path as one JSON object per line.")
    args = parser.parse_args(argv)

    if args.reset and os.path.exists(args.db):
        os.remove(args.db)
        print(f"Removed existing database: {args.db}")

    summary = run_simulation(
        db_path=args.db,
        n_drones=args.drones,
        n_trips=args.trips,
        seed=args.seed,
    )

    print()
    print("--- Simulation summary " + "-" * 40)
    print(f"  db_path:          {summary['db_path']}")
    print(f"  drones:           {summary['drones']}")
    print(f"  trips_requested:  {summary['trips_requested']}")
    print(f"  trips_completed:  {summary['trips_completed']}")
    print(f"  events_written:   {summary['events_written']}")
    print("  event_counts_by_type:")
    for ev_type, n in sorted(summary["event_counts_by_type"].items()):
        print(f"    {ev_type:<22} {n:>6}")

    if args.export_jsonl:
        exported = export_events_to_jsonl(args.db, args.export_jsonl)
        print(f"  jsonl_export:     {args.export_jsonl} ({exported} rows)")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
