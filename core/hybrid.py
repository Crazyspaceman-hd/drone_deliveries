"""
core/hybrid.py

Hybrid logistics modeling — drones as augmentation, trucks/drivers as
the baseline.

Phase 18 framed the project around "truck replacement" and the headline
finding was that drones lose at the default cost knobs.  Phase 19
reframes the question: **when should a delivery system activate drones
in addition to its truck fleet?**

This module is intentionally rule-based and explainable:

  * Each order gets a synthetic profile (weight, urgency, premium,
    congestion, queue pressure) generated from a *derived* RNG seeded
    from ``(run_seed, trip_idx, "hybrid")``.  This keeps the main
    simulator RNG sequence untouched, so the seed=42 = 156 baseline is
    preserved.
  * ``decide_fulfillment(...)`` scores a small set of activation
    reasons and returns ``(TRUCK | DRONE | HYBRID, activation_reason)``.
  * Truck cost / latency models include simple batching and a
    congestion penalty.
  * Drone latency comes from a flat prep time + cruise speed × distance.

What this is not
─────────────────
- Not a dispatcher.  The simulator still flies every order via drone;
  the fulfillment_mode column records what a hybrid dispatcher *would
  have* chosen, so analytics can compare hybrid vs truck-only vs
  drone-only strategies.
- Not a routing engine.  Truck batch size is a constant.  No real
  geographic clustering.
- Not weather / FAA / traffic.  ``congestion_factor`` is synthetic.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Fulfillment modes
# ─────────────────────────────────────────────────────────────────────────────

TRUCK   = "TRUCK"
DRONE   = "DRONE"
HYBRID  = "HYBRID"

FULFILLMENT_MODES = (TRUCK, DRONE, HYBRID)


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic constants (all visible at top of file for easy retuning).
# ─────────────────────────────────────────────────────────────────────────────

# Order generation
URGENCY_LEVELS              = ("low", "medium", "high")
URGENCY_WEIGHTS             = (0.45, 0.40, 0.15)
PAYLOAD_KG_RANGE            = (0.2, 8.0)       # uniform
PREP_TIME_MIN_RANGE         = (2.0, 15.0)
PROMISED_WINDOW_MIN_RANGE   = (30.0, 120.0)
PREMIUM_PROB                = 0.15
CONGESTION_RANGE            = (0.0, 1.0)        # uniform; sin-perturbed by trip_idx

# Activation thresholds
LIGHT_PAYLOAD_KG            = 2.5
HEAVY_PAYLOAD_KG            = 5.0
SHORT_DISTANCE_KM           = 8.0
HIGH_CONGESTION             = 0.6
HIGH_QUEUE_PRESSURE         = 0.65

# Truck baseline model
TRUCK_BASE_COST_PER_DELIVERY = 6.0      # before batching
TRUCK_CONGESTION_COST_PENALTY = 4.0      # max additional per delivery
TRUCK_BATCH_SIZE             = 5
TRUCK_BASE_LATENCY_MIN       = 25.0
TRUCK_BATCH_LATENCY_PER_STOP = 2.5       # additional minutes per other stop
TRUCK_CONGESTION_LATENCY_MULT = 0.8

# Drone latency model
DRONE_PREP_MIN              = 3.0
DRONE_CRUISE_KMH            = 50.0       # ~14 m/s; matches simulator speed_mps=15 within 10%


# ─────────────────────────────────────────────────────────────────────────────
# Order characteristics
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrderCharacteristics:
    payload_weight_kg:         float
    urgency_level:             str
    estimated_prep_time_min:   float
    promised_delivery_window_min: float
    premium_delivery:          bool
    congestion_factor:         float
    queue_pressure:            float


def _derive_rng(run_seed: int, trip_idx: int) -> random.Random:
    """Per-trip RNG derived from (run_seed, trip_idx).

    Independent from the main simulator RNG so the operational event
    sequence stays deterministic in the seed=42 baseline regardless of
    how many attribute draws happen here.
    """
    return random.Random(f"{run_seed}-{trip_idx}-hybrid")


def queue_pressure_for_trip(trip_idx: int, total_trips: int) -> float:
    """Synthetic queue pressure in [0, 1] driven by trip index.

    Combines a slow upward trend with a sinusoidal rush/lull rhythm so
    later trips in a long run see more pressure overall, with peaks
    spread across the run.  Deterministic.
    """
    if total_trips <= 0:
        return 0.0
    progress = (trip_idx + 1) / total_trips
    rush     = 0.5 * (1.0 + math.sin(progress * 4.0 * math.pi - 1.5))
    raw      = 0.30 + 0.45 * progress + 0.25 * rush
    return max(0.0, min(1.0, raw))


def generate_order_characteristics(
    run_seed: int, trip_idx: int, total_trips: int,
) -> OrderCharacteristics:
    """Deterministic per-trip synthetic order profile.

    Uses a derived RNG so the main simulator RNG sequence is untouched.
    """
    rng = _derive_rng(run_seed, trip_idx)
    urgency = rng.choices(URGENCY_LEVELS, weights=URGENCY_WEIGHTS, k=1)[0]
    payload = rng.uniform(*PAYLOAD_KG_RANGE)
    prep    = rng.uniform(*PREP_TIME_MIN_RANGE)
    window  = rng.uniform(*PROMISED_WINDOW_MIN_RANGE)
    premium = rng.random() < PREMIUM_PROB
    # Congestion: small per-trip jitter on top of a sin-shaped baseline
    # so neighbouring trips see related congestion (more realistic than
    # iid noise).
    base_cong = 0.5 + 0.5 * math.sin((trip_idx + 1) * 0.31 - 0.7)
    congestion = max(0.0, min(1.0, base_cong + rng.uniform(-0.2, 0.2)))
    queue   = queue_pressure_for_trip(trip_idx, total_trips)
    return OrderCharacteristics(
        payload_weight_kg            = round(payload, 2),
        urgency_level                = urgency,
        estimated_prep_time_min      = round(prep, 1),
        promised_delivery_window_min = round(window, 1),
        premium_delivery             = bool(premium),
        congestion_factor            = round(congestion, 3),
        queue_pressure               = round(queue, 3),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Activation logic
# ─────────────────────────────────────────────────────────────────────────────

def decide_fulfillment(
    chars: OrderCharacteristics, distance_km: float,
) -> tuple[str, str]:
    """Rule-based fulfillment mode + activation reason.

    Returns one of (TRUCK, DRONE, HYBRID) along with a comma-separated
    list of the reasons that fired.  Heavy payload always disqualifies
    the drone regardless of how many other reasons fire.
    """
    # Hard disqualifier first — keeps the rest of the rules simple.
    if chars.payload_weight_kg > HEAVY_PAYLOAD_KG:
        return TRUCK, "heavy_payload"

    reasons: list[str] = []
    if chars.premium_delivery:
        reasons.append("premium")
    if chars.urgency_level == "high":
        reasons.append("urgent")
    if chars.payload_weight_kg < LIGHT_PAYLOAD_KG:
        reasons.append("light_payload")
    if chars.congestion_factor > HIGH_CONGESTION:
        reasons.append("congestion_bypass")
    if chars.queue_pressure > HIGH_QUEUE_PRESSURE:
        reasons.append("queue_pressure")
    if distance_km < SHORT_DISTANCE_KM:
        reasons.append("short_distance")

    if len(reasons) >= 3:
        return DRONE, ",".join(reasons) if reasons else "n/a"
    if len(reasons) == 2:
        return HYBRID, ",".join(reasons)
    if reasons:
        return TRUCK, "default_baseline_with_signal:" + ",".join(reasons)
    return TRUCK, "default_baseline"


# ─────────────────────────────────────────────────────────────────────────────
# Truck and drone estimates
# ─────────────────────────────────────────────────────────────────────────────

def estimate_truck_cost(
    chars: OrderCharacteristics, distance_km: float,
    batch_size: int = TRUCK_BATCH_SIZE,
) -> float:
    """Per-delivery truck cost under simple batching.

    Cost = base / sqrt(batch_size)   ← diminishing returns from batching
         + congestion * penalty       ← traffic / staffing pressure
    """
    batched = TRUCK_BASE_COST_PER_DELIVERY / max(1.0, math.sqrt(batch_size))
    congestion = TRUCK_CONGESTION_COST_PENALTY * chars.congestion_factor
    return round(batched + congestion, 4)


def estimate_truck_latency_min(
    chars: OrderCharacteristics, distance_km: float,
    batch_size: int = TRUCK_BATCH_SIZE,
) -> float:
    """Per-delivery truck latency (prep + route + congestion + queue)."""
    route_factor   = 1.0 + TRUCK_CONGESTION_LATENCY_MULT * chars.congestion_factor
    base_route     = TRUCK_BASE_LATENCY_MIN * route_factor
    batching_drag  = TRUCK_BATCH_LATENCY_PER_STOP * (batch_size - 1)
    queue_drag     = 10.0 * chars.queue_pressure
    return round(chars.estimated_prep_time_min + base_route + batching_drag + queue_drag, 2)


def estimate_drone_latency_min(
    chars: OrderCharacteristics, distance_km: float,
) -> float:
    """Per-delivery drone latency (drone prep + flight time)."""
    flight_min = distance_km * 60.0 / DRONE_CRUISE_KMH
    return round(DRONE_PREP_MIN + flight_min, 2)
