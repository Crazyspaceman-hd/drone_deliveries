# from airflow import DAG
# from airflow.operators.python import PythonOperator
# from datetime import datetime, timedelta
# from scripts.batch_delivery_iceberg import main as sync_to_iceberg

# default_args = {
#     'owner': 'Henry Deane (crazyspaceman)',
#     'retries': 0,
#     'retry_delay': timedelta(minutes=5),
# }

# with DAG(
#     dag_id='sync_deliveries_dag_v0.32',
#     default_args=default_args,
#     description='Batch sync unsynced delivery legs from SQLite to Iceberg',
#     schedule_interval='*/30 * * * *',
#     start_date=datetime(2024, 1, 1),
#     catchup=False,
#     is_paused_upon_creation=False,
#     tags=['sync']
# ) as dag:

#     sync_deliveries_task = PythonOperator(
#         task_id='sync_sqlite_to_iceberg',
#         python_callable=sync_to_iceberg
#     )

#     sync_deliveries_task
