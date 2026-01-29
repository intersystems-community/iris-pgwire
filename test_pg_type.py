import psycopg
import os

PGWIRE_PORT = int(os.environ.get("PGWIRE_PORT", "5435"))


def test_pg_type():
    print(f"Connecting to localhost:{PGWIRE_PORT}...")
    conn = psycopg.connect(
        host="localhost",
        port=PGWIRE_PORT,
        user="_SYSTEM",
        password="SYS",
        dbname="USER",
        autocommit=True,
    )
    cur = conn.cursor()

    print("Executing pg_type query...")
    # This matches the query pattern in the bug report
    cur.execute(
        "SELECT oid, typname, typnamespace, typtype, typcategory FROM pg_catalog.pg_type WHERE typname = 'int4'"
    )
    row = cur.fetchone()

    if row:
        print(f"Found row: {row}")
        assert row[1] == "int4"
        assert row[0] == 23
        print("✅ pg_type test PASSED")
    else:
        print("❌ pg_type test FAILED: No row returned")
        exit(1)

    conn.close()


if __name__ == "__main__":
    test_pg_type()
