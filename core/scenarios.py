"""
core/scenarios.py

Operational scenarios for comparative simulation.

A `Scenario` is a small bag of knobs the simulator reads to decide how
trips behave.  Choosing a scenario does not change the event vocabulary
or the SQLite schema — it just shifts the rates and quantities so the
same simulator can produce data for dense urban, suburban, or rural
operations.

Determinism note
─────────────────
The scenario knobs are designed so that switching scenarios does NOT
introduce new RNG draws and does NOT reorder existing ones.  Each knob
either:
  - replaces a hard-coded constant in a probability comparison
    (e.g. ``rng.random() < scenario.emergency_return_chance``), or
  - is added/multiplied AFTER an RNG draw to shift the value
    (e.g. ``rng.randint(3, 6) + scenario.telemetry_bonus_per_leg``).
That way ``seed + scenario`` together produce a deterministic run, and
the default scenario (``suburban_standard``) reproduces the pre-Phase-9
seeded behaviour exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class Scenario:
    """Operational knobs for one delivery environment."""

    name: str

    # Informational only (documented for the README; not used in dispatch).
    avg_trip_distance_km:   float
    trip_distance_variance: float

    # Telemetry density.  Added to the rng.randint() result for each leg's
    # ping count, so larger values → more pings per trip.
    telemetry_bonus_per_leg: int

    # Multiplied into each rng.uniform() battery-drain step.
    battery_drain_multiplier: float

    # Mid-flight probabilities (replace the hard-coded literals in the simulator).
    route_deviation_chance:    float
    emergency_return_chance:   float

    # Threshold below which a telemetry ping may trigger a battery_warning.
    battery_warning_threshold: float

    # Post-trip maintenance roll probability.
    maintenance_chance: float

    # How long a maintenance cycle takes in simulated seconds.
    maintenance_duration_seconds: int


# ── Built-in scenarios ──────────────────────────────────────────────────────

# suburban_standard is the historical default — its knobs reproduce the
# Phase 8 hard-coded behaviour exactly (so existing tests stay deterministic).
_SCENARIOS: dict[str, Scenario] = {
    "suburban_standard": Scenario(
        name                         = "suburban_standard",
        avg_trip_distance_km         = 6.0,
        trip_distance_variance       = 2.0,
        telemetry_bonus_per_leg      = 0,
        battery_drain_multiplier     = 1.0,
        route_deviation_chance       = 0.05,
        emergency_return_chance      = 0.05,
        battery_warning_threshold    = 30.0,
        maintenance_chance           = 0.08,
        maintenance_duration_seconds = 240,
    ),

    # Short trips, dense telemetry, more weaving around obstacles, gentler
    # battery use because legs are short.
    "urban_dense": Scenario(
        name                         = "urban_dense",
        avg_trip_distance_km         = 3.0,
        trip_distance_variance       = 1.0,
        telemetry_bonus_per_leg      = 2,
        battery_drain_multiplier     = 0.8,
        route_deviation_chance       = 0.10,
        emergency_return_chance      = 0.02,
        battery_warning_threshold    = 25.0,
        maintenance_chance           = 0.06,
        maintenance_duration_seconds = 180,
    ),

    # Long trips, fewer obstacles, harder on the battery, more aborts.
    "rural_extended": Scenario(
        name                         = "rural_extended",
        avg_trip_distance_km         = 12.0,
        trip_distance_variance       = 4.0,
        telemetry_bonus_per_leg      = 0,
        battery_drain_multiplier     = 1.6,
        route_deviation_chance       = 0.02,
        emergency_return_chance      = 0.10,
        battery_warning_threshold    = 35.0,
        maintenance_chance           = 0.12,
        maintenance_duration_seconds = 360,
    ),
}


DEFAULT_SCENARIO_NAME = "suburban_standard"


def list_scenarios() -> list[str]:
    """Names of all registered scenarios."""
    return sorted(_SCENARIOS.keys())


def get_scenario(name_or_obj: Union[str, Scenario, None]) -> Scenario:
    """Resolve a scenario by name, pass through a Scenario, or fall back to default."""
    if name_or_obj is None:
        return _SCENARIOS[DEFAULT_SCENARIO_NAME]
    if isinstance(name_or_obj, Scenario):
        return name_or_obj
    try:
        return _SCENARIOS[name_or_obj]
    except KeyError:
        known = ", ".join(list_scenarios())
        raise KeyError(f"unknown scenario {name_or_obj!r}; known: {known}")
