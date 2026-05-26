"""
core/telemetry_model.py

Per-ping drone telemetry observation generator (Phase 21).

What this is
─────────────
A tiny, deterministic, *plausible* synthesis of the kind of values a real
drone flight controller would surface on its telemetry channel —
altitude, airspeed, heading, vertical speed, battery temperature, motor
temperature, signal strength, GPS quality, and the controller's own
estimate of remaining flight range.

Plausibility ranges (broad consumer/prosumer drone class):

    altitude_m        0–120     (Part 107-style ceiling)
    airspeed_mps      ~14 cruise, up to ~30 burst
    heading_deg       0–360
    vertical_speed    -5..+5 (positive = climb)
    battery_temp_c    operating envelope 15–60, optimal 15–35, warning >45
                      (per public LiPo / drone-battery guidance)
    motor_temp_c      BLDC typical 20–80, thermal limit ~95
    signal_strength_pct  0–100  (RC link)
    gps_signal_quality   0–100  (single quality score; standard receivers
                                 surface this as fix type + HDOP — we
                                 collapse to a synthetic 0–100)

What this is *not*
──────────────────
- Not a thermal/aerodynamic model.  One load proxy, two scalars.
- Not weather, terrain, or RF propagation simulation.
- Not derived analytics (anomaly detection, trend analysis, health
  scoring — those live in ``transforms/telemetry.py``).

Determinism
────────────
Uses the simulator's main RNG via the caller, so adding telemetry
generation does shift the seeded sequence relative to the Phase 20
baseline.  ``SIMULATOR_VERSION`` bumps to ``phase21`` to match.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from typing import Optional


# ── Thermal model constants (visible at top of file for retuning) ────────────
AMBIENT_C                = 22.0   # baseline air temp
BATTERY_LOAD_COEFF       = 30.0   # heat rise (°C) at full load
MOTOR_LOAD_COEFF         = 55.0   # motors run hotter than batteries
THERMAL_RISE_PER_MIN     = 0.8    # gradual cumulative warm-up during a leg
BATTERY_TEMP_BAND        = (15.0, 60.0)
MOTOR_TEMP_BAND          = (20.0, 95.0)

# ── Flight envelope ──────────────────────────────────────────────────────────
DEFAULT_CRUISE_AIRSPEED_MPS = 14.0  # matches simulator's drones.speed_mps
CRUISE_ALTITUDE_M           = 80.0  # well below Part 107 120 m ceiling
ALTITUDE_BAND               = (0.0, 120.0)

# ── Signal quality ──────────────────────────────────────────────────────────
SIGNAL_STRENGTH_BASE_PCT    = 92.0  # baseline RC link strength
GPS_QUALITY_BASE            = 88.0  # baseline GPS quality score

# ── Obstacle warning frequency (per-ping probability) ────────────────────────
OBSTACLE_WARNING_BASE_PROB  = 0.012

# ── Emergency-return trigger (Phase 21) ──────────────────────────────────────
# If the onboard controller's own remaining-range estimate falls below the
# straight-line distance back to depot multiplied by this safety factor,
# the simulator triggers an emergency_return at this ping.  Replaces (or
# augments) the prior RNG-only emergency probability.
REMAINING_RANGE_SAFETY_FACTOR = 1.15


# Flight phases — used as a load proxy for the heat model.
PHASE_ASCEND  = "ascend"
PHASE_CRUISE  = "cruise"
PHASE_DESCEND = "descend"
PHASE_HOVER   = "hover"


@dataclass(frozen=True)
class TelemetryObservation:
    """Plain bag of per-ping observables.  Persisted to ``telemetry_observations``."""
    altitude_m:                    float
    airspeed_mps:                  float
    heading_deg:                   float
    vertical_speed_mps:            float
    battery_temp_c:                float
    motor_temp_c:                  float
    estimated_remaining_range_km:  float
    signal_strength_pct:           float
    gps_signal_quality:            float

    def to_dict(self) -> dict:
        return asdict(self)


def load_proxy(payload_kg: float, phase: str, max_payload_kg: float = 5.0) -> float:
    """Return a 0..1 load value driven by payload + flight phase.

    Phase weighting reflects what a flight controller would actually
    experience — ascending under payload draws the highest current,
    cruising is moderate, descending and hovering are easy.
    """
    payload_load = max(0.0, min(1.0, payload_kg / max(0.01, max_payload_kg)))
    phase_weight = {
        PHASE_ASCEND:  0.95,
        PHASE_CRUISE:  0.55,
        PHASE_DESCEND: 0.25,
        PHASE_HOVER:   0.20,
    }.get(phase, 0.55)
    # Blend: heavier payload always raises load; phase determines the
    # baseline contribution.
    return max(0.0, min(1.0, 0.6 * phase_weight + 0.4 * payload_load))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def generate_observation(
    rng: random.Random,
    *,
    phase: str,
    payload_kg: float,
    leg_seconds_so_far: float,
    bearing_deg: float,
    battery_pct: float,
    battery_health_pct: float,
    drone_range_km: float,
    distance_to_depot_km: float,
) -> TelemetryObservation:
    """One ping's observation.  Deterministic per (rng_state, args).

    Costs ~7 RNG draws.  Caller is responsible for using a derived or
    main RNG depending on the simulator's determinism contract.
    """
    load = load_proxy(payload_kg, phase)
    minutes = leg_seconds_so_far / 60.0
    cumulative_rise = THERMAL_RISE_PER_MIN * minutes

    # Two-scalar heat model — same load proxy, two coefficients.
    battery_temp_c = _clamp(
        AMBIENT_C + BATTERY_LOAD_COEFF * load + cumulative_rise + rng.uniform(-1.0, 1.0),
        *BATTERY_TEMP_BAND,
    )
    motor_temp_c = _clamp(
        AMBIENT_C + MOTOR_LOAD_COEFF * load + cumulative_rise + rng.uniform(-2.0, 2.0),
        *MOTOR_TEMP_BAND,
    )

    # Altitude profile by phase: ascend climbs toward cruise, cruise stays
    # near cruise altitude, descend falls toward pickup/dropoff.
    if phase == PHASE_ASCEND:
        altitude_m   = _clamp(CRUISE_ALTITUDE_M * (0.4 + 0.6 * rng.random()),
                              *ALTITUDE_BAND)
        vertical     = rng.uniform(1.5, 4.5)
    elif phase == PHASE_CRUISE:
        altitude_m   = _clamp(CRUISE_ALTITUDE_M + rng.uniform(-4.0, 4.0),
                              *ALTITUDE_BAND)
        vertical     = rng.uniform(-0.5, 0.5)
    elif phase == PHASE_DESCEND:
        altitude_m   = _clamp(CRUISE_ALTITUDE_M * (0.1 + 0.4 * rng.random()),
                              *ALTITUDE_BAND)
        vertical     = rng.uniform(-4.5, -1.5)
    else:  # hover
        altitude_m   = _clamp(rng.uniform(2.0, 8.0), *ALTITUDE_BAND)
        vertical     = rng.uniform(-0.3, 0.3)

    # Airspeed: cruise nominal with mild jitter, ascend/descend slower.
    airspeed_base = {
        PHASE_ASCEND:  DEFAULT_CRUISE_AIRSPEED_MPS * 0.70,
        PHASE_CRUISE:  DEFAULT_CRUISE_AIRSPEED_MPS,
        PHASE_DESCEND: DEFAULT_CRUISE_AIRSPEED_MPS * 0.55,
        PHASE_HOVER:   0.5,
    }.get(phase, DEFAULT_CRUISE_AIRSPEED_MPS)
    airspeed_mps = max(0.0, airspeed_base + rng.uniform(-1.5, 1.5))

    # Heading: noise around the inbound bearing.
    heading_deg  = (bearing_deg + rng.uniform(-8.0, 8.0)) % 360.0

    # Signal quality — generally high, with mild jitter and occasional dips.
    signal_strength_pct = _clamp(
        SIGNAL_STRENGTH_BASE_PCT + rng.uniform(-6.0, 4.0), 40.0, 100.0,
    )
    gps_signal_quality  = _clamp(
        GPS_QUALITY_BASE + rng.uniform(-8.0, 6.0), 30.0, 100.0,
    )

    # Estimated remaining range: derived by the onboard controller from
    # current SoC + degraded capacity.  Linear here — proportional to
    # battery_pct (current SoC) and battery_health (capacity fade).
    eff_range = drone_range_km * (battery_pct / 100.0) * (battery_health_pct / 100.0)
    estimated_remaining_range_km = round(eff_range, 3)

    return TelemetryObservation(
        altitude_m                   = round(altitude_m, 2),
        airspeed_mps                 = round(airspeed_mps, 2),
        heading_deg                  = round(heading_deg, 1),
        vertical_speed_mps           = round(vertical, 2),
        battery_temp_c               = round(battery_temp_c, 2),
        motor_temp_c                 = round(motor_temp_c, 2),
        estimated_remaining_range_km = estimated_remaining_range_km,
        signal_strength_pct          = round(signal_strength_pct, 1),
        gps_signal_quality           = round(gps_signal_quality, 1),
    )


def bearing_deg(
    start: tuple[float, float], end: tuple[float, float],
) -> float:
    """Approximate compass bearing from start → end (degrees, 0 = north)."""
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def remaining_range_triggers_emergency(
    obs: TelemetryObservation, distance_to_depot_km: float,
    safety_factor: float = REMAINING_RANGE_SAFETY_FACTOR,
) -> bool:
    """The on-board controller's own emergency-return rule.

    True iff the controller's estimated remaining range is less than the
    straight-line distance back to depot multiplied by ``safety_factor``.
    """
    return obs.estimated_remaining_range_km < distance_to_depot_km * safety_factor
