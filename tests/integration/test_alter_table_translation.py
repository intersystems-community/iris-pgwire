import psycopg
import pytest


@pytest.mark.e2e
class TestAlterTableTranslationE2E:
    def test_alter_table_set_data_type(self, pgwire_client):
        """FR-005: ALTER TABLE SET DATA TYPE"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_alter")
            cursor.execute("CREATE TABLE test_alter (id INT, col1 VARCHAR(10))")

            # Postgres syntax
            sql = "ALTER TABLE test_alter ALTER COLUMN col1 SET DATA TYPE VARCHAR(100)"
            cursor.execute(sql)

            # Verify (via catalog or insert)
            cursor.execute("INSERT INTO test_alter (id, col1) VALUES (1, '" + "a" * 50 + "')")

    def test_alter_table_drop_not_null(self, pgwire_client):
        """FR-005: ALTER TABLE DROP NOT NULL"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_alter_null")
            cursor.execute("CREATE TABLE test_alter_null (id INT, col1 INT NOT NULL)")

            sql = "ALTER TABLE test_alter_null ALTER COLUMN col1 DROP NOT NULL"
            cursor.execute(sql)

            # Verify
            cursor.execute("INSERT INTO test_alter_null (id, col1) VALUES (1, NULL)")
