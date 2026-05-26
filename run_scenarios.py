"""
run_scenarios.py — execute multiple operational scenarios into ONE SQLite DB.

Events from each scenario are tagged with ``scenario_name`` so the
``analytics/sql/scenario_summary.sql`` query (and any custom comparative
analytics) can group by scenario without doing anything special.

Example::

    python run_scenarios.py --scenarios urban_dense suburban_standard rural_extended \\
                            --drones 3 --trips 50 --seed 42

Notes
─────
The same SQLite DB hosts every scenario.  Drone and trip projection rows are
created fresh in each scenario's call to ``run_simulation``; cross-scenario
projection state can therefore be slightly inconsistent (the simulator's
Python-side fleet view starts each scenario with all drones idle, regardless
of the DB's residual state from the previous scenario).  This is acceptable
because the comparative analysis is event-driven — the append-only event log
remains coherent and scenario-tagged throughout.

Caveat: the per-scenario ``events_written`` printed in the streaming output
is the *cumulative* row count of ``delivery_events`` at the end of that
scenario's call, not the per-scenario contribution.  Use
``analytics/sql/scenario_summary.sql`` (e.g. via ``run_analytics.py``) for
clean per-scenario totals.
"""

import argparse
import os
import sys

from core.scenarios import list_scenarios
from core.simulator import run_simulation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run multiple operational scenarios into a single SQLite DB."
    )
    parser.add_argument("--db",        default="data/delivery_system.sqlite")
    parser.add_argument("--drones",    type=int, default=3)
    parser.add_argument("--trips",     type=int, default=50)
    parser.add_argument("--seed",      type=int, default=42)
    parser.add_argument("--scenarios", nargs="+",
                        default=["urban_dense", "suburban_standard", "rural_extended"],
                        help=f"Known: {', '.join(list_scenarios())}")
    parser.add_argument("--reset",     action="store_true",
                        help="Remove the SQLite file before running.")
    parser.add_argument("--export-parquet", dest="export_parquet",
                        action="store_true",
                        help="After each run, export its per-run tables to "
                             "outputs/runs/run_id=<id>/parquet/")
    parser.add_argument("--no-transforms", dest="run_transforms",
                        action="store_false", default=True,
                        help="Skip the post-simulation transform pipeline. "
                             "By default transforms (economics, hybrid) run "
                             "automatically per simulation so derived columns "
                             "are populated for the API / UI.")
    args = parser.parse_args(argv)

    if args.reset and os.path.exists(args.db):
        os.remove(args.db)
        print(f"Removed existing database: {args.db}")

    print(f"Running {len(args.scenarios)} scenario(s) into {args.db}\n")
    summaries: list[dict] = []
    for scen in args.scenarios:
        print(f"--- scenario: {scen} -------------------------------------")
        summ = run_simulation(
            db_path=args.db,
            n_drones=args.drones,
            n_trips=args.trips,
            seed=args.seed,
            scenario=scen,
        )
        summaries.append(summ)
        print(f"  trips_requested={summ['trips_requested']:>4}  "
              f"trips_completed={summ['trips_completed']:>4}  "
              f"events_written={summ['events_written']:>5}")

        # Phase 20: derived columns are populated automatically by
        # run_simulation() unless the caller passes --no-transforms.

        if args.export_parquet:
            # Lazy import: only require pyarrow/pandas when the user asks.
            from core.sinks import export_run_to_parquet
            res = export_run_to_parquet(args.db, summ["run_id"])
            total_rows = sum(res["rows"].values())
            print(f"  parquet_export:   {res['out_dir']} ({total_rows} rows)")

    # Compact comparison table.
    print()
    print("--- comparison " + "-" * 60)
    headers = ["scenario", "trips_req", "trips_done", "events", "battery_warn",
               "emerg_ret", "route_dev", "maint_req"]
    widths  = [max(len(h), 18) for h in headers]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for s in summaries:
        c = s["event_counts_by_type"]
        print(fmt.format(
            s["scenario"],
            s["trips_requested"],
            s["trips_completed"],
            s["events_written"],
            c.get("battery_warning", 0),
            c.get("emergency_return", 0),
            c.get("route_deviation", 0),
            c.get("maintenance_required", 0),
        ))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
