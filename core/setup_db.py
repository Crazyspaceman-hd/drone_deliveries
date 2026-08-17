"""
core/setup_db.py

Creates the local SQLite database used by the simulator.

Two layers:

  Append-only event log
    delivery_events    — every event ever emitted

  Mutable projections (current derived state, maintained by core.projections)
    depots, drones, orders, trips, trip_legs
"""

import os
import sqlite3


DEFAULT_DB_PATH = "data/delivery_system.sqlite"


def _maybe_add_column(cur: "sqlite3.Cursor", table: str, column: str, definition: str) -> None:
    """Add *column* to *table* if it does not already exist.

    SQLite raises ``OperationalError: duplicate column name`` when the
    column is already present, which we treat as a no-op.  This is the
    standard in-place migration pattern for SQLite — no schema-version
    table needed for single-column additions.
    """
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    except sqlite3.OperationalError:
        pass  # column already exists


def create_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialize all tables and indexes.  Idempotent."""
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ── depots ─────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS depots (
            depot_id   TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            lat        REAL,
            lon        REAL,
            is_active  INTEGER DEFAULT 1,
            created_at TIMESTAMP
        )
    """)

    # ── drones ─────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drones (
            drone_id          TEXT PRIMARY KEY,
            depot_id          TEXT NOT NULL,
            model             TEXT,
            speed_mps         REAL,
            range_km          REAL,

            status            TEXT NOT NULL DEFAULT 'idle',
            current_trip_id   TEXT,
            current_leg_id    TEXT,
            current_lat       REAL,
            current_lon       REAL,
            battery_pct       REAL,
            trips_flown       INTEGER NOT NULL DEFAULT 0,
            legs_flown        INTEGER NOT NULL DEFAULT 0,
            last_event_at     TIMESTAMP,
            last_event_id     TEXT,

            -- Phase 21: drone-level (slowly-changing) health metadata.
            -- Update cadence: ``battery_cycle_count`` increments per
            -- ``maintenance_completed`` event; ``battery_health_pct`` decays
            -- slightly each cycle.  Not per-ping telemetry.
            battery_cycle_count  INTEGER NOT NULL DEFAULT 0,
            battery_health_pct   REAL    NOT NULL DEFAULT 100.0
        )
    """)

    # ── orders ─────────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id          TEXT PRIMARY KEY,
            customer_id       TEXT NOT NULL,
            store_name        TEXT NOT NULL,
            pickup_lat        REAL NOT NULL,
            pickup_lon        REAL NOT NULL,
            dropoff_lat       REAL NOT NULL,
            dropoff_lon       REAL NOT NULL,
            depot_id          TEXT NOT NULL,
            created_at        TIMESTAMP NOT NULL,

            status            TEXT NOT NULL DEFAULT 'pending',
            assigned_drone_id TEXT,
            trip_id           TEXT,
            last_event_at     TIMESTAMP,
            last_event_id     TEXT,
            run_id            TEXT,      -- lineage (Phase 15)
            scenario_name     TEXT,      -- denormalized from trips for analytics (Phase 19)

            -- Hybrid logistics characteristics + decision (Phase 19).
            -- All fields are synthetic and deterministic per (seed, trip_idx).
            payload_weight_kg              REAL,
            urgency_level                  TEXT,    -- 'low' | 'medium' | 'high'
            estimated_prep_time_min        REAL,
            promised_delivery_window_min   REAL,
            premium_delivery               INTEGER, -- 0 or 1
            congestion_factor              REAL,    -- 0..1
            queue_pressure                 REAL,    -- 0..1
            fulfillment_mode               TEXT,    -- 'TRUCK' | 'DRONE' | 'HYBRID'
            activation_reason              TEXT,
            truck_baseline_cost            REAL,
            truck_baseline_latency_min     REAL,
            drone_estimated_latency_min    REAL
        )
    """)

    # ── trips ──────────────────────────────────────────────────────────────
    # One trip per delivery attempt.  Trips own legs.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trips (
            trip_id        TEXT PRIMARY KEY,
            drone_id       TEXT NOT NULL,
            order_id       TEXT NOT NULL,
            depot_id       TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'planned',
            launched_at    TIMESTAMP,
            completed_at   TIMESTAMP,
            legs_completed INTEGER NOT NULL DEFAULT 0,
            last_event_at  TIMESTAMP,
            last_event_id  TEXT,
            scenario_name  TEXT,      -- operational scenario this trip belongs to

            -- ── Synthetic economics (populated at end-of-trip; see simulator) ──
            -- These are illustrative numbers for comparative analysis, NOT a
            -- real cost model.  Aborted trips can carry costs without revenue.
            trip_distance_km                  REAL,
            estimated_energy_cost             REAL,
            estimated_maintenance_cost        REAL,
            estimated_operational_cost        REAL,
            estimated_revenue                 REAL,
            estimated_profit                  REAL,
            emergency_return_penalty_applied  REAL,
            run_id                            TEXT       -- lineage (Phase 15)
        )
    """)

    # ── trip_legs ──────────────────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trip_legs (
            leg_id     TEXT PRIMARY KEY,
            trip_id    TEXT NOT NULL,
            leg_index  INTEGER NOT NULL,    -- 1=hub→pickup, 2=pickup→drop, 3=drop→hub
            start_lat  REAL,
            start_lon  REAL,
            end_lat    REAL,
            end_lon    REAL,
            started_at TIMESTAMP,
            ended_at   TIMESTAMP
        )
    """)

    # ── simulation_runs (experiment / lineage registry) ────────────────────
    # Every call to run_simulation() inserts one row here.  Other tables
    # carry a run_id FK so any event/trip/order can be attributed back to a
    # specific experiment (seed + scenario + code state).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS simulation_runs (
            run_id              TEXT PRIMARY KEY,
            created_at          TEXT NOT NULL,   -- UTC ISO-8601 wall clock
            seed                INTEGER,
            scenario_names      TEXT,            -- comma-separated; usually one
            trip_count          INTEGER,
            drone_count         INTEGER,
            notes               TEXT,            -- optional free-text
            git_commit          TEXT,            -- short hash if `git` is available
            assumption_version  TEXT,            -- e.g. 'phase14_calibrated'
            simulator_version   TEXT             -- e.g. 'phase15'
        )
    """)

    # ── experiment_runs (Phase 24: experiment orchestration lineage) ──────────
    # Each row represents one invocation of Experiment.run() — a named
    # sweep of analytical knobs over existing sim-run data.  Experiments
    # are orchestration-only; they never own sim events.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS experiment_runs (
            experiment_run_id  TEXT PRIMARY KEY,
            experiment_name    TEXT NOT NULL,
            definition_json    TEXT NOT NULL,    -- frozen ExperimentDefinition at run time
            status             TEXT NOT NULL,    -- 'pending' | 'running' | 'completed' | 'failed'
            started_at         TEXT,
            completed_at       TEXT,
            error              TEXT
        )
    """)

    # ── transformation_runs (Phase 20: derived-table lineage) ──────────────
    # Each row records one execution of a transform module against one
    # source simulation_runs.run_id.  Lets analytics distinguish "the
    # simulator changed" from "the derivation logic changed."
    # Phase 24: experiment_run_id (nullable FK) links rows produced by
    # an experiment sweep back to the experiment that triggered them.
    # Rows produced by direct transforms/*.run() calls leave it NULL.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transformation_runs (
            transform_run_id    TEXT PRIMARY KEY,
            source_run_id       TEXT,            -- simulation_runs.run_id (FK; NULL = global)
            transform_name      TEXT NOT NULL,   -- 'economics' / 'hybrid' / etc.
            transform_version   TEXT NOT NULL,   -- e.g. 'economics.v1'
            created_at          TEXT NOT NULL,   -- UTC ISO-8601
            parameters_json     TEXT,            -- serialized inputs (EconomicModel/thresholds)
            git_commit          TEXT,            -- short hash; best-effort
            row_count           INTEGER,         -- rows updated/inserted
            notes               TEXT,
            experiment_run_id   TEXT             -- experiment_runs.experiment_run_id (Phase 24)
        )
    """)

    # ── trip_economics_snapshots (Phase 22) ────────────────────────────────
    # Multiple recompute passes of the economics transform write a row here
    # keyed by (trip_id, transform_run_id).  The trips.estimated_* columns
    # continue to reflect the *most recent* recompute; this table is the
    # history that lets analysts compare two domains over the same events.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trip_economics_snapshots (
            trip_id                          TEXT NOT NULL,
            transform_run_id                 TEXT NOT NULL,
            domain_name                      TEXT,
            trip_distance_km                 REAL,
            estimated_energy_cost            REAL,
            estimated_maintenance_cost       REAL,
            estimated_operational_cost       REAL,
            estimated_revenue                REAL,
            estimated_profit                 REAL,
            emergency_return_penalty_applied REAL,
            created_at                       TEXT NOT NULL,
            PRIMARY KEY (trip_id, transform_run_id)
        )
    """)

    # ── trip_scale_snapshots (Phase 23) ────────────────────────────────────
    # Parallel table to trip_economics_snapshots: each row reinterprets ONE
    # economics snapshot under a fleet-scale overlay (amortized overhead +
    # utilization rebate).  Joins back to the economics row via
    # ``source_snapshot_run_id``.  Two scale_models against the same
    # economics snapshot are two distinct rows; the cartesian product of
    # (domain × scale) is explicit in the data, not collapsed by schema.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS trip_scale_snapshots (
            trip_id                       TEXT NOT NULL,
            transform_run_id              TEXT NOT NULL,
            source_snapshot_run_id        TEXT NOT NULL,
            scale_model_name              TEXT NOT NULL,
            amortized_overhead_per_trip   REAL,
            effective_profit              REAL,
            utilization_efficiency        REAL,
            created_at                    TEXT NOT NULL,
            PRIMARY KEY (trip_id, transform_run_id)
        )
    """)

    # ── delivery_events (append-only log) ──────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS delivery_events (
            event_id     TEXT PRIMARY KEY,
            event_time   TIMESTAMP NOT NULL,
            ingested_at  TIMESTAMP NOT NULL,

            drone_id     TEXT,
            trip_id      TEXT,
            leg_id       TEXT,

            event_type   TEXT NOT NULL,

            latitude     REAL,
            longitude    REAL,
            battery_pct  REAL,

            payload_json TEXT,

            scenario_name TEXT,      -- operational scenario this event belongs to
            run_id        TEXT       -- simulation_runs.run_id (lineage; Phase 15)
        )
    """)

    # ── telemetry_observations (Phase 21 — raw drone-side observables) ─────
    # One row per telemetry_ping event.  Kept out of delivery_events so the
    # event log itself stays narrow (the prior phases warned against widening
    # it for ping-only fields).  Joins on event_id.
    #
    # Plausibility ranges (broad consumer-class drone) used during generation:
    #   altitude_m        0–120  (Part 107-style ceiling)
    #   airspeed_mps      0–30   (~14 m/s cruise; 30 m/s sport top)
    #   heading_deg       0–360
    #   vertical_speed_mps  -5..+5 (positive = climb)
    #   battery_temp_c    15–60  (operating envelope per public LiPo guidance)
    #   motor_temp_c      20–95  (BLDC typical operating + thermal limit)
    #   estimated_remaining_range_km  derived from battery and range
    #   signal_strength_pct  0–100  (RC link)
    #   gps_signal_quality   0–100  (synthetic quality score)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS telemetry_observations (
            event_id                       TEXT PRIMARY KEY,
            altitude_m                     REAL,
            airspeed_mps                   REAL,
            heading_deg                    REAL,
            vertical_speed_mps             REAL,
            battery_temp_c                 REAL,
            motor_temp_c                   REAL,
            estimated_remaining_range_km   REAL,
            signal_strength_pct            REAL,
            gps_signal_quality             REAL
        )
    """)

    # Indexes the analytics queries lean on.
    for stmt in [
        "CREATE INDEX IF NOT EXISTS idx_de_type     ON delivery_events (event_type)",
        "CREATE INDEX IF NOT EXISTS idx_de_drone    ON delivery_events (drone_id)",
        "CREATE INDEX IF NOT EXISTS idx_de_trip     ON delivery_events (trip_id)",
        "CREATE INDEX IF NOT EXISTS idx_de_time     ON delivery_events (event_time)",
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status)",
        "CREATE INDEX IF NOT EXISTS idx_drones_status ON drones (status)",
        "CREATE INDEX IF NOT EXISTS idx_trips_status  ON trips  (status)",
        "CREATE INDEX IF NOT EXISTS idx_legs_trip     ON trip_legs (trip_id)",
        "CREATE INDEX IF NOT EXISTS idx_de_scenario   ON delivery_events (scenario_name)",
        "CREATE INDEX IF NOT EXISTS idx_trips_scenario ON trips (scenario_name)",
        "CREATE INDEX IF NOT EXISTS idx_de_run        ON delivery_events (run_id)",
        "CREATE INDEX IF NOT EXISTS idx_trips_run     ON trips (run_id)",
        "CREATE INDEX IF NOT EXISTS idx_orders_run    ON orders (run_id)",
        "CREATE INDEX IF NOT EXISTS idx_orders_mode   ON orders (fulfillment_mode)",
        "CREATE INDEX IF NOT EXISTS idx_tx_source     ON transformation_runs (source_run_id)",
        "CREATE INDEX IF NOT EXISTS idx_tx_name       ON transformation_runs (transform_name)",
        # "give me the latest snapshot for this trip" / domain queries
        "CREATE INDEX IF NOT EXISTS idx_snap_trip_created ON trip_economics_snapshots (trip_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_snap_domain   ON trip_economics_snapshots (domain_name)",
        # Phase 23 scale snapshots
        "CREATE INDEX IF NOT EXISTS idx_scale_snap_trip_created ON trip_scale_snapshots (trip_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_scale_snap_model        ON trip_scale_snapshots (scale_model_name)",
        "CREATE INDEX IF NOT EXISTS idx_scale_snap_source       ON trip_scale_snapshots (source_snapshot_run_id)",
        # Phase 24: fast lookup of all transform rows that belong to an experiment.
        "CREATE INDEX IF NOT EXISTS idx_tx_experiment ON transformation_runs (experiment_run_id)",
        "CREATE INDEX IF NOT EXISTS idx_exp_name      ON experiment_runs (experiment_name)",
    ]:
        cur.execute(stmt)

    # ── In-place migration for existing databases ──────────────────────────
    # CREATE TABLE IF NOT EXISTS won't update tables that already exist; we
    # need ALTER TABLE ADD COLUMN for any column added *after* a table's
    # initial introduction.  _maybe_add_column swallows the
    # OperationalError SQLite raises when the column already exists, so
    # every call below is idempotent.
    #
    # Add a new entry here every time a column is added to a pre-existing
    # table.  Pure new tables (CREATE TABLE IF NOT EXISTS above) need no
    # entry — those are migrated automatically.
    _maybe_add_column(cur, "transformation_runs", "experiment_run_id",   "TEXT")
    # Phase 21: drone-level health metadata bolted onto the existing drones
    # table.  Missing these on a pre-Phase-21 DB makes
    # /analytics/telemetry-health 500 with `no such column`.
    _maybe_add_column(cur, "drones", "battery_cycle_count", "INTEGER NOT NULL DEFAULT 0")
    _maybe_add_column(cur, "drones", "battery_health_pct",  "REAL    NOT NULL DEFAULT 100.0")

    conn.commit()
    conn.close()
    print(f"Database ready: {db_path}")


if __name__ == "__main__":
    create_db()
