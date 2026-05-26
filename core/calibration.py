"""
core/calibration.py

Observed-vs-configured drift analysis.

This module compares what the scenarios *say* should happen (the knobs in
core.scenarios) against what the simulator *actually* produced (rows in
the SQLite event log).  The output is plain dicts of numbers plus a few
rule-based interpretation strings.

Important framing
──────────────────
This is **calibration**, not **validation**.  We're checking whether the
simulator's emergent behaviour matches the dial settings the operator
turned — not whether either matches the real world.  A low drift just
means "the simulator did what you told it to," not "the simulator is
realistic."

Drift convention
─────────────────
    drift = observed - configured

Positive drift means "observed exceeded the configured expectation."

Threshold labels (documented and tunable, top of file):

    |drift| <  0.02          → aligned
    0.02 <= |drift| <  0.05  → minor_divergence
    |drift| >= 0.05          → significant_divergence

Distance drift uses kilometres instead of probabilities, with its own
thresholds (also tunable).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from core.scenarios import _SCENARIOS, list_scenarios


# ── Tunable thresholds (documented in docs/assumptions.md once Phase 14
#    needs them; for now they live here as the single source of truth). ────
ALIGN_PROB     = 0.02
DIVERGE_PROB   = 0.05
ALIGN_KM       = 0.5
DIVERGE_KM     = 2.0


# ─────────────────────────────────────────────────────────────────────────────
# Observed metrics (computed straight from the DB)
# ─────────────────────────────────────────────────────────────────────────────

_OBSERVED_SQL = """
WITH t AS (
    SELECT scenario_name,
           COUNT(*)                                            AS trips,
           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
           AVG(trip_distance_km)                               AS avg_distance_km,
           AVG(estimated_profit)                               AS avg_profit_per_trip
      FROM trips
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
),
e AS (
    SELECT scenario_name,
           SUM(CASE WHEN event_type='emergency_return'     THEN 1 ELSE 0 END) AS emergencies,
           SUM(CASE WHEN event_type='maintenance_required' THEN 1 ELSE 0 END) AS maintenance,
           SUM(CASE WHEN event_type='battery_warning'      THEN 1 ELSE 0 END) AS battery_warnings,
           SUM(CASE WHEN event_type='route_deviation'      THEN 1 ELSE 0 END) AS route_deviations,
           SUM(CASE WHEN event_type='telemetry_ping'       THEN 1 ELSE 0 END) AS pings
      FROM delivery_events
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
)
SELECT t.scenario_name, t.trips, t.completed,
       t.avg_distance_km, t.avg_profit_per_trip,
       COALESCE(e.emergencies,       0) AS emergencies,
       COALESCE(e.maintenance,       0) AS maintenance,
       COALESCE(e.battery_warnings,  0) AS battery_warnings,
       COALESCE(e.route_deviations,  0) AS route_deviations,
       COALESCE(e.pings,             0) AS pings
  FROM t
  LEFT JOIN e ON e.scenario_name = t.scenario_name
 ORDER BY t.scenario_name ASC
"""


def compute_observed_metrics(db_path: str) -> list[dict[str, Any]]:
    """One dict per scenario with observed rates and totals.

    All rate fields land in [0, 1]; distance is in km; profit is in
    synthetic USD units.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(_OBSERVED_SQL).fetchall()
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for (name, trips, completed, avg_dist, avg_profit,
         emerg, maint, batt_warn, route_dev, pings) in rows:
        trips = trips or 0
        out.append({
            "scenario_name":              name,
            "trips":                      trips,
            "completed_trips":            completed or 0,
            "completion_rate":            round((completed or 0) / trips, 4) if trips else 0.0,
            "observed_avg_trip_distance_km": round(avg_dist or 0.0, 3),
            "observed_avg_profit_per_trip": round(avg_profit or 0.0, 2),
            "observed_emergency_return_rate":
                round((emerg or 0) / trips, 4) if trips else 0.0,
            "observed_maintenance_rate":
                round((maint or 0) / trips, 4) if trips else 0.0,
            # Battery warnings are rolled per telemetry ping in
            # _maybe_inject_warnings, so the per-ping rate is the comparable
            # quantity (analogous to observed_route_deviation_rate).
            "observed_battery_warning_rate":
                round((batt_warn or 0) / pings, 4) if pings else 0.0,
            # Route deviation is rolled per telemetry ping in the simulator,
            # so the observed *per-ping* rate is what compares directly to
            # the configured chance.
            "observed_route_deviation_rate":
                round((route_dev or 0) / pings, 4) if pings else 0.0,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Drift
# ─────────────────────────────────────────────────────────────────────────────

def _drift_label_prob(diff: float) -> str:
    a = abs(diff)
    if a < ALIGN_PROB:
        return "aligned"
    if a < DIVERGE_PROB:
        return "minor_divergence"
    return "significant_divergence"


def _drift_label_km(diff_km: float) -> str:
    a = abs(diff_km)
    if a < ALIGN_KM:
        return "aligned"
    if a < DIVERGE_KM:
        return "minor_divergence"
    return "significant_divergence"


def compute_calibration_drift(db_path: str) -> list[dict[str, Any]]:
    """For each scenario, configured + observed + drift + drift labels."""
    observed = {r["scenario_name"]: r for r in compute_observed_metrics(db_path)}
    out: list[dict[str, Any]] = []
    for name in list_scenarios():
        sc = _SCENARIOS[name]
        obs = observed.get(name)
        if obs is None:
            # Scenario configured but no rows in DB — skip rather than guess.
            continue

        emerg_d = obs["observed_emergency_return_rate"] - sc.emergency_return_chance
        maint_d = obs["observed_maintenance_rate"]      - sc.maintenance_chance
        route_d = obs["observed_route_deviation_rate"]  - sc.route_deviation_chance
        dist_d  = obs["observed_avg_trip_distance_km"]  - sc.avg_trip_distance_km

        out.append({
            "scenario_name":                   name,
            # Configured side (from core.scenarios)
            "configured_emergency_return_chance":  sc.emergency_return_chance,
            "configured_maintenance_chance":       sc.maintenance_chance,
            "configured_route_deviation_chance":   sc.route_deviation_chance,
            "configured_avg_trip_distance_km":     sc.avg_trip_distance_km,
            # Observed side (from DB)
            "observed_emergency_return_rate":      obs["observed_emergency_return_rate"],
            "observed_maintenance_rate":           obs["observed_maintenance_rate"],
            "observed_route_deviation_rate":       obs["observed_route_deviation_rate"],
            "observed_avg_trip_distance_km":       obs["observed_avg_trip_distance_km"],
            "completion_rate":                     obs["completion_rate"],
            "observed_avg_profit_per_trip":        obs["observed_avg_profit_per_trip"],
            # Drifts and labels
            "emergency_return_drift":              round(emerg_d, 4),
            "emergency_return_drift_label":        _drift_label_prob(emerg_d),
            "maintenance_drift":                   round(maint_d, 4),
            "maintenance_drift_label":             _drift_label_prob(maint_d),
            "route_deviation_drift":               round(route_d, 4),
            "route_deviation_drift_label":         _drift_label_prob(route_d),
            "avg_trip_distance_drift_km":          round(dist_d, 3),
            "avg_trip_distance_drift_label":       _drift_label_km(dist_d),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Interpretations (rule-based, no hard-coded scenario names)
# ─────────────────────────────────────────────────────────────────────────────

def _phrase(metric: str, diff: float) -> str:
    direction = "exceeded" if diff > 0 else "fell short of"
    return f"observed {metric} {direction} the configured expectation by {abs(diff):.3f}"


def generate_calibration_interpretations(db_path: str) -> list[str]:
    rows = compute_calibration_drift(db_path)
    bullets: list[str] = []
    if not rows:
        return ["No scenario data found in the database."]

    # Per-scenario, per-metric rules.
    for r in rows:
        name = r["scenario_name"]
        for metric_key, drift_key, label_key, observed_key in [
            ("emergency-return rate", "emergency_return_drift",
             "emergency_return_drift_label",     "observed_emergency_return_rate"),
            ("maintenance rate",      "maintenance_drift",
             "maintenance_drift_label",          "observed_maintenance_rate"),
            ("route-deviation rate",  "route_deviation_drift",
             "route_deviation_drift_label",      "observed_route_deviation_rate"),
        ]:
            label = r[label_key]
            if label == "aligned":
                bullets.append(
                    f"{name}: {metric_key} aligned closely with configured "
                    f"expectation (drift {r[drift_key]:+.3f})."
                )
            else:
                bullets.append(
                    f"{name}: {_phrase(metric_key, r[drift_key])} "
                    f"({label})."
                )

        # Distance is in km, not a probability.
        d_lab = r["avg_trip_distance_drift_label"]
        d_drift = r["avg_trip_distance_drift_km"]
        if d_lab == "aligned":
            bullets.append(
                f"{name}: average trip distance aligned with configured "
                f"value (drift {d_drift:+.2f} km)."
            )
        else:
            direction = "exceeded" if d_drift > 0 else "fell short of"
            bullets.append(
                f"{name}: observed average trip distance {direction} "
                f"the configured value by {abs(d_drift):.2f} km ({d_lab})."
            )

    # Cross-scenario summary rule.
    sig = [r["scenario_name"] for r in rows
           if "significant_divergence" in (
                r["emergency_return_drift_label"],
                r["maintenance_drift_label"],
                r["route_deviation_drift_label"],
                r["avg_trip_distance_drift_label"],
           )]
    if sig:
        bullets.append(
            "Scenarios with at least one significantly divergent metric: "
            + ", ".join(sig) + "."
        )
    else:
        bullets.append(
            "No scenario showed significant divergence on any tracked metric."
        )
    return bullets


def generate_calibration_summary(db_path: str) -> dict[str, Any]:
    return {
        "drift_rows":      compute_calibration_drift(db_path),
        "interpretations": generate_calibration_interpretations(db_path),
        "thresholds": {
            "ALIGN_PROB":   ALIGN_PROB,
            "DIVERGE_PROB": DIVERGE_PROB,
            "ALIGN_KM":     ALIGN_KM,
            "DIVERGE_KM":   DIVERGE_KM,
        },
    }
