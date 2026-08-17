"""
core/assumptions.py

Machine-readable view of the simulator's assumptions.

Each Scenario field is tagged with one of two categories:
  - "publicly_informed": loosely anchored to ranges that appear in
        public reporting / industry discussion of delivery operations,
        energy use, urban-vs-rural density, last-mile economics.  The
        VALUES are still chosen by the project — the category just
        records that "there is a real-world range to anchor against."
  - "synthetic": invented for comparative behavior with no claim of
        external grounding.

This module reads the registry in core/scenarios.py and re-emits it as
plain dicts so other code (CLI, tests, markdown report) can consume it
without importing matplotlib or pulling SQL.

See docs/assumptions.md for the narrative version and rationale.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from core.business_intelligence import (
    BORDERLINE_SCORE_MIN, STRONG_SCORE_MIN,
    W_COMPLETION, W_EMERGENCY_PENALTY,
    W_MAINTENANCE_PENALTY, W_PROFIT_MARGIN,
)
from core.scenarios import _SCENARIOS, list_scenarios


# Field → (category, short description).  Update both here AND docs/assumptions.md
# if you change the categorisation.
FIELD_CATEGORIES: dict[str, tuple[str, str]] = {
    # Operational geometry
    "avg_trip_distance_km":         ("publicly_informed",
        "Loosely tracks urban single-digit-km / rural longer-range public discussion. "
        "Drives pickup/dropoff coordinate radius around depot (Phase 14)."),
    "trip_distance_variance":       ("synthetic",
        "Documentation-only; the simulator picks coordinates from fixed lat/lon ranges."),
    "battery_warning_threshold":    ("publicly_informed",
        "Typical fleet-ops low-alert band, 20–35%."),

    # Power / energy
    "avg_kwh_per_km":               ("publicly_informed",
        "Roughly tracks small-drone per-km energy discussions, ~0.05–0.15 kWh/km."),
    "energy_cost_per_kwh":          ("publicly_informed",
        "Loosely tracks U.S. retail electricity ranges; held constant across scenarios."),

    # Maintenance
    "maintenance_duration_seconds": ("publicly_informed",
        "Few-minutes field-swap ranges; longer for rural where parts/transport are harder."),
    "maintenance_cost_per_event":   ("publicly_informed",
        "Direction (rural > urban) reflects field-service discussions; absolute values comparative."),

    # Revenue
    "delivery_fee":                 ("publicly_informed",
        "Last-mile fee ranges vary widely; chosen so the BI 'needs >2x fee for rural' finding surfaces."),

    # Synthetic behavior knobs
    "telemetry_bonus_per_leg":      ("synthetic",
        "Extra pings/leg in dense urban; invented for visual texture."),
    "battery_drain_multiplier":     ("synthetic",
        "Scales per-step drain; suburban=1.0 preserves the historical seeded baseline."),
    "route_deviation_chance":       ("synthetic",
        "Probability knob shaping urban 'weave' vs rural 'open airspace' texture."),
    "emergency_return_chance":      ("synthetic",
        "Per-trip abort probability; chosen for visible inter-scenario contrast."),
    "maintenance_chance":           ("synthetic",
        "Per-trip non-emergency maintenance probability."),

    # Synthetic economics
    "emergency_return_penalty":     ("synthetic",
        "Financial drag applied to aborted trips; invented absolute values."),
    "labor_cost_per_delivery":      ("synthetic",
        "Flat per-trip labor overhead; invented."),
    "drone_depreciation_per_trip":  ("synthetic",
        "Per-trip equipment wear; invented."),
}


def get_scenario_assumptions() -> list[dict[str, Any]]:
    """One dict per scenario.  Each dict carries every Scenario field, plus a
    nested ``categories`` mapping so downstream code can render an annotated
    table without re-reading this module's constants."""
    out: list[dict[str, Any]] = []
    for name in list_scenarios():
        sc = _SCENARIOS[name]
        row = asdict(sc)
        row["categories"] = {
            field: {
                "category": FIELD_CATEGORIES.get(field, ("synthetic", ""))[0],
                "note":     FIELD_CATEGORIES.get(field, ("synthetic", ""))[1],
            }
            for field in row if field != "name"
        }
        out.append(row)
    return out


def get_bi_assumptions() -> dict[str, Any]:
    """BI scoring weights + thresholds.  All synthetic by construction."""
    return {
        "category": "synthetic",
        "weights": {
            "W_COMPLETION":          W_COMPLETION,
            "W_PROFIT_MARGIN":       W_PROFIT_MARGIN,
            "W_EMERGENCY_PENALTY":   W_EMERGENCY_PENALTY,
            "W_MAINTENANCE_PENALTY": W_MAINTENANCE_PENALTY,
        },
        "thresholds": {
            "STRONG_SCORE_MIN":     STRONG_SCORE_MIN,
            "BORDERLINE_SCORE_MIN": BORDERLINE_SCORE_MIN,
        },
        "notes": (
            "Tuned to the three built-in scenarios so the ranking visibly "
            "separates them; retune if you change the cost model."
        ),
    }


def get_assumption_summary() -> dict[str, Any]:
    """Single bundled dict: scenarios + BI + categorised fields."""
    return {
        "scenarios":         get_scenario_assumptions(),
        "bi":                get_bi_assumptions(),
        "field_categories":  {k: {"category": v[0], "note": v[1]}
                              for k, v in FIELD_CATEGORIES.items()},
        "doc_path":          "docs/assumptions.md",
    }
