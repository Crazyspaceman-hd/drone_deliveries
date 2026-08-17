"""
core/labor_costs.py

Single source of truth for the daily labor-cost constants shared by the
two cost-structure registries — ``core/scale_models.py`` (Phase 23) and
``core/capacity_models.py`` (Phase 28).

These rates were previously hard-coded independently in both modules
(literal ``240.0`` / ``280.0`` in each capacity profile, named constants
in scale_models). They happened to match, but nothing kept them in sync:
retuning one surface would silently desync the other. Centralizing them
here removes that latent bug without changing any value.

Both are **synthetic base** daily wages (single 8-hour shift) — not
fully-loaded employer cost (no benefits / payroll tax / supervision
overhead). See ``docs/cost_model_research.md`` §3 for the public wage
ranges these land in and the base-vs-loaded caveat.
"""

from __future__ import annotations

OPERATOR_DAILY_USD    = 240.0   # ~8 hours × $30/hr (synthetic base wage)
MAINTENANCE_DAILY_USD = 280.0   # slightly higher to reflect parts/tools (synthetic)
