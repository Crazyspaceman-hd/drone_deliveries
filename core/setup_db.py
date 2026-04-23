"""
core/setup_db.py

Initializes the local SQLite database used as the operational data store for
the drone delivery simulation.

Design principle: every meaningful thing that happens in the system is written
to delivery_events as an immutable append-only record.  Derived state (order
status, drone location, etc.) is computed from the event log rather than
mutated in place.  This mirrors how real-world operational systems are built
on top of event streams (Kafka, Iceberg, etc.) and makes the local SQLite
layer a faithful stand-in during development.
"""

import sqlite3
import os


# ---------------------------------------------------------------------------
# Default path — callers may override by passing db_path explicitly.
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = "data/delivery_system.sqlite"


def create_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Create all tables if they do not already exist.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS throughout
    so re-running never destroys existing data.
    """
    # Ensure the parent directory exists before SQLite tries to open the file.
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # ------------------------------------------------------------------
    # depots — physical locations where drones are stored and recharged.
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS depots (
            depot_id   TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            lat        REAL,
            lon        REAL,
            is_active  BOOLEAN,
            created_at TIMESTAMP
        )
    """)

    # ------------------------------------------------------------------
    # orders — one row per customer delivery request.
    #
    # status is intentionally kept here as a convenience column.
    # The canonical truth about an order's lifecycle lives in delivery_events.
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id    TEXT PRIMARY KEY,
            customer_id TEXT,
            store_name  TEXT,
            pickup_lat  REAL,
            pickup_lon  REAL,
            dropoff_lat REAL,
            dropoff_lon REAL,
            depot_id    TEXT,
            created_at  TIMESTAMP,
            status      TEXT
        )
    """)

    # ------------------------------------------------------------------
    # drones — fleet registry.  last_heartbeat is updated by the simulator
    # to show liveness; it is NOT the source of truth for position.
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drones (
            drone_id        TEXT PRIMARY KEY,
            depot_id        TEXT,
            status          TEXT,
            last_heartbeat  TIMESTAMP
        )
    """)

    # ------------------------------------------------------------------
    # delivery_events — THE central append-only event log.
    #
    # Every state transition in the system (order created, drone assigned,
    # leg started, leg completed, delivery confirmed, error encountered) is
    # written here as a new row.  Rows are never updated or deleted.
    #
    # This is the v2 data spine.  Analytics, dashboards, and derived tables
    # should query this table rather than reading mutable status columns.
    #
    # Column notes:
    #   event_id    — UUID, globally unique identifier for this event.
    #   event_type  — machine-readable verb:
    #                   order_created | drone_assigned | leg_started |
    #                   leg_completed | delivery_confirmed | error
    #   order_id    — FK to orders; NULL for system-level events.
    #   drone_id    — FK to drones; NULL when no drone is involved yet.
    #   leg_number  — 1 (hub→pickup), 2 (pickup→dropoff), 3 (dropoff→hub).
    #                 NULL for non-flight events.
    #   payload_json — arbitrary JSON blob for event-specific details
    #                  (coordinates, cost, duration, error message, etc.).
    #                  Keeping extra data in JSON avoids ALTER TABLE churn
    #                  as the schema evolves.
    #   occurred_at — UTC timestamp when the event happened in the simulation.
    #   recorded_at — UTC timestamp when this row was inserted; useful for
    #                 detecting processing lag.
    # ------------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS delivery_events (
            event_id      TEXT PRIMARY KEY,
            event_type    TEXT NOT NULL,
            order_id      TEXT,
            drone_id      TEXT,
            leg_number    INTEGER,
            payload_json  TEXT,
            occurred_at   TIMESTAMP NOT NULL,
            recorded_at   TIMESTAMP DEFAULT (datetime('now'))
        )
    """)

    # Index on event_type so analytics queries that filter by event kind
    # (e.g. "all leg_completed events this hour") stay fast even as the
    # table grows into the millions of rows.
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_events_type
            ON delivery_events (event_type)
    """)

    # Index on order_id for efficient per-order event history lookups.
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_delivery_events_order
            ON delivery_events (order_id)
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at: {db_path}")


if __name__ == "__main__":
    create_db()
