import iris


def test_order_by_behavior():
    print("Testing IRIS ORDER BY behavior...")

    try:
        iris.sql.exec("DROP TABLE SQLUser.test_order_by CASCADE")
    except:
        pass

    iris.sql.exec("CREATE TABLE SQLUser.test_order_by (id int, val int)")
    iris.sql.exec("INSERT INTO SQLUser.test_order_by (id, val) VALUES (1, 10)")
    iris.sql.exec("INSERT INTO SQLUser.test_order_by (id, val) VALUES (2, 5)")

    print("\n1. Testing with ALIAS in ORDER BY:")
    sql1 = "SELECT val * 2 AS doubled FROM SQLUser.test_order_by ORDER BY doubled"
    try:
        res1 = iris.sql.exec(sql1).fetch()
        print(f"SUCCESS: Result={res1}")
    except Exception as e:
        print(f"FAIL: {e}")

    print("\n2. Testing with EXPRESSION in ORDER BY:")
    sql2 = "SELECT val * 2 AS doubled FROM SQLUser.test_order_by ORDER BY val * 2"
    try:
        res2 = iris.sql.exec(sql2).fetch()
        print(f"SUCCESS: Result={res2}")
    except Exception as e:
        print(f"FAIL: {e}")

    print("\n3. Testing with ALIAS + LIMIT in ORDER BY:")
    sql3 = "SELECT val * 2 AS doubled FROM SQLUser.test_order_by ORDER BY doubled LIMIT 1"
    try:
        res3 = iris.sql.exec(sql3).fetch()
        print(f"SUCCESS: Result={res3}")
    except Exception as e:
        print(f"FAIL: {e}")


if __name__ == "__main__":
    test_order_by_behavior()
