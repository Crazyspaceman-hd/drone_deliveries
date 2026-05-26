"""
run_validation.py — rule-based data-quality checks over the project DB.

This is not enterprise governance; it's a sanity layer that asserts
the operational invariants the simulator is supposed to maintain.

Examples::

    python run_validation.py
    python run_validation.py --run-id <id>
    python run_validation.py --markdown outputs/reports/validation_report.md
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from core.validation import (
    ERROR, INFO, WARN, generate_validation_summary,
)


_TABLE_COLS = [
    ("rule_name",     "rule",            42),
    ("severity",      "severity",         8),
    ("passed",        "passed",           6),
    ("run_id",        "run",             10),
    ("details",       "details",         70),
]


def _print_table(results: list[dict]) -> None:
    headers = [h for _, h, _ in _TABLE_COLS]
    widths  = [w for _, _, w in _TABLE_COLS]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in results:
        vals = []
        for key, _h, w in _TABLE_COLS:
            v = r.get(key)
            if key == "run_id":
                v = "" if v is None else str(v)[:8]
            elif key == "passed":
                v = "yes" if v else "NO"
            s = "" if v is None else str(v)
            if len(s) > w:
                s = s[:w-1] + "…"
            vals.append(s)
        print(fmt.format(*vals))


def _to_markdown(summary: dict) -> str:
    th = summary["counts_by_severity"]
    failed = summary["failed_by_severity"]
    lines = [
        "# Drone delivery — validation report",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}._",
        "",
        ("This report enforces the simulator's operational invariants — "
         "completed trips have their terminal events, run_id lineage is "
         "intact, economics are finite, the Parquet export matches the "
         "SQLite source, and DuckDB cross-layer aggregates agree with "
         "SQLite within rounding tolerance."),
        "",
        "## Headline",
        "",
        f"- Total checks: {sum(th.values())}",
        f"- Severity counts: INFO={th[INFO]}, WARN={th[WARN]}, ERROR={th[ERROR]}",
        f"- Failures by severity: INFO={failed[INFO]}, WARN={failed[WARN]}, "
        f"ERROR={failed[ERROR]}",
        f"- Overall: {'ERRORS PRESENT' if summary['any_errors'] else 'no errors'}",
        "",
        "## Results",
        "",
        "| Rule | Severity | Passed | Run | Details | Affected (sample) |",
        "|---|---|---|---|---|---|",
    ]
    for r in summary["results"]:
        affected = r["affected_rows"][:5]
        if len(r["affected_rows"]) > 5:
            affected = affected + [f"...(+{len(r['affected_rows'])-5} more)"]
        run = (r.get("run_id") or "")[:8]
        details_md = r["details"].replace("|", "\\|")
        passed_md  = "yes" if r["passed"] else "NO"
        affected_md = ", ".join(str(a) for a in affected)
        lines.append(
            f"| `{r['rule_name']}` "
            f"| {r['severity']} "
            f"| {passed_md} "
            f"| {run} "
            f"| {details_md} "
            f"| {affected_md} |"
        )
    lines += [
        "",
        "## What this is not",
        "",
        "- Not enterprise compliance tooling.",
        "- Not a schema registry.",
        "- Not a substitute for the test suite.",
        "",
        "These checks are runtime invariants over the local SQLite store "
        "and the per-run Parquet exports.  Re-run after every scenario "
        "set, or wire into CI before publishing a run as canonical.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rule-based data-quality validation over the project DB."
    )
    parser.add_argument("--db",       default="data/delivery_system.sqlite")
    parser.add_argument("--run-id",   default=None,
                        help="Scope checks to one simulation run.")
    parser.add_argument("--markdown", default=None,
                        help="If set, also write the report to this path.")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 2

    summary = generate_validation_summary(args.db, run_id=args.run_id)

    print("\n--- Validation results " + "-" * 60)
    _print_table(summary["results"])
    th, failed = summary["counts_by_severity"], summary["failed_by_severity"]
    print(
        f"\nTotal: {sum(th.values())} checks  "
        f"(INFO={th[INFO]}, WARN={th[WARN]}, ERROR={th[ERROR]})  "
        f"| failures: INFO={failed[INFO]}, WARN={failed[WARN]}, "
        f"ERROR={failed[ERROR]}"
    )
    if summary["any_errors"]:
        print("STATUS: ERRORS PRESENT")
    else:
        print("STATUS: no errors")
    print()

    if args.markdown:
        os.makedirs(os.path.dirname(args.markdown) or ".", exist_ok=True)
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(_to_markdown(summary))
        print(f"Wrote markdown report: {args.markdown}\n")

    return 1 if summary["any_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
