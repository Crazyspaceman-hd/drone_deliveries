# from trino.dbapi import connect
# from drone_deliveries.scripts.config.trino_config import TRINO_CONFIG

# conn = connect(**TRINO_CONFIG)
# cursor = conn.cursor()

# cursor.execute("SHOW TABLES")
# print(cursor.fetchall())



import sqlite3

conn = sqlite3.connect("../data/delivery_system.sqlite")
cur = conn.cursor()
cur.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 5")
print(cur.fetchall())
conn.close()