import pytest
import os


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("IRIS_EMBEDDED"), reason="IRIS_EMBEDDED not set")
def test_multi_column_alter_table_embedded(embedded_iris):
    """Test multi-column ALTER TABLE splitting in embedded mode."""
    # Setup
    embedded_iris.execute("DROP TABLE IF EXISTS test_alter_split_emb")
    embedded_iris.execute("CREATE TABLE test_alter_split_emb (id INT)")

    # Multi-action ALTER TABLE
    # In embedded mode, IRIS Executor should split this
    embedded_iris.execute(
        "ALTER TABLE test_alter_split_emb ADD COLUMN col1 INT, ADD COLUMN col2 INT"
    )

    # Verify columns exist
    result = embedded_iris.execute("SELECT col1, col2 FROM test_alter_split_emb")
    # Should not raise error
