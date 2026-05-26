"""Phase 19: hybrid logistics — characteristics, activation, baseline, analytics, API."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from core.hybrid import (
    DRONE, HEAVY_PAYLOAD_KG, HYBRID, LIGHT_PAYLOAD_KG, TRUCK,
    OrderCharacteristics, decide_fulfillment,
    estimate_drone_latency_min, estimate_truck_cost, estimate_truck_latency_min,
    generate_order_characteristics, queue_pressure_for_trip,
)
from core.hybrid_analytics import (
    activation_reasons, hybrid_summary, latency_by_mode,
)
from core.simulator import run_simulation


# ─────────────────────────────────────────────────────────────────────────────
# Pure-function tests (no DB needed)
# ─────────────────────────────────────────────────────────────────────────────

def _chars(**overrides):
    # Default payload is intentionally between LIGHT and HEAVY thresholds
    # so no implicit reason fires; tests opt in to signals by overriding.
    base = dict(
        payload_weight_kg            = 3.0,
        urgency_level                = "medium",
        estimated_prep_time_min      = 5.0,
        promised_delivery_window_min = 60.0,
        premium_delivery             = False,
        congestion_factor            = 0.3,
        queue_pressure               = 0.3,
    )
    base.update(overrides)
    return OrderCharacteristics(**base)


def test_heavy_payload_is_hard_truck_disqualifier():
    chars = _chars(
        payload_weight_kg=HEAVY_PAYLOAD_KG + 0.5,
        urgency_level="high",
        premium_delivery=True,
        congestion_factor=0.9,
        queue_pressure=0.9,
    )
    mode, reason = decide_fulfillment(chars, distance_km=5.0)
    assert mode   == TRUCK
    assert reason == "heavy_payload"


def test_urgent_light_premium_short_activates_drone():
    chars = _chars(
        payload_weight_kg=1.0,    # light_payload signal
        urgency_level="high",     # urgent signal
        premium_delivery=True,    # premium signal
        congestion_factor=0.2,
        queue_pressure=0.2,
    )
    mode, _reason = decide_fulfillment(chars, distance_km=4.0)
    assert mode == DRONE          # 4 signals (urgent, light, premium, short_distance)


def test_only_one_signal_stays_truck():
    chars = _chars(urgency_level="high")   # only one reason
    mode, _ = decide_fulfillment(chars, distance_km=20.0)
    assert mode == TRUCK


def test_two_signals_lands_in_hybrid():
    chars = _chars(urgency_level="high", congestion_factor=0.8)
    mode, _ = decide_fulfillment(chars, distance_km=20.0)
    assert mode == HYBRID


def test_truck_batching_lowers_cost():
    chars = _chars(congestion_factor=0.4)
    single = estimate_truck_cost(chars, distance_km=5.0, batch_size=1)
    batch  = estimate_truck_cost(chars, distance_km=5.0, batch_size=10)
    assert batch < single, (
        f"expected batch={batch} < single={single}"
    )


def test_congestion_increases_truck_cost_and_latency():
    low  = _chars(congestion_factor=0.0)
    high = _chars(congestion_factor=1.0)
    assert estimate_truck_cost(high, 5.0)        > estimate_truck_cost(low,  5.0)
    assert estimate_truck_latency_min(high, 5.0) > estimate_truck_latency_min(low, 5.0)


def test_drone_latency_scales_with_distance():
    chars = _chars()
    short = estimate_drone_latency_min(chars, distance_km=2.0)
    long_ = estimate_drone_latency_min(chars, distance_km=20.0)
    assert long_ > short


def test_queue_pressure_increases_through_run():
    early = queue_pressure_for_trip(0,   100)
    late  = queue_pressure_for_trip(95,  100)
    # Sinusoid makes the comparison noisy at neighbouring points but the
    # ramp dominates over a 95-point gap.
    assert late > early


def test_order_characteristics_deterministic_by_seed():
    a = generate_order_characteristics(42, 0, 100)
    b = generate_order_characteristics(42, 0, 100)
    assert a == b
    c = generate_order_characteristics(7, 0, 100)
    assert c != a   # different seed → different draws


# ─────────────────────────────────────────────────────────────────────────────
# DB-backed tests
# hybrid_db fixture is provided by conftest.py (session-scoped).
# ─────────────────────────────────────────────────────────────────────────────

def test_orders_carry_hybrid_columns(hybrid_db: Path):
    conn = sqlite3.connect(str(hybrid_db))
    try:
        row = conn.execute(
            "SELECT payload_weight_kg, urgency_level, fulfillment_mode, "
            "       activation_reason, truck_baseline_latency_min, "
            "       drone_estimated_latency_min "
            "FROM orders LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert all(v is not None for v in row)


def test_seed42_simulation_baseline_preserved(tmp_path: Path):
    """seed=42 event count matches the registered baseline for the current
    simulator version (see tests/baselines.py)."""
    import sys
    from pathlib import Path as _P
    sys.path.insert(0, str(_P(__file__).parent))
    from baselines import expected_events
    db = tmp_path / "baseline.sqlite"
    summ = run_simulation(db_path=str(db), n_drones=3, n_trips=10, seed=42)
    assert summ["events_written"] == expected_events(seed=42)


def test_hybrid_summary_returns_per_scenario_counts(hybrid_db: Path):
    summary = hybrid_summary(str(hybrid_db))
    assert summary["totals"]["orders"] > 0
    seen = {r["scenario_name"] for r in summary["by_scenario"]}
    assert seen == {"urban_dense", "rural_extended"}
    for r in summary["by_scenario"]:
        assert r["orders"] == r["truck_orders"] + r["drone_orders"] + r["hybrid_orders"]


def test_hybrid_strategy_beats_trucks_only_on_latency(hybrid_db: Path):
    """The whole point of the hybrid layer: average latency should improve."""
    strat = latency_by_mode(str(hybrid_db))["strategy_comparison"]
    assert strat["hybrid_strategy_avg_latency_min"] \
         < strat["trucks_only_avg_latency_min"]


def test_activation_reasons_non_empty(hybrid_db: Path):
    out = activation_reasons(str(hybrid_db))
    assert out["total_orders"] > 0
    assert out["reason_counts"]
    # Heavy payload should be visible since it fires on >5kg orders.
    assert "heavy_payload" in out["reason_counts"]


def test_hybrid_sql_view_executes(hybrid_db: Path):
    sql = Path("analytics/sql/hybrid_summary.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(str(hybrid_db))
    try:
        rows = conn.execute(sql).fetchall()
        headers = [d[0] for d in conn.execute(sql).description]
    finally:
        conn.close()
    assert rows
    for col in ("scenario_name", "orders", "drone_activation_pct",
                "avg_hybrid_latency_min", "hybrid_latency_savings_min"):
        assert col in headers


@pytest.mark.slow
def test_hybrid_charts_render(hybrid_db: Path, tmp_path: Path):
    from core.visualizations import generate_charts
    paths = generate_charts(db_path=str(hybrid_db),
                            out_dir=str(tmp_path / "charts"))
    for key in ("hybrid_activation_breakdown",
                "delivery_latency_by_mode",
                "queue_pressure_vs_drone_activation"):
        p = Path(paths[key])
        assert p.exists()
        assert p.stat().st_size > 0


def test_api_hybrid_endpoints_shape(hybrid_db: Path):
    """The three new endpoints return structured JSON, not error pages."""
    from fastapi.testclient import TestClient
    old = os.environ.get("DRONE_API_DB")
    os.environ["DRONE_API_DB"] = str(hybrid_db)
    try:
        from api.main import app
        client = TestClient(app)
        h = client.get("/analytics/hybrid-summary").json()
        l = client.get("/analytics/latency").json()
        r = client.get("/analytics/activation-reasons").json()
    finally:
        if old is None: del os.environ["DRONE_API_DB"]
        else:           os.environ["DRONE_API_DB"] = old

    for key in ("by_scenario", "totals"):
        assert key in h
    for key in ("by_mode", "strategy_comparison"):
        assert key in l
    for key in ("reason_counts", "reason_by_mode", "total_orders"):
        assert key in r
