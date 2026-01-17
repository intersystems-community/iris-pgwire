"""
Test Fixture Management Agentic Skill Integration.
Validates FR-009, FR-010.
"""

import os

import pytest


@pytest.mark.skip(
    reason="Depends on iris-devtester fixes for directory-based loading and namespace mounting"
)
def test_fixture_loading(iris_fixture, iris_connection, iris_container):
    """
    Test that iris_fixture can load data into a new namespace.
    """
    # Create unique namespace for testing
    target_ns = "FIXTURE_TEST"
    iris_container.create_namespace(target_ns)

    # Create a temporary table and some data
    with iris_connection.cursor() as cursor:
        cursor.execute("CREATE TABLE TestFixtureTable (id INT, name VARCHAR(50))")
        cursor.execute("INSERT INTO TestFixtureTable VALUES (1, 'Test Data')")
        iris_connection.commit()

    # Export to directory
    fixture_dir = "test_fixture_dir"
    try:
        # Export from USER
        iris_fixture.export("test-id", fixture_dir)
        assert os.path.exists(fixture_dir)

        # Load into target namespace
        # We need a way to pass target_namespace to iris_fixture.load()
        # My helper doesn't support it yet, I'll update it.
        iris_fixture.load_into(fixture_dir, target_ns)

        # Verify data in target namespace
        # (Need a connection to that namespace)
        from iris_devtester.config import IRISConfig
        from iris_devtester.connections import get_connection

        config = iris_container.get_config()
        config.namespace = target_ns

        with get_connection(config) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT name FROM TestFixtureTable WHERE id = 1")
                row = cursor.fetchone()
                assert row[0] == "Test Data"

    finally:
        if os.path.exists(fixture_dir):
            import shutil

            shutil.rmtree(fixture_dir)
        # Cleanup namespace
        iris_container.delete_namespace(target_ns)
        # Final cleanup in USER
        with iris_connection.cursor() as cursor:
            try:
                cursor.execute("DROP TABLE TestFixtureTable")
                iris_connection.commit()
            except:
                pass
