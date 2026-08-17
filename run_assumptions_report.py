"""
run_assumptions_report.py — print the simulator's assumption tables.

Reads the machine-readable view from core.assumptions and prints a
readable table per scenario, plus the BI weighting block.  Optionally
writes a deterministic markdown report to disk.

Usage::

    python run_assumptions_report.py
    python run_assumptions_report.py --markdown outputs/reports/assumptions_report.md
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from core.assumptions import (
    FIELD_CATEGORIES, get_assumption_summary,
)


# Fields shown per scenario (in display order).
_SCENARIO_FIELDS = [
    "avg_trip_distance_km",
    "trip_distance_variance",
    "battery_warning_threshold",
    "avg_kwh_per_km",
    "energy_cost_per_kwh",
    "maintenance_duration_seconds",
    "maintenance_cost_per_event",
    "delivery_fee",
    "telemetry_bonus_per_leg",
    "battery_drain_multiplier",
    "route_deviation_chance",
    "emergency_return_chance",
    "maintenance_chance",
    "emergency_return_penalty",
    "labor_cost_per_delivery",
    "drone_depreciation_per_trip",
]


def _scenario_table_rows(summary: dict) -> list[list[str]]:
    """Build a list-of-rows table: field | category | <scenario columns>."""
    scenarios = summary["scenarios"]
    headers = ["field", "category"] + [s["name"] for s in scenarios]
    rows: list[list[str]] = [headers]
    for field in _SCENARIO_FIELDS:
        cat = FIELD_CATEGORIES.get(field, ("synthetic", ""))[0]
        row = [field, cat]
        for s in scenarios:
            v = s.get(field)
            row.append("" if v is None else str(v))
        rows.append(row)
    return rows


def _print_grid(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*rows[0]))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows[1:]:
        print(fmt.format(*r))


def _to_markdown(summary: dict) -> str:
    scenarios = summary["scenarios"]
    bi        = summary["bi"]

    lines = [
        "# Drone delivery — assumption calibration report",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}._",
        "",
        "This report is a machine-generated view of the assumptions in "
        "`core/scenarios.py` and `core/business_intelligence.py`. "
        "See `docs/assumptions.md` for the narrative version.",
        "",
        "Categories:",
        "",
        "- **publicly_informed** — picked to land in a plausible public range. "
        "Values are still chosen by the project; no specific source is cited.",
        "- **synthetic** — invented for comparative behavior with no claim of "
        "external grounding.",
        "",
        "## Scenario knobs",
        "",
    ]

    # Markdown table
    header = ["field", "category"] + [s["name"] for s in scenarios]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for field in _SCENARIO_FIELDS:
        cat = FIELD_CATEGORIES.get(field, ("synthetic", ""))[0]
        row = [f"`{field}`", cat]
        for s in scenarios:
            v = s.get(field)
            row.append("" if v is None else str(v))
        lines.append("| " + " | ".join(row) + " |")

    lines += [
        "",
        "### Field notes",
        "",
    ]
    for field in _SCENARIO_FIELDS:
        cat, note = FIELD_CATEGORIES.get(field, ("synthetic", ""))
        if note:
            lines.append(f"- `{field}` ({cat}) — {note}")

    lines += [
        "",
        "## Business-intelligence scoring",
        "",
        f"Category: **{bi['category']}**.  {bi['notes']}",
        "",
        "Weights:",
        "",
    ]
    for k, v in bi["weights"].items():
        lines.append(f"- `{k}` = {v}")
    lines += ["", "Thresholds:", ""]
    for k, v in bi["thresholds"].items():
        lines.append(f"- `{k}` = {v}")

    lines += [
        "",
        "## What this report is not",
        "",
        "- Not a forecast.",
        "- Not a citation of any single industry source.",
        "- Not a claim of accuracy for any individual number.",
        "",
        "It is a snapshot of the simulator's inputs so the comparative "
        "outputs (scenario rankings, profitability charts) can be read "
        "against the assumptions that produced them.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print or export the simulator's assumption tables."
    )
    parser.add_argument("--markdown", default=None,
                        help="If set, also write the report as a markdown file.")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    summary = get_assumption_summary()

    print("\n--- Scenario knob assumptions " + "-" * 40)
    _print_grid(_scenario_table_rows(summary))

    bi = summary["bi"]
    print("\n--- Business-intelligence scoring " + "-" * 36)
    print(f"  category: {bi['category']}")
    for k, v in bi["weights"].items():
        print(f"  {k:<24} {v}")
    for k, v in bi["thresholds"].items():
        print(f"  {k:<24} {v}")
    print(f"  note: {bi['notes']}")

    print("\nFull narrative: docs/assumptions.md")
    print()

    if args.markdown:
        os.makedirs(os.path.dirname(args.markdown) or ".", exist_ok=True)
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(_to_markdown(summary))
        print(f"Wrote markdown report: {args.markdown}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
