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
| `delivery_completed` | Drone delivered the package (end of leg 2). |
| `battery_warning` | Battery dropped below a threshold mid-flight. |
| `route_deviation` | Drone deviated from the expected route. |
| `emergency_return` | Trip aborted; drone returned to depot. |
| `maintenance_required` | Drone flagged for service between trips. |
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
  trips_completed:  9
  events_written:   172
  event_counts_by_type:
    battery_warning             7
    delivery_completed          9
    drone_assigned             10
    drone_launched             10
    emergency_return            1
    maintenance_required        3
    order_created              10
    pickup_completed           10
    route_deviation             9
    telemetry_ping            103
  jsonl_export:     data/events.jsonl (172 rows)
```

One trip was aborted via `emergency_return`; the related order ends up
with `status = 'error'` (see Known limitations).

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

## Design notes

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
- **No maintenance gate.** A drone flagged `maintenance` will still be
  picked on the next round-robin tick; the event log records the flag
  but dispatch does not honor it.
- **No cloud pipeline yet.** Phase 3 stops at portable JSONL on local
  disk.
- **No return-to-depot leg event.** The simulator models trips as
  depot → pickup → dropoff and stops there. As a result `trips.legs_completed`
  caps at 2 for completed trips even though `trip_legs` defines three legs.
- **Order/trip semantics on abort.** `emergency_return` maps the order
  to `OrderStatus.ERROR` (no dedicated `aborted` enum value yet) and the
  trip to `aborted`.
- **Legacy pathfinding is preserved but not integrated.** The A* code
  under `legacy/terrain_v1/` does not currently feed the event stream.

---

## Future work

- Add maintenance-aware dispatch so drones flagged for service are not
  reassigned until cleared.
- Add a `return_to_depot_completed` event so trip-leg-3 has its own
  milestone and `legs_completed` reaches 3.
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
