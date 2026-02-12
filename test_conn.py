
import psycopg

conn_params = {
    "host": "localhost",
    "port": 5435,
    "user": "_SYSTEM",
    "password": "SYS",
    "dbname": "USER",
}

try:
    conn = psycopg.connect(**conn_params)
    print("Connection successful!")
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        print(f"Query result: {cur.fetchone()}")
    conn.close()
except Exception as e:
    print(f"Connection failed: {e}")
