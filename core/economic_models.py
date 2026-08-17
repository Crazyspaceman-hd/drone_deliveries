"""
core/economic_models.py

Economic assumption sets — separated from operational scenario knobs
(Phase 20 decomposition).

Why this is its own module
───────────────────────────
Before Phase 20, every economic knob (`delivery_fee`, `avg_kwh_per_km`,
`maintenance_cost_per_event`, …) lived directly on the Scenario object
and was applied at simulator-write time.  That made sensitivity
analysis painful: changing delivery_fee required regenerating events.

After Phase 20:

* Operational knobs (battery, telemetry density, distance, congestion)
  still live on Scenario.  These genuinely change what events the
  simulator emits.
* Economic knobs live here, as an ``EconomicModel`` dataclass.  Each
  Scenario implicitly *defines* a default EconomicModel (built from its
  own fields), but transforms (``transforms/economics.py``) accept an
  arbitrary EconomicModel override.  Same events, different economics.

That is the architectural separation the Phase 20 refactor pays for.

Backward compatibility
───────────────────────
Scenario fields are unchanged — see Phase 9 for the original definitions.
We don't remove them; we *promote* them into EconomicModel via
``from_scenario_name(name)``.  This avoids churning every test that
asserts a Scenario shape while still unlocking parameter overrides.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional

from core.scenarios import get_scenario, list_scenarios


# Phase 18 placeholder.  Truck cost-per-delivery isn't on Scenario (it
# arrived with the displacement model), so we centralize its default here.
DEFAULT_TRUCK_COST_PER_DELIVERY = 12.0


@dataclass(frozen=True)
class EconomicModel:
    """Pricing/cost assumptions used by the economics transform."""
    name: str
    energy_cost_per_kwh:         float
    avg_kwh_per_km:              float
    maintenance_cost_per_event:  float
    labor_cost_per_delivery:     float
    drone_depreciation_per_trip: float
    emergency_return_penalty:    float
    delivery_fee:                float
    truck_cost_per_delivery:     float = DEFAULT_TRUCK_COST_PER_DELIVERY


def from_scenario_name(scenario_name: str) -> EconomicModel:
    """The implicit default model for a given operational scenario."""
    sc = get_scenario(scenario_name)  # raises KeyError for unknown names
    return EconomicModel(
        name                        = f"{sc.name}_default",
        energy_cost_per_kwh         = sc.energy_cost_per_kwh,
        avg_kwh_per_km              = sc.avg_kwh_per_km,
        maintenance_cost_per_event  = sc.maintenance_cost_per_event,
        labor_cost_per_delivery     = sc.labor_cost_per_delivery,
        drone_depreciation_per_trip = sc.drone_depreciation_per_trip,
        emergency_return_penalty    = sc.emergency_return_penalty,
        delivery_fee                = sc.delivery_fee,
    )


def to_parameters_json(model: EconomicModel) -> str:
    """Serialize the model for the transformation_runs.parameters_json column."""
    import json
    return json.dumps(asdict(model), separators=(",", ":"), sort_keys=True)


# ── EconomicModel registry (Phase 24) ────────────────────────────────────────
# Scenario names are used as EconomicModel identifiers: each scenario carries
# the default economic knobs for its environment (delivery_fee, $/kWh, etc.).
# ``get_economic_model(name)`` resolves a scenario name → EconomicModel; this
# is the handle ExperimentDefinition.economic_models entries resolve against.


def list_economic_models() -> list[str]:
    """All registered economic model names (= scenario names), sorted."""
    return list_scenarios()


def get_economic_model(name_or_none: "Optional[str]") -> EconomicModel:
    """Resolve an economic model by scenario name, or return the default.

    Raises ``KeyError`` for unknown names so ``Experiment.run()`` can
    surface a clean error and mark the experiment as failed.
    """
    if name_or_none is None:
        return from_scenario_name("suburban_standard")
    # from_scenario_name() raises KeyError for unknown scenario names.
    return from_scenario_name(name_or_none)
