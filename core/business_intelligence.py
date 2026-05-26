"""
core/business_intelligence.py

Rule-based decision-support layer over the simulated scenario data.

There is no machine learning here.  Every output is derived from a
transparent SQL aggregation followed by an explicit, hand-written
weighting / threshold / rule.  The goal is comparative scoring you can
read top-to-bottom and reason about — not a forecast.

Public surface
───────────────
  compute_scenario_metrics(db_path)
      Returns one dict per scenario with the raw inputs to scoring
      (completion_rate, profit_margin_pct, emergency_rate,
       maintenance_per_trip, avg_profit_per_trip, total_profit, ...).

  feasibility_score(metrics)
      Pure function: dict → float.  Documented weighting below.

  feasibility_label(score)
      Pure function: float → "strong_candidate" / "borderline" /
      "poor_candidate".  Thresholds are documented and tuned to the
      built-in scenarios; adjust them if you change the cost model.

  generate_scenario_rankings(db_path)
      Returns scenarios sorted by score, each enriched with the score
      and label.

  generate_recommendations(db_path)
      Returns a list of plain-English bullets, derived from the
      computed metrics — no hard-coded scenario names.

  generate_feasibility_report(db_path)
      Bundles the three outputs above into one dict.
"""

from __future__ import annotations

import sqlite3
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Scoring constants (intentionally simple, tunable, and visible from the top).
# ─────────────────────────────────────────────────────────────────────────────

# Weights applied to normalised inputs in feasibility_score().
W_COMPLETION         = 50.0   # +completion_rate (0..1)
W_PROFIT_MARGIN      = 30.0   # +clip(profit_margin_pct / 100, -1..+1)
W_EMERGENCY_PENALTY  = 40.0   # -emergency_rate (0..1)
W_MAINTENANCE_PENALTY = 10.0  # -maintenance_per_trip (events / trip)

# Label thresholds.  Tuned against the three built-in scenarios so the
# ranking visibly separates them; revisit if you change the cost model.
STRONG_SCORE_MIN     = 25.0
BORDERLINE_SCORE_MIN = 10.0


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

_METRICS_SQL = """
WITH trip_stats AS (
    SELECT scenario_name,
           COUNT(*)                                              AS trips,
           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END)   AS completed,
           SUM(CASE WHEN status='aborted'   THEN 1 ELSE 0 END)   AS aborted,
           SUM(estimated_revenue)                                AS revenue,
           SUM(estimated_operational_cost)                       AS op_cost,
           SUM(estimated_profit)                                 AS profit,
           AVG(estimated_profit)                                 AS avg_profit
      FROM trips
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
),
event_counts AS (
    SELECT scenario_name,
           SUM(CASE WHEN event_type='emergency_return'     THEN 1 ELSE 0 END) AS emergencies,
           SUM(CASE WHEN event_type='maintenance_required' THEN 1 ELSE 0 END) AS maintenances
      FROM delivery_events
     WHERE scenario_name IS NOT NULL
     GROUP BY scenario_name
)
SELECT t.scenario_name,
       t.trips,
       t.completed,
       t.aborted,
       t.revenue,
       t.op_cost,
       t.profit,
       t.avg_profit,
       COALESCE(e.emergencies,  0) AS emergencies,
       COALESCE(e.maintenances, 0) AS maintenances
  FROM trip_stats t
  LEFT JOIN event_counts e ON e.scenario_name = t.scenario_name
 ORDER BY t.scenario_name ASC
"""


def compute_scenario_metrics(db_path: str) -> list[dict]:
    """One dict per scenario with the inputs to scoring."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(_METRICS_SQL).fetchall()
    finally:
        conn.close()

    out: list[dict] = []
    for (name, trips, completed, aborted, revenue, op_cost, profit, avg_profit,
         emergencies, maintenances) in rows:
        trips = trips or 0
        revenue = revenue or 0.0
        completion_rate    = (completed / trips) if trips else 0.0
        emergency_rate     = (emergencies / trips) if trips else 0.0
        maint_per_trip     = (maintenances / trips) if trips else 0.0
        profit_margin_pct  = (100.0 * profit / revenue) if revenue else None
        out.append({
            "scenario_name":         name,
            "trips":                 trips,
            "completed_trips":       completed or 0,
            "aborted_trips":         aborted or 0,
            "total_revenue":         round(revenue, 2),
            "total_operational_cost": round(op_cost or 0.0, 2),
            "total_profit":          round(profit  or 0.0, 2),
            "avg_profit_per_trip":   round(avg_profit or 0.0, 2),
            "completion_rate":       round(completion_rate, 4),
            "emergency_rate":        round(emergency_rate, 4),
            "maintenance_per_trip":  round(maint_per_trip, 4),
            "profit_margin_pct":     None if profit_margin_pct is None
                                          else round(profit_margin_pct, 2),
            "emergency_returns":     emergencies,
            "maintenance_events":    maintenances,
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def feasibility_score(m: dict) -> float:
    """Weighted score, higher = better.

    score =   W_COMPLETION         × completion_rate
            + W_PROFIT_MARGIN      × clip(profit_margin_pct / 100, -1..+1)
            - W_EMERGENCY_PENALTY  × emergency_rate
            - W_MAINTENANCE_PENALTY × maintenance_per_trip
    """
    margin_norm = 0.0
    if m.get("profit_margin_pct") is not None:
        margin_norm = _clip(m["profit_margin_pct"] / 100.0, -1.0, 1.0)
    score = (
        W_COMPLETION          * m["completion_rate"]
        + W_PROFIT_MARGIN     * margin_norm
        - W_EMERGENCY_PENALTY * m["emergency_rate"]
        - W_MAINTENANCE_PENALTY * m["maintenance_per_trip"]
    )
    return round(score, 2)


def feasibility_label(score: float) -> str:
    if score >= STRONG_SCORE_MIN:
        return "strong_candidate"
    if score >= BORDERLINE_SCORE_MIN:
        return "borderline"
    return "poor_candidate"


# ─────────────────────────────────────────────────────────────────────────────
# Rankings + recommendations
# ─────────────────────────────────────────────────────────────────────────────

def generate_scenario_rankings(db_path: str) -> list[dict]:
    """Scenarios sorted best→worst by feasibility_score."""
    rows = compute_scenario_metrics(db_path)
    for r in rows:
        r["feasibility_score"] = feasibility_score(r)
        r["feasibility_label"] = feasibility_label(r["feasibility_score"])
    rows.sort(key=lambda r: r["feasibility_score"], reverse=True)
    return rows


def _names(items: list[dict]) -> str:
    return ", ".join(i["scenario_name"] for i in items)


def generate_recommendations(db_path: str) -> list[str]:
    """Plain-English bullets, derived from the metrics (no hard-coded names)."""
    ranked = generate_scenario_rankings(db_path)
    recs: list[str] = []
    if not ranked:
        return ["No scenarios found in the database."]

    best  = ranked[0]
    worst = ranked[-1]

    recs.append(
        f"{best['scenario_name']} has the strongest feasibility profile in this "
        f"comparison (score {best['feasibility_score']}, "
        f"label '{best['feasibility_label']}')."
    )
    if best is not worst:
        recs.append(
            f"{worst['scenario_name']} has the weakest feasibility profile "
            f"(score {worst['feasibility_score']}, "
            f"label '{worst['feasibility_label']}')."
        )

    if all((r["profit_margin_pct"] or 0) < 0 for r in ranked):
        recs.append(
            "Every evaluated scenario runs at a loss under the current cost "
            "assumptions; consider raising delivery_fee, reducing "
            "maintenance_cost_per_event, or both to approach breakeven."
        )

    high_emerg = [r for r in ranked if r["emergency_rate"] >= 0.08]
    if high_emerg:
        recs.append(
            "Emergency returns are a major loss driver in: "
            f"{_names(high_emerg)}. Reducing emergency_return_chance "
            "would have an outsized economic impact in these scenarios."
        )

    high_maint = [r for r in ranked if r["maintenance_per_trip"] >= 0.30]
    if high_maint:
        recs.append(
            "Maintenance burden is elevated (>=0.30 maintenance events per "
            f"trip) in: {_names(high_maint)}."
        )

    # Per-scenario "what would breakeven look like?" hint, when we have data.
    for r in ranked:
        if r["completed_trips"] and r["total_operational_cost"] > 0:
            needed = r["total_operational_cost"] / r["completed_trips"]
            current_implied = (
                r["total_revenue"] / r["completed_trips"] if r["completed_trips"] else 0
            )
            if current_implied < needed:
                gap = needed - current_implied
                recs.append(
                    f"Raising delivery_fee by ~{gap:.2f} units in "
                    f"{r['scenario_name']} would approach breakeven on "
                    f"completed trips (current ≈ {current_implied:.2f}, "
                    f"required ≈ {needed:.2f})."
                )
    return recs


def generate_feasibility_report(db_path: str) -> dict:
    """Single bundled dict: rankings + recommendations + raw metrics."""
    rankings = generate_scenario_rankings(db_path)
    return {
        "rankings":        rankings,
        "recommendations": generate_recommendations(db_path),
        "scoring_weights": {
            "W_COMPLETION":          W_COMPLETION,
            "W_PROFIT_MARGIN":       W_PROFIT_MARGIN,
            "W_EMERGENCY_PENALTY":   W_EMERGENCY_PENALTY,
            "W_MAINTENANCE_PENALTY": W_MAINTENANCE_PENALTY,
            "STRONG_SCORE_MIN":      STRONG_SCORE_MIN,
            "BORDERLINE_SCORE_MIN":  BORDERLINE_SCORE_MIN,
        },
    }
