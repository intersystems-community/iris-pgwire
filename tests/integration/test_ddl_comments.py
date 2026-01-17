import psycopg
import pytest


@pytest.mark.e2e
class TestDdlCommentsE2E:
    def test_multi_statement_ddl_with_leading_comments(self, pgwire_client):
        """FR-001: Multi-statement DDL with comments should not corrupt"""
        sql = """
        -- Create first table
        CREATE TABLE test_ddl_1 (id INT PRIMARY KEY);
        -- Create second table
        CREATE TABLE test_ddl_2 (id INT PRIMARY KEY);
        """
        with pgwire_client.cursor() as cursor:
            cursor.execute(sql)

        # Verify both tables exist
        with pgwire_client.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM test_ddl_1")
            cursor.execute("SELECT COUNT(*) FROM test_ddl_2")

    def test_ddl_with_semicolon_in_comment(self, pgwire_client):
        """FR-001: Semicolon in comment should not split statement"""
        sql = "CREATE TABLE test_ddl_3 (id INT PRIMARY KEY); -- comment with ; semicolon\nCREATE TABLE test_ddl_4 (id INT PRIMARY KEY);"
        with pgwire_client.cursor() as cursor:
            cursor.execute(sql)

        # Verify
        with pgwire_client.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM test_ddl_3")
            cursor.execute("SELECT COUNT(*) FROM test_ddl_4")
