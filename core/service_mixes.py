"""
core/service_mixes.py

Named multi-domain service mixes (Phase 33).

A *service mix* is a weighted portfolio of delivery domains, modelling
one delivery operator that serves a blended demand profile rather than a
single pure domain.  It is an **analytical overlay** — it reuses the
existing domain economics, capacity coupling, and domain volume-response
logic.  It does NOT create new delivery events, mutate snapshots, or
replace the delivery-domain concept.

Volume interpretation (Phase 33 decision: split-volume)
────────────────────────────────────────────────────────
A mix at total ``deliveries_per_day = V`` serves each component domain
``d`` at ``V × weight_d``.  Each component is therefore evaluated at its
*own share* of the volume, keeping it consistent with the Phase 29
addressable-demand ceiling: blending is precisely how an operator
reaches higher total volume without pushing any single domain past its
ceiling.  Capacity overhead is shared — one fleet sized for the total
volume.  See ``core/service_mix_analysis.py`` for the formula.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.delivery_domains import get_domain
from core.parameter_sweeps import SEPARATOR

# Weights must sum to 1.0 within this tolerance.
_WEIGHT_TOLERANCE = 1e-6


@dataclass(frozen=True)
class ServiceMixComponent:
    """One weighted slice of a service mix."""
    delivery_domain: str
    weight: float


@dataclass(frozen=True)
class ServiceMix:
    """A named weighted portfolio of delivery domains."""
    name: str
    description: str
    components: tuple

    def __post_init__(self) -> None:
        if SEPARATOR in self.name:
            raise ValueError(
                f"service mix name {self.name!r} may not contain the reserved "
                f"synthetic-name character {SEPARATOR!r}"
            )
        if not self.components:
            raise ValueError(f"service mix {self.name!r} has no components")

        seen: set = set()
        total = 0.0
        for c in self.components:
            if c.weight <= 0:
                raise ValueError(
                    f"service mix {self.name!r}: component {c.delivery_domain!r} "
                    f"has non-positive weight {c.weight}"
                )
            if c.delivery_domain in seen:
                raise ValueError(
                    f"service mix {self.name!r}: duplicate component domain "
                    f"{c.delivery_domain!r}"
                )
            seen.add(c.delivery_domain)
            # Resolve to validate the domain exists (raises KeyError if not).
            get_domain(c.delivery_domain)
            total += c.weight

        if abs(total - 1.0) > _WEIGHT_TOLERANCE:
            raise ValueError(
                f"service mix {self.name!r}: component weights sum to {total}, "
                f"must sum to 1.0 (±{_WEIGHT_TOLERANCE})"
            )

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "components": [
                {"component_domain": c.delivery_domain, "mix_weight": c.weight}
                for c in self.components
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Built-in registry — restrained, operationally-coherent mixes.
# ─────────────────────────────────────────────────────────────────────────────

def _mk(domain: str, weight: float) -> ServiceMixComponent:
    return ServiceMixComponent(delivery_domain=domain, weight=weight)


_SERVICE_MIXES: dict = {
    "urgent_medical_courier": ServiceMix(
        name        = "urgent_medical_courier",
        description = ("Focused courier network for time-sensitive documents "
                       "and small medical payloads (lab samples, prescriptions)."),
        components  = (_mk("urgent_documents", 0.60), _mk("medical_delivery", 0.40)),
    ),
    "pharmacy_courier": ServiceMix(
        name        = "pharmacy_courier",
        description = ("Pharmacy / medical-supply operator with some general "
                       "courier spillover."),
        components  = (_mk("medical_delivery", 0.70), _mk("urgent_documents", 0.20),
                       _mk("retail_package", 0.10)),
    ),
    "local_courier_mix": ServiceMix(
        name        = "local_courier_mix",
        description = ("Same-day local courier serving mixed small-item demand."),
        components  = (_mk("urgent_documents", 0.45), _mk("retail_package", 0.35),
                       _mk("medical_delivery", 0.20)),
    ),
    "platform_mixed_local": ServiceMix(
        name        = "platform_mixed_local",
        description = ("Broad local-platform mix — intentionally less focused; "
                       "may show dilution from low-margin volume."),
        components  = (_mk("food_delivery", 0.50), _mk("urgent_documents", 0.30),
                       _mk("retail_package", 0.20)),
    ),
}


def list_service_mixes() -> list:
    """All registered service-mix names, sorted."""
    return sorted(_SERVICE_MIXES.keys())


def get_service_mix(name: str) -> ServiceMix:
    """Resolve a service mix by name.  Raises ``KeyError`` for unknown names."""
    try:
        return _SERVICE_MIXES[name]
    except KeyError:
        known = ", ".join(list_service_mixes())
        raise KeyError(f"unknown service_mix {name!r}; known: {known}") from None


def iter_service_mixes() -> Iterable:
    """Iterate the registered ServiceMix objects in sorted-name order."""
    for n in list_service_mixes():
        yield _SERVICE_MIXES[n]
