def outer(sql):
    def inner():
        # This should fail if sql is assigned to in inner
        print(f"Reading sql: {sql}")

    inner()
    sql = "assigned in outer"
    print(f"Outer sql: {sql}")


try:
    outer("initial")
    print("Test 1 Success")
except UnboundLocalError as e:
    print(f"Test 1 Error: {e}")


def outer2(sql):
    def inner():
        # This will fail if sql is assigned to ANYWHERE in inner
        try:
            print(f"Reading sql: {sql}")
        except UnboundLocalError as e:
            print(f"Inner Error (as expected if assigned later): {e}")

        sql = "assigned in inner"
        print(f"Inner sql: {sql}")

    inner()


try:
    outer2("initial")
    print("Test 2 Success")
except UnboundLocalError as e:
    print(f"Test 2 Error: {e}")
