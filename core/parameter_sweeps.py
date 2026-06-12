"""
core/parameter_sweeps.py

Synthetic-name protocol for parameter sweeps (Phase 31).

A *synthetic* name encodes a base registry entry plus one or more
field overrides in a single string::

    food_delivery@saturation_volume_per_day=1500
    food_delivery@saturation_volume_per_day=1500,premium_share=0.25
    pilot_capacity@operator_to_drone_ratio=0.30

The convention lets parameter sweeps flow through every analytical
surface (viability grid, volume sensitivity, FailureModes) without any
of them having to know about the experiment system.  The snapshot's
``domain_name`` / ``scale_model_name`` column carries the full
synthetic string; the reader resolves it back to a working dataclass
via :func:`parse_synthetic_name` + :func:`apply_overrides`.

Type-coercion rule
──────────────────
Override values are parsed from strings and coerced via a fixed trial
chain: ``int`` → ``float`` → leave as ``str``.  This is intentionally
limited to numeric and string fields; ``bool`` and container types are
out of scope for Phase 31 because nothing we want to sweep currently
needs them.  A test pins that a non-numeric string round-trips as a
string (no spurious integer coercion).

Forbidden character
───────────────────
Registered entry names must not contain ``@``.  The character is
reserved for the synthetic-name protocol.  Registry-level assertions
in ``core/delivery_domains.py`` and ``core/capacity_models.py``
enforce this on import.
"""

from __future__ import annotations

import dataclasses
from typing import Any


SEPARATOR = "@"


def parse_synthetic_name(name: str) -> tuple[str, dict[str, object]]:
    """Split a synthetic name into ``(base_name, overrides)``.

    Pure registered names (no ``@``) return empty overrides — the
    caller can fall through to the normal registry lookup.

    Raises:
        ValueError: malformed override pair (no ``=``, empty key, etc.).
    """
    if SEPARATOR not in name:
        return name, {}

    base, raw_overrides = name.split(SEPARATOR, 1)
    if not base:
        raise ValueError(f"synthetic name {name!r} has empty base before {SEPARATOR!r}")
    if not raw_overrides.strip():
        raise ValueError(f"synthetic name {name!r} has empty override block after {SEPARATOR!r}")

    overrides: dict[str, object] = {}
    for raw_pair in raw_overrides.split(","):
        pair = raw_pair.strip()
        if not pair:
            raise ValueError(f"synthetic name {name!r} has empty override pair")
        if "=" not in pair:
            raise ValueError(
                f"synthetic name {name!r}: override pair {pair!r} is missing '='"
            )
        key, raw_value = pair.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            raise ValueError(f"synthetic name {name!r}: override pair {pair!r} has empty field name")
        overrides[key] = _coerce(raw_value)
    return base, overrides


def _coerce(raw: str) -> object:
    """Trial-coerce ``int → float → str``.

    Limited by design: complex types (bools, containers, dataclasses)
    are out of scope for Phase 31.  A non-numeric value falls through
    to a string verbatim.
    """
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def apply_overrides(base: Any, overrides: dict[str, object], synthetic_name: str) -> Any:
    """Return a frozen-dataclass copy of *base* with *overrides* applied.

    The returned object's ``name`` field is set to ``synthetic_name`` so
    a round-trip through ``compute_viability_summary`` (which keys on
    ``cm.name`` / ``dom.name``) preserves the synthetic identity.

    Raises:
        KeyError: an override key isn't a field on the base dataclass.
            The error lists valid field names.
    """
    valid_fields = {f.name for f in dataclasses.fields(base)}
    unknown = set(overrides) - valid_fields
    if unknown:
        raise KeyError(
            f"unknown override field(s) {sorted(unknown)!r} for "
            f"{type(base).__name__}; valid fields: {sorted(valid_fields)}"
        )
    # ``name`` is always overridden so the synthetic identity survives.
    payload = dict(overrides)
    payload["name"] = synthetic_name
    return dataclasses.replace(base, **payload)


def assert_no_reserved_chars(names: list[str], registry_label: str) -> None:
    """Defensive assertion called at module import for built-in
    registries.  Registered names must not contain ``@``."""
    bad = [n for n in names if SEPARATOR in n]
    if bad:
        raise AssertionError(
            f"{registry_label}: names containing {SEPARATOR!r} are reserved for "
            f"the synthetic-name protocol; offending entries: {bad!r}"
        )
