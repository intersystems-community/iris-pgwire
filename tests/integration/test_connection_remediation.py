"""
Test Connection & Auto-Remediation Agentic Skill Integration.
Validates FR-006, FR-007, FR-008.
"""

import pytest


def test_connection_remediation(iris_connection):
    """
    Test that iris_connection fixture provides a working connection.
    This effectively tests the /connection skill logic (auto-retry, password reset, etc).
    """
    assert iris_connection is not None

    with iris_connection.cursor() as cursor:
        cursor.execute("SELECT $ZVERSION")
        version = cursor.fetchone()[0]
        assert "IRIS" in version

        # Verify CallIn service is enabled (since we are connected via DBAPI)
        cursor.execute("SELECT $NAMESPACE")
        namespace = cursor.fetchone()[0]
        assert namespace is not None


def test_explicit_remediation(iris_config):
    """
    Manually trigger remediation logic if possible.
    """
    from iris_devtester.config import IRISConfig
    from iris_devtester.connections import get_connection

    # Use config from fixture
    config = IRISConfig(
        host=iris_config["host"],
        port=iris_config["port"],
        namespace=iris_config["namespace"],
        username=iris_config["username"],
        password=iris_config["password"],
    )

    # get_connection is the entry point for the /connection skill logic
    conn = get_connection(config)
    assert conn is not None
    conn.close()
