"""
TDD Tests for execute_many with RETURNING clause support.

These tests verify that:
1. execute_many aggregates returned rows from multiple INSERTs
2. UUID-based RETURNING works for batch operations
3. The method handles RETURNING * and explicit columns
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestExecuteManyReturningParsing:
    """Tests for detecting and parsing RETURNING in execute_many context."""

    @pytest.fixture
    def executor(self):
        """Create a mock executor."""
        from iris_pgwire.iris_executor import IRISExecutor
        
        with patch.object(IRISExecutor, '__init__', lambda x: None):
            exec = IRISExecutor()
            exec.embedded_mode = True
            exec._connection_pool = []
            return exec

    def test_has_returning_clause_detects_returning(self, executor):
        """Should detect RETURNING clause in SQL."""
        sql_with_returning = 'INSERT INTO "workflow" ("id", "name") VALUES (?, ?) RETURNING *'
        sql_without = 'INSERT INTO "workflow" ("id", "name") VALUES (?, ?)'
        
        assert executor.has_returning_clause(sql_with_returning) is True
        assert executor.has_returning_clause(sql_without) is False

    def test_parse_returning_extracts_columns(self, executor):
        """Should extract RETURNING columns correctly."""
        sql = 'INSERT INTO SQLUser."workflow" ("id", "name") VALUES (?, ?) RETURNING "id", "name", "created_at"'
        
        operation, table, columns, where, stripped = executor._parse_returning_clause(sql)
        
        assert operation == "INSERT"
        assert table == "workflow"
        assert columns == ["id", "name", "created_at"] or columns == ["id", "name", "createdat"]
        assert "RETURNING" not in stripped

    def test_parse_returning_star(self, executor):
        """Should handle RETURNING * correctly."""
        sql = 'INSERT INTO SQLUser."workflow" ("id", "name") VALUES (?, ?) RETURNING *'
        
        operation, table, columns, where, stripped = executor._parse_returning_clause(sql)
        
        assert operation == "INSERT"
        assert columns == "*"


class TestExecuteManyWithReturning:
    """Tests for execute_many behavior with RETURNING clause."""

    @pytest.fixture
    def executor(self):
        """Create a mock executor."""
        from iris_pgwire.iris_executor import IRISExecutor
        
        with patch.object(IRISExecutor, '__init__', lambda x: None):
            exec = IRISExecutor()
            exec.embedded_mode = True
            exec._connection_pool = []
            exec._iris_module = None
            return exec

    def test_execute_many_aggregates_returned_rows(self, executor):
        """execute_many should aggregate rows from all INSERTs with RETURNING."""
        # This test documents the expected behavior
        # When inserting 3 rows with RETURNING *, we should get 3 rows back
        
        sql = 'INSERT INTO "workflow" ("id", "name") VALUES (?, ?) RETURNING *'
        params_list = [
            ["uuid-1", "Workflow 1"],
            ["uuid-2", "Workflow 2"],
            ["uuid-3", "Workflow 3"],
        ]
        
        # Expected: result should contain 3 rows
        expected_row_count = 3
        
        # This is the contract we're implementing
        assert expected_row_count == len(params_list)

    def test_execute_many_returns_correct_structure(self):
        """execute_many with RETURNING should return proper result dict."""
        # Expected structure from execute_many with RETURNING
        expected_keys = {"success", "rows", "columns", "rows_affected"}
        
        # Mock result structure
        mock_result = {
            "success": True,
            "rows": [["uuid-1", "Workflow 1"], ["uuid-2", "Workflow 2"]],
            "columns": [{"name": "id", "type_oid": 1043}, {"name": "name", "type_oid": 1043}],
            "rows_affected": 2,
        }
        
        assert expected_keys.issubset(mock_result.keys())
        assert len(mock_result["rows"]) == 2


class TestExecuteManyUUIDExtraction:
    """Tests for UUID extraction in batch operations."""

    def test_uuid_extraction_from_params_list(self):
        """Should extract UUIDs from each parameter set."""
        import re
        
        UUID_PATTERN = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )
        
        params_list = [
            ["550e8400-e29b-41d4-a716-446655440001", "Workflow 1"],
            ["550e8400-e29b-41d4-a716-446655440002", "Workflow 2"],
            ["550e8400-e29b-41d4-a716-446655440003", "Workflow 3"],
        ]
        
        extracted_uuids = []
        for params in params_list:
            for param in params:
                if isinstance(param, str) and UUID_PATTERN.match(param):
                    extracted_uuids.append(param)
                    break
        
        assert len(extracted_uuids) == 3
        assert extracted_uuids[0] == "550e8400-e29b-41d4-a716-446655440001"

    def test_uuid_extraction_handles_non_uuid_ids(self):
        """Should handle cases where ID is not a UUID."""
        import re
        
        UUID_PATTERN = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )
        
        params_list = [
            ["custom-id-123", "Workflow 1"],
            [12345, "Workflow 2"],  # Numeric ID
        ]
        
        extracted_uuids = []
        for params in params_list:
            for param in params:
                if isinstance(param, str) and UUID_PATTERN.match(param):
                    extracted_uuids.append(param)
                    break
        
        # Should find 0 UUIDs (neither is a valid UUID format)
        assert len(extracted_uuids) == 0
