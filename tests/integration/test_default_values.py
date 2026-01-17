import psycopg
import pytest


@pytest.mark.e2e
class TestDefaultValuesE2E:
    def test_insert_with_default_in_values(self, pgwire_client):
        """FR-003: DEFAULT in VALUES clause"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_defaults")
            cursor.execute("CREATE TABLE test_defaults (id INT, val INT DEFAULT 42)")

            # This is the problematic syntax for IRIS
            sql = "INSERT INTO test_defaults (id, val) VALUES (1, DEFAULT)"
            cursor.execute(sql)

            cursor.execute("SELECT val FROM test_defaults WHERE id = 1")
            result = cursor.fetchone()
            assert result[0] == 42

    def test_multiple_defaults_in_values(self, pgwire_client):
        """FR-003: Multiple DEFAULTs in VALUES"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_defaults_multi")
            cursor.execute(
                "CREATE TABLE test_defaults_multi (id INT, v1 INT DEFAULT 10, v2 INT DEFAULT 20)"
            )

            sql = "INSERT INTO test_defaults_multi (id, v1, v2) VALUES (1, DEFAULT, DEFAULT)"
            cursor.execute(sql)

            cursor.execute("SELECT v1, v2 FROM test_defaults_multi WHERE id = 1")
            v1, v2 = cursor.fetchone()
            assert v1 == 10
            assert v2 == 20
