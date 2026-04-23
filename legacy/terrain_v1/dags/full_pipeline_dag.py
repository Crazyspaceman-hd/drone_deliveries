import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator
from datetime import datetime, timedelta

# Import all the components of the pipeline
from scripts.generate_orders import generate_orders
from scripts.generate_cost_grid import main as generate_cost_grid
from scripts.download_data import run_elevation_download, elevation_tif_missing
from scripts.drone_pathfinding import main as simulate_drone_paths
from scripts.batch_delivery_iceberg import main as sync_to_iceberg
TILE_LOCAL_PATH = "data/raw/USGS_13_n46w123_20240124.tif"

# DAG default arguments
default_args = {
    'owner': 'Henry Deane (crazyspaceman)',
    'depends_on_past': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=1),
}

with DAG(
    dag_id='full_drone_delivery_pipeline_v0.20.3',
    default_args=default_args,
    description='End-to-end drone delivery ETL pipeline',
    schedule_interval='*/10 * * * *',
    start_date=datetime(2024, 1, 1),
    catchup=False,
    is_paused_upon_creation=False,
    tags=['drone', 'etl', 'full']
) as dag:

    # 1. Generate Orders
    task_generate_orders = PythonOperator(
        task_id='generate_orders',
        python_callable=generate_orders
    )

    # 2. Process Orders
    task_generate_cost_grid = PythonOperator(
        task_id='generate_cost_grid',
        python_callable=generate_cost_grid
    )

    # 3. Elevation Check and Download
    task_check_elevation = ShortCircuitOperator(
        task_id='check_if_elevation_needed',
        python_callable=elevation_tif_missing,
        dag=dag,
    )

    task_download_elevation = PythonOperator(
        task_id='download_elevation_tif',
        python_callable=run_elevation_download
    )

    # 4. Simulate Drone Paths
    task_simulate_deliveries = PythonOperator(
        task_id='simulate_drone_deliveries',
        python_callable=simulate_drone_paths
    )

    # 5. Sync Data to Iceberg
    task_sync_to_iceberg = PythonOperator(
        task_id='sync_to_iceberg',
        python_callable=sync_to_iceberg
    )
    # 3. Elevation Check and Download
    

# DAG execution flow

# Always try to generate orders
task_generate_orders >> task_simulate_deliveries

# Elevation checker conditionally triggers download
task_check_elevation >> task_download_elevation

# Cost grid must always run (regardless of whether elevation was downloaded)
task_generate_cost_grid.set_upstream([task_download_elevation, task_check_elevation])

# Simulation requires both cost grid and orders
[task_generate_cost_grid, task_generate_orders] >> task_simulate_deliveries

# Final sync
task_simulate_deliveries >> task_sync_to_iceberg