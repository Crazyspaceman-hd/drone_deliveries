"""
core/scale_models.py

Fleet-scale economic overlay (Phase 23).

Layering rule for the analytical stack:

    Scenario           = operational knobs (battery, telemetry, distance)
    EconomicModel      = unit prices ($/kWh, $/event, delivery_fee)
    delivery_domain    = demand-side (who orders, payload mean, AOV)
    scale_model        = fleet-wide structural costs (overhead,
                         staffing, amortization, utilization)
    hybrid             = per-order dispatch decisions; does NOT see
                         scale.

A ScaleModel is read-only analytical input.  It never mutates
operational events, telemetry, trips, or economics snapshots — the
scale transform writes only to ``trip_scale_snapshots`` and to
``transformation_runs``.

Counterfactual semantics
─────────────────────────
Every knob below — ``fleet_size``, ``deliveries_per_day``, all the
overhead $/day fields — is **analytical only**.  ``fleet_size`` does
NOT have to match ``simulation_runs.drone_count``.  The recompute
asks: *"what would costs look like AT this scale?"*  The simulator's
actual fleet is irrelevant; we're computing a counterfactual.

This mirrors the way Phase 22 treats ``delivery_domain.payload_kg_mean``
as documentation while the demand-side knobs (AOV, premium share) do
the real work.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Union


# Bump when built-in profiles change in a way analytics should be able
# to distinguish.  Recorded in
# ``transformation_runs.parameters_json.registry_versions`` so an
# analyst can tell whether a snapshot from six months ago used
# "urban_dense_fleet v1" or "urban_dense_fleet v2".
SCALE_MODEL_REGISTRY_VERSION = "v1"


# Default = smallest, closest to "barely any amortization yet".  Picked
# so the auto-pipeline's default behavior is recognizably similar to
# pre-Phase-23 (operational cost dominates; overhead is small but
# present).
DEFAULT_SCALE_MODEL_NAME = "pilot_program"


# Synthetic daily-cost constants for staff.  Single source of truth now
# lives in ``core/labor_costs.py`` so this registry and the Phase 28
# CapacityModel registry cannot silently desync when a rate is retuned.
# Re-exported here so existing ``scale_models.OPERATOR_DAILY_USD``
# references keep working.
from core.labor_costs import OPERATOR_DAILY_USD, MAINTENANCE_DAILY_USD


@dataclass(frozen=True)
class ScaleModel:
    """Analytical overlay describing fleet-wide structural costs.

    Every field is COUNTERFACTUAL — see module docstring.  The scale
    transform reads these knobs and writes a per-trip row into
    ``trip_scale_snapshots``; nothing else moves.
    """

    name: str

    # Analytical-only fleet sizing (not validated against
    # simulation_runs.drone_count).
    fleet_size:         int
    deliveries_per_day: int

    # Staffing ratios — multiplied by fleet_size to produce daily
    # operator / maintenance headcounts; each headcount draws the
    # corresponding *_DAILY_USD constant.
    operator_to_drone_ratio:     float
    maintenance_staff_per_drone: float

    # Direct fixed costs ($/day).  Sum into the daily overhead pool;
    # divided by deliveries_per_day for the per-trip amortization.
    fixed_platform_overhead_usd_day:      float
    charging_infrastructure_cost_usd_day: float
    software_operations_cost_usd_day:     float

    # Utilization model.  ``utilization_efficiency`` is a 0..1 score
    # describing how much of the available drone time is productive;
    # ``idle_reduction_factor`` is how much of the per-trip operational
    # cost is recovered by avoiding idle waste at this scale.  The
    # product (efficiency × idle_reduction × op_cost) is added back to
    # effective_profit — better utilization = less wasted operational
    # spend.
    utilization_efficiency: float
    idle_reduction_factor:  float

    def to_dict(self) -> dict:
        return asdict(self)

    def daily_overhead_usd(self) -> float:
        """Total daily structural cost at this scale (synthetic)."""
        operator_count    = self.operator_to_drone_ratio   * self.fleet_size
        maintenance_count = self.maintenance_staff_per_drone * self.fleet_size
        staff = (operator_count    * OPERATOR_DAILY_USD
                 + maintenance_count * MAINTENANCE_DAILY_USD)
        return (self.fixed_platform_overhead_usd_day
                + self.charging_infrastructure_cost_usd_day
                + self.software_operations_cost_usd_day
                + staff)

    def amortized_overhead_per_trip(self) -> float:
        """Per-trip amortization of daily overhead."""
        if self.deliveries_per_day <= 0:
            return 0.0
        return self.daily_overhead_usd() / self.deliveries_per_day


# ─────────────────────────────────────────────────────────────────────────────
# Built-in registry — four scales spanning pilot to national.
# ─────────────────────────────────────────────────────────────────────────────

_SCALE_MODELS: dict[str, ScaleModel] = {
    # Small fleet, modest daily volume, poor utilization.  Fixed
    # overhead dominates per-trip economics — the canonical
    # "this isn't paying for itself yet" stage.
    "pilot_program": ScaleModel(
        name                                 = "pilot_program",
        fleet_size                           = 5,
        deliveries_per_day                   = 40,
        operator_to_drone_ratio              = 0.50,    # 2.5 operators
        maintenance_staff_per_drone          = 0.20,    # 1 maintenance tech
        fixed_platform_overhead_usd_day      = 400.0,
        charging_infrastructure_cost_usd_day = 30.0,
        software_operations_cost_usd_day     = 80.0,
        utilization_efficiency               = 0.40,
        idle_reduction_factor                = 0.10,
    ),

    # Moderate fleet, daily volume large enough to start amortizing
    # the platform/software floor.  Utilization rises with denser
    # routing.
    "regional_network": ScaleModel(
        name                                 = "regional_network",
        fleet_size                           = 25,
        deliveries_per_day                   = 500,
        operator_to_drone_ratio              = 0.15,    # ~4 operators
        maintenance_staff_per_drone          = 0.10,    # ~3 maintenance
        fixed_platform_overhead_usd_day      = 1200.0,
        charging_infrastructure_cost_usd_day = 200.0,
        software_operations_cost_usd_day     = 350.0,
        utilization_efficiency               = 0.65,
        idle_reduction_factor                = 0.30,
    ),

    # Dense urban deployment with high duty cycles and tight routing.
    # Utilization is the best of the four; per-trip overhead is small
    # despite a larger absolute overhead pool.
    "urban_dense_fleet": ScaleModel(
        name                                 = "urban_dense_fleet",
        fleet_size                           = 100,
        deliveries_per_day                   = 3000,
        operator_to_drone_ratio              = 0.08,    # ~8 operators
        maintenance_staff_per_drone          = 0.06,    # ~6 maintenance
        fixed_platform_overhead_usd_day      = 3500.0,
        charging_infrastructure_cost_usd_day = 1200.0,
        software_operations_cost_usd_day     = 1200.0,
        utilization_efficiency               = 0.85,
        idle_reduction_factor                = 0.50,
    ),

    # Very large fleet across many cities.  Platform/software cost grows
    # substantially; geographic spread reintroduces some idle time, so
    # utilization is slightly below the urban-dense peak — a
    # diseconomy-of-scale story.
    "national_scale": ScaleModel(
        name                                 = "national_scale",
        fleet_size                           = 1000,
        deliveries_per_day                   = 20000,
        operator_to_drone_ratio              = 0.05,    # ~50 operators
        maintenance_staff_per_drone          = 0.04,    # ~40 maintenance
        fixed_platform_overhead_usd_day      = 18000.0,
        charging_infrastructure_cost_usd_day = 6000.0,
        software_operations_cost_usd_day     = 6000.0,
        utilization_efficiency               = 0.80,
        idle_reduction_factor                = 0.45,
    ),
}


def list_scale_models() -> list[str]:
    """Return every registered scale-model name, sorted."""
    return sorted(_SCALE_MODELS.keys())


def get_scale_model(name_or_obj: Union[str, ScaleModel, None]) -> ScaleModel:
    """Resolve a scale model by name, pass through a ScaleModel, or
    fall back to the default profile."""
    if name_or_obj is None:
        return _SCALE_MODELS[DEFAULT_SCALE_MODEL_NAME]
    if isinstance(name_or_obj, ScaleModel):
        return name_or_obj
    try:
        return _SCALE_MODELS[name_or_obj]
    except KeyError:
        known = ", ".join(list_scale_models())
        raise KeyError(f"unknown scale_model {name_or_obj!r}; known: {known}")
