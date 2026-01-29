import pytest
from iris_pgwire.iris_executor import IRISExecutor


def test_parse_returning_clause():
    executor = IRISExecutor(
        {
            "host": "localhost",
            "port": 1972,
            "username": "_SYSTEM",
            "password": "SYS",
            "namespace": "USER",
        }
    )

    # 1. INSERT RETURNING *
    sql = 'INSERT INTO "public"."users" ("id", "name") VALUES ($1, $2) RETURNING *'
    op, table, cols, where, stripped = executor._parse_returning_clause(sql)
    assert op == "INSERT"
    assert table == "USERS"  # Normalized to UPPERCASE
    assert cols == "*"
    assert stripped == 'INSERT INTO "public"."users" ("id", "name") VALUES ($1, $2)'

    # 2. UPDATE RETURNING specific columns
    sql = 'UPDATE "public"."users" SET "status" = $1 WHERE "id" = $2 RETURNING "id", "name"'
    op, table, cols, where, stripped = executor._parse_returning_clause(sql)
    assert op == "UPDATE"
    assert table == "USERS"  # Normalized to UPPERCASE
    assert cols == ["id", "name"]
    assert where == '"id" = $2'
    assert stripped == 'UPDATE "public"."users" SET "status" = $1 WHERE "id" = $2'

    # 3. DELETE RETURNING
    sql = 'DELETE FROM "public"."users" WHERE "id" = $1 RETURNING "id"'
    op, table, cols, where, stripped = executor._parse_returning_clause(sql)
    assert op == "DELETE"
    assert table == "USERS"  # Normalized to UPPERCASE
    assert cols == ["id"]
    assert where == '"id" = $1'
    assert stripped == 'DELETE FROM "public"."users" WHERE "id" = $1'


def test_parse_returning_clause_complex():
    executor = IRISExecutor(
        {
            "host": "localhost",
            "port": 1972,
            "username": "_SYSTEM",
            "password": "SYS",
            "namespace": "USER",
        }
    )

    # Complex case with quotes and schema
    sql = 'INSERT INTO "SQLUser"."CopilotChats" ("id", "workflowId") VALUES ($1, $2) RETURNING "id", "createdAt"'
    op, table, cols, where, stripped = executor._parse_returning_clause(sql)
    assert op == "INSERT"
    assert table == "COPILOTCHATS"  # Normalized to UPPERCASE
    assert cols == ["id", "createdat"]

    print("✅ RETURNING clause parsing tests passed")


if __name__ == "__main__":
    test_parse_returning_clause()
    test_parse_returning_clause_complex()
