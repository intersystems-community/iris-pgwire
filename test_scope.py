def outer(sql):
    def inner(captured_sql):
        print(sql)  # This should fail if sql is local but not yet assigned
        sql = captured_sql

    inner("hello")


try:
    outer("world")
except UnboundLocalError as e:
    print(f"Caught expected error: {e}")
