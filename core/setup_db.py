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


def create_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Initialise all tables and indexes.  Idempotent."""
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
            last_event_id     TEXT
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
            last_event_id     TEXT
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
            last_event_id  TEXT
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

            payload_json TEXT
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
    ]:
        cur.execute(stmt)

    conn.commit()
    conn.close()
    print(f"Database ready: {db_path}")


if __name__ == "__main__":
    create_db()
