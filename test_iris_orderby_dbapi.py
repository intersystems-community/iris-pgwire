import psycopg
import os


def test_order_by_dbapi():
    print("Testing IRIS ORDER BY behavior via DBAPI...")

    conn_str = "host=localhost port=5432 user=_SYSTEM password=SYS dbname=USER"
    try:
        with psycopg.connect(conn_str, autocommit=True) as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("DROP TABLE SQLUser.test_order_by CASCADE")
                except:
                    pass

                cur.execute("CREATE TABLE SQLUser.test_order_by (id int, val int)")
                cur.execute("INSERT INTO SQLUser.test_order_by (id, val) VALUES (1, 10)")
                cur.execute("INSERT INTO SQLUser.test_order_by (id, val) VALUES (2, 5)")

                print("\n1. Testing with ALIAS in ORDER BY:")
                sql1 = "SELECT val * 2 AS doubled FROM SQLUser.test_order_by ORDER BY doubled"
                try:
                    cur.execute(sql1)
                    print(f"SUCCESS: Result={cur.fetchone()}")
                except Exception as e:
                    print(f"FAIL: {e}")

                print("\n2. Testing with EXPRESSION in ORDER BY:")
                sql2 = "SELECT val * 2 AS doubled FROM SQLUser.test_order_by ORDER BY val * 2"
                try:
                    cur.execute(sql2)
                    print(f"SUCCESS: Result={cur.fetchone()}")
                except Exception as e:
                    print(f"FAIL: {e}")

                print("\n3. Testing with ALIAS + LIMIT in ORDER BY:")
                sql3 = (
                    "SELECT val * 2 AS doubled FROM SQLUser.test_order_by ORDER BY doubled LIMIT 1"
                )
                try:
                    cur.execute(sql3)
                    print(f"SUCCESS: Result={cur.fetchone()}")
                except Exception as e:
                    print(f"FAIL: {e}")
    except Exception as e:
        print(f"Connection Error: {e}")


if __name__ == "__main__":
    test_order_by_dbapi()
