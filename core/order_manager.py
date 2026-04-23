"""
core/order_manager.py

CRUD operations for the orders table.

All functions accept an explicit db_path argument so they work regardless of
the caller's working directory.  The module-level DEFAULT_DB_PATH is used when
no path is passed — callers should override it for tests.
"""

import sqlite3
import uuid
from datetime import datetime, timezone

DEFAULT_DB_PATH = "data/delivery_system.sqlite"


def insert_order(
    customer_id: str,
    store_name: str,
    pickup_lat: float,
    pickup_lon: float,
    dropoff_lat: float,
    dropoff_lon: float,
    depot_id: str = "depot-001",
    db_path: str = DEFAULT_DB_PATH,
) -> str:
    """
    Insert a new order row and return its generated order_id.

    Status is always 'pending' on creation.  The order lifecycle
    (pending → delivered / error) is tracked in delivery_events;
    the status column here is a convenience denormalization.
    """
    order_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders (
                order_id, customer_id, store_name,
                pickup_lat, pickup_lon,
                dropoff_lat, dropoff_lon,
                depot_id, created_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id, customer_id, store_name,
                pickup_lat, pickup_lon,
                dropoff_lat, dropoff_lon,
                depot_id, created_at, "pending",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    print(f"Order {order_id} created for {customer_id}")
    return order_id


def fetch_pending_orders(db_path: str = DEFAULT_DB_PATH) -> list:
    """Return all orders where status = 'pending'."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT order_id, customer_id, store_name,
                   pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
                   depot_id, created_at, status
            FROM   orders
            WHERE  status = 'pending'
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return rows


def mark_order_delivered(order_id: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """
    Update the convenience status column to 'delivered'.

    The canonical delivery record is the delivery_confirmed event in
    delivery_events; this update keeps the orders table queryable by status
    without joining the event log every time.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE orders SET status = 'delivered' WHERE order_id = ?",
            (order_id,),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"Order {order_id} marked as delivered.")


if __name__ == "__main__":
    insert_order(
        customer_id="C001",
        store_name="Powell's City of Books",
        pickup_lat=45.5231,
        pickup_lon=-122.6819,
        dropoff_lat=45.5351,
        dropoff_lon=-122.6210,
    )
    print("=== Pending Orders ===")
    for row in fetch_pending_orders():
        print(row)
