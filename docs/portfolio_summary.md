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
  overhead amortizes faster despite lower per-drone productivity.
- **The tightest addressable ceiling** is `urgent_documents` at 600
  deliveries / day. Its break-even (150 / day under regional) sits
  comfortably inside the ceiling — viability is not addressable-demand
  bound for this domain.
- **No yellow cells under the current registry** — whenever the model
  finds break-even, that break-even sits inside addressable demand.

The aggregated dictionary that backs these claims is embedded at the
bottom of this document.

## Why some cells don't work

The grid says *which* cells fail. The same aggregator decomposes
overhead into five components (platform fixed, drone leases, operator
wages, maintenance, chargers) and surfaces the dominant one per cell.

**The headline:** operator wages dominate every failing pilot cell at
~60% of total overhead.

| capacity × domain | platform | drone leases | **operator wages** | maintenance | chargers | total | gap |
|---|---:|---:|---:|---:|---:|---:|---:|
| pilot × food_delivery     | 0.10 | 1.88 | **15.00 (60%)** | 7.00 | 1.00 | 24.98 | −13.74 |
| pilot × medical_delivery  | 0.62 | 1.89 | **15.14 (58%)** | 7.32 | 1.01 | 25.98 |  −9.53 |
| pilot × retail_package    | 0.16 | 1.88 | **15.07 (60%)** | 7.06 | 1.00 | 25.17 | −13.28 |
| pilot × urgent_documents  | 1.00 | 1.88 | **15.00 (58%)** | 7.00 | 1.00 | 25.88 | −11.98 |

The pattern: pilot's `operator_to_drone_ratio = 0.50` forces 250
operators behind 500 drones at $240 / day each. Per-delivery operator
share never falls below ≈ $15, and no domain has source value above
that. The lever isn't demand-side (different domain, more volume); it's
productivity-side (`deliveries_per_drone_per_day`). Regional achieves
viability because it pairs a higher productivity rate (20 vs 8) with a
lower operator ratio (0.15 vs 0.50), which collapses operator wages to
a fraction of pilot's level. Across all 12 cells the constraint mix is
8 viable, 4 capacity-overhead-dominated (all four operator-wages
dominant), 0 addressable-demand-capped — every current failure is a
cost-structure problem, not a demand problem.

## What-if experiments

The workbench lets a reviewer change an assumption and watch the
viability grid respond. Sweeps use a synthetic-name protocol
(`pilot_capacity@operator_to_drone_ratio=0.30`) so every variant carries
its own self-describing audit trail. A 1-D launcher feeds the main grid;
a 2-D explorer renders a heatmap across two parameters at once.

Headline what-if result: reducing pilot staffing from **0.60 → 0.20
operators per drone** narrows the gap from **−$15.89 to −$3.89** per
delivery — a big move that still does not reach break-even. The 2-D
explorer shows the red→green diagonal where staffing *and* per-drone
productivity improve together; neither lever alone is enough.

## Service mix analysis

Real operators serve blended demand, not one pure domain. A **service
mix** is a named weighted portfolio of delivery domains, evaluated
split-volume: a mix at total V serves each component at `V × weight`
(keeping it inside that domain's addressable demand), while capacity
overhead is shared across one fleet sized for the total.

At `pilot_capacity`, 650 deliveries/day: best mix `pharmacy_courier`
(**−$9.82**), worst `platform_mixed_local` (**−$11.94**). **Every** mix
beat its own weakest component — blending lifts the position — yet all
stayed negative under pilot. Blending helps; it does not remove the
capacity-overhead floor by itself.

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

- Event-driven data modeling with an append-only operational log.
- Snapshot-based lineage — analytical results are persisted artifacts,
  not ephemeral query results.
- Rerunnable transforms composed in deterministic pipeline order.
- Rule-based validation across snapshot tables, severity-tagged.
- Capacity-coupled cost modeling (fleet + support derived from volume,
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
terminal and runs `npm install` on first boot. Or run the full reference
workflow in one shot: `bash scripts/run_demo.sh`.

## Future v2 direction

The v1 contribution is the analytical framework and the workbench that
make assumptions visible and testable. The clear v2 step is **real
data**: import historical delivery records from a real operator,
normalize them into the same `delivery_events` → snapshot schema, and
run the existing feasibility overlays (domains, capacity, volume,
service mixes, what-if) against real demand history instead of synthetic
generators. The JSONL export path is already shaped for that ingestion.
Real-data ingestion is future work — not required for v1.

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
