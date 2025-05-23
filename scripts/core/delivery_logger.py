import uuid
from datetime import datetime
from trino.dbapi import connect

def insert_delivery_leg(
    drone_id,
    leg_type,
    start_lat,
    start_lon,
    end_lat,
    end_lon,
    cost,
    path_length,
    duration_seconds,
    flight_id=None,
    trino_config=None
):
    if not flight_id:
        flight_id = str(uuid.uuid4())

    timestamp = datetime.utcnow()
    log_date = timestamp.date()

    if not trino_config:
        from config.trino_config import TRINO_CONFIG
        trino_config = TRINO_CONFIG

    conn = connect(**trino_config)
    cursor = conn.cursor()

    insert_query = f"""
        INSERT INTO {trino_config['catalog']}.{trino_config['schema']}.delivery_logs (
            flight_id, drone_id, leg_type,
            start_lat, start_lon, end_lat, end_lon,
            cost, path_length, duration_seconds,
            timestamp, log_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    cursor.execute(insert_query, (
        flight_id, drone_id, leg_type,
        start_lat, start_lon, end_lat, end_lon,
        cost, path_length, duration_seconds,
        timestamp, log_date
    ))

    print(f"✅ Inserted delivery leg for drone {drone_id} ({leg_type})")
    return flight_id