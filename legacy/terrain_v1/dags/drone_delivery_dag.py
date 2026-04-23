# from airflow import DAG
# from airflow.operators.python import PythonOperator
# from datetime import datetime
# import os

# # Import your pipeline scripts
# from scripts.download_data import main as download_data_main
# from scripts.generate_cost_grid import main as generate_cost_grid_main
# from scripts.drone_pathfinding import main as simulate_deliveries_main
# from scripts.generate_orders import generate_orders as generate_requests_main
# from scripts.transfer_summaries_to_snowflake import main as transfer_summaries_main
# from scripts.generate_orders import generate_orders as generate_requests_main

# default_args = {
#     'owner': 'airflow',
#     'start_date': datetime(2024, 1, 1),
#     'retries': 0
# }

# with DAG(
#     dag_id='drone_delivery_pipeline',
#     default_args=default_args,
#     description='Drone delivery route simulation DAG',
#     schedule_interval=None,  # Run manually for now
#     catchup=False
# ) as dag:

#     generate_app_orders = PythonOperator(
#         task_id='generate_app_orders',
#         python_callable=generate_requests_main
#     )

#     download_data = PythonOperator(
#         task_id='download_data',
#         python_callable=download_data_main
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
#     task_id='transfer_summaries_to_snowflake',
#     python_callable=transfer_summaries_main
#     )

#     # Set task dependencies
#     generate_app_orders >> download_data >> generate_cost_grid >> simulate_paths >> transfer_summaries
