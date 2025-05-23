import sqlite3
import uuid
from datetime import datetime

DB_PATH = "data/delivery_system.sqlite"

def insert_order(customer_id, store_name, pickup_lat, pickup_lon, dropoff_lat, dropoff_lon, depot_id="depot-001"):
    order_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()
    status = "pending"

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO orders (
            order_id, customer_id, store_name,
            pickup_lat, pickup_lon,
            dropoff_lat, dropoff_lon,
            depot_id, created_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        order_id, customer_id, store_name,
        pickup_lat, pickup_lon,
        dropoff_lat, dropoff_lon,
        depot_id, created_at, status
    ))

    conn.commit()
    conn.close()
    print(f"✅ Order {order_id} created for {customer_id}")
    return order_id


def fetch_pending_orders():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT order_id, customer_id, store_name,
               pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
               depot_id, created_at, status
        FROM orders
        WHERE status = 'pending'
    """)

    rows = cur.fetchall()
    conn.close()
    return rows

def mark_order_delivered(order_id):
    conn = sqlite3.connect("data/delivery_system.sqlite")
    cur = conn.cursor()
    cur.execute("""
        UPDATE orders
        SET status = 'delivered'
        WHERE order_id = ?
    """, (order_id,))
    conn.commit()
    conn.close()
    print(f"✅ Order {order_id} marked as delivered.")


# Example usage (for testing)
if __name__ == "__main__":
    # Fake customer order
    insert_order(
        customer_id="C001",
        store_name="Powell's City of Books",
        pickup_lat=45.5231,
        pickup_lon=-122.6819,
        dropoff_lat=45.5351,
        dropoff_lon=-122.6210
    )

    print("=== Pending Orders ===")
    for row in fetch_pending_orders():
        print(row)
