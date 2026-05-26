"""
core/hybrid_analytics.py

Thin Python wrappers around the hybrid-side analytics so the FastAPI
endpoints and tests can call them without writing SQL.

Reads only.  No new tables.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Optional


def hybrid_summary(db_path: str) -> dict:
    """Per-scenario fulfillment split + latency comparison + totals."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT scenario_name,
                   COUNT(*),
                   SUM(CASE WHEN fulfillment_mode='TRUCK'  THEN 1 ELSE 0 END),
                   SUM(CASE WHEN fulfillment_mode='DRONE'  THEN 1 ELSE 0 END),
                   SUM(CASE WHEN fulfillment_mode='HYBRID' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN premium_delivery=1        THEN 1 ELSE 0 END),
                   AVG(truck_baseline_latency_min),
                   AVG(drone_estimated_latency_min),
                   AVG(CASE WHEN fulfillment_mode='TRUCK'
                            THEN truck_baseline_latency_min
                            ELSE drone_estimated_latency_min END),
                   AVG(queue_pressure),
                   AVG(congestion_factor)
              FROM orders
             WHERE fulfillment_mode IS NOT NULL
             GROUP BY scenario_name
             ORDER BY scenario_name ASC
            """
        ).fetchall()
    finally:
        conn.close()

    by_scenario = []
    total = {
        "orders": 0, "truck": 0, "drone": 0, "hybrid": 0, "premium": 0,
        "truck_lat_sum": 0.0, "drone_lat_sum": 0.0, "hybrid_lat_sum": 0.0,
    }
    for (scen, n, t, d, h, prem,
         avg_truck, avg_drone, avg_hybrid,
         avg_queue, avg_cong) in rows:
        n = n or 0
        entry = {
            "scenario_name":             scen,
            "orders":                    int(n),
            "truck_orders":              int(t or 0),
            "drone_orders":              int(d or 0),
            "hybrid_orders":             int(h or 0),
            "premium_orders":            int(prem or 0),
            "drone_activation_pct":      round(100.0 * (d or 0) / n, 1) if n else 0.0,
            "drone_or_hybrid_pct":       round(100.0 * ((d or 0) + (h or 0)) / n, 1) if n else 0.0,
            "avg_truck_latency_min":     round(avg_truck  or 0.0, 2),
            "avg_drone_latency_min":     round(avg_drone  or 0.0, 2),
            "avg_hybrid_latency_min":    round(avg_hybrid or 0.0, 2),
            "hybrid_latency_savings_min": round(
                (avg_truck or 0.0) - (avg_hybrid or 0.0), 2
            ),
            "avg_queue_pressure":        round(avg_queue or 0.0, 3),
            "avg_congestion":            round(avg_cong  or 0.0, 3),
        }
        by_scenario.append(entry)
        total["orders"]         += entry["orders"]
        total["truck"]          += entry["truck_orders"]
        total["drone"]          += entry["drone_orders"]
        total["hybrid"]         += entry["hybrid_orders"]
        total["premium"]        += entry["premium_orders"]
        total["truck_lat_sum"]  += (avg_truck  or 0.0) * n
        total["drone_lat_sum"]  += (avg_drone  or 0.0) * n
        total["hybrid_lat_sum"] += (avg_hybrid or 0.0) * n

    n = total["orders"]
    totals = {
        "orders":                    n,
        "truck_orders":              total["truck"],
        "drone_orders":              total["drone"],
        "hybrid_orders":             total["hybrid"],
        "premium_orders":            total["premium"],
        "drone_activation_pct":      round(100.0 * total["drone"] / n, 1) if n else 0.0,
        "drone_or_hybrid_pct":       round(100.0 * (total["drone"] + total["hybrid"]) / n, 1) if n else 0.0,
        "avg_truck_latency_min":     round(total["truck_lat_sum"]  / n, 2) if n else 0.0,
        "avg_drone_latency_min":     round(total["drone_lat_sum"]  / n, 2) if n else 0.0,
        "avg_hybrid_latency_min":    round(total["hybrid_lat_sum"] / n, 2) if n else 0.0,
        "hybrid_latency_savings_min": (
            round((total["truck_lat_sum"] - total["hybrid_lat_sum"]) / n, 2)
            if n else 0.0
        ),
    }
    return {"by_scenario": by_scenario, "totals": totals}


def latency_by_mode(db_path: str) -> dict:
    """Average latency by fulfillment mode, plus the hybrid-vs-trucks-only
    delta computed identically to the SQL view."""
    conn = sqlite3.connect(db_path)
    try:
        # Per-mode averages.  These are *actual* mode averages — i.e. for
        # orders flagged TRUCK we average their truck_baseline_latency_min,
        # for DRONE we average their drone_estimated_latency_min, etc.
        rows = conn.execute(
            """
            SELECT fulfillment_mode,
                   COUNT(*),
                   AVG(CASE WHEN fulfillment_mode='TRUCK'
                            THEN truck_baseline_latency_min
                            ELSE drone_estimated_latency_min END)
              FROM orders
             WHERE fulfillment_mode IS NOT NULL
             GROUP BY fulfillment_mode
             ORDER BY fulfillment_mode ASC
            """
        ).fetchall()
        # Strategy comparison — what would the average latency look like
        # if we sent EVERY order to trucks vs to drones vs followed the
        # hybrid rules?
        strat = conn.execute(
            """
            SELECT AVG(truck_baseline_latency_min),
                   AVG(drone_estimated_latency_min),
                   AVG(CASE WHEN fulfillment_mode='TRUCK'
                            THEN truck_baseline_latency_min
                            ELSE drone_estimated_latency_min END)
              FROM orders
             WHERE fulfillment_mode IS NOT NULL
            """
        ).fetchone()
    finally:
        conn.close()

    by_mode = [
        {
            "fulfillment_mode": mode,
            "orders":           int(n or 0),
            "avg_latency_min":  round(avg or 0.0, 2),
        }
        for mode, n, avg in rows
    ]
    truck_only, drone_only, hybrid_strat = strat or (0.0, 0.0, 0.0)
    return {
        "by_mode": by_mode,
        "strategy_comparison": {
            "trucks_only_avg_latency_min": round(truck_only  or 0.0, 2),
            "drones_only_avg_latency_min": round(drone_only  or 0.0, 2),
            "hybrid_strategy_avg_latency_min": round(hybrid_strat or 0.0, 2),
            "hybrid_vs_trucks_only_savings_min":
                round((truck_only or 0.0) - (hybrid_strat or 0.0), 2),
        },
    }


def activation_reasons(db_path: str) -> dict:
    """Count how often each individual reason fired across all orders.

    The ``activation_reason`` column is a comma-separated list; we expand
    it so analysts can see which factors drive activation most often.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT activation_reason, fulfillment_mode FROM orders "
            "WHERE activation_reason IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    counter:    Counter[str] = Counter()
    by_mode:    dict[str, Counter[str]] = {"TRUCK": Counter(),
                                           "DRONE": Counter(),
                                           "HYBRID": Counter()}
    for raw, mode in rows:
        # Strip "default_baseline_with_signal:" prefix so the underlying
        # reason still gets counted even when it didn't reach the
        # activation threshold.
        cleaned = (raw or "").replace("default_baseline_with_signal:", "")
        for r in [t.strip() for t in cleaned.split(",") if t.strip()]:
            counter[r] += 1
            if mode in by_mode:
                by_mode[mode][r] += 1
    return {
        "reason_counts":    dict(counter.most_common()),
        "reason_by_mode":   {m: dict(c.most_common()) for m, c in by_mode.items()},
        "total_orders":     len(rows),
    }
