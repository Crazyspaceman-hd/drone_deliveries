# from airflow import DAG
# from airflow.operators.python import PythonOperator
# from airflow.sensors.sql import SqlSensor
# from datetime import datetime, timedelta

# # Import pipeline steps
# from scripts.download_data import run_elevation_download
# from scripts.generate_cost_grid import main as generate_cost_grid_main
# from scripts.drone_pathfinding import main as simulate_deliveries_main
# from scripts.batch_delivery_iceberg import main as transfer_summaries_main

# default_args = {
#     'owner': 'Henry Deane (crazyspaceman)',
#     'retries': 0,
#     'retry_delay': timedelta(minutes=5),
# }

# with DAG(
#     dag_id='process_orders_dag_v0.32',
#     default_args=default_args,
#     description='Processes new delivery orders very frequently',
#     schedule_interval='*/10 * * * *',  # Every 10 minutes
#     start_date=datetime(2024, 1, 1),
#     catchup=False,
#     is_paused_upon_creation=False,
#     tags=['processing']
# ) as dag:

#     wait_for_orders = SqlSensor(
#         task_id='wait_for_pending_orders',
#         conn_id='sqlite_conn',
#         sql="""
#             SELECT COUNT(*) FROM orders WHERE status = 'pending'
#         """,
#         mode='poke',
#         poke_interval=5,     # check every 5 seconds
#         timeout=60           # give up after 1 minute
#     )

#     download_data = PythonOperator(
#         task_id='download_data',
#         python_callable=run_elevation_download
#     )

#     generate_cost_grid = PythonOperator(
#         task_id='generate_cost_grid',
#         python_callable=generate_cost_grid_main
#     )

#     simulate_paths = PythonOperator(
#         task_id='simulate_delivery_paths',
#         python_callable=simulate_deliveries_main
#     )

#     transfer_summaries = PythonOperator(
#         task_id='transfer_summaries_to_snowflake',
#         python_callable=transfer_summaries_main
#     )

#     wait_for_orders >> download_data >> generate_cost_grid >> simulate_paths >> transfer_summaries
