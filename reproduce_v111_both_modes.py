import os
import unittest
from unittest.mock import MagicMock, patch
import sys

# Add current dir to path
sys.path.insert(0, os.getcwd())

# Mock iris module for embedded mode
mock_iris = MagicMock()
sys.modules["iris"] = mock_iris

from iris_pgwire.iris_executor import IRISExecutor
from iris_pgwire.schema_mapper import configure_schema


def reproduce_both_modes():
    # Setup custom mapping
    configure_schema(mapping={"drizzle": "SQLUser", "public": "SQLUser"})

    test_queries = [
        ('SELECT * FROM drizzle."workflow"', "Bug 1: Custom Schema Mapping"),
        ('SELECT * FROM "workflow"', "Bug 2: Bare Table Name"),
    ]

    modes = ["embedded", "dbapi"]

    for mode in modes:
        print(f"\n=== Testing Mode: {mode.upper()} ===")
        os.environ["BACKEND_TYPE"] = mode

        # Force re-detection of backend
        with patch(
            "iris_pgwire.iris_executor.is_embedded_python", return_value=(mode == "embedded")
        ):
            # Reset mocks
            mock_iris.sql.exec.reset_mock()

            with patch("psycopg.connect") as mock_connect:
                mock_conn = MagicMock()
                mock_connect.return_value = mock_conn
                # Ensure DBAPI cursor returns our mock
                mock_conn.cursor.return_value = MagicMock()

                executor = IRISExecutor(iris_config={})

                for sql, description in test_queries:
                    print(f"\n--- {description} ---")
                    print(f"Input SQL: {sql}")

                    try:
                        executor.execute(sql, session_id="test-session")
                    except Exception as e:
                        # Execution will fail because mocks aren't full-featured
                        pass

                    # Capture the SQL from the mock
                    final_sql = "UNKNOWN"
                    if mode == "embedded":
                        if mock_iris.sql.exec.call_args:
                            final_sql = mock_iris.sql.exec.call_args[0][0]
                    else:
                        cursor_mock = mock_conn.cursor.return_value
                        if cursor_mock.execute.call_args:
                            final_sql = cursor_mock.execute.call_args[0][0]

                    print(f"Final SQL sent to IRIS: {final_sql}")


if __name__ == "__main__":
    reproduce_both_modes()
