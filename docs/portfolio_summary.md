# Drone Deliveries — Portfolio Summary

*Event-driven analytics pipeline using synthetic drone delivery data to
evaluate last-mile delivery economics.*

## What this is

A data-engineering project that asks one comparative question and
builds the pipeline needed to answer it: **under what combination of
fleet capacity, scale-cost structure, and delivery-domain mix does
drone delivery actually clear break-even?**

Operational events (deliveries, telemetry, maintenance, emergencies)
flow into SQLite from a deterministic synthetic simulator. Rerunnable
transforms layer four analytical overlays on top — economics, scale,
hybrid logistics, telemetry — and write to dedicated snapshot tables
keyed by `transformation_runs` for full lineage. A FastAPI backend
exposes the snapshot tables; a React workbench renders them with
shareable URLs per analytical view.

## The analytical question and the answer

The headline chart cross-tabulates three capacity-cost structures
against four delivery-domain assumptions:

![viability grid](../outputs/charts/viability_by_capacity_and_domain.png)

Each cell asks: *does the synthetic model find a delivery volume at
which this domain breaks even, and does that volume sit inside the
domain's addressable demand?*

Current findings (from the live database at the time of this writing):

- **Pilot-scale cost structure is fundamentally non-viable** — every
  domain ends the sweep red. 4 of 12 cells.
- **Regional and dense-urban cost structures both clear break-even for
  every domain within addressable demand** — 8 of 12 cells green.
- **Regional reaches break-even at *lower* volume than dense-urban**
  (≈150–250 / day vs ≈250–400 / day). The smaller absolute daily
  overhead amortises faster despite lower per-drone productivity.
- **The tightest addressable ceiling** is `urgent_documents` at 600
  deliveries / day. Its break-even (150 / day under regional) sits
  comfortably inside the ceiling — viability is not addressable-demand
  bound for this domain.
- **No yellow cells under the current registry** — whenever the model
  finds break-even, that break-even sits inside addressable demand.

The aggregated dictionary that backs these claims is embedded at the
bottom of this document.

## Technical architecture

```
synthetic events → SQLite (events + telemetry + projections)
                 ↓
   rerunnable transforms (auto-discovered)
       economics → trip_economics_snapshots  (per trip × domain)
       scale     → trip_scale_snapshots      (per trip × scale_model)
       hybrid    → fulfillment classification on orders
       telemetry → telemetry_summaries
                 ↓
   core/volume_sensitivity  (capacity-coupled overhead + domain volume response)
   core/portfolio_summary   (viability cross-tab)
                 ↓
   FastAPI analytics endpoints  ←  React workbench  ←  python workbench.py
```

Every recompute writes a `transformation_runs` row carrying git commit
hash and the full parameter dictionary as JSON. Every analytical claim
in the workbench traces back to a specific transformation_runs row.

## What it demonstrates

- Event-driven data modelling with an append-only operational log.
- Snapshot-based lineage — analytical results are persisted artifacts,
  not ephemeral query results.
- Rerunnable transforms composed in deterministic pipeline order.
- Rule-based validation across snapshot tables, severity-tagged.
- Capacity-coupled cost modelling (fleet + support derived from volume,
  not asserted).
- Synthetic comparative analytics with bounded, auditable formulas.
- FastAPI + React workbench with shareable URLs.
- Single-command launcher (`python workbench.py`).

## What it does not claim

- Not a routing or operations system. No GIS, no path planning, no
  charging-queue simulation.
- Not real demand or cost data. Every dollar value is synthetic and
  documented as such at its registry of origin.
- Not predictive. Curves and cells answer *"if these assumptions held,
  what would the model say?"* — they do not forecast real demand
  elasticity.
- Not measured fleet productivity. `deliveries_per_drone_per_day` is
  an analytical knob; it is not validated against any drone vendor's
  duty-cycle data.

## How to run it

```bash
# One-time seed (~30 s):
python run_scenarios.py --scenarios urban_dense suburban_standard rural_extended --trips 100 --seed 42
python run_transforms.py --all-runs --all-delivery-domains
python run_transforms.py --all-runs --all-scale-models
python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts

# Launch (single command, opens http://localhost:5173):
python workbench.py
```

The launcher boots the FastAPI backend and Vite dev server in one
terminal and runs `npm install` on first boot.

<details>
<summary>Live aggregator output (the numbers above)</summary>

```json
{
  "viability_states":            {"viable": 8, "beyond": 0, "never": 4},
  "viability_by_capacity": {
    "dense_urban_capacity":      {"viable": 4, "beyond": 0, "never": 0},
    "pilot_capacity":            {"viable": 0, "beyond": 0, "never": 4},
    "regional_capacity":         {"viable": 4, "beyond": 0, "never": 0}
  },
  "capacity_models_fully_viable": ["dense_urban_capacity", "regional_capacity"],
  "capacity_models_fully_red":    ["pilot_capacity"],
  "capacity_models_mixed":        [],
  "headline": {
    "lowest_breakeven_cells": [
      {"capacity_model": "regional_capacity", "delivery_domain": "medical_delivery",
       "breakeven_deliveries_per_day": 150, "addressable_ceiling": 800},
      {"capacity_model": "regional_capacity", "delivery_domain": "urgent_documents",
       "breakeven_deliveries_per_day": 150, "addressable_ceiling": 600}
    ],
    "tightest_addressable_ceiling": {"domain": "urgent_documents", "ceiling": 600}
  },
  "run_counts":                  {"simulation_runs": 3, "experiments": 3}
}
```

Regenerate with:

```bash
python -c "from core.portfolio_summary import generate_portfolio_summary; \
import json; \
print(json.dumps(generate_portfolio_summary('data/delivery_system.sqlite'), indent=2))"
```

</details>
