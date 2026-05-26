"""
run_duckdb_analytics.py — DuckDB analytics over per-run Parquet exports.

The simulator's SQLite DB is the operational source of truth.  This CLI
queries the per-run Parquet exports under ``outputs/runs/run_id=*/parquet``
through an in-process DuckDB connection.

Usage::

    python run_duckdb_analytics.py --all-runs
    python run_duckdb_analytics.py --run-id <id>
    python run_duckdb_analytics.py --all-runs --markdown outputs/reports/duckdb_summary.md
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.duckdb_analytics import (
    discover_run_parquet_dirs, generate_duckdb_summary,
)


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


def _resolve_dirs(args) -> list[str]:
    if args.run_id:
        d = Path(args.base) / f"run_id={args.run_id}" / "parquet"
        if not d.is_dir():
            print(f"No parquet directory at {d}", file=sys.stderr)
            return []
        return [str(d)]
    return discover_run_parquet_dirs(args.base)


def _to_markdown(summary: dict[str, dict], dirs: list[str]) -> str:
    lines = [
        "# DuckDB analytics summary",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}._",
        "",
        f"Scanned {len(dirs)} parquet director{'y' if len(dirs)==1 else 'ies'}:",
        "",
    ]
    for d in dirs:
        lines.append(f"- `{d}`")
    lines.append("")
    for name, result in summary.items():
        lines += [f"## {name}", "", f"_Source: `{result['path']}`_", ""]
        if not result["rows"]:
            lines.append("_(no rows)_")
            lines.append("")
            continue
        lines.append("| " + " | ".join(result["headers"]) + " |")
        lines.append("|" + "|".join(["---"] * len(result["headers"])) + "|")
        for r in result["rows"]:
            lines.append("| " + " | ".join("" if v is None else str(v) for v in r) + " |")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run DuckDB queries over per-run Parquet exports."
    )
    parser.add_argument("--base",    default="outputs/runs",
                        help="Base directory holding run_id=*/parquet folders.")
    parser.add_argument("--run-id",  default=None,
                        help="Limit to a single run; otherwise all runs found.")
    parser.add_argument("--all-runs", action="store_true",
                        help="(Default) glob every run under --base.")
    parser.add_argument("--sql-dir", default="analytics/duckdb")
    parser.add_argument("--markdown", default=None,
                        help="Optional path to also write a markdown summary.")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    dirs = _resolve_dirs(args)
    if not dirs:
        print(
            "No per-run Parquet directories found.\n"
            "Run an export first, e.g.:\n"
            "  python run_scenarios.py --export-parquet --trips 50 --seed 42",
            file=sys.stderr,
        )
        return 2

    print(f"Scanning {len(dirs)} parquet director{'y' if len(dirs)==1 else 'ies'}:")
    for d in dirs:
        print(f"  {d}")
    print()

    summary = generate_duckdb_summary(dirs, sql_dir=args.sql_dir)
    if not summary:
        print(f"No SQL files in {args.sql_dir}", file=sys.stderr)
        return 2

    for name, result in summary.items():
        print(f"=== {name} " + "=" * max(0, 56 - len(name)))
        _print_table(result["headers"], result["rows"])
        print()

    if args.markdown:
        os.makedirs(os.path.dirname(args.markdown) or ".", exist_ok=True)
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(_to_markdown(summary, dirs))
        print(f"Wrote markdown summary: {args.markdown}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
