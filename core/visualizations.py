"""
core/visualizations.py

Static PNG charts derived from the SQLite event store.

Reads only; no writes to the database, no simulator coupling.  Uses
matplotlib with the non-interactive Agg backend so tests and headless
runs do not need a display.

Public entry point::

    from core.visualizations import generate_charts
    paths = generate_charts(db_path="data/delivery_system.sqlite",
                            out_dir="outputs/charts")
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Optional

import matplotlib

matplotlib.use("Agg")  # must be set before importing pyplot
import matplotlib.pyplot as plt


CHART_FILENAMES = {
    "event_counts":             "event_counts.png",
    "trip_outcomes":            "trip_outcomes.png",
    "drone_utilization":        "drone_utilization.png",
    "battery_warnings":         "battery_warnings_by_drone.png",
    "battery_over_time":        "battery_over_time.png",
    # Scenario-comparison chart.  Skipped automatically when only one (or
    # zero) scenarios are present in the database.
    "scenario_comparison":      "scenario_comparison.png",
    # Synthetic profit + cost per scenario.
    "scenario_profitability":   "scenario_profitability.png",
    # Rule-based feasibility scores per scenario.
    "scenario_feasibility":     "scenario_feasibility_scores.png",
    # Observed operational profile per scenario.
    "scenario_operational_profile": "scenario_operational_profile.png",
    # Configured-vs-observed drift per scenario.
    "scenario_calibration_drift":   "scenario_calibration_drift.png",
    # Total profit per simulation_runs row.
    "run_comparison_profit":        "run_comparison_profit.png",
    # DuckDB-sourced cross-run profitability (Parquet → DuckDB; Phase 16).
    "cross_run_profitability":      "cross_run_profitability.png",
    # Phase 17 — rule-based validation results.
    "validation_results":           "validation_results.png",
    # Phase 18 — delivery displacement / savings.
    "delivery_displacement_savings": "delivery_displacement_savings.png",
    # Phase 21 — telemetry observations.
    "battery_temperature_by_scenario": "battery_temperature_by_scenario.png",
    "signal_quality_distribution":     "signal_quality_distribution.png",
    # Phase 19 — hybrid logistics views.
    "hybrid_activation_breakdown":   "hybrid_activation_breakdown.png",
    "delivery_latency_by_mode":      "delivery_latency_by_mode.png",
    "queue_pressure_vs_drone_activation": "queue_pressure_vs_drone_activation.png",
    # Phase 22 — delivery-domain reinterpretation: same events, different
    # demand-side overlay.  The chart shows revenue per trip by domain so
    # an analyst can see at a glance how the SAME operational events
    # produce different economics under different domains.
    "revenue_by_delivery_domain":   "revenue_by_delivery_domain.png",
    # Phase 23 — scale-model amortization.  Bar chart (categorical) by
    # scale_model name; not a "fleet size curve" because four datapoints
    # don't make a curve, they make a line through dots.
    "cost_per_delivery_by_scale":   "cost_per_delivery_by_scale.png",
}


# ─────────────────────────────────────────────────────────────────────────────
# Small SQL helpers (no ORM, plain tuples)
# ─────────────────────────────────────────────────────────────────────────────

def _fetch(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[tuple]:
    return conn.execute(sql, params).fetchall()


def _save(fig, out_path: str) -> str:
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    return out_path


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Individual chart builders
# ─────────────────────────────────────────────────────────────────────────────

def _chart_event_counts(conn: sqlite3.Connection, out_path: str) -> str:
    rows = _fetch(conn,
        "SELECT event_type, COUNT(*) FROM delivery_events "
        "GROUP BY event_type ORDER BY COUNT(*) DESC, event_type ASC"
    )
    labels = [r[0] for r in rows]
    counts = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(labels, counts, color="steelblue")
    ax.set_title("Drone Delivery Events by Type")
    ax.set_xlabel("event_type")
    ax.set_ylabel("count")
    ax.tick_params(axis="x", rotation=35)
    for tick in ax.get_xticklabels():
        tick.set_ha("right")
    return _save(fig, out_path)


def _chart_trip_outcomes(conn: sqlite3.Connection, out_path: str) -> str:
    rows = _fetch(conn,
        "SELECT status, COUNT(*) FROM trips GROUP BY status ORDER BY status ASC"
    )
    labels = [r[0] for r in rows]
    counts = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(6, 4))
    colors = ["seagreen" if l == "completed" else "indianred" if l == "aborted"
              else "slategray" for l in labels]
    ax.bar(labels, counts, color=colors)
    ax.set_title("Trip Outcomes")
    ax.set_xlabel("status")
    ax.set_ylabel("count")
    return _save(fig, out_path)


def _chart_drone_utilization(conn: sqlite3.Connection, out_path: str) -> str:
    rows = _fetch(conn,
        "SELECT drone_id, trips_flown FROM drones ORDER BY drone_id ASC"
    )
    labels = [r[0] for r in rows]
    counts = [r[1] for r in rows]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(labels, counts, color="darkorange")
    ax.set_title("Trips Flown by Drone")
    ax.set_xlabel("drone_id")
    ax.set_ylabel("trips_flown")
    return _save(fig, out_path)


def _chart_battery_warnings(conn: sqlite3.Connection, out_path: str) -> str:
    # Include every known drone, even with zero warnings, so the chart is
    # always self-explanatory.
    drones = [r[0] for r in _fetch(conn,
        "SELECT drone_id FROM drones ORDER BY drone_id ASC"
    )]
    warning_counts = dict(_fetch(conn,
        "SELECT drone_id, COUNT(*) FROM delivery_events "
        "WHERE event_type = 'battery_warning' AND drone_id IS NOT NULL "
        "GROUP BY drone_id"
    ))
    counts = [warning_counts.get(d, 0) for d in drones]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(drones, counts, color="crimson")
    ax.set_title("Battery Warnings by Drone")
    ax.set_xlabel("drone_id")
    ax.set_ylabel("battery_warning events")
    return _save(fig, out_path)


def _chart_battery_over_time(conn: sqlite3.Connection, out_path: str) -> str:
    rows = _fetch(conn,
        "SELECT drone_id, event_time, battery_pct FROM delivery_events "
        "WHERE drone_id IS NOT NULL AND battery_pct IS NOT NULL "
        "ORDER BY drone_id ASC, event_time ASC"
    )

    series: dict[str, tuple[list[datetime], list[float]]] = {}
    for drone_id, ts, battery in rows:
        when = _parse_iso(ts)
        if when is None:
            continue
        xs, ys = series.setdefault(drone_id, ([], []))
        xs.append(when)
        ys.append(float(battery))

    fig, ax = plt.subplots(figsize=(10, 5))
    for drone_id in sorted(series.keys()):
        xs, ys = series[drone_id]
        ax.plot(xs, ys, marker="", linewidth=1.2, label=drone_id)
    ax.set_title("Battery Percentage Over Time")
    ax.set_xlabel("event_time")
    ax.set_ylabel("battery_pct")
    ax.set_ylim(0, 100)
    if series:
        ax.legend(loc="best", fontsize=8)
    fig.autofmt_xdate()
    return _save(fig, out_path)


def _chart_scenario_comparison(conn: sqlite3.Connection, out_path: str) -> str:
    """Grouped bar chart: operational event counts per scenario.

    Works for one scenario (single group) as well as many.
    """
    rows = _fetch(conn,
        """
        SELECT scenario_name,
               SUM(CASE WHEN event_type='battery_warning'      THEN 1 ELSE 0 END),
               SUM(CASE WHEN event_type='route_deviation'      THEN 1 ELSE 0 END),
               SUM(CASE WHEN event_type='emergency_return'     THEN 1 ELSE 0 END),
               SUM(CASE WHEN event_type='maintenance_required' THEN 1 ELSE 0 END)
          FROM delivery_events
         WHERE scenario_name IS NOT NULL
         GROUP BY scenario_name
         ORDER BY scenario_name ASC
        """
    )
    metrics = ["battery_warning", "route_deviation",
               "emergency_return", "maintenance_required"]
    scenarios = [r[0] for r in rows] or ["(none)"]
    values = [
        [r[1] for r in rows],
        [r[2] for r in rows],
        [r[3] for r in rows],
        [r[4] for r in rows],
    ] if rows else [[0], [0], [0], [0]]

    fig, ax = plt.subplots(figsize=(9, 5))
    n_groups = len(scenarios)
    n_bars = len(metrics)
    bar_w = 0.8 / n_bars
    for i, (m, vs) in enumerate(zip(metrics, values)):
        xs = [j + (i - (n_bars - 1) / 2) * bar_w for j in range(n_groups)]
        ax.bar(xs, vs, width=bar_w, label=m)
    ax.set_xticks(range(n_groups))
    ax.set_xticklabels(scenarios)
    ax.set_title("Operational Event Counts by Scenario")
    ax.set_ylabel("event count")
    ax.legend(fontsize=8)
    return _save(fig, out_path)


def _chart_scenario_profitability(conn: sqlite3.Connection, out_path: str) -> str:
    """Bar chart: synthetic revenue, operational cost, and profit per scenario."""
    rows = _fetch(conn,
        """
        SELECT scenario_name,
               COALESCE(SUM(estimated_revenue),           0),
               COALESCE(SUM(estimated_operational_cost),  0),
               COALESCE(SUM(estimated_profit),            0)
          FROM trips
         WHERE scenario_name IS NOT NULL
         GROUP BY scenario_name
         ORDER BY scenario_name ASC
        """
    )
    scenarios = [r[0] for r in rows] or ["(none)"]
    revenue   = [float(r[1]) for r in rows] if rows else [0]
    op_cost   = [float(r[2]) for r in rows] if rows else [0]
    profit    = [float(r[3]) for r in rows] if rows else [0]

    fig, ax = plt.subplots(figsize=(9, 5))
    n_groups = len(scenarios)
    series = [
        ("revenue",          revenue, "seagreen"),
        ("operational_cost", op_cost, "indianred"),
        ("profit",           profit,  "steelblue"),
    ]
    bar_w = 0.8 / len(series)
    for i, (label, vals, color) in enumerate(series):
        xs = [j + (i - (len(series) - 1) / 2) * bar_w for j in range(n_groups)]
        ax.bar(xs, vals, width=bar_w, label=label, color=color)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(range(n_groups))
    ax.set_xticklabels(scenarios)
    ax.set_title("Synthetic Profitability by Scenario (illustrative)")
    ax.set_ylabel("synthetic units (revenue / cost / profit)")
    ax.legend(fontsize=8)
    return _save(fig, out_path)


def _chart_scenario_feasibility(conn: sqlite3.Connection, out_path: str) -> str:
    """Bar chart: rule-based feasibility score per scenario, coloured by label."""
    # Local import to avoid an import-cycle from a project standpoint and to
    # keep business_intelligence.py free of matplotlib at module load.
    from core.business_intelligence import (
        BORDERLINE_SCORE_MIN, STRONG_SCORE_MIN,
        compute_scenario_metrics, feasibility_score, feasibility_label,
    )
    # compute_scenario_metrics() needs a path, but we only have a connection.
    # Round-trip via the connection's filename.
    db_path = None
    try:
        for _id, _name, fname in conn.execute("PRAGMA database_list").fetchall():
            if _name == "main":
                db_path = fname
                break
    except sqlite3.Error:
        pass
    rows = compute_scenario_metrics(db_path) if db_path else []
    for r in rows:
        r["feasibility_score"] = feasibility_score(r)
        r["feasibility_label"] = feasibility_label(r["feasibility_score"])

    rows.sort(key=lambda r: r["feasibility_score"], reverse=True)
    scenarios = [r["scenario_name"]      for r in rows] or ["(none)"]
    scores    = [r["feasibility_score"]  for r in rows] or [0]
    colors    = []
    for r in rows:
        lab = r["feasibility_label"]
        colors.append("seagreen"  if lab == "strong_candidate"
                      else "goldenrod" if lab == "borderline"
                      else "indianred")
    if not colors:
        colors = ["slategray"]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(scenarios, scores, color=colors)
    ax.axhline(STRONG_SCORE_MIN,     color="seagreen",  linewidth=0.8, linestyle="--",
               label=f"strong ≥ {STRONG_SCORE_MIN}")
    ax.axhline(BORDERLINE_SCORE_MIN, color="goldenrod", linewidth=0.8, linestyle="--",
               label=f"borderline ≥ {BORDERLINE_SCORE_MIN}")
    ax.axhline(0,                    color="black",     linewidth=0.6)
    ax.set_title("Scenario Feasibility Scores (rule-based)")
    ax.set_ylabel("feasibility score")
    ax.legend(fontsize=8, loc="best")
    return _save(fig, out_path)


def _chart_scenario_operational_profile(conn: sqlite3.Connection, out_path: str) -> str:
    """2x2 grid of observed metrics per scenario.

    Subplots:
        (0,0) completion_rate        — fraction completed
        (0,1) emergency_return_rate  — events / trip
        (1,0) maintenance_per_trip   — events / trip
        (1,1) avg_trip_distance_km   — from trips.trip_distance_km
    """
    rows = _fetch(conn,
        """
        WITH t AS (
            SELECT scenario_name,
                   COUNT(*)                                            AS trips,
                   SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,
                   AVG(trip_distance_km)                               AS avg_dist
              FROM trips
             WHERE scenario_name IS NOT NULL
             GROUP BY scenario_name
        ),
        e AS (
            SELECT scenario_name,
                   SUM(CASE WHEN event_type='emergency_return'     THEN 1 ELSE 0 END) AS emerg,
                   SUM(CASE WHEN event_type='maintenance_required' THEN 1 ELSE 0 END) AS maint
              FROM delivery_events
             WHERE scenario_name IS NOT NULL
             GROUP BY scenario_name
        )
        SELECT t.scenario_name,
               1.0 * t.completed / NULLIF(t.trips, 0),
               1.0 * COALESCE(e.emerg, 0) / NULLIF(t.trips, 0),
               1.0 * COALESCE(e.maint, 0) / NULLIF(t.trips, 0),
               t.avg_dist
          FROM t LEFT JOIN e ON e.scenario_name = t.scenario_name
         ORDER BY t.scenario_name ASC
        """
    )
    scenarios = [r[0] for r in rows] or ["(none)"]
    if rows:
        completion = [float(r[1] or 0) for r in rows]
        emergency  = [float(r[2] or 0) for r in rows]
        maint      = [float(r[3] or 0) for r in rows]
        distance   = [float(r[4] or 0) for r in rows]
    else:
        completion = emergency = maint = distance = [0]

    fig, axes = plt.subplots(2, 2, figsize=(10, 7))
    panels = [
        (axes[0][0], "Completion rate (fraction)", completion, "seagreen"),
        (axes[0][1], "Emergency-return rate (events/trip)", emergency, "indianred"),
        (axes[1][0], "Maintenance events per trip", maint, "goldenrod"),
        (axes[1][1], "Avg trip distance (km)", distance, "steelblue"),
    ]
    for ax, title, vals, color in panels:
        ax.bar(scenarios, vals, color=color)
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=20)
        for tick in ax.get_xticklabels():
            tick.set_ha("right")
    fig.suptitle("Observed operational profile by scenario", y=1.02)
    return _save(fig, out_path)


def _chart_scenario_calibration_drift(conn: sqlite3.Connection, out_path: str) -> str:
    """Grouped bars: configured vs observed rates per scenario, three metrics."""
    from core.calibration import compute_calibration_drift
    db_path = None
    try:
        for _id, _name, fname in conn.execute("PRAGMA database_list").fetchall():
            if _name == "main":
                db_path = fname
                break
    except sqlite3.Error:
        pass
    rows = compute_calibration_drift(db_path) if db_path else []

    scenarios = [r["scenario_name"] for r in rows] or ["(none)"]
    metrics = [
        ("emergency_return", "configured_emergency_return_chance",
                             "observed_emergency_return_rate"),
        ("maintenance",      "configured_maintenance_chance",
                             "observed_maintenance_rate"),
        ("route_deviation",  "configured_route_deviation_chance",
                             "observed_route_deviation_rate"),
    ]

    fig, axes = plt.subplots(1, len(metrics), figsize=(13, 4.5), sharey=False)
    n_groups = len(scenarios)
    for ax, (label, cfg_key, obs_key) in zip(axes, metrics):
        cfg_vals = [r[cfg_key] for r in rows] if rows else [0]
        obs_vals = [r[obs_key] for r in rows] if rows else [0]
        bar_w = 0.4
        xs_cfg = [j - bar_w / 2 for j in range(n_groups)]
        xs_obs = [j + bar_w / 2 for j in range(n_groups)]
        ax.bar(xs_cfg, cfg_vals, width=bar_w, label="configured", color="slategray")
        ax.bar(xs_obs, obs_vals, width=bar_w, label="observed",   color="steelblue")
        ax.set_xticks(range(n_groups))
        ax.set_xticklabels(scenarios, rotation=20, ha="right")
        ax.set_title(label)
        ax.legend(fontsize=8)
    fig.suptitle("Configured vs observed rates by scenario", y=1.02)
    return _save(fig, out_path)


def _chart_run_comparison_profit(conn: sqlite3.Connection, out_path: str) -> str:
    """Total profit per simulation_runs row, with scenario as a label tag."""
    rows = _fetch(conn,
        """
        SELECT r.run_id,
               r.scenario_names,
               COALESCE(SUM(t.estimated_profit), 0) AS total_profit
          FROM simulation_runs r
          LEFT JOIN trips t ON t.run_id = r.run_id
         GROUP BY r.run_id
         ORDER BY r.created_at ASC, r.run_id ASC
        """
    )
    # Use a short run_id prefix + scenario for the X label so the chart is
    # readable even with 5–10 runs.
    labels = [f"{(r[0] or '')[:6]}\n{r[1] or '-'}" for r in rows] or ["(none)"]
    profits = [float(r[2] or 0) for r in rows] or [0.0]

    fig, ax = plt.subplots(figsize=(max(7, 0.9 * len(labels)), 4.5))
    colors = ["seagreen" if p > 0 else "indianred" for p in profits]
    if not rows:
        colors = ["slategray"]
    ax.bar(range(len(labels)), profits, color=colors)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_title("Total Profit by Simulation Run")
    ax.set_ylabel("total profit (synthetic units)")
    return _save(fig, out_path)

def _chart_cross_run_profitability(conn: sqlite3.Connection, out_path: str) -> str:
    """DuckDB → Parquet sourced. Falls back to SQLite if no parquet present.

    The chart is the same shape as ``_chart_run_comparison_profit`` but the
    data path proves the Phase 16 Parquet/DuckDB layer is wired correctly.
    """
    from core.duckdb_analytics import discover_run_parquet_dirs, run_duckdb_query
    dirs = discover_run_parquet_dirs()
    used_duckdb = False
    rows: list[tuple] = []
    if dirs:
        try:
            sql = (
                "SELECT r.run_id, r.scenario_names, "
                "       COALESCE(SUM(t.estimated_profit), 0) AS total_profit "
                "  FROM simulation_runs r "
                "  LEFT JOIN trips t ON t.run_id = r.run_id "
                " GROUP BY r.run_id, r.scenario_names "
                " ORDER BY total_profit DESC"
            )
            _hdr, rows = run_duckdb_query(dirs, sql)
            used_duckdb = True
        except Exception:
            rows = []
    if not used_duckdb:
        rows = _fetch(conn,
            """
            SELECT r.run_id, r.scenario_names,
                   COALESCE(SUM(t.estimated_profit), 0) AS total_profit
              FROM simulation_runs r
              LEFT JOIN trips t ON t.run_id = r.run_id
             GROUP BY r.run_id, r.scenario_names
             ORDER BY total_profit DESC
            """
        )

    labels  = [f"{(r[0] or '')[:6]}\n{r[1] or '-'}" for r in rows] or ["(none)"]
    profits = [float(r[2] or 0) for r in rows] or [0.0]
    colors  = ["seagreen" if p > 0 else "indianred" for p in profits]

    fig, ax = plt.subplots(figsize=(max(7, 0.9 * len(labels)), 4.5))
    ax.bar(range(len(labels)), profits, color=colors)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=8)
    src = "DuckDB / Parquet" if used_duckdb else "SQLite fallback"
    ax.set_title(f"Cross-Run Profitability ({src})")
    ax.set_ylabel("total profit (synthetic units)")
    return _save(fig, out_path)

def _chart_validation_results(conn: sqlite3.Connection, out_path: str) -> str:
    """Two-panel chart: pass/fail counts (left) and failures by rule (right)."""
    from core.validation import run_validation_checks
    db_path = None
    try:
        for _id, _name, fname in conn.execute("PRAGMA database_list").fetchall():
            if _name == "main":
                db_path = fname
                break
    except sqlite3.Error:
        pass
    if not db_path:
        results: list[dict] = []
    else:
        try:
            results = run_validation_checks(db_path)
        except Exception:
            results = []

    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    by_rule: dict[str, int] = {}
    for r in results:
        if not r["passed"]:
            by_rule[r["rule_name"]] = by_rule.get(r["rule_name"], 0) + 1

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    ax1.bar(["passed", "failed"], [passed, failed],
            color=["seagreen", "indianred"])
    ax1.set_title("Validation checks")
    ax1.set_ylabel("count")
    if by_rule:
        rules  = list(by_rule.keys())
        counts = [by_rule[r] for r in rules]
        ax2.barh(rules, counts, color="indianred")
        ax2.set_title("Failed rules")
        ax2.set_xlabel("failure count")
    else:
        ax2.text(0.5, 0.5, "no validation failures",
                 ha="center", va="center", transform=ax2.transAxes,
                 fontsize=12, color="seagreen")
        ax2.set_xticks([])
        ax2.set_yticks([])
        ax2.set_title("Failed rules")
    return _save(fig, out_path)

def _chart_delivery_displacement_savings(conn: sqlite3.Connection, out_path: str) -> str:
    """Per-scenario grouped bars: truck cost / drone op cost / cost difference."""
    from core.displacement import compute_delivery_displacement
    db_path = None
    try:
        for _id, _name, fname in conn.execute("PRAGMA database_list").fetchall():
            if _name == "main":
                db_path = fname
                break
    except sqlite3.Error:
        pass
    if not db_path:
        rows: list[dict] = []
    else:
        try:
            rows = compute_delivery_displacement(db_path)["by_scenario"]
        except Exception:
            rows = []

    scenarios = [r["scenario_name"] for r in rows] or ["(none)"]
    truck     = [r["estimated_truck_delivery_cost"]    for r in rows] or [0]
    drone     = [r["estimated_drone_operational_cost"] for r in rows] or [0]
    diff      = [r["estimated_cost_difference"]        for r in rows] or [0]

    fig, ax = plt.subplots(figsize=(9, 5))
    n_groups = len(scenarios)
    bar_w = 0.27
    xs = list(range(n_groups))
    ax.bar([x - bar_w for x in xs], truck, width=bar_w,
           color="slategray", label="truck baseline cost")
    ax.bar(xs,                       drone, width=bar_w,
           color="steelblue", label="drone operational cost")
    ax.bar([x + bar_w for x in xs], diff, width=bar_w,
           color=["seagreen" if d >= 0 else "indianred" for d in diff],
           label="cost difference (truck − drone)")
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(xs)
    ax.set_xticklabels(scenarios)
    ax.set_title("Synthetic Delivery Displacement Savings (illustrative)")
    ax.set_ylabel("cost (synthetic units)")
    ax.legend(fontsize=8, loc="best")
    return _save(fig, out_path)

def _db_path_from_conn(conn: sqlite3.Connection) -> Optional[str]:
    try:
        for _i, name, fname in conn.execute("PRAGMA database_list").fetchall():
            if name == "main":
                return fname
    except sqlite3.Error:
        pass
    return None


def _chart_hybrid_activation_breakdown(conn: sqlite3.Connection, out_path: str) -> str:
    """Per-scenario stacked bars: how many orders TRUCK / DRONE / HYBRID."""
    rows = _fetch(conn,
        """
        SELECT scenario_name,
               SUM(CASE WHEN fulfillment_mode='TRUCK'  THEN 1 ELSE 0 END),
               SUM(CASE WHEN fulfillment_mode='DRONE'  THEN 1 ELSE 0 END),
               SUM(CASE WHEN fulfillment_mode='HYBRID' THEN 1 ELSE 0 END)
          FROM orders
         WHERE fulfillment_mode IS NOT NULL
         GROUP BY scenario_name
         ORDER BY scenario_name ASC
        """
    )
    scenarios = [r[0] for r in rows] or ["(none)"]
    truck = [r[1] for r in rows] or [0]
    drone = [r[2] for r in rows] or [0]
    hybrid = [r[3] for r in rows] or [0]

    fig, ax = plt.subplots(figsize=(9, 5))
    xs = list(range(len(scenarios)))
    ax.bar(xs, truck,                 color="slategray", label="truck")
    ax.bar(xs, hybrid, bottom=truck,  color="goldenrod", label="hybrid")
    ax.bar(xs, drone,
           bottom=[t + h for t, h in zip(truck, hybrid)],
           color="steelblue", label="drone")
    ax.set_xticks(xs)
    ax.set_xticklabels(scenarios)
    ax.set_title("Hybrid activation breakdown by scenario")
    ax.set_ylabel("orders")
    ax.legend(fontsize=8)
    return _save(fig, out_path)


def _chart_delivery_latency_by_mode(conn: sqlite3.Connection, out_path: str) -> str:
    """Three bars: trucks-only, drones-only, hybrid-strategy avg latency."""
    db_path = _db_path_from_conn(conn)
    if db_path:
        from core.hybrid_analytics import latency_by_mode
        strat = latency_by_mode(db_path)["strategy_comparison"]
    else:
        strat = {"trucks_only_avg_latency_min": 0,
                 "drones_only_avg_latency_min": 0,
                 "hybrid_strategy_avg_latency_min": 0}

    labels = ["trucks only", "drones only", "hybrid strategy"]
    vals   = [strat["trucks_only_avg_latency_min"],
              strat["drones_only_avg_latency_min"],
              strat["hybrid_strategy_avg_latency_min"]]
    colors = ["slategray", "steelblue", "seagreen"]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(labels, vals, color=colors)
    for i, v in enumerate(vals):
        ax.text(i, v + 0.3, f"{v:.1f}", ha="center", fontsize=9)
    ax.set_title("Average delivery latency by strategy")
    ax.set_ylabel("minutes")
    return _save(fig, out_path)


def _chart_queue_pressure_vs_drone_activation(
    conn: sqlite3.Connection, out_path: str,
) -> str:
    """Scatter: queue_pressure on X, drone-activation rate on Y, binned."""
    rows = _fetch(conn,
        """
        SELECT queue_pressure, fulfillment_mode
          FROM orders
         WHERE queue_pressure IS NOT NULL AND fulfillment_mode IS NOT NULL
        """
    )
    if not rows:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.text(0.5, 0.5, "no orders with queue_pressure data",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, out_path)

    # Bin into deciles of queue_pressure and compute drone-rate per bin.
    n_bins = 10
    bins: list[list[int]] = [[] for _ in range(n_bins)]
    for qp, mode in rows:
        idx = min(int((qp or 0.0) * n_bins), n_bins - 1)
        bins[idx].append(1 if mode in ("DRONE", "HYBRID") else 0)
    centers   = [(i + 0.5) / n_bins for i in range(n_bins)]
    bin_rates = [sum(b) / len(b) if b else None for b in bins]
    sizes     = [len(b) for b in bins]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    xs, ys, ss = [], [], []
    for c, r, s in zip(centers, bin_rates, sizes):
        if r is None:
            continue
        xs.append(c); ys.append(r); ss.append(max(20, 6 * s))
    ax.scatter(xs, ys, s=ss, color="steelblue", alpha=0.7,
               edgecolors="black", linewidths=0.4)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("queue pressure (decile midpoint)")
    ax.set_ylabel("share of orders flagged DRONE or HYBRID")
    ax.set_title("Queue pressure vs hybrid activation rate")
    return _save(fig, out_path)


def _chart_battery_temperature_by_scenario(
    conn: sqlite3.Connection, out_path: str,
) -> str:
    """Per-scenario avg + max battery temperature (Phase 21).

    Side-by-side bars with the LiPo "warm" (45 °C) and "concerning"
    (55 °C) reference lines from public guidance overlaid.
    """
    rows = _fetch(conn,
        """
        SELECT de.scenario_name,
               AVG(t.battery_temp_c), MAX(t.battery_temp_c)
          FROM delivery_events de
          JOIN telemetry_observations t ON t.event_id = de.event_id
         WHERE de.scenario_name IS NOT NULL
         GROUP BY de.scenario_name
         ORDER BY de.scenario_name ASC
        """
    )
    scenarios = [r[0] for r in rows] or ["(none)"]
    avg_t     = [float(r[1] or 0) for r in rows] or [0]
    max_t     = [float(r[2] or 0) for r in rows] or [0]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    xs = list(range(len(scenarios)))
    bar_w = 0.35
    ax.bar([x - bar_w / 2 for x in xs], avg_t, width=bar_w,
           label="avg", color="steelblue")
    ax.bar([x + bar_w / 2 for x in xs], max_t, width=bar_w,
           label="max", color="indianred")
    ax.axhline(45, color="goldenrod", linewidth=0.8, linestyle="--",
               label="warm (45 °C)")
    ax.axhline(55, color="darkred", linewidth=0.8, linestyle="--",
               label="concerning (55 °C)")
    ax.set_xticks(xs)
    ax.set_xticklabels(scenarios)
    ax.set_ylabel("battery_temp_c")
    ax.set_title("Battery temperature by scenario")
    ax.legend(fontsize=8)
    return _save(fig, out_path)


def _chart_signal_quality_distribution(
    conn: sqlite3.Connection, out_path: str,
) -> str:
    """Histogram of signal_strength_pct + gps_signal_quality (Phase 21)."""
    rows = _fetch(conn,
        "SELECT signal_strength_pct, gps_signal_quality FROM telemetry_observations"
    )
    if not rows:
        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.text(0.5, 0.5, "no telemetry observations yet",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, out_path)
    sig = [r[0] for r in rows if r[0] is not None]
    gps = [r[1] for r in rows if r[1] is not None]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bins = list(range(40, 105, 5))
    ax.hist(sig, bins=bins, alpha=0.6, label="signal_strength_pct",
            color="steelblue")
    ax.hist(gps, bins=bins, alpha=0.6, label="gps_signal_quality",
            color="seagreen")
    ax.set_xlabel("quality / strength (%)")
    ax.set_ylabel("ping count")
    ax.set_title("Signal quality distribution across telemetry pings")
    ax.legend(fontsize=8)
    return _save(fig, out_path)


def _chart_revenue_by_delivery_domain(
    conn: sqlite3.Connection, out_path: str,
) -> str:
    """Per-domain avg revenue, avg cost, avg profit on the same events.

    Phase 22 finding chart.  Reads ``trip_economics_snapshots`` so every
    domain that has ever been recomputed shows up, regardless of which
    one's numbers currently live in ``trips.estimated_*``.

    The prompt asked for ``activation_by_delivery_domain`` (fulfillment
    mode split by domain), but Phase 22's hybrid transform is
    unchanged and doesn't read the domain — so that chart would show
    identical splits across all domains.  Revenue/cost/profit is the
    chart that actually reveals the Phase 22 finding.
    """
    rows = _fetch(conn,
        """
        SELECT domain_name,
               AVG(estimated_revenue),
               AVG(estimated_operational_cost),
               AVG(estimated_profit),
               COUNT(*)
          FROM trip_economics_snapshots
         WHERE domain_name IS NOT NULL
         GROUP BY domain_name
         ORDER BY domain_name ASC
        """
    )
    if not rows:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.text(0.5, 0.5,
                "no trip_economics_snapshots rows yet —\n"
                "run `python run_transforms.py --all-runs` to populate.",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, out_path)

    domains = [r[0] for r in rows]
    revenue = [float(r[1] or 0) for r in rows]
    op_cost = [float(r[2] or 0) for r in rows]
    profit  = [float(r[3] or 0) for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5))
    xs = list(range(len(domains)))
    bar_w = 0.27
    ax.bar([x - bar_w for x in xs], revenue, width=bar_w,
           color="seagreen", label="avg revenue")
    ax.bar(xs,                       op_cost, width=bar_w,
           color="indianred", label="avg op cost")
    ax.bar([x + bar_w for x in xs], profit, width=bar_w,
           color=["steelblue" if p >= 0 else "darkred" for p in profit],
           label="avg profit (per trip)")
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(xs)
    ax.set_xticklabels(domains, rotation=15, ha="right")
    ax.set_ylabel("synthetic units (USD)")
    ax.set_title("Revenue / cost / profit per trip by delivery domain "
                 "(same operational events)")
    ax.legend(fontsize=8)
    return _save(fig, out_path)


def _chart_cost_per_delivery_by_scale(
    conn: sqlite3.Connection, out_path: str,
) -> str:
    """Per-scale_model: avg operational cost, avg amortized overhead,
    avg effective profit.  Categorical bar chart (NOT a synthetic
    fleet-size curve — four datapoints don't reveal curvature).
    """
    rows = _fetch(conn,
        """
        SELECT s.scale_model_name,
               AVG(e.estimated_operational_cost),
               AVG(s.amortized_overhead_per_trip),
               AVG(s.effective_profit),
               COUNT(*)
          FROM trip_scale_snapshots s
          JOIN trip_economics_snapshots e
               ON  e.transform_run_id = s.source_snapshot_run_id
               AND e.trip_id          = s.trip_id
         GROUP BY s.scale_model_name
         ORDER BY s.scale_model_name ASC
        """
    )
    if not rows:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.text(0.5, 0.5,
                "no trip_scale_snapshots rows yet —\n"
                "run `python run_transforms.py --all-scale-models`.",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig, out_path)

    scales   = [r[0] for r in rows]
    op_cost  = [float(r[1] or 0) for r in rows]
    overhead = [float(r[2] or 0) for r in rows]
    profit   = [float(r[3] or 0) for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5))
    xs = list(range(len(scales)))
    bar_w = 0.27
    ax.bar([x - bar_w for x in xs], op_cost,  width=bar_w,
           color="indianred", label="avg operational cost")
    ax.bar(xs,                       overhead, width=bar_w,
           color="goldenrod", label="avg amortized overhead")
    ax.bar([x + bar_w for x in xs], profit,    width=bar_w,
           color=["seagreen" if p >= 0 else "darkred" for p in profit],
           label="avg effective profit")
    ax.axhline(0, color="black", linewidth=0.6)
    ax.set_xticks(xs)
    ax.set_xticklabels(scales, rotation=15, ha="right")
    ax.set_ylabel("synthetic units (USD)")
    ax.set_title("Cost per delivery by scale model "
                 "(same operational events)")
    ax.legend(fontsize=8)
    return _save(fig, out_path)


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_charts(
    db_path: str = "data/delivery_system.sqlite",
    out_dir: str = "outputs/charts",
) -> dict[str, str]:
    """Build all charts from db_path into out_dir; return {name: file_path}."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"database not found: {db_path}")
    os.makedirs(out_dir, exist_ok=True)

    builders = {
        "event_counts":           _chart_event_counts,
        "trip_outcomes":          _chart_trip_outcomes,
        "drone_utilization":      _chart_drone_utilization,
        "battery_warnings":       _chart_battery_warnings,
        "battery_over_time":      _chart_battery_over_time,
        "scenario_comparison":    _chart_scenario_comparison,
        "scenario_profitability": _chart_scenario_profitability,
        "scenario_feasibility":   _chart_scenario_feasibility,
        "scenario_operational_profile": _chart_scenario_operational_profile,
        "scenario_calibration_drift":   _chart_scenario_calibration_drift,
        "run_comparison_profit":        _chart_run_comparison_profit,
        "cross_run_profitability":      _chart_cross_run_profitability,
        "validation_results":           _chart_validation_results,
        "delivery_displacement_savings": _chart_delivery_displacement_savings,
        "battery_temperature_by_scenario": _chart_battery_temperature_by_scenario,
        "signal_quality_distribution":     _chart_signal_quality_distribution,
        "revenue_by_delivery_domain":      _chart_revenue_by_delivery_domain,
        "cost_per_delivery_by_scale":      _chart_cost_per_delivery_by_scale,
        "hybrid_activation_breakdown":   _chart_hybrid_activation_breakdown,
        "delivery_latency_by_mode":      _chart_delivery_latency_by_mode,
        "queue_pressure_vs_drone_activation": _chart_queue_pressure_vs_drone_activation,
    }

    results: dict[str, str] = {}
    conn = sqlite3.connect(db_path)
    try:
        for name, fn in builders.items():
            out_path = os.path.join(out_dir, CHART_FILENAMES[name])
            results[name] = fn(conn, out_path)
    finally:
        conn.close()
    return results
