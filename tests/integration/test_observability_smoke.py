import psycopg
import pytest


@pytest.mark.e2e
class TestObservabilitySmokeE2E:
    def test_health_check_select_1(self, pgwire_client):
        """Verify basic health check still works"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            assert result[0] == 1

    def test_logging_metrics_smoke(self, pgwire_client):
        """Verify server doesn't crash during multiple operations"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_obs")
            cursor.execute("CREATE TABLE test_obs (id INT)")
            for i in range(5):
                cursor.execute("INSERT INTO test_obs VALUES (%s)", (i,))
            cursor.execute("SELECT COUNT(*) FROM test_obs")
            assert cursor.fetchone()[0] == 5
