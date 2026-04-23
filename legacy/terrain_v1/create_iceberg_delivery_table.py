from trino.dbapi import connect
from drone_deliveries.scripts.config.trino_config import TRINO_CONFIG

def create_delivery_logs_table(config=TRINO_CONFIG):
    catalog = config["catalog"]
    schema = config["schema"]
    table = "delivery_logs"

    conn = connect(**config)
    cursor = conn.cursor()

    # Check if table exists
    cursor.execute(f"SHOW TABLES IN {schema}")
    existing_tables = [row[0] for row in cursor.fetchall()]
    if table in existing_tables:
        print(f"✅ Table {schema}.{table} already exists.")
        return

    # Create the table with partitioning on log_date
    create_query = f"""
        CREATE TABLE {catalog}.{schema}.{table} (
            flight_id VARCHAR,
            drone_id VARCHAR,
            leg_type VARCHAR,
            start_lat DOUBLE,
            start_lon DOUBLE,
            end_lat DOUBLE,
            end_lon DOUBLE,
            cost DOUBLE,
            path_length INT,
            duration_seconds DOUBLE,
            timestamp TIMESTAMP,
            log_date DATE
        )
        WITH (
            format = 'parquet',
            partitioning = ARRAY['log_date']
        )
    """

    cursor.execute(create_query)
    print(f"✅ Created table {catalog}.{schema}.{table}")

if __name__ == "__main__":
    create_delivery_logs_table()

