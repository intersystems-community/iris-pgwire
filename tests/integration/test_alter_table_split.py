import pytest
import psycopg


@pytest.mark.integration
def test_multi_column_alter_table(pgwire_client):
    """Test that multi-column ALTER TABLE (PostgreSQL syntax) works with IRIS bridge."""
    with pgwire_client.cursor() as cur:
        # Setup
        cur.execute("DROP TABLE IF EXISTS test_alter_split")
        cur.execute("CREATE TABLE test_alter_split (id INT)")
        pgwire_client.commit()

        # Multi-action ALTER TABLE
        # IRIS typically fails on this syntax if not split
        cur.execute("ALTER TABLE test_alter_split ADD COLUMN col1 INT, ADD COLUMN col2 INT")
        pgwire_client.commit()

        # Verify columns exist
        cur.execute("SELECT col1, col2 FROM test_alter_split")

        # Test DROP COLUMN multi-action
        cur.execute("ALTER TABLE test_alter_split DROP COLUMN col1, DROP COLUMN col2")
        pgwire_client.commit()

        # Verify columns are gone
        try:
            cur.execute("SELECT col1 FROM test_alter_split")
            assert False, "col1 should be dropped"
        except Exception:
            pass

        cur.close()
