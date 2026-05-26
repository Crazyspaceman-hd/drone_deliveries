# Drone Deliveries Event Simulation

A small data-engineering portfolio project that simulates drone delivery
operations as an **event stream**, stores those events in a local SQLite
database, exports them as JSONL for future lakehouse/object-storage
ingestion, and ships a handful of SQL queries that answer the kinds of
questions an analytics or operations team would ask.

The pipeline is intentionally simple end-to-end:

```
synthetic simulator  →  SQLite (operational store)  →  JSONL export  →  SQL analytics
```

---

## Why this project exists

An earlier version of this repo focused on A* pathfinding over real
elevation data — interesting, but the value lived in the routing
algorithm, not in the data it produced.

The project has since shifted focus toward **how a delivery system
generates data** and how that data is modeled, stored, and queried.
The simulator does not try to be a realistic routing engine; it tries
to be a realistic *event producer* so that the rest of the project —
schema design, projections, exports, and analytics — has something
honest to chew on.

Legacy pathfinding code is preserved under `legacy/terrain_v1/` but is
not integrated into the current event flow.

---

## Current capabilities

- Deterministic synthetic event generation (`--seed`).
- Fleet, order, trip, and trip-leg modeling.
- Append-only `delivery_events` table — the immutable audit log.
- Projection tables (`orders`, `drones`, `trips`, `trip_legs`) maintained
  atomically with each event.
- JSONL export for portable downstream ingestion.
- SQLite-compatible analytics queries.
- Single-file CLI runners (`run_simulation.py`, `run_analytics.py`).
- Legacy A* pathfinding work preserved on disk.

---

## Event model

### Event types

| Event | Meaning |
|---|---|
| `order_created` | A delivery request entered the system. |
| `drone_assigned` | A drone was matched to a pending order. |
| `drone_launched` | A drone left the depot at the start of a leg. |
| `telemetry_ping` | Position + battery sample mid-flight. |
| `pickup_completed` | Drone reached the pickup location (end of leg 1). |
| `delivery_completed` | Drone delivered the package to the customer (end of leg 2). |
| `returned_to_depot` | Drone landed back at the depot (end of leg 3); operational trip done. |
| `battery_warning` | Battery dropped below a threshold mid-flight. |
| `route_deviation` | Drone deviated from the expected route. |
| `emergency_return` | Trip aborted; drone returned to depot. |
| `maintenance_required` | Drone flagged for service between trips. |
| `maintenance_completed` | Drone finished service and returned to the idle pool. |
| `error` | Catch-all for software/operational failures. |

### Event schema (`delivery_events` table and JSONL columns)

| Column | Type | Notes |
|---|---|---|
| `event_id` | TEXT (UUID) | Primary key. |
| `event_time` | TIMESTAMP | When the event happened (simulation clock). |
| `ingested_at` | TIMESTAMP | When the row landed in the store. |
| `drone_id` | TEXT, nullable | Null for `order_created`. |
| `trip_id` | TEXT, nullable | Null for events unrelated to a trip. |
| `leg_id` | TEXT, nullable | Set for mid-flight events. |
| `event_type` | TEXT | One of the values above. |
| `latitude` | REAL, nullable | WGS-84. |
| `longitude` | REAL, nullable | WGS-84. |
| `battery_pct` | REAL, nullable | 0–100. |
| `payload_json` | TEXT, nullable | Event-specific detail. Kept as a string on purpose (see Design notes). |

---

## Repository layout

```
core/
  models.py        # DeliveryEvent + Drone/Order/Trip/TripLeg dataclasses, status enums
  events.py        # event-type constants, emit(), fetch_events()
  projections.py   # cursor-level projection updaters for orders/drones/trips
  setup_db.py      # SQLite schema creation
  simulator.py     # synthetic event-stream generator
  sinks.py         # JsonlSink + export_events_to_jsonl helper
  order_manager.py # create_order / fetch_order helpers
analytics/sql/     # SQLite-compatible analytics queries
run_simulation.py  # CLI: run the simulator (+ optional JSONL export)
run_analytics.py   # CLI: execute all analytics/sql/*.sql against the DB
legacy/terrain_v1/ # earlier A* pathfinder + elevation pipeline (not wired in)
data/              # runtime SQLite + JSONL artifacts (gitignored)
```

Some older sandbox directories (`scripts/`, `dev/`, `research/`, etc.)
remain on disk for now. Cleanup is incremental.

---

## Quickstart

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

python run_simulation.py --reset --drones 3 --trips 10 --seed 42 \
    --export-jsonl data/events.jsonl

python run_analytics.py
```

> **Note on `requirements.txt`.** The current simulator and analytics
> stack uses only the Python standard library. `requirements.txt` still
> lists `numpy`, `matplotlib`, `rasterio`, `scipy`, and `strm` from the
> legacy pathfinding pipeline. They are only needed if you intend to
> run code under `legacy/terrain_v1/`. The Phase 1–3 code will install
> and run without any of them.

---

## Example output (seed = 42)

```
--- Simulation summary -----------------------------------------
  db_path:          data/delivery_system.sqlite
  drones:           3
  trips_requested:  10
  trips_completed:  10
  events_written:   245
  event_counts_by_type:
    battery_warning            10
    delivery_completed         10
    drone_assigned             10
    drone_launched             10
    maintenance_completed       3
    maintenance_required        4
    order_created              10
    pickup_completed           10
    returned_to_depot          10
    route_deviation             7
    telemetry_ping            161
  jsonl_export:     data/events.jsonl (245 rows)
```

Each trip is the full three-leg cycle: `drone_launched → pickup_completed
→ delivery_completed → returned_to_depot`. Larger runs (e.g. 8 drones × 150
trips) will surface `emergency_return` events; in those, the aborted trip
ends after `emergency_return` with no `delivery_completed` or
`returned_to_depot`.

---

## Analytics examples

The queries in `analytics/sql/` are SQLite-compatible. Each answers one
operational question.

| File | Question it answers |
|---|---|
| `event_counts.sql` | What did the simulator emit, and how much of each event type? |
| `orders_by_status.sql` | How did orders end up — delivered, errored, still pending? |
| `drone_utilization.sql` | Per drone: how many trips, current status, battery, telemetry volume, warnings, deviations, returns, maintenance flags. |
| `trip_outcomes.sql` | Per trip: launched_at, completed_at, status, leg progress, duration in seconds. |
| `battery_warnings_per_drone.sql` | Which drones triggered the most low-battery warnings, lowest battery seen, latest reading. |

Run them all at once with `python run_analytics.py`, or individually:

```bash
sqlite3 data/delivery_system.sqlite < analytics/sql/drone_utilization.sql
```

---

## Scenarios

The simulator can run under different **operational scenarios** so the
same event pipeline can answer comparative questions like *"would drone
delivery make sense in dense urban, suburban, or rural conditions?"*. A
scenario is a small bag of knobs (target trip distance, telemetry
density, battery drain, emergency-return probability, maintenance
duration, etc.) — switching scenarios does **not** change the event
vocabulary or the schema; it just shifts the rates and quantities the
simulator emits.

**Phase 14 made scenario assumptions causally active**, not just
descriptive: pickup and dropoff coordinates are now sampled around the
depot with a radius derived from `avg_trip_distance_km`, telemetry
density scales with leg distance (~1.5 pings/km), and post-trip
maintenance probability is bumped by low end-of-trip battery and by
long trips. Observed average trip distance now tracks the configured
value to within ~1–2 km across all three built-in scenarios.

Built-in scenarios (see `core/scenarios.py`):

| Scenario | Telemetry | Battery drain | Route deviations | Emergency returns | Maintenance |
|---|---|---|---|---|---|
| `urban_dense` | denser (+2 pings/leg) | gentler (×0.8) | more likely (10%) | rare (2%) | short cycles (180 s) |
| `suburban_standard` | baseline | baseline (×1.0) | baseline (5%) | baseline (5%) | baseline (240 s) |
| `rural_extended` | baseline | harder (×1.6) | rare (2%) | more likely (10%) | longer cycles (360 s) |

Run several scenarios into the same database and compare:

```bash
python run_scenarios.py --reset --scenarios urban_dense suburban_standard rural_extended \
    --drones 3 --trips 50 --seed 42

python run_analytics.py            # includes scenario_summary.sql
python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts
```

Every event and every trip carries a `scenario_name` column so
`analytics/sql/scenario_summary.sql` can group cleanly. A
`scenario_comparison.png` chart is added to the standard PNG set when
scenario-tagged events are present.

The project is increasingly framed as **comparative operational analysis**
on top of a synthetic event stream, not a routing optimiser.

---

## Cost & feasibility modeling

Each scenario also carries a small bag of **synthetic economics** knobs —
energy cost per kWh, kWh per km, maintenance cost per event, labor cost
per delivery, drone depreciation, emergency-return penalty, delivery fee
— and the simulator computes a per-trip economics row at trip end using
transparent formulas (see `_compute_economics` in `core/simulator.py`).

> **Disclaimer.** Costs and revenue here are **illustrative synthetic
> units**, not a real cost model. The goal is comparative feasibility
> ("which scenarios bleed more?"), not financial forecasting.

Persisted to the `trips` table per trip:

```
trip_distance_km, estimated_energy_cost, estimated_maintenance_cost,
estimated_operational_cost, estimated_revenue, estimated_profit,
emergency_return_penalty_applied
```

Formulas (all per trip):

```
energy_cost     = distance_km × avg_kwh_per_km × energy_cost_per_kwh
maintenance     = maintenance_events × maintenance_cost_per_event
operational     = energy + maintenance + labor + depreciation + emergency_penalty
revenue         = delivery_fee  (0 if aborted)
profit          = revenue − operational
```

Aborted trips still incur operational cost (and the emergency-return
penalty) but earn no revenue, so they show up as negative-profit rows in
`analytics/sql/scenario_economics.sql`.

Example findings at `--trips 100 --seed 42` (synthetic units):

| scenario | completed | aborted | total_profit | avg/trip | emergency_returns |
|---|---:|---:|---:|---:|---:|
| `urban_dense` | 100 | 0 | -780 | -7.80 | 0 |
| `suburban_standard` | 95 | 5 | -1,197 | -11.97 | 5 |
| `rural_extended` | 84 | 16 | -3,906 | -39.06 | 16 |

Same direction as the operational analytics: urban completes more, costs
less, and absorbs fewer emergency-return penalties. Rural carries roughly
**5× the per-trip loss** of urban under these knobs.

Commands:

```bash
python run_scenarios.py --reset \
    --scenarios urban_dense suburban_standard rural_extended \
    --trips 100 --seed 42
python run_analytics.py             # includes scenario_economics.sql
python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts
```

---

## Business intelligence layer

On top of the operational and economic data the project ships a small
**rule-based** BI layer that turns scenario metrics into rankings and
plain-English recommendations.

> **Disclaimer.** No ML, no forecasting, no LLM. Every output is an
> arithmetic combination of SQL aggregates followed by a hand-written
> rule. The synthetic cost model from the previous section still
> applies — all numbers are illustrative.

Inputs (per scenario, computed from `trips` and `delivery_events`):

- `completion_rate` (0..1)
- `profit_margin_pct` (signed)
- `emergency_rate` (events / trip)
- `maintenance_per_trip` (events / trip)

Feasibility score:

```
score = 50 * completion_rate
      + 30 * clip(profit_margin_pct / 100, -1..+1)
      - 40 * emergency_rate
      - 10 * maintenance_per_trip
```

Labels:

| Range | Label |
|---|---|
| `score >= 25` | `strong_candidate` |
| `10 <= score < 25` | `borderline` |
| `score < 10` | `poor_candidate` |

The weights and thresholds live at the top of
`core/business_intelligence.py` and are tuned to the current built-in
scenarios; revisit them if you change the cost model.

Recommendation rules (no scenario names hard-coded — they're derived):

- The best- and worst-ranked scenarios are always called out by name.
- If every scenario runs at a loss, the report suggests raising
  `delivery_fee` or reducing maintenance/emergency costs.
- Any scenario with `emergency_rate >= 0.08` is flagged as
  emergency-driven.
- Any scenario with `maintenance_per_trip >= 0.30` is flagged for
  maintenance burden.
- For every scenario the report computes a per-completed-trip
  breakeven `delivery_fee` and suggests the gap.

Example output (seed=42, 100 trips, three built-in scenarios):

```
scenario             score  label              complete  avg_profit/trip  emerg_rate  maint/trip
-------------------  -----  -----------------  --------  ---------------  ----------  ----------
urban_dense          32.1   strong_candidate   1.00      -7.80            0.00        0.49
suburban_standard    22.6   borderline         0.95      -11.97           0.05        0.40
rural_extended        1.6   poor_candidate     0.84      -39.06           0.16        0.40

- urban_dense has the strongest feasibility profile in this comparison
  (score 32.1, label 'strong_candidate').
- rural_extended has the weakest feasibility profile
  (score 1.6, label 'poor_candidate').
- Every evaluated scenario runs at a loss under the current cost
  assumptions; consider raising delivery_fee or reducing
  maintenance_cost_per_event.
- Emergency returns are a major loss driver in: rural_extended.
- Raising delivery_fee by ~46.50 units in rural_extended would
  approach breakeven on completed trips.
```

Commands:

```bash
python run_scenarios.py --reset \
    --scenarios urban_dense suburban_standard rural_extended \
    --trips 100 --seed 42

python run_business_intelligence.py --db data/delivery_system.sqlite
# Optional markdown report:
python run_business_intelligence.py --db data/delivery_system.sqlite \
                                    --markdown outputs/reports/bi_report.md
```

`analytics/sql/feasibility_summary.sql` exposes the same per-scenario
metric rows (without the Python scoring layer) for ad-hoc queries.

---

## Assumptions & calibration

The simulator runs on a small set of explicit knobs. Two categories:

- **publicly informed** — picked to land in plausible public ranges
  (urban single-digit-km vs rural longer trips, ~20–35% low-battery
  alerts, ~0.05–0.15 kWh/km drone energy, residential retail
  electricity, last-mile fees, field-service costs). No specific source
  is cited; values are chosen to land in defensible ballparks, not to
  match any one study.
- **explicitly synthetic** — invented for comparative simulation
  behaviour (emergency-return / route-deviation / maintenance
  probabilities, drain multiplier, BI scoring weights and label
  thresholds).

The narrative — including which knob is which, why direction matters
more than absolute values, and what is *intentionally not modelled* —
lives in [`docs/assumptions.md`](docs/assumptions.md). A
machine-readable view is in [`core/assumptions.py`](core/assumptions.py).

The simulator's outputs remain **comparative, not predictive.** It is
meant for exploratory operational analysis ("which scenario bleeds
least, and what would help?"), not forecasting.

```bash
python run_assumptions_report.py
python run_assumptions_report.py --markdown outputs/reports/assumptions_report.md

# Observed-vs-assumed analytics:
sqlite3 data/delivery_system.sqlite < analytics/sql/assumption_summary.sql
```

---

## Architecture: source system / transforms / analytics

Phase 20 decomposed the project along the data-engineering lifecycle.
The simulator is now treated like a **source system** that emits raw
operational events. A **transform layer** derives analytical state
(economics, hybrid decisions). **Analytics** (DuckDB, SQL files,
charts, the API and frontend) read from the derived state.

```
┌─────────────────┐   raw events    ┌──────────────────┐   derived state   ┌─────────────────┐
│ core/simulator  │ ──────────────► │  transforms/     │ ────────────────► │ analytics + UI  │
│ (source system) │                 │ (re-computable)  │                   │ (read-only)     │
└─────────────────┘                 └──────────────────┘                   └─────────────────┘
   simulation_runs                   transformation_runs
   (source lineage)                  (derivation lineage)
```

What lives where:

| Layer | Owns | Examples |
|---|---|---|
| `core/simulator.py` | Raw event emission, trip/order/leg row creation, dispatch state, telemetry, maintenance, emergency returns | Writes `delivery_events`, `orders` (intrinsic fields only), `trips`, `trip_legs` |
| `transforms/economics.py` | Distance derivation, energy/maintenance/labour costs, revenue, profit | Updates `trips.estimated_*` columns |
| `transforms/hybrid.py` | Fulfillment-mode decision, activation reason, truck baseline, drone latency estimate | Updates `orders.fulfillment_mode` etc. |
| `analytics/` + `api/` + `frontend/` | Aggregation, BI scoring, calibration drift, charts, workbench UI | Read-only over derived state |

Two key consequences:

1. **Analytical assumptions are recomputable without re-running the
   simulator.** Override `EconomicModel` or `HybridThresholds` and call
   the transform again; events stay untouched.
2. **Lineage is split.** `simulation_runs` tracks *what produced these
   events*. `transformation_runs` tracks *what derivation logic was
   applied to them*. When a calibration number changes between commits,
   you can tell whether the simulator changed or the derivation
   changed.

### Running the pipeline

```bash
# 1. Simulate (transforms auto-run by default).
python run_scenarios.py --reset \
    --scenarios urban_dense suburban_standard rural_extended \
    --trips 100 --seed 42

# 2. (Optional) re-derive with different assumptions, no re-sim needed.
python run_transforms.py --all-runs

# 3. Scope to one transform, one run.
python run_transforms.py --run-id <id> --transform economics
```

### Storage layers — honest framing

| Layer | Role | Required? |
|---|---|---|
| **SQLite** | Operational source of truth + derived state | Yes |
| **Parquet** | Analytical export format for portability | No — optional |
| **DuckDB** | OLAP engine; can read Parquet *or* SQLite directly | Optional |

Phase 20 reframes Parquet as an **export format** rather than a
required persistence layer. DuckDB ships with a `sqlite_scanner`
extension, so the analytics layer can query SQLite without going
through Parquet at all (see `core/duckdb_analytics.open_duckdb_for_sqlite`).
Parquet exports remain useful when you want to ship runs elsewhere or
load them into a real lakehouse — they're just no longer load-bearing.

### Versioned baselines

The "seed=42 must always equal X events forever" invariant has been
replaced with an explicit registry in `tests/baselines.py`. When the
simulator semantics change in a way that shifts event counts on
purpose, bump `SIMULATOR_VERSION` and add a new entry. Tests prefer
*behavioral invariants* (no double-assignment, no NaN economics, drones
faster than trucks on average) over exact counts where appropriate.

---

## Operational telemetry (Phase 21)

The simulator emits the kind of values a real drone flight controller
would surface on its telemetry channel — not a derived "stress score",
not a forecast, just observables. Each `telemetry_ping` event has a
matching row in the new `telemetry_observations` side-table with:

| Field | Units | Plausibility band |
|---|---|---|
| `altitude_m` | metres AGL | 0–120 (Part 107 ceiling) |
| `airspeed_mps` | metres/sec | 0–30 (cruise ~14, sport top ~25) |
| `heading_deg` | degrees | 0–360 |
| `vertical_speed_mps` | metres/sec | ±5 (climb / descent) |
| `battery_temp_c` | °C | 15–60 normal, >45 warm, >55 concerning |
| `motor_temp_c` | °C | 20–80 normal, ~95 thermal limit |
| `estimated_remaining_range_km` | km | controller's own SoC × capacity-fade estimate |
| `signal_strength_pct` | % | 0–100 (RC link) |
| `gps_signal_quality` | 0–100 | synthetic quality score |

Plus a new event type `obstacle_warning` (discrete events stay
discrete) and two slowly-changing drone-level columns
(`battery_cycle_count`, `battery_health_pct`).

**On-board emergency trigger.** Whenever the on-board controller's own
remaining-range estimate falls below the straight-line distance back to
depot × 1.15, the simulator now emits an `emergency_return` with
`payload.reason = "onboard_remaining_range"` and routes back to depot
mid-leg. The previous RNG-driven trigger still exists for "obstacle /
weather / unknown" emergencies.

**Source vs derived.** The observations table is *raw*. Anomaly counts
(battery > 50 °C, motor > 85 °C, signal < 60%, GPS degraded), trends,
and per-scenario summaries are derived by `transforms/telemetry.py`,
which the auto-discovering pipeline runs last (`RUN_ORDER = 30`):

```bash
python run_scenarios.py --reset \
    --scenarios urban_dense suburban_standard rural_extended \
    --trips 100 --seed 42
# transforms (economics → hybrid → telemetry) auto-run.

# Recompute just telemetry with new thresholds, no resim:
python run_transforms.py --all-runs --transform telemetry

# Inspect via API:
curl http://localhost:8000/analytics/telemetry-summary
curl http://localhost:8000/analytics/telemetry-health
```

The frontend's new **Operational telemetry** tab surfaces the signal-
quality metric grid, per-scenario anomaly counts, drone-health table,
and the two new charts.

---

## Delivery-domain reinterpretation (Phase 22)

The economics transform now accepts a **demand-side overlay** — a
`DeliveryDomain` profile that influences revenue without touching any
physics-side field.  The same operational events produce different
economics under different domains.

Layering rule (pinned in `core/delivery_domains.py`):

| Layer | What it owns |
|---|---|
| `Scenario` | operational knobs (battery drain, telemetry density, distance) |
| `EconomicModel` | per-trip unit prices ($/kWh, $/event, base delivery_fee) |
| `delivery_domain` | demand-side characteristics (who orders, what they carry, what they'll pay, how urgent) |
| `scale_model` | (Phase 23) fleet-wide structural costs |

Built-in profiles in `core/delivery_domains.py`:

| Profile | Payload | Urgency | Premium share | AOV (USD) |
|---|---:|---:|---:|---:|
| `food_delivery` | ~0.8 kg | 55% high | 30% | 25 |
| `medical_delivery` | ~0.4 kg | 85% high | 50% | 75 |
| `retail_package` *(default)* | ~2.5 kg | 5% high | 8% | 40 |
| `urgent_documents` | ~0.1 kg | 75% high | 60% | 40 |

### The snapshot table

`trip_economics_snapshots` is new this phase. Multiple recompute passes
(different domains, different EconomicModels) write history rows keyed
by `(trip_id, transform_run_id)`. The `trips.estimated_*` columns
continue to reflect the most-recent recompute, so existing analytics
keep working unchanged; the snapshot table is the durable history that
lets you compare two domains over the same events.

### Example finding

Same operational events (suburban_standard, 10 trips, seed=42),
recomputed under each domain:

```
domain              avg revenue   avg op cost   avg profit
------------------  -----------   -----------   ----------
medical_delivery        25.88        19.59         +6.29
urgent_documents        25.20        19.59         +5.62
food_delivery           21.82        19.59         +2.24
retail_package          20.52        19.59         +0.94
```

`avg op cost` is **identical** across all four domains (the physics is
unchanged); the spread in profit comes entirely from the demand-side
overlay. Medical delivery looks **6.7× more profitable per trip** than
retail under the same physics.

### Recompute commands

```bash
# Same events as before — just a new economics overlay.
python -c "from transforms import economics; \
           economics.run('data/delivery_system.sqlite', \
                         delivery_domain='food_delivery')"

# API exposes the latest snapshot per (scenario, domain) + the profile
# registry.  Read-only.
curl http://localhost:8000/analytics/delivery-domains
```

Phase 23 layers a `scale_model` overlay on top of these snapshots.

---

## Scale-model amortization (Phase 23)

The economics layer says how much a single delivery *costs to fly*; the
scale layer says how much it costs to *operate the platform that flies
it*. Same operational events, new analytical question:

> *Given this run's trips, what would per-delivery economics look like
> if the operating fleet were 5 drones doing 40 deliveries/day — or
> 1000 drones doing 20,000 deliveries/day?*

Four-layer rule (pinned in `core/scale_models.py`):

| Layer | What it owns |
|---|---|
| `Scenario` | operational knobs (battery, telemetry, distance) |
| `EconomicModel` | per-trip unit prices ($/kWh, $/event, base delivery_fee) |
| `delivery_domain` | demand-side (who orders, payload mean, AOV) |
| `scale_model` | fleet-wide structural costs (overhead, staffing, amortization, utilization) |
| `hybrid` | per-order dispatch decisions; **does not see scale** |

### Two-table snapshot architecture

Phase 22's `trip_economics_snapshots` records the per-trip physics +
revenue under one (domain, EconomicModel) pair. Phase 23 adds
`trip_scale_snapshots` joined back via `source_snapshot_run_id`:

```
trip_economics_snapshots  ── source_snapshot_run_id ──►  trip_scale_snapshots
  (trip × domain × model)                                  (× scale_model)
```

The two tables stay separate by design — collapsing them would
conflate two analytical dimensions in one row, and "economics with
scale" vs "economics without scale" would become schema-indistinguishable.
With separate tables the cartesian product `(domain × scale)` over a
trip is just `len(economics_snapshots) × len(scale_snapshots)` rows,
explicit and queryable.

### Counterfactual semantics

`scale_model.fleet_size` and `deliveries_per_day` are
**analytical-only** — they do *not* have to match the simulator's
actual `drone_count` or run length. The recompute asks *"what would
costs look like AT this scale?"* — the simulator's real fleet is
irrelevant to the projection. (Same convention Phase 22 used for
`delivery_domain.payload_kg_mean`.)

### Built-in scale profiles

| Profile | Fleet | Deliveries/day | Daily overhead | Per-trip overhead | Utilization |
|---|---:|---:|---:|---:|---:|
| `pilot_program` *(default)* | 5 | 40 | $1,390 | $34.75 | 0.40 |
| `regional_network` | 25 | 500 | $2,610 | $5.22 | 0.65 |
| `urban_dense_fleet` | 100 | 3,000 | $9,140 | $3.05 | 0.85 |
| `national_scale` | 1,000 | 20,000 | $43,200 | $2.16 | 0.80 |

Daily overhead = fixed platform + charging + software + (operator-headcount × $240/day) + (maintenance-headcount × $280/day). Per-trip overhead = daily overhead ÷ deliveries_per_day.

Note the diminishing return between `urban_dense_fleet` and
`national_scale`: per-trip overhead falls only from $3.05 to $2.16 even
though deliveries-per-day grows ~7×, because platform/software costs
grow with footprint. Utilization also dips slightly at national scale
(0.85 → 0.80) reflecting geographic spread.

### Effective profit formula

```
effective_profit = source.estimated_profit                      # from Phase 22
                 - amortized_overhead_per_trip                  # scale fixed costs
                 + utilization_efficiency
                   * idle_reduction_factor
                   * source.estimated_operational_cost           # utilization rebate
```

The rebate captures *"better utilization recovers wasted operational
spend on idle drones."* Without it, larger fleets would look strictly
worse than smaller ones, which is the wrong story.

### Recompute commands

```bash
# Default pipeline auto-runs economics + scale (pilot_program) + hybrid + telemetry.
python run_transforms.py

# Cross every domain × every scale on the same events:
python run_transforms.py --all-delivery-domains   # 4 economics recomputes
python run_transforms.py --all-scale-models       # 4 scale recomputes per econ snapshot

# Single overlay choices:
python run_transforms.py --delivery-domain food_delivery
python run_transforms.py --scale-model urban_dense_fleet

# API rollup of the latest (scale_model, scenario) snapshots:
curl http://localhost:8000/analytics/scale-models
```

---

## Hybrid logistics augmentation

Earlier phases framed the project as "drones vs. trucks." That framing
was wrong. The current synthetic cost model says broad truck
*replacement* economics are weak — drones are too expensive per
delivery to win on aggregate. But once you let drones be an
*augmentation* layer on top of a truck baseline, the picture changes.

The simulator now asks a different question:

> *When should a delivery system activate drones in addition to its
> truck fleet?*

Every order gets a synthetic profile (payload weight, urgency level,
premium flag, congestion factor, queue pressure) computed from a
*derived* RNG, so existing seeded baselines stay deterministic. A
small rule set in [`core/hybrid.py`](core/hybrid.py) decides each
order's `fulfillment_mode`:

| Mode | Trigger |
|---|---|
| `TRUCK` | < 2 activation signals (default) or heavy_payload (hard disqualifier) |
| `HYBRID` | exactly 2 activation signals (borderline) |
| `DRONE` | ≥ 3 activation signals |

Activation signals: `premium`, `urgent` (high urgency), `light_payload`
(< 2.5 kg), `congestion_bypass` (> 60%), `queue_pressure` (> 65%),
`short_distance` (< 8 km).

Trucks are now modelled with simple batching (`batch_size=5`,
cost ∝ `1/√batch`) and a congestion-driven latency penalty. Drone
latency is `prep + distance / cruise_speed`.

### Headline finding (seed=42, 100 trips × 3 scenarios)

```
trucks_only_avg_latency_min          59.97
drones_only_avg_latency_min          10.67
hybrid_strategy_avg_latency_min      38.80
hybrid_vs_trucks_only_savings_min   +21.17
```

Per-scenario drone-or-hybrid activation (% of orders):

```
urban_dense          45 %   (30 DRONE + 15 HYBRID)
suburban_standard    45 %   (30 DRONE + 15 HYBRID)
rural_extended       32 %   (13 DRONE + 19 HYBRID)
```

The hybrid layer reduces average delivery latency by ~21 minutes
compared with a trucks-only baseline. Rural scenarios get the smallest
boost because long distances and lower congestion mean fewer orders
trip the drone-activation thresholds.

```bash
# After running scenarios:
python -c "
from core.hybrid_analytics import hybrid_summary
import json; print(json.dumps(hybrid_summary('data/delivery_system.sqlite'), indent=2))"

# Or via the API (see Workbench section):
curl http://localhost:8000/analytics/hybrid-summary
curl http://localhost:8000/analytics/latency
curl http://localhost:8000/analytics/activation-reasons
```

What this is **not**: a dispatcher, a routing engine, weather/FAA/traffic
modelling, or any kind of optimization solver. The activation rules are
rule-based and explainable; trucks remain the baseline; drones are
treated as augmentation.

---

## Analytical workbench (FastAPI + React)

A small, local-first UI sits on top of everything else. It is a
read-only view onto the existing SQLite + Parquet store; no new
business logic lives in the UI layer.

```
React (Vite, plain CSS)
     │  fetch /api/*
     ▼
FastAPI thin wrappers  ── core/{runs,validation,business_intelligence,…}
     │
     ▼
SQLite + Parquet + DuckDB  (Phases 1–17)
```

**Backend.** `api/main.py` mounts seven route modules:

| Route | Backed by |
|---|---|
| `GET /runs`, `/runs/{id}`, `/runs/{id}/transforms` | `core/runs.py` + `transformation_runs` table |
| `GET /scenarios`, `/scenarios/summary` | `core/assumptions.py` + `core/business_intelligence.py` + `core/calibration.py` |
| `GET /validation`, `/validation/{run_id}` | `core/validation.py` |
| `GET /business-intelligence`, `/.../{run_id}` | `core/business_intelligence.py` |
| `GET /charts`, `/charts/{name}` | serves PNGs from `outputs/charts/` |
| `GET /analytics/delivery-displacement` | `core/displacement.py` |
| `GET /analytics/hybrid-summary`, `/latency`, `/activation-reasons` | `core/hybrid_analytics.py` |
| `GET /analytics/telemetry-summary`, `/telemetry-health` | telemetry observation tables |
| `GET /analytics/delivery-domains` | `trip_economics_snapshots` × domain registry |
| `GET /analytics/scale-models` | `trip_scale_snapshots` × scale registry |
| `GET /analytics/domain-scale-matrix` | join across both snapshot tables |
| `GET /experiments`, `/experiments/{id}` | `experiment_runs` + `core/experiments.py` |

The DB path is configurable via the `DRONE_API_DB` environment variable
(defaults to `data/delivery_system.sqlite`); the charts directory via
`DRONE_API_CHARTS_DIR` (defaults to `outputs/charts`).

### Workbench walkthrough

The frontend (React + Vite, plain CSS, `react-router-dom` for shareable
URLs) is organised as a narrative path for reviewers, not a tab gallery
over endpoints. Nine primary nav items:

| Page | URL | What it answers |
|---|---|---|
| **Overview** | `/` | What is this project and what's the current thesis? |
| **Main finding** | `/finding` | One-glance answer cards: replacement viability, hybrid latency improvement, best domain, best scale, best (domain × scale) cell, validation status. |
| **Runs** | `/runs` | What simulation runs exist? Click a row to see its transform lineage (flat `transformation_runs` table). |
| **Experiments** | `/experiments` | Named Cartesian sweeps (Phase 24). Click one to see its full (scenario × domain × scale) profile matrix. |
| **Domain & Scale** | `/domain-scale` | Delivery-domain profiles, scale-model profiles, and the domain × scale matrix per scenario. The most reviewer-relevant page. |
| **Hybrid** | `/hybrid` | Trucks-only vs hybrid vs drones-only latency, activation reason histograms, fulfillment split by scenario. |
| **Telemetry** | `/telemetry` | Per-scenario telemetry summaries, anomaly counts, drone-level battery health. |
| **Validation** | `/validation` | Rule-based snapshot validation; ERROR rules sorted first. |
| **Charts** | `/charts` | Pre-rendered PNG artifacts grouped by category. |

Reviewer-suggested reading order: **Overview → Main finding → Domain &
Scale → Hybrid → Validation**. The other pages are evidence stores you
drill into when a finding card raises a question.

Every page that depends on snapshot data shows an empty state with the
exact CLI command needed to populate it — no blank screens.

**Delivery displacement.** The headline analytical view. Each completed
drone delivery (`returned_to_depot` event) is treated as displacing one
truck delivery. With an editable `truck_cost_per_delivery` knob the UI
shows truck baseline cost vs drone operational cost vs the difference,
both in aggregate and per scenario. Synthetic, illustrative — never
forecasting.

```bash
# Terminal 1 — backend
uvicorn api.main:app --reload
# Serves http://localhost:8000 with auto-generated docs at /docs.

# Terminal 2 — frontend
cd frontend
npm install
npm run dev
# Opens http://localhost:5173 with Vite proxying /api/* to :8000.
```

The frontend's production build (`npm run build`) outputs to
`frontend/dist/` (gitignored). Nothing here is hardened for production
hosting; it's a local analytical workbench.

---

## Local analytics architecture

The project keeps three storage/query layers cleanly separated:

| Layer | Role | Where it lives |
|---|---|---|
| **SQLite** | Operational system of record. Every event/trip/order/run is written here first, transactionally. | `data/delivery_system.sqlite` |
| **Parquet** | Portable analytical export. One file per table per run. Same shape lakehouse loaders expect. | `outputs/runs/run_id=<id>/parquet/` |
| **DuckDB** | In-process OLAP engine. Reads Parquet directly via `read_parquet()`; no server, no persistent file. | invoked by `run_duckdb_analytics.py` |

SQLite stays the source of truth. Parquet is what an analyst, a
downstream lakehouse, or DuckDB can consume without reaching back into
the operational store. DuckDB gives you cross-run analytical queries in
plain SQL over those Parquet files.

### Running the full pipeline

```bash
# 1. Simulate three scenarios into SQLite AND export per-run Parquet.
python run_scenarios.py --reset \
    --scenarios urban_dense suburban_standard rural_extended \
    --trips 100 --seed 42 --export-parquet

# 2. Run DuckDB analytics across every per-run parquet directory.
python run_duckdb_analytics.py --all-runs

# 3. Or scope to one run.
python run_duckdb_analytics.py --run-id <id>

# 4. Optional: also write a markdown report.
python run_duckdb_analytics.py --all-runs \
    --markdown outputs/reports/duckdb_summary.md
```

### Parquet output layout

```
outputs/runs/
  run_id=<uuid>/
    parquet/
      delivery_events.parquet
      trips.parquet
      orders.parquet
      simulation_runs.parquet
    events.jsonl          # optional, from Phase 15
```

The `run_id=<uuid>` partition is Hive-style on purpose — downstream
lakehouse loaders (BigQuery external tables, Athena, Iceberg via Trino)
pick it up as a partition key without configuration.

### DuckDB SQL files

`analytics/duckdb/` holds analytical queries written for the DuckDB
engine (some use DuckDB-specific syntax like `GREATEST` / `LEAST`):

| File | What it answers |
|---|---|
| `cross_run_profitability.sql` | Total profit, completion rate, avg profit/trip per run. |
| `event_volume_by_run.sql` | Event counts by type, grouped by run. |
| `maintenance_burden.sql` | Per-run maintenance and emergency rates. |
| `feasibility_rankings.sql` | Same weighted feasibility score as the Python BI layer, recomputed in pure SQL over Parquet. |

The Phase 11 BI ranking (`urban_dense` strong / `suburban_standard`
strong / `rural_extended` borderline at seed=42 / 100 trips) reproduces
exactly from `feasibility_rankings.sql` — confirming that the
SQLite → Parquet → DuckDB path doesn't lose semantics.

---

## Data quality and validation

A small rule-based layer (`core/validation.py`) enforces the simulator's
operational invariants and the cross-layer parity between SQLite,
Parquet and DuckDB. It is **not** a governance framework — it is the
runtime sanity layer that asserts the things the design promises.

| Rule | Severity | What it asserts |
|---|---|---|
| `completed_trip_has_delivery_event` | ERROR | Every `status='completed'` trip has a `delivery_completed` event. |
| `completed_trip_has_returned_to_depot` | ERROR | …and a `returned_to_depot` event. |
| `completed_trip_legs_completed_eq_3` | WARN | Trip projection records all three legs. |
| `maintenance_lifecycle_balance` | WARN | Per `(run_id, drone_id)`, `maintenance_required + emergency_return == maintenance_completed`, with one trailing-open cycle permitted iff the drone's current projection is `maintenance` and this is its most recent run. |
| `maintenance_trailing_open_documented` | INFO | Reports the trailing-open drones (informational). |
| `drone_no_overlapping_trips` | ERROR | No drone has two trips whose flight windows overlap. |
| `run_lineage_delivery_events / trips / orders` | ERROR | Every non-null `run_id` exists in `simulation_runs`. |
| `economics_finite_and_nonnegative_inputs` | ERROR | Terminal trips have finite, non-negative distance/profit/cost. |
| `parquet_row_count_parity` | INFO/WARN | For runs that have Parquet exports, row counts agree with SQLite. |
| `cross_layer_duckdb_profit` | INFO/WARN | DuckDB's per-run `SUM(estimated_profit)` agrees with SQLite within rounding. |

Severity levels are strings (`INFO` / `WARN` / `ERROR`); the CLI exits 1
only when at least one `ERROR` failed.

```bash
python run_validation.py
python run_validation.py --run-id <id>
python run_validation.py --markdown outputs/reports/validation_report.md

# Analyst-side SQL view (per-run violation counts):
sqlite3 data/delivery_system.sqlite < analytics/sql/validation_summary.sql
```

**Known behaviour:** running `run_scenarios.py` with multiple scenarios
against the same SQLite DB can leave the *first* scenario's drone with
a trailing-open maintenance cycle — the next scenario reinitialises
that drone's Python-side state. The validation layer surfaces this as a
WARN under `maintenance_lifecycle_balance` (it is a documented design
trade-off, not a bug). One-shot single-scenario runs validate cleanly.

---

## Experiment tracking

Every call to `run_simulation` records a row in `simulation_runs` and
stamps every event/trip/order it emits with that run's `run_id`. The
result is that any chart, JSONL line, or analytics row can be traced
back to:

- the **seed** and **scenario** that produced it
- the **simulator_version** and **assumption_version** it was built with
- the **git_commit** of the working tree at the time (best-effort)
- the **timestamp** the run was created

This turns the simulator into a small experiment registry — each run is
an analytical experiment, reproducible from `(seed, scenario, code state)`.

```bash
# Run, then list the recorded runs.
python run_scenarios.py --reset \
    --scenarios urban_dense suburban_standard rural_extended \
    --trips 100 --seed 42
python run_history.py --limit 5

# Inspect one run in detail.
python run_history.py --run-id <run-id-prefix>

# SQL view of all runs in the DB.
sqlite3 data/delivery_system.sqlite < analytics/sql/run_summary.sql
```

Per-run JSONL exports land under `outputs/runs/run_id=<id>/events.jsonl`
(Hive-style key=value path, suitable for partitioned lakehouse loaders
later):

```python
from core.sinks import export_run_events_to_jsonl
export_run_events_to_jsonl("data/delivery_system.sqlite", "<run-id>")
```

**What this is.** Lightweight lineage: a `simulation_runs` table, a
`run_id` column on event/trip/order rows, and a small CLI to browse
them. Three short text columns (`simulator_version`, `assumption_version`,
`git_commit`) capture code state without any artifact registry.

**What this is not.** Not an orchestrator, not an MLflow-style metadata
server, not an automatic uploader. Phase 15 is the thin lineage layer
that lets later phases (or a real metadata tool) hook in cleanly.

---

## Calibration drift

Once a scenario run has landed in the DB, the calibration layer asks
the next question: *did the simulator actually do what the scenario
knobs asked it to?* It compares **configured** values from
`core/scenarios.py` against **observed** rates measured from the event
log:

```
drift = observed − configured
```

…labelled as **aligned** (`|drift| < 0.02`), **minor_divergence**
(`< 0.05`), or **significant_divergence** (`>= 0.05`) for
probabilities. Distance gets its own thresholds in km.

> **Calibration ≠ validation.** A low drift means the simulator did
> what its knobs said. It does *not* mean the knobs reflect the real
> world.

The report surfaces structural asymmetries by design — e.g. the
configured `maintenance_chance` is a per-trip RNG roll, but the
simulator *also* fires maintenance when battery drops below 25%, so
the observed maintenance rate is expected to exceed the configured
chance. That kind of drift is informative, not a bug.

Commands:

```bash
python run_calibration_analysis.py --db data/delivery_system.sqlite
python run_calibration_analysis.py --db data/delivery_system.sqlite \
    --markdown outputs/reports/calibration_report.md

# Ad-hoc SQL view:
sqlite3 data/delivery_system.sqlite < analytics/sql/calibration_drift.sql
```

---

## Charts

Static PNG charts can be generated from the SQLite store with matplotlib.
They land in `outputs/charts/` (gitignored) by default.

```bash
python run_simulation.py --reset --drones 3 --trips 10 --seed 42 --export-jsonl data/events.jsonl
python run_visualizations.py --db data/delivery_system.sqlite --out outputs/charts
```

Charts produced:

| File | Content |
|---|---|
| `event_counts.png` | Bar chart of `delivery_events` counts by `event_type`. |
| `trip_outcomes.png` | Bar chart of trips by final status. |
| `drone_utilization.png` | Bar chart of `trips_flown` per drone. |
| `battery_warnings_by_drone.png` | Count of `battery_warning` events per drone. |
| `battery_over_time.png` | Per-drone line plot of `battery_pct` vs `event_time`. |
| `scenario_comparison.png` | Grouped bar chart: warnings, deviations, emergencies, maintenance per scenario. |
| `scenario_profitability.png` | Revenue / operational cost / profit by scenario (synthetic units). |
| `scenario_feasibility_scores.png` | Rule-based feasibility score per scenario with strong/borderline thresholds. |
| `scenario_operational_profile.png` | 2×2 grid: observed completion / emergency / maintenance / avg distance per scenario. |
| `scenario_calibration_drift.png` | Three side-by-side grouped bars: configured vs observed rates for emergency, maintenance, and route deviation. |
| `run_comparison_profit.png` | Total profit per `simulation_runs` row, coloured green/red by sign. |
| `cross_run_profitability.png` | Same data, but sourced from DuckDB → Parquet (with SQLite fallback if no Parquet present). |
| `validation_results.png` | Two-panel chart: passed/failed counts + failures by rule. |
| `delivery_displacement_savings.png` | Per-scenario truck-baseline vs drone-op cost vs the difference. |
| `battery_temperature_by_scenario.png` | Avg + max battery temp per scenario with 45 °C / 55 °C reference lines. |
| `signal_quality_distribution.png` | Histogram of RC signal strength and GPS quality across all telemetry pings. |
| `hybrid_activation_breakdown.png` | Stacked TRUCK / HYBRID / DRONE order counts per scenario. |
| `delivery_latency_by_mode.png` | Three-bar comparison: trucks-only vs drones-only vs hybrid-strategy avg latency. |
| `queue_pressure_vs_drone_activation.png` | Per-decile scatter: queue pressure (X) vs drone-or-hybrid activation rate (Y). |

---

## Design notes

- **Delivery completion vs. operational trip completion.** `delivery_completed`
  marks the moment the package reached the customer — the order is
  `delivered` at that point. The drone is still in flight on its return
  leg, so the trip stays `in_flight` and the drone stays `flying` until
  `returned_to_depot` fires. Analytical questions about customer SLA use
  `delivery_completed`; questions about fleet/drone utilisation use
  `returned_to_depot`.
- **SQLite is the local operational store.** It is the source of truth
  for everything `run_analytics.py` queries. No external service is
  required to run the project.
- **`delivery_events` is append-only.** Rows are never updated or
  deleted. The table is the audit log; analytical questions about the
  *path* a delivery took live here.
- **Projection tables (`orders`, `drones`, `trips`) hold current state.**
  They are updated by `core/projections.py` inside the same transaction
  as the event insert, so the projection is never out of sync with the
  log. They exist so that "what is drone_002 doing right now?" is a
  single primary-key lookup rather than a replay of the event stream.
- **JSONL is the portable export path.** One JSON object per line is the
  shape that S3 + Athena, BigQuery external tables, DuckDB, Iceberg via
  Trino, and Snowflake stages all accept directly. No schema rewrite is
  needed to move from local SQLite to a cloud lakehouse — only an
  ingestion job that reads the JSONL.
- **`payload_json` stays stringified on purpose.** Different events
  carry different fields. Keeping `payload_json` as a single TEXT/STRING
  column means the table schema never has to grow when a new event type
  adds a field. Consumers parse it on read.

---

## Known limitations

- **Synthetic data only.** No real drones, customers, or routing.
- **Round-robin dispatch.** The simulator does not implement realistic
  fleet selection.
- **Simplified dispatch.** A drone in maintenance is now skipped until a
  `maintenance_completed` event lands, but the dispatcher itself is still
  a round-robin over the idle pool — not a real optimizer.
- **No cloud pipeline yet.** Phase 3 stops at portable JSONL on local
  disk.
- **Order/trip semantics on abort.** `emergency_return` maps the order
  to `OrderStatus.ERROR` (no dedicated `aborted` enum value yet) and the
  trip to `aborted`.
- **Legacy pathfinding is preserved but not integrated.** The A* code
  under `legacy/terrain_v1/` does not currently feed the event stream.

---

## Dispatch

When the simulator picks a drone for a new trip it now considers only
drones currently `idle`. Drones in `maintenance` are skipped until their
`maintenance_completed` event fires. If no drone is idle, the simulator
advances its clock to the earliest scheduled maintenance completion,
emits that event, and tries again. Maintenance has a fixed 240-second
cooldown and restores battery to 100%. This is intentionally a
simplified dispatcher, not a real fleet optimizer.

---

## Future work

- Replace round-robin dispatch with something workload-aware
  (e.g. nearest-idle, battery-weighted).
- Add chunked / streaming JSONL export for runs that don't fit in memory.
- Add a small `pytest` suite covering schema setup, `emit()`
  projections, and a single-trip simulator path.
- Add a cloud/lakehouse ingestion path (Iceberg via Trino, S3 + Athena,
  or BigQuery external tables) — the JSONL export is already shaped for it.
- Add a notebook or dashboard layer over the SQL queries.
- Optionally reintegrate the legacy terrain/pathfinding work as a
  route-cost feature feeding `route_deviation` events.

---

## License

See [LICENSE](LICENSE).
