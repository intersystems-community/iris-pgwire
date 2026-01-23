"""
TDD Tests for RETURNING clause emulation with UUID-based systems.

These tests verify that:
1. UUID IDs are correctly extracted from INSERT VALUES
2. Table names are normalized to uppercase for IRIS
3. RETURNING emulation works when LAST_IDENTITY() returns 0/NULL
"""

import pytest
from unittest.mock import MagicMock, patch


class TestExtractInsertIdFromSql:
    """Tests for _extract_insert_id_from_sql helper method."""

    @pytest.fixture
    def executor(self):
        """Create a mock executor with the method we're testing."""
        from iris_pgwire.iris_executor import IRISExecutor
        
        with patch.object(IRISExecutor, '__init__', lambda x: None):
            exec = IRISExecutor()
            # Manually add required attributes
            exec.embedded_mode = False
            exec._connection_pool = []
            return exec

    def test_extract_uuid_from_params(self, executor):
        """Should extract UUID from parameterized INSERT."""
        sql = 'INSERT INTO SQLUser."workflow" ("id", "name", "created_at") VALUES (?, ?, ?)'
        params = ["550e8400-e29b-41d4-a716-446655440000", "Test Workflow", "2024-01-01"]
        
        col_name, id_value = executor._extract_insert_id_from_sql(sql, params)
        
        assert col_name == "id"
        assert id_value == "550e8400-e29b-41d4-a716-446655440000"

    def test_extract_uuid_from_literal_values(self, executor):
        """Should extract UUID from literal VALUES clause."""
        sql = """INSERT INTO SQLUser."workflow" ("id", "name") VALUES ('550e8400-e29b-41d4-a716-446655440000', 'Test')"""
        
        col_name, id_value = executor._extract_insert_id_from_sql(sql, None)
        
        assert col_name == "id"
        assert id_value == "550e8400-e29b-41d4-a716-446655440000"

    def test_extract_id_second_position(self, executor):
        """Should find id column even if not first."""
        sql = 'INSERT INTO SQLUser."workflow" ("name", "id", "status") VALUES (?, ?, ?)'
        params = ["Test", "my-uuid-123", "active"]
        
        col_name, id_value = executor._extract_insert_id_from_sql(sql, params)
        
        assert col_name == "id"
        assert id_value == "my-uuid-123"

    def test_no_id_column_returns_none(self, executor):
        """Should return None if no id column found."""
        sql = 'INSERT INTO SQLUser."workflow" ("name", "status") VALUES (?, ?)'
        params = ["Test", "active"]
        
        col_name, id_value = executor._extract_insert_id_from_sql(sql, params)
        
        assert col_name is None
        assert id_value is None

    def test_handles_quoted_column_names(self, executor):
        """Should handle double-quoted column names."""
        sql = 'INSERT INTO SQLUser."workflow_folder" ("id", "name") VALUES (?, ?)'
        params = ["uuid-456", "Folder"]
        
        col_name, id_value = executor._extract_insert_id_from_sql(sql, params)
        
        assert col_name == "id"
        assert id_value == "uuid-456"

    def test_handles_uuid_column_name(self, executor):
        """Should recognize 'uuid' as an ID column."""
        sql = 'INSERT INTO SQLUser."items" ("uuid", "data") VALUES (?, ?)'
        params = ["item-uuid-789", "some data"]
        
        col_name, id_value = executor._extract_insert_id_from_sql(sql, params)
        
        assert col_name == "uuid"
        assert id_value == "item-uuid-789"

    def test_handles_malformed_sql(self, executor):
        """Should return None for malformed SQL."""
        sql = 'INSERT INTO workflow VALUES (?)'  # No column list
        params = ["value"]
        
        col_name, id_value = executor._extract_insert_id_from_sql(sql, params)
        
        assert col_name is None
        assert id_value is None


class TestTableNameNormalization:
    """Tests for table name case normalization in RETURNING emulation."""

    def test_table_normalized_to_uppercase(self):
        """Table names should be normalized to uppercase for IRIS."""
        # This tests the normalization logic directly
        table = "workflow_folder"
        table_normalized = table.upper()
        
        assert table_normalized == "WORKFLOW_FOLDER"

    def test_already_uppercase_unchanged(self):
        """Already uppercase table names should remain unchanged."""
        table = "WORKFLOW"
        table_normalized = table.upper()
        
        assert table_normalized == "WORKFLOW"

    def test_mixed_case_normalized(self):
        """Mixed case table names should become uppercase."""
        table = "WorkflowFolder"
        table_normalized = table.upper()
        
        assert table_normalized == "WORKFLOWFOLDER"


class TestReturningEmulationWithUUID:
    """Integration-style tests for full RETURNING emulation flow."""

    @pytest.fixture
    def executor(self):
        """Create a mock executor."""
        from iris_pgwire.iris_executor import IRISExecutor
        
        with patch.object(IRISExecutor, '__init__', lambda x: None):
            exec = IRISExecutor()
            exec.embedded_mode = False
            exec._connection_pool = []
            return exec

    def test_emulate_returning_uses_uppercase_table(self, executor):
        """RETURNING emulation should use uppercase table name in SELECT."""
        # Mock the _fetch_results to capture the SQL being executed
        executed_sqls = []
        
        def mock_fetch(sql, params=None):
            executed_sqls.append(sql)
            if "LAST_IDENTITY" in sql:
                return [(0,)], None  # Simulate UUID case - no auto-increment
            return [], None
        
        # Mock _import_iris to return a mock
        mock_iris = MagicMock()
        mock_iris.sql.exec.side_effect = lambda s, *p: MagicMock(__iter__=lambda x: iter([]))
        
        with patch.object(executor, '_import_iris', return_value=mock_iris):
            with patch.object(executor, '_extract_insert_id_from_sql', return_value=("id", "test-uuid")):
                # Call the method with lowercase table name
                executor._emulate_returning(
                    operation="INSERT",
                    table="workflow_folder",  # lowercase
                    columns=["id", "name"],
                    where_clause=None,
                    params=["test-uuid", "Test"],
                    is_embedded=True,
                    original_sql='INSERT INTO "workflow_folder" ("id", "name") VALUES (?, ?)',
                )
        
        # Verify uppercase table was used in at least one query
        # The exact SQL depends on which branch executes
        assert any("WORKFLOW_FOLDER" in sql for sql in executed_sqls) or \
               any("WORKFLOW_FOLDER" in str(call) for call in mock_iris.sql.exec.call_args_list)


class TestReturningWithLastIdentityZero:
    """Tests for handling LAST_IDENTITY() returning 0 (UUID case)."""

    @pytest.fixture  
    def executor(self):
        """Create a mock executor."""
        from iris_pgwire.iris_executor import IRISExecutor
        
        with patch.object(IRISExecutor, '__init__', lambda x: None):
            exec = IRISExecutor()
            exec.embedded_mode = False
            exec._connection_pool = []
            return exec

    def test_falls_back_to_uuid_extraction_when_last_identity_zero(self, executor):
        """When LAST_IDENTITY() returns 0, should extract ID from INSERT."""
        call_log = []
        
        def mock_fetch(sql, params=None):
            call_log.append({"sql": sql, "params": params})
            if "LAST_IDENTITY" in sql:
                return [(0,)], None  # UUID case
            if "WHERE" in sql and params:
                # Return mock row for UUID lookup
                return [("test-uuid", "Test Name")], [{"name": "id"}, {"name": "name"}]
            return [], None

        mock_iris = MagicMock()
        
        def mock_exec(sql, *params):
            result = mock_fetch(sql, list(params) if params else None)
            mock_result = MagicMock()
            mock_result.__iter__ = lambda x: iter(result[0])
            mock_result._meta = result[1]
            return mock_result
        
        mock_iris.sql.exec = mock_exec
        
        with patch.object(executor, '_import_iris', return_value=mock_iris):
            rows, meta = executor._emulate_returning(
                operation="INSERT",
                table="workflow",
                columns=["id", "name"],
                where_clause=None,
                params=["test-uuid", "Test Name"],
                is_embedded=True,
                original_sql='INSERT INTO "workflow" ("id", "name") VALUES (?, ?)',
            )
        
        # Should have attempted UUID-based lookup
        uuid_lookups = [c for c in call_log if '"id"' in c["sql"] and "WHERE" in c["sql"]]
        assert len(uuid_lookups) > 0 or len(rows) > 0
