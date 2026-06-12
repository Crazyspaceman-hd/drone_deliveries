"""
run_visualizations.py — render PNG charts from the local SQLite event store.

Usage::

    python run_visualizations.py
    python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts

After ``generate_charts`` writes everything under ``--out`` (gitignored
by default), the small ``PUBLISHED_CHARTS`` set is also copied to
``docs/img/`` so the README's embedded headline chart resolves on
GitHub.  ``outputs/`` stays a pure scratch directory; ``docs/img/``
is the tracked publish path.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

from core.visualizations import generate_charts


# Charts the README + docs embed directly.  Copied to ``docs/img/``
# alongside the main render so the tracked-path reference resolves on
# GitHub without poking a hole in the ``outputs/`` gitignore rule.
PUBLISHED_CHARTS = (
    "viability_by_capacity_and_domain",
    "service_mix_profit_by_volume",
)
PUBLISH_DIR      = Path(__file__).resolve().parent / "docs" / "img"


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
    # Print the ABSOLUTE path of the output directory so there is no
    # ambiguity about where the files landed.  Past failure mode: the
    # relative path "outputs/charts" looks identical when it resolves to
    # ``C:\Users\you\Documents\...`` (local) vs ``...\OneDrive\Documents\...``
    # (synced) — the terminal sees one, Explorer's "Documents" shortcut
    # often points at the other.  Showing the absolute path makes the
    # mismatch impossible to miss.
    out_abs = os.path.abspath(args.out)
    print(f"Wrote {len(paths)} charts to:")
    print(f"  {out_abs}")
    print()
    for name, path in paths.items():
        print(f"  {name:<40} {os.path.basename(path)}")

    # Copy the published headline chart(s) into the tracked docs/img/
    # path so the README's embed resolves on GitHub.
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    published_any = False
    for name in PUBLISHED_CHARTS:
        src = paths.get(name)
        if not src or not os.path.exists(src):
            continue
        dest = PUBLISH_DIR / os.path.basename(src)
        shutil.copyfile(src, dest)
        if not published_any:
            print()
            print(f"Published to {PUBLISH_DIR}:")
            published_any = True
        print(f"  {name:<40} {dest.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
