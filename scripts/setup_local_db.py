import sqlite3
import os
from datetime import datetime

def create_db(db_path="data/delivery_system.sqlite"):
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Depots table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS depots (
            depot_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            lat REAL,
            lon REAL,
            is_active BOOLEAN,
            created_at TIMESTAMP
        )
    """)

    # Orders table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            customer_id TEXT,
            store_name TEXT,
            pickup_lat REAL,
            pickup_lon REAL,
            dropoff_lat REAL,
            dropoff_lon REAL,
            depot_id TEXT,
            created_at TIMESTAMP,
            status TEXT
        )
    """)

    # (Optional) Drones table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS drones (
            drone_id TEXT PRIMARY KEY,
            depot_id TEXT,
            status TEXT,
            last_heartbeat TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print("✅ SQLite database initialized at:", db_path)

if __name__ == "__main__":
    create_db()
