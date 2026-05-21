"""
core/order_manager.py

Create and query delivery orders.

create_order() emits an `order_created` event in the same transaction as the
orders-row INSERT.  Because order_created carries no trip context, the order
projection's INSERT defaults serve as the initial state and the event row is
the audit trail.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.events import EVT_ORDER_CREATED
from core.models import DeliveryEvent, OrderStatus
from core.projections import _insert_event_row

DEFAULT_DB_PATH = "data/delivery_system.sqlite"


def create_order(
    customer_id: str,
    store_name: str,
    pickup_lat: float,
    pickup_lon: float,
    dropoff_lat: float,
    dropoff_lon: float,
    depot_id: str = "depot-001",
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """Insert one order row and append an order_created event atomically."""
    order_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    payload = DeliveryEvent.encode_payload({
        "order_id":   order_id,
        "customer_id": customer_id,
        "store_name":  store_name,
    })
    event = DeliveryEvent(
        event_type=EVT_ORDER_CREATED,
        payload_json=payload,
    )

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (
                order_id, customer_id, store_name,
                pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
                depot_id, created_at, status,
                last_event_at, last_event_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id, customer_id, store_name,
                pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
                depot_id, created_at, OrderStatus.PENDING,
                event.event_time, event.event_id,
            ),
        )
        _insert_event_row(cur, event)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return order_id


def fetch_order(order_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def fetch_orders_by_status(status: str, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM orders WHERE status = ? ORDER BY created_at ASC",
            (status,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def fetch_pending_orders(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    return fetch_orders_by_status(OrderStatus.PENDING, db_path)
