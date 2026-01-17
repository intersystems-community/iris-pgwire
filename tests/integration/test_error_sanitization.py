import psycopg
import pytest


@pytest.mark.e2e
class TestErrorSanitizationE2E:
    def test_error_message_no_leaks(self, pgwire_client):
        """Verify error messages do not leak sensitive IRIS internals"""
        with pgwire_client.cursor() as cursor:
            # Trigger a deliberate error (table not found)
            try:
                cursor.execute("SELECT * FROM non_existent_table_xyz")
                pytest.fail("Should have raised an error")
            except psycopg.errors.Error as e:
                msg = str(e)
                # Check that it's a standard-looking SQL error
                assert "SQLCODE" in msg or "not found" in msg.lower()
                # Basic check: no Python file paths or stack traces should be in the message
                assert "/Users/tdyar" not in msg
                assert ".py" not in msg
