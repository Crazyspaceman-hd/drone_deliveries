"""
core/delivery_domains.py

Demand-side reinterpretation overlay (Phase 22).

Layering rule for the analytical stack:

    Scenario           = operational knobs (battery drain, telemetry,
                         distance ranges).  Phase 9.
    EconomicModel      = per-trip unit prices ($/kWh, $/event,
                         delivery_fee).  Phase 20.
    delivery_domain    = demand-side characteristics — who orders, what
                         they carry, what they're willing to pay, how
                         urgent it is.  Phase 22 (this module).
    scale_model        = fleet-wide structural costs (overhead,
                         amortization, staffing ratios).  Phase 23.

A DeliveryDomain is a recomputable overlay: the SAME operational events
can be reinterpreted under multiple domain profiles without rerunning
the simulator.  ``transforms/economics.py`` consumes a DeliveryDomain
and writes its result to ``trip_economics_snapshots`` so multiple
recomputes coexist for comparison.

What this module deliberately does NOT do
─────────────────────────────────────────
- No physics.  Energy cost, maintenance cost, distance, telemetry —
  none of those depend on domain.  Phase 22 enforces this via test
  invariants in ``tests/test_delivery_domains.py``.
- No fleet-wide costs.  Overhead and amortization belong in
  ``scale_model`` (Phase 23).
- No new simulator architecture.  Domain is read-only analytical input.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Union


# Bump this string when the built-in profiles change in a way analytics
# should be able to distinguish.  Recorded in
# ``transformation_runs.parameters_json.registry_versions`` so an analyst
# can tell whether a snapshot from six months ago used "food_delivery v1"
# or "food_delivery v2".
#
# v1 → v2 (Phase 29):  added synthetic volume-response fields
# (volume_efficiency_gain_rate, volume_value_decay_rate,
# saturation_volume_per_day).  These do NOT enter the persisted
# economics snapshots — they apply at volume-sensitivity sweep time only.
# v2 → v3 (Phase 29 revision): retuned retail_package's addressable
# demand ceiling (5000 → 3000) so the chart honestly reflects regional
# saturation.  Also reframed saturation_volume_per_day as the
# addressable-demand ceiling rather than just a math knob — the
# volume-sensitivity sweep now flags rows beyond this point as
# extrapolation.
DELIVERY_DOMAIN_REGISTRY_VERSION = "v3"


# Default profile — picked because retail packages are the closest match
# to the implicit assumptions of the pre-Phase-22 economics transform
# (modest premium share, moderate order value).
DEFAULT_DOMAIN_NAME = "retail_package"


@dataclass(frozen=True)
class DeliveryDomain:
    """A demand-side profile applied as an analytical overlay.

    Fields fall into two groups with very different lifecycles:

    Static fields (applied per-trip; affect ``trip_economics_snapshots``):
      * payload_kg_mean, payload_kg_std
      * urgency_high_share, urgency_medium_share
      * premium_share
      * average_order_value_usd
      * acceptable_window_min
      * freshness_sensitivity
      * batching_suitability

    Dynamic volume-response fields (Phase 29; applied at sweep time only;
    do NOT enter snapshots):
      * volume_efficiency_gain_rate
      * volume_value_decay_rate
      * saturation_volume_per_day

    The volume-response fields are consumed by
    ``core/volume_sensitivity.py`` — they let different domains produce
    differently-shaped curves (not just vertical offsets) as
    deliveries-per-day rises.  Changing them does NOT trigger any
    economics-snapshot recompute.

    Every static field is a customer/order characteristic — not a cost,
    not a physics input.  When the economics transform runs with this
    overlay, the static fields influence *revenue*; operational costs
    stay invariant (enforced by tests/test_delivery_domains.py).
    """

    name: str

    # ── Static fields (affect trip_economics_snapshots) ────────────────────

    # Payload distribution — for now, mean + std are documentation only;
    # the simulator already generates per-trip payload weights, and
    # Phase 22 doesn't try to re-inject them.  Surfaced here so a future
    # analytics pass can compare configured-domain vs observed-trips.
    payload_kg_mean: float
    payload_kg_std:  float

    # Urgency distribution — fraction of orders in each urgency band.
    # The shares should sum to <= 1.0; the remainder is "low" urgency.
    urgency_high_share:   float
    urgency_medium_share: float

    # Premium-customer share — fraction willing to pay a premium uplift.
    premium_share: float

    # Average order value (USD) — used to scale per-delivery revenue
    # alongside the EconomicModel's base ``delivery_fee``.
    average_order_value_usd: float

    # Promised delivery-window length (minutes).  Documentation here;
    # future phases can use this for SLA analysis.
    acceptable_window_min: float

    # Freshness sensitivity (0..1).  Higher = more value lost per minute
    # of latency; used by future latency-adjusted-value analytics.
    freshness_sensitivity: float

    # Batching suitability (0..1).  Higher = easier for trucks to combine
    # this order with others on a route; used by future scale-side
    # analytics.
    batching_suitability: float

    # ── Dynamic volume-response fields (Phase 29; sweep-time only) ─────────

    # Cost-side efficiency improvement as volume rises.  Caps at
    # ``avg_operational_cost * volume_efficiency_gain_rate`` once volume
    # reaches saturation_volume_per_day.  Synthetic — modelled as a
    # saturation-normalised log so the credit grows quickly at first and
    # then flattens.  See core/volume_sensitivity.domain_efficiency_credit.
    volume_efficiency_gain_rate: float

    # Revenue-side dilution as lower-priority volume enters the mix.
    # Caps at ``avg_revenue * volume_value_decay_rate`` once volume
    # reaches saturation_volume_per_day.  Modelled linearly from 0 to
    # saturation, then flat.  See core/volume_sensitivity.domain_value_decay.
    volume_value_decay_rate: float

    # Addressable-demand ceiling — the upper bound of volumes the
    # synthetic model believes itself within.  Both response terms
    # saturate here; ``core/volume_sensitivity.py`` also flags rows past
    # this point as ``within_addressable_demand=False`` so the chart can
    # render extrapolated regions as dashed.  Higher for broad-appeal
    # domains (food, retail); lower for niche domains (medical,
    # urgent_documents).  Synthetic — not measured.
    saturation_volume_per_day: int

    def to_dict(self) -> dict:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# Built-in registry — four lightweight profiles.  Add a new one by
# appending to ``_DOMAINS``; analytics pick it up via list_domains().
# ─────────────────────────────────────────────────────────────────────────────

_DOMAINS: dict[str, DeliveryDomain] = {
    # Small parcels, urgent, freshness-sensitive — restaurant deliveries
    # are the canonical example of a domain where speed has real dollar value.
    "food_delivery": DeliveryDomain(
        name                     = "food_delivery",
        payload_kg_mean          = 0.8,
        payload_kg_std           = 0.5,
        urgency_high_share       = 0.55,
        urgency_medium_share     = 0.35,
        premium_share            = 0.30,
        average_order_value_usd  = 25.0,
        acceptable_window_min    = 35.0,
        freshness_sensitivity    = 0.85,
        batching_suitability     = 0.25,
        # Moderate efficiency gain (route density), moderate value decay
        # (premium dilution as casual customers enter), high saturation
        # (broad appeal).
        volume_efficiency_gain_rate = 0.06,
        volume_value_decay_rate     = 0.12,
        saturation_volume_per_day   = 4000,
    ),

    # Very small, very urgent, almost never batched.  Pays for reliability,
    # not for speed alone.
    "medical_delivery": DeliveryDomain(
        name                     = "medical_delivery",
        payload_kg_mean          = 0.4,
        payload_kg_std           = 0.3,
        urgency_high_share       = 0.85,
        urgency_medium_share     = 0.10,
        premium_share            = 0.50,
        average_order_value_usd  = 75.0,
        acceptable_window_min    = 25.0,
        freshness_sensitivity    = 0.70,
        batching_suitability     = 0.05,
        # Low efficiency gain (chain-of-custody overhead), low value
        # decay (high-value customers don't churn easily), low saturation
        # (niche demand).
        volume_efficiency_gain_rate = 0.03,
        volume_value_decay_rate     = 0.06,
        saturation_volume_per_day   = 800,
    ),

    # Heavier, lower urgency, batches well — the truck-favouring baseline
    # used as the default domain because it most closely matches the
    # implicit assumptions of the pre-Phase-22 economics transform.
    "retail_package": DeliveryDomain(
        name                     = "retail_package",
        payload_kg_mean          = 2.5,
        payload_kg_std           = 1.5,
        urgency_high_share       = 0.05,
        urgency_medium_share     = 0.25,
        premium_share            = 0.08,
        average_order_value_usd  = 40.0,
        acceptable_window_min    = 120.0,
        freshness_sensitivity    = 0.10,
        batching_suitability     = 0.85,
        # Higher efficiency gain (batching scales well), low value decay
        # (already a commodity service).  Addressable demand ceiling
        # was 5000/day in v2; retuned to 3000/day in v3 so the chart
        # honestly reflects regional saturation — a metro that supports
        # 4000 food deliveries/day will not also yield 5000 retail/day.
        volume_efficiency_gain_rate = 0.08,
        volume_value_decay_rate     = 0.05,
        saturation_volume_per_day   = 3000,
    ),

    # Tiny payload, high urgency, high willingness-to-pay for speed.
    # Freshness doesn't matter much — a document is still a document
    # five minutes later — but the customer paid for "now".
    "urgent_documents": DeliveryDomain(
        name                     = "urgent_documents",
        payload_kg_mean          = 0.1,
        payload_kg_std           = 0.05,
        urgency_high_share       = 0.75,
        urgency_medium_share     = 0.20,
        premium_share            = 0.60,
        average_order_value_usd  = 40.0,
        acceptable_window_min    = 30.0,
        freshness_sensitivity    = 0.30,
        batching_suitability     = 0.20,
        # Low efficiency gain (each delivery is bespoke), high value
        # decay (premium urgency loses meaning as routine volume rises),
        # low saturation (limited addressable demand).
        volume_efficiency_gain_rate = 0.03,
        volume_value_decay_rate     = 0.18,
        saturation_volume_per_day   = 600,
    ),
}


def list_domains() -> list[str]:
    """Return every registered delivery-domain name, sorted."""
    return sorted(_DOMAINS.keys())


def get_domain(name_or_obj: Union[str, DeliveryDomain, None]) -> DeliveryDomain:
    """Resolve a domain by name, pass through a DeliveryDomain, or fall
    back to default.

    Phase 31: also resolves *synthetic* names of the form
    ``base_name@field=value[,field2=value2]``.  The base is looked up
    in the registry; the overrides are applied via
    :func:`core.parameter_sweeps.apply_overrides`.
    """
    if name_or_obj is None:
        return _DOMAINS[DEFAULT_DOMAIN_NAME]
    if isinstance(name_or_obj, DeliveryDomain):
        return name_or_obj
    # Synthetic-name path: parse out the base, look it up, apply overrides.
    from core.parameter_sweeps import (
        SEPARATOR, apply_overrides, parse_synthetic_name,
    )
    if SEPARATOR in name_or_obj:
        base_name, overrides = parse_synthetic_name(name_or_obj)
        try:
            base = _DOMAINS[base_name]
        except KeyError:
            known = ", ".join(list_domains())
            raise KeyError(
                f"unknown delivery_domain base {base_name!r} (from {name_or_obj!r}); "
                f"known: {known}"
            )
        return apply_overrides(base, overrides, synthetic_name=name_or_obj)
    try:
        return _DOMAINS[name_or_obj]
    except KeyError:
        known = ", ".join(list_domains())
        raise KeyError(f"unknown delivery_domain {name_or_obj!r}; known: {known}")


# Phase 31 invariant: registered entry names cannot contain the
# synthetic-name separator (``@``).  Asserted at import time so a
# misnamed future addition fails loud rather than silently corrupting
# the protocol.
from core.parameter_sweeps import assert_no_reserved_chars as _assert_no_reserved
_assert_no_reserved(list(_DOMAINS.keys()), "_DOMAINS")
