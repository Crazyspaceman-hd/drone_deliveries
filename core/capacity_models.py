"""
core/capacity_models.py

Capacity-coupled cost-structure overlay (Phase 28).

Why this exists separately from ScaleModel
───────────────────────────────────────────
Phase 23's ``ScaleModel`` treats ``fleet_size`` and ``deliveries_per_day``
as independent knobs.  Phase 27's volume sensitivity exposed the flaw:
sweeping deliveries/day while holding fleet_size constant lets a 5-drone
pilot model absorb 6000 deliveries/day with no extra capacity, which is
not how anything works.

``CapacityModel`` corrects that by promoting **per-drone productivity**
(``deliveries_per_drone_per_day``) to the primary structural knob.  Given
volume, capacity (drones, operators, chargers, maintenance staff) is
*derived*, not assumed.  See ``core/volume_sensitivity.py`` for the
sweep that consumes this dataclass.

Relation to ScaleModel (transition state)
──────────────────────────────────────────
This module does NOT replace ``ScaleModel``.  The four named scale
models, the existing scale snapshot writer (``transforms/scale.py``),
and the persisted ``trip_scale_snapshots`` table all remain on the
original fixed-overhead formula.  Only the volume-sensitivity surface
uses CapacityModel.

A future phase will reconcile the two registries — either by deriving
ScaleModel from CapacityModel (or vice-versa) or by retiring one.  This
phase deliberately leaves them parallel so the correction is reviewable
in isolation, without breaking Phase 22/23 snapshots.

What we deliberately dropped
─────────────────────────────
``ScaleModel`` carries a utilization rebate term in
``transforms/scale.py._effective_profit``:

    rebate = utilization_efficiency × idle_reduction_factor × source_op_cost

That rebate was a counterweight that prevented large fleets from
looking strictly worse under the original fixed-overhead formula.  In
the capacity-coupled model, utilization is already encoded directly
via ``deliveries_per_drone_per_day`` — a productivity rate of 30
vs. 8 deliveries/drone/day IS the economy-of-scale story.  Carrying
the rebate forward would double-count utilization.

So this module's formula does NOT apply a rebate.  Phase 23 snapshots
keep their original numbers; new capacity-coupled computations are
clean of the fudge factor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Union


# Bump when default profiles change in a way analytics should be able
# to distinguish across snapshots / API responses.
CAPACITY_MODEL_REGISTRY_VERSION = "v1"


# Default = pilot_capacity.  Smallest, most conservative; the most
# honest starting view before economies of scale.  See Phase 27's
# rationale for the same default choice.
DEFAULT_CAPACITY_MODEL_NAME = "pilot_capacity"


@dataclass(frozen=True)
class CapacityModel:
    """Analytical capacity + cost structure.

    Every field is COUNTERFACTUAL.  Nothing here is validated against
    ``simulation_runs.drone_count`` — the sweep asks *"what would costs
    look like if the fleet were sized to meet this volume?"*

    No utilization rebate knobs — see module docstring.
    """

    name: str

    # The primary structural knob.  Determines how many drones a given
    # volume requires.  Holds productivity assumptions about how often a
    # single drone can fly, recharge, and be re-dispatched per 24 h.
    deliveries_per_drone_per_day: float

    # Staffing ratios (per drone).  Multiplied by required_drones at
    # sweep time and ceil()'d to produce headcounts.
    operator_to_drone_ratio:     float
    maintenance_staff_per_drone: float

    # Charging infrastructure.  Modeled as a count (not a flat daily
    # cost) so it scales with required_drones the way real depots do.
    charger_to_drone_ratio: float

    # Daily cost components.  These are the inputs to
    # daily_capacity_overhead_at(volume).  Explicit per-resource costs
    # so the formula is auditable: which dollar moved which way under
    # which assumption.
    platform_fixed_cost_usd_day:           float
    operator_daily_cost_usd:               float
    maintenance_daily_cost_usd:            float
    charger_daily_cost_usd:                float
    drone_daily_lease_or_depreciation_usd: float

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Built-in registry — three profiles spanning pilot → regional → dense urban.
# Values chosen so the implied daily overhead at the profile's "natural"
# volume tracks the corresponding ScaleModel within ~10%, so reviewers can
# sanity-check against the Phase 23 numbers.
# ─────────────────────────────────────────────────────────────────────────────

_CAPACITY_MODELS: dict[str, CapacityModel] = {
    # Small fleet, modest productivity per drone.  One charger per
    # drone (no shared infra yet).  Per-delivery overhead is high
    # because the platform/staffing floor is amortized over few trips.
    "pilot_capacity": CapacityModel(
        name                                  = "pilot_capacity",
        deliveries_per_drone_per_day          = 8.0,
        operator_to_drone_ratio               = 0.50,
        maintenance_staff_per_drone           = 0.20,
        charger_to_drone_ratio                = 1.0,
        platform_fixed_cost_usd_day           = 400.0,
        operator_daily_cost_usd               = 240.0,
        maintenance_daily_cost_usd            = 280.0,
        charger_daily_cost_usd                = 8.0,
        drone_daily_lease_or_depreciation_usd = 15.0,
    ),

    # Moderate productivity, denser staffing.  Chargers shared 2:1.
    "regional_capacity": CapacityModel(
        name                                  = "regional_capacity",
        deliveries_per_drone_per_day          = 20.0,
        operator_to_drone_ratio               = 0.15,
        maintenance_staff_per_drone           = 0.10,
        charger_to_drone_ratio                = 0.5,
        platform_fixed_cost_usd_day           = 1200.0,
        operator_daily_cost_usd               = 240.0,
        maintenance_daily_cost_usd            = 280.0,
        charger_daily_cost_usd                = 8.0,
        drone_daily_lease_or_depreciation_usd = 15.0,
    ),

    # Dense urban routing — high per-drone productivity, shared infra.
    # At its natural volume (≈3000/day) per-delivery overhead lands
    # within ~7% of ScaleModel.urban_dense_fleet's overhead.
    "dense_urban_capacity": CapacityModel(
        name                                  = "dense_urban_capacity",
        deliveries_per_drone_per_day          = 30.0,
        operator_to_drone_ratio               = 0.08,
        maintenance_staff_per_drone           = 0.06,
        charger_to_drone_ratio                = 0.4,
        platform_fixed_cost_usd_day           = 3500.0,
        operator_daily_cost_usd               = 240.0,
        maintenance_daily_cost_usd            = 280.0,
        charger_daily_cost_usd                = 8.0,
        drone_daily_lease_or_depreciation_usd = 15.0,
    ),
}


def list_capacity_models() -> list[str]:
    """All registered capacity model names, sorted."""
    return sorted(_CAPACITY_MODELS.keys())


def get_capacity_model(name_or_obj: Union[str, CapacityModel, None]) -> CapacityModel:
    """Resolve a capacity model by name, pass through a CapacityModel,
    or fall back to the default profile.

    Phase 31: also resolves *synthetic* names of the form
    ``base_name@field=value[,field2=value2]``.
    """
    if name_or_obj is None:
        return _CAPACITY_MODELS[DEFAULT_CAPACITY_MODEL_NAME]
    if isinstance(name_or_obj, CapacityModel):
        return name_or_obj
    from core.parameter_sweeps import (
        SEPARATOR, apply_overrides, parse_synthetic_name,
    )
    if SEPARATOR in name_or_obj:
        base_name, overrides = parse_synthetic_name(name_or_obj)
        try:
            base = _CAPACITY_MODELS[base_name]
        except KeyError:
            known = ", ".join(list_capacity_models())
            raise KeyError(
                f"unknown capacity_model base {base_name!r} (from {name_or_obj!r}); "
                f"known: {known}"
            )
        return apply_overrides(base, overrides, synthetic_name=name_or_obj)
    try:
        return _CAPACITY_MODELS[name_or_obj]
    except KeyError:
        known = ", ".join(list_capacity_models())
        raise KeyError(f"unknown capacity_model {name_or_obj!r}; known: {known}")


# Phase 31 invariant: registered names cannot contain the synthetic-name
# separator (``@``).
from core.parameter_sweeps import assert_no_reserved_chars as _assert_no_reserved
_assert_no_reserved(list(_CAPACITY_MODELS.keys()), "_CAPACITY_MODELS")
