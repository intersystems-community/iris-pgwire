import psycopg
import pytest


@pytest.mark.e2e
class TestPreparedTranslationE2E:
    def test_prepared_statement_with_dollar_n(self, pgwire_client):
        """FR-002: Prepared statements with $n should work"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_prep")
            cursor.execute("CREATE TABLE test_prep (id INT, name VARCHAR(50))")
            cursor.execute("INSERT INTO test_prep VALUES (1, 'alice')")
            cursor.execute("INSERT INTO test_prep VALUES (2, 'bob')")

        # Psycopg 3 uses %s which it translates to $1/$2 for the wire protocol
        sql = "SELECT name FROM test_prep WHERE id = %s"
        with pgwire_client.cursor() as cursor:
            cursor.execute(sql, (1,))
            result = cursor.fetchone()
            assert result[0] == "alice"

    def test_prepared_statement_with_type_casts(self, pgwire_client):
        """FR-002: Type casts in prepared statements"""
        # Test with explicit type cast
        sql = "SELECT %s::int + 1"
        with pgwire_client.cursor() as cursor:
            cursor.execute(sql, (10,))
            result = cursor.fetchone()
            assert result[0] == 11
