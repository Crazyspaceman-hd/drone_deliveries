# from airflow import DAG
# from airflow.operators.python import PythonOperator
# from datetime import datetime, timedelta
# from scripts.generate_orders import generate_orders

# default_args = {
#     'owner': 'Henry Deane (crazyspaceman)',
#     'retries': 0,
#     'retry_delay': timedelta(minutes=5),
# }

# with DAG(
#     dag_id='generate_orders_dag_v0.32',
#     default_args=default_args,
#     description='Generates new delivery orders every 10 minutes',
#     schedule_interval='*/10 * * * *',
#     start_date=datetime(2024, 1, 1),
#     catchup=False,
#     is_paused_upon_creation=False,
#     tags=['orders']
# ) as dag:

#     generate_orders_task = PythonOperator(
#         task_id='generate_app_orders',
#         python_callable=generate_orders
#     )

#     generate_orders_task