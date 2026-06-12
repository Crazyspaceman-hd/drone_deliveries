"""
run_calibration_analysis.py — configured-vs-observed drift report.

Calibration here means "did the simulator do what the scenario knobs
asked it to" — *not* "is the simulator realistic."  Outputs are
plain-English drift bullets plus a per-scenario table.

Usage::

    python run_calibration_analysis.py --db data/delivery_system.sqlite
    python run_calibration_analysis.py --db data/delivery_system.sqlite \\
                                       --markdown outputs/reports/calibration_report.md
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from cli_common import add_db_arg, require_db
from core.calibration import (
    ALIGN_KM, ALIGN_PROB, DIVERGE_KM, DIVERGE_PROB,
    generate_calibration_summary,
)


_TABLE_COLS = [
    ("scenario_name",                       "scenario",        18),
    ("configured_emergency_return_chance",  "cfg_emerg",       10),
    ("observed_emergency_return_rate",      "obs_emerg",       10),
    ("emergency_return_drift",              "drift_emerg",     12),
    ("emergency_return_drift_label",        "label_emerg",     22),
    ("configured_maintenance_chance",       "cfg_maint",       10),
    ("observed_maintenance_rate",           "obs_maint",       10),
    ("maintenance_drift",                   "drift_maint",     12),
    ("maintenance_drift_label",             "label_maint",     22),
    ("configured_route_deviation_chance",   "cfg_route",       10),
    ("observed_route_deviation_rate",       "obs_route",       10),
    ("route_deviation_drift",               "drift_route",     12),
    ("route_deviation_drift_label",         "label_route",     22),
    ("configured_avg_trip_distance_km",     "cfg_dist_km",     12),
    ("observed_avg_trip_distance_km",       "obs_dist_km",     12),
    ("avg_trip_distance_drift_km",          "drift_dist_km",   14),
    ("avg_trip_distance_drift_label",       "label_dist",      22),
]


def _print_table(rows: list[dict]) -> None:
    headers = [h for _, h, _ in _TABLE_COLS]
    widths  = [w for _, _, w in _TABLE_COLS]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*("-" * w for w in widths)))
    for r in rows:
        vals = [str(r.get(k, "")) for k, _h, _w in _TABLE_COLS]
        print(fmt.format(*vals))


def _to_markdown(summary: dict) -> str:
    rows = summary["drift_rows"]
    th   = summary["thresholds"]
    lines = [
        "# Drone delivery — calibration drift report",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}._",
        "",
        "This report compares **observed** simulator outputs against the "
        "**configured** scenario knobs.  Calibration is not validation: a "
        "low drift just means the simulator did what its knobs said; it "
        "does not mean the knobs reflect the real world.",
        "",
        "**Drift convention:** `drift = observed − configured` (positive = "
        "observed exceeded the configured expectation).",
        "",
        f"**Thresholds:** `|drift| < {th['ALIGN_PROB']}` aligned · "
        f"`< {th['DIVERGE_PROB']}` minor · `≥ {th['DIVERGE_PROB']}` "
        f"significant (probabilities). "
        f"Distance: `< {th['ALIGN_KM']}` aligned · `< {th['DIVERGE_KM']}` "
        f"minor · `≥ {th['DIVERGE_KM']}` significant.",
        "",
        "## Per-scenario drift",
        "",
    ]
    if not rows:
        lines.append("_No scenario data in the database._")
    else:
        headers = ["scenario", "metric", "configured", "observed", "drift", "label"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for r in rows:
            for metric, cfg_k, obs_k, drift_k, label_k in [
                ("emergency_return_rate",
                 "configured_emergency_return_chance",
                 "observed_emergency_return_rate",
                 "emergency_return_drift",
                 "emergency_return_drift_label"),
                ("maintenance_rate",
                 "configured_maintenance_chance",
                 "observed_maintenance_rate",
                 "maintenance_drift",
                 "maintenance_drift_label"),
                ("route_deviation_rate",
                 "configured_route_deviation_chance",
                 "observed_route_deviation_rate",
                 "route_deviation_drift",
                 "route_deviation_drift_label"),
                ("avg_trip_distance_km",
                 "configured_avg_trip_distance_km",
                 "observed_avg_trip_distance_km",
                 "avg_trip_distance_drift_km",
                 "avg_trip_distance_drift_label"),
            ]:
                lines.append(
                    f"| {r['scenario_name']} | {metric} | {r[cfg_k]} | "
                    f"{r[obs_k]} | {r[drift_k]} | {r[label_k]} |"
                )

    lines += ["", "## Interpretations", ""]
    for b in summary["interpretations"]:
        lines.append(f"- {b}")

    lines += [
        "",
        "## Caveats",
        "",
        "- Calibration ≠ validation; nothing here claims real-world accuracy.",
        "- Configured probabilities for `maintenance_chance` are per-trip; "
        "the simulator can *also* fire maintenance when battery < 25%, so "
        "observed maintenance rates frequently exceed the configured chance.",
        "- Route-deviation chance is rolled per telemetry ping (not per "
        "trip).  The observed rate is therefore deviations / pings, not "
        "deviations / trips.",
        "- Average trip distance comes from Haversine over Portland-area "
        "coordinates; the configured value is informational only.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configured-vs-observed calibration report."
    )
    add_db_arg(parser)
    parser.add_argument("--markdown", default=None,
                        help="If set, also write the report as markdown.")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    if not require_db(args.db):
        return 2

    summary = generate_calibration_summary(args.db)

    print("\n--- Configured vs observed " + "-" * 56)
    if not summary["drift_rows"]:
        print("  (no scenario-tagged rows in database)")
    else:
        _print_table(summary["drift_rows"])

    th = summary["thresholds"]
    print(
        f"\nThresholds: |drift| < {th['ALIGN_PROB']} aligned · "
        f"< {th['DIVERGE_PROB']} minor · >= {th['DIVERGE_PROB']} significant "
        f"(probabilities). Distance: < {th['ALIGN_KM']} aligned · "
        f"< {th['DIVERGE_KM']} minor · >= {th['DIVERGE_KM']} significant."
    )

    print("\n--- Interpretations " + "-" * 50)
    for b in summary["interpretations"]:
        print(f"  - {b}")
    print()

    if args.markdown:
        os.makedirs(os.path.dirname(args.markdown) or ".", exist_ok=True)
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(_to_markdown(summary))
        print(f"Wrote markdown report: {args.markdown}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
