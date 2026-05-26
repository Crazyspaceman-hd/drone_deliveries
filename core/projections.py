"""
core/projections.py

Cursor-level writers that maintain the projection tables (orders, drones,
trips) in lock-step with the delivery_events log.

All functions accept an open sqlite3.Cursor.  The caller (events.emit or
order_manager.create_order) owns the connection and commit.  This lets the
event INSERT and every projection UPDATE share a single transaction.

Visibility: leading underscore — internal use only.
"""

import sqlite3
from typing import Optional

from core.models import DeliveryEvent, DroneStatus, OrderStatus, TripStatus


# ─────────────────────────────────────────────────────────────────────────────
# Event log writer
# ─────────────────────────────────────────────────────────────────────────────

def _insert_event_row(cur: sqlite3.Cursor, event: DeliveryEvent) -> None:
    cur.execute(
        """
        INSERT INTO delivery_events (
            event_id, event_time, ingested_at,
            drone_id, trip_id, leg_id, event_type,
            latitude, longitude, battery_pct, payload_json,
            scenario_name, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id, event.event_time, event.ingested_at,
            event.drone_id, event.trip_id, event.leg_id, event.event_type,
            event.latitude, event.longitude, event.battery_pct,
            event.payload_json,
            event.scenario_name, event.run_id,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Order projection
# ─────────────────────────────────────────────────────────────────────────────

def _apply_order_projection(cur: sqlite3.Cursor, event: DeliveryEvent) -> None:
    """Update orders row based on the event.

    Order_id is not a direct column on DeliveryEvent in this schema — we
    look it up from the trips table when trip_id is present.
    """
    from core.events import (
        EVT_DRONE_ASSIGNED,
        EVT_DELIVERY_COMPLETED,
        EVT_EMERGENCY_RETURN,
        EVT_ERROR,
        EVT_DRONE_LAUNCHED,
    )

    # Resolve order_id from trip_id when needed.
    order_id = None
    if event.trip_id is not None:
        row = cur.execute(
            "SELECT order_id FROM trips WHERE trip_id = ?", (event.trip_id,)
        ).fetchone()
        if row:
            order_id = row[0]

    if order_id is None:
        return

    t = event.event_type
    if t == EVT_DRONE_ASSIGNED:
        cur.execute(
            """
            UPDATE orders
               SET status            = ?,
                   assigned_drone_id = ?,
                   trip_id           = ?,
                   last_event_at     = ?,
                   last_event_id     = ?
             WHERE order_id = ?
            """,
            (OrderStatus.ASSIGNED, event.drone_id, event.trip_id,
             event.event_time, event.event_id, order_id),
        )
    elif t == EVT_DRONE_LAUNCHED:
        cur.execute(
            """
            UPDATE orders
               SET status        = ?,
                   last_event_at = ?,
                   last_event_id = ?
             WHERE order_id = ?
            """,
            (OrderStatus.IN_FLIGHT, event.event_time, event.event_id, order_id),
        )
    elif t == EVT_DELIVERY_COMPLETED:
        cur.execute(
            """
            UPDATE orders
               SET status        = ?,
                   last_event_at = ?,
                   last_event_id = ?
             WHERE order_id = ?
            """,
            (OrderStatus.DELIVERED, event.event_time, event.event_id, order_id),
        )
    elif t in (EVT_ERROR, EVT_EMERGENCY_RETURN):
        # OrderStatus has no dedicated "aborted" value; mapping
        # emergency_return to ERROR keeps the projection schema unchanged.
        cur.execute(
            """
            UPDATE orders
               SET status        = ?,
                   last_event_at = ?,
                   last_event_id = ?
             WHERE order_id = ?
            """,
            (OrderStatus.ERROR, event.event_time, event.event_id, order_id),
        )
    else:
        cur.execute(
            """
            UPDATE orders
               SET last_event_at = ?,
                   last_event_id = ?
             WHERE order_id = ?
            """,
            (event.event_time, event.event_id, order_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Drone projection
# ─────────────────────────────────────────────────────────────────────────────

def _apply_drone_projection(cur: sqlite3.Cursor, event: DeliveryEvent) -> None:
    if event.drone_id is None:
        return

    from core.events import (
        EVT_DRONE_ASSIGNED,
        EVT_DRONE_LAUNCHED,
        EVT_DELIVERY_COMPLETED,
        EVT_RETURNED_TO_DEPOT,
        EVT_EMERGENCY_RETURN,
        EVT_TELEMETRY_PING,
        EVT_PICKUP_COMPLETED,
        EVT_MAINTENANCE_REQUIRED,
        EVT_MAINTENANCE_COMPLETED,
        EVT_ERROR,
    )

    t = event.event_type
    common_pos = (
        "current_lat  = COALESCE(?, current_lat), "
        "current_lon  = COALESCE(?, current_lon), "
        "battery_pct  = COALESCE(?, battery_pct), "
    )

    if t == EVT_DRONE_ASSIGNED:
        cur.execute(
            f"""
            UPDATE drones
               SET status          = ?,
                   current_trip_id = ?,
                   {common_pos}
                   last_event_at   = ?,
                   last_event_id   = ?
             WHERE drone_id = ?
            """,
            (DroneStatus.ASSIGNED, event.trip_id,
             event.latitude, event.longitude, event.battery_pct,
             event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_DRONE_LAUNCHED:
        cur.execute(
            f"""
            UPDATE drones
               SET status         = ?,
                   current_leg_id = ?,
                   {common_pos}
                   last_event_at  = ?,
                   last_event_id  = ?
             WHERE drone_id = ?
            """,
            (DroneStatus.FLYING, event.leg_id,
             event.latitude, event.longitude, event.battery_pct,
             event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_TELEMETRY_PING:
        cur.execute(
            f"""
            UPDATE drones
               SET {common_pos}
                   last_event_at = ?,
                   last_event_id = ?
             WHERE drone_id = ?
            """,
            (event.latitude, event.longitude, event.battery_pct,
             event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_PICKUP_COMPLETED:
        cur.execute(
            f"""
            UPDATE drones
               SET {common_pos}
                   last_event_at = ?,
                   last_event_id = ?
             WHERE drone_id = ?
            """,
            (event.latitude, event.longitude, event.battery_pct,
             event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_DELIVERY_COMPLETED:
        # Package was delivered to the customer, but the operational trip is
        # not finished — the drone still has to fly back to the depot.  Keep
        # the drone airborne (status unchanged) and just record the new
        # position / battery sample.
        cur.execute(
            f"""
            UPDATE drones
               SET {common_pos}
                   last_event_at   = ?,
                   last_event_id   = ?
             WHERE drone_id = ?
            """,
            (event.latitude, event.longitude, event.battery_pct,
             event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_RETURNED_TO_DEPOT:
        # Operational trip complete.  Drone is back at depot, idle, with the
        # trip counter incremented.
        cur.execute(
            f"""
            UPDATE drones
               SET status          = ?,
                   current_trip_id = NULL,
                   current_leg_id  = NULL,
                   trips_flown     = trips_flown + 1,
                   {common_pos}
                   last_event_at   = ?,
                   last_event_id   = ?
             WHERE drone_id = ?
            """,
            (DroneStatus.IDLE,
             event.latitude, event.longitude, event.battery_pct,
             event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_EMERGENCY_RETURN:
        # Drone is no longer airborne after an emergency return.  Decide
        # between MAINTENANCE and IDLE based on remaining battery or any
        # reason hint in the payload.  Position/battery come from the
        # event itself when present (COALESCE keeps prior values otherwise).
        p = event.payload() or {}
        reason = str(p.get("reason", "")).lower()
        needs_service = (
            (event.battery_pct is not None and event.battery_pct < 30.0)
            or "battery" in reason
            or "fault"   in reason
            or "obstacle" in reason
        )
        new_status = DroneStatus.MAINTENANCE if needs_service else DroneStatus.IDLE
        cur.execute(
            f"""
            UPDATE drones
               SET status          = ?,
                   current_trip_id = NULL,
                   current_leg_id  = NULL,
                   {common_pos}
                   last_event_at   = ?,
                   last_event_id   = ?
             WHERE drone_id = ?
            """,
            (new_status,
             event.latitude, event.longitude, event.battery_pct,
             event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_MAINTENANCE_REQUIRED:
        cur.execute(
            """
            UPDATE drones
               SET status        = ?,
                   last_event_at = ?,
                   last_event_id = ?
             WHERE drone_id = ?
            """,
            (DroneStatus.MAINTENANCE, event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_MAINTENANCE_COMPLETED:
        # Service finished.  Drone returns to idle and clears any stale
        # trip/leg references.  Battery may be restored if the event
        # carries a new value (COALESCE preserves it otherwise).
        cur.execute(
            f"""
            UPDATE drones
               SET status          = ?,
                   current_trip_id = NULL,
                   current_leg_id  = NULL,
                   {common_pos}
                   last_event_at   = ?,
                   last_event_id   = ?
             WHERE drone_id = ?
            """,
            (DroneStatus.IDLE,
             event.latitude, event.longitude, event.battery_pct,
             event.event_time, event.event_id, event.drone_id),
        )
    elif t == EVT_ERROR:
        cur.execute(
            """
            UPDATE drones
               SET status        = ?,
                   last_event_at = ?,
                   last_event_id = ?
             WHERE drone_id = ?
            """,
            (DroneStatus.ERROR, event.event_time, event.event_id, event.drone_id),
        )
    else:
        cur.execute(
            """
            UPDATE drones
               SET last_event_at = ?,
                   last_event_id = ?
             WHERE drone_id = ?
            """,
            (event.event_time, event.event_id, event.drone_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Trip projection
# ─────────────────────────────────────────────────────────────────────────────

def _apply_trip_projection(cur: sqlite3.Cursor, event: DeliveryEvent) -> None:
    if event.trip_id is None:
        return

    from core.events import (
        EVT_DRONE_LAUNCHED,
        EVT_DELIVERY_COMPLETED,
        EVT_RETURNED_TO_DEPOT,
        EVT_EMERGENCY_RETURN,
        EVT_PICKUP_COMPLETED,
        EVT_ERROR,
    )

    t = event.event_type
    if t == EVT_DRONE_LAUNCHED:
        cur.execute(
            """
            UPDATE trips
               SET status        = ?,
                   launched_at   = COALESCE(launched_at, ?),
                   last_event_at = ?,
                   last_event_id = ?
             WHERE trip_id = ?
            """,
            (TripStatus.IN_FLIGHT, event.event_time,
             event.event_time, event.event_id, event.trip_id),
        )
    elif t == EVT_PICKUP_COMPLETED:
        cur.execute(
            """
            UPDATE trips
               SET legs_completed = legs_completed + 1,
                   last_event_at  = ?,
                   last_event_id  = ?
             WHERE trip_id = ?
            """,
            (event.event_time, event.event_id, event.trip_id),
        )
    elif t == EVT_DELIVERY_COMPLETED:
        # Customer delivery is done, but the operational trip isn't finished
        # until the drone returns to depot.  Increment legs_completed and
        # keep status = in_flight.
        cur.execute(
            """
            UPDATE trips
               SET legs_completed = legs_completed + 1,
                   last_event_at  = ?,
                   last_event_id  = ?
             WHERE trip_id = ?
            """,
            (event.event_time, event.event_id, event.trip_id),
        )
    elif t == EVT_RETURNED_TO_DEPOT:
        # Leg 3 (dropoff → depot) finished.  Mark the trip completed.
        cur.execute(
            """
            UPDATE trips
               SET status         = ?,
                   completed_at   = ?,
                   legs_completed = legs_completed + 1,
                   last_event_at  = ?,
                   last_event_id  = ?
             WHERE trip_id = ?
            """,
            (TripStatus.COMPLETED, event.event_time,
             event.event_time, event.event_id, event.trip_id),
        )
    elif t in (EVT_EMERGENCY_RETURN, EVT_ERROR):
        cur.execute(
            """
            UPDATE trips
               SET status        = ?,
                   completed_at  = ?,
                   last_event_at = ?,
                   last_event_id = ?
             WHERE trip_id = ?
            """,
            (TripStatus.ABORTED, event.event_time,
             event.event_time, event.event_id, event.trip_id),
        )
    else:
        cur.execute(
            """
            UPDATE trips
               SET last_event_at = ?,
                   last_event_id = ?
             WHERE trip_id = ?
            """,
            (event.event_time, event.event_id, event.trip_id),
        )
