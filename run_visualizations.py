"""
run_visualizations.py — render PNG charts from the local SQLite event store.

Usage::

    python run_visualizations.py
    python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts
"""

import argparse
import os
import sys

from core.visualizations import generate_charts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate static PNG charts from the local SQLite event store."
    )
    parser.add_argument("--db",  default="data/delivery_system.sqlite",
                        help="SQLite database path (default: data/delivery_system.sqlite)")
    parser.add_argument("--out", default="outputs/charts",
                        help="Output directory for PNGs (default: outputs/charts)")
    args = parser.parse_args(argv)

    if not os.path.exists(args.db):
        print(
            f"Database not found: {args.db}\n"
            "Run the simulator first, e.g.:\n"
            "    python run_simulation.py --reset --drones 3 --trips 10 --seed 42",
            file=sys.stderr,
        )
        return 2

    paths = generate_charts(db_path=args.db, out_dir=args.out)
    print(f"Wrote {len(paths)} charts to {args.out}:")
    for name, path in paths.items():
        print(f"  {name:<22} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
