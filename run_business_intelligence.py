"""
run_business_intelligence.py — rule-based BI report over a scenario-tagged DB.

Reads the SQLite store, prints a ranked scenario table and a list of
recommendations.  Optionally writes a small markdown report under
``outputs/reports/``.

Usage::

    python run_business_intelligence.py --db data/delivery_system.sqlite
    python run_business_intelligence.py --markdown outputs/reports/bi_report.md
"""

import argparse
import os
import sys
from datetime import datetime

from cli_common import add_db_arg, require_db
from core.business_intelligence import generate_feasibility_report


_TABLE_COLS = (
    ("scenario_name",         "scenario",         18),
    ("feasibility_score",     "score",             8),
    ("feasibility_label",     "label",            18),
    ("completion_rate",       "complete_rate",    14),
    ("avg_profit_per_trip",   "avg_profit/trip",  16),
    ("emergency_rate",        "emerg_rate",       11),
    ("maintenance_per_trip",  "maint/trip",       11),
)


def _print_table(rankings: list[dict]) -> None:
    headers = [h for _, h, _ in _TABLE_COLS]
    widths  = [w for _, _, w in _TABLE_COLS]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rankings:
        vals = []
        for key, _hdr, _w in _TABLE_COLS:
            v = r.get(key)
            vals.append("" if v is None else str(v))
        print(fmt.format(*vals))


def _to_markdown(report: dict) -> str:
    lines = ["# Drone delivery scenario feasibility report",
             "",
             f"_Generated {datetime.utcnow().isoformat(timespec='seconds')}Z._",
             "",
             "## Rankings",
             "",
             "| Scenario | Score | Label | Completion | Avg profit/trip | Emergency rate | Maint/trip |",
             "|---|---:|---|---:|---:|---:|---:|"]
    for r in report["rankings"]:
        lines.append(
            f"| {r['scenario_name']} "
            f"| {r['feasibility_score']} "
            f"| {r['feasibility_label']} "
            f"| {r['completion_rate']} "
            f"| {r['avg_profit_per_trip']} "
            f"| {r['emergency_rate']} "
            f"| {r['maintenance_per_trip']} |"
        )
    lines += ["", "## Recommendations", ""]
    for rec in report["recommendations"]:
        lines.append(f"- {rec}")
    lines += ["", "## Scoring weights", ""]
    for k, v in report["scoring_weights"].items():
        lines.append(f"- `{k}` = {v}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rule-based business-intelligence report over a scenario-tagged DB."
    )
    add_db_arg(parser)
    parser.add_argument("--markdown", default=None,
                        help="If set, also write the report as a markdown file.")
    # Force-set encoding for stdout on Windows so we can print recommendation
    # text that may contain non-ASCII characters in the future.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = parser.parse_args(argv)

    if not require_db(args.db):
        return 2

    report = generate_feasibility_report(args.db)

    print("\n--- Scenario feasibility ranking " + "-" * 36)
    _print_table(report["rankings"])
    print("\n--- Recommendations " + "-" * 50)
    if not report["recommendations"]:
        print("  (no recommendations)")
    for rec in report["recommendations"]:
        print(f"  - {rec}")
    print()

    if args.markdown:
        os.makedirs(os.path.dirname(args.markdown) or ".", exist_ok=True)
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(_to_markdown(report))
        print(f"Wrote markdown report: {args.markdown}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
