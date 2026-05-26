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
DELIVERY_DOMAIN_REGISTRY_VERSION = "v1"


# Default profile — picked because retail packages are the closest match
# to the implicit assumptions of the pre-Phase-22 economics transform
# (modest premium share, moderate order value).
DEFAULT_DOMAIN_NAME = "retail_package"


@dataclass(frozen=True)
class DeliveryDomain:
    """A demand-side profile applied as an analytical overlay.

    Every field is a customer/order characteristic — not a cost, not a
    physics input.  When the economics transform runs with this overlay,
    these knobs influence *revenue*; operational costs stay invariant.
    """

    name: str

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
    ),
}


def list_domains() -> list[str]:
    """Return every registered delivery-domain name, sorted."""
    return sorted(_DOMAINS.keys())


def get_domain(name_or_obj: Union[str, DeliveryDomain, None]) -> DeliveryDomain:
    """Resolve a domain by name, pass through a DeliveryDomain, or fall back to default."""
    if name_or_obj is None:
        return _DOMAINS[DEFAULT_DOMAIN_NAME]
    if isinstance(name_or_obj, DeliveryDomain):
        return name_or_obj
    try:
        return _DOMAINS[name_or_obj]
    except KeyError:
        known = ", ".join(list_domains())
        raise KeyError(f"unknown delivery_domain {name_or_obj!r}; known: {known}")
