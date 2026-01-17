import pytest

from iris_pgwire.conversions.ddl_splitter import DdlSplitter


class TestDdlSplitterFixes:
    @pytest.fixture
    def splitter(self):
        return DdlSplitter()

    def test_split_sql_with_comments(self, splitter):
        """FR-001: Splitter must be comment-aware"""
        sql = "CREATE TABLE t1 (id INT); -- comment with ;\nCREATE TABLE t2 (id INT);"
        statements = splitter.split(sql)
        assert len(statements) == 2
        assert "t1" in statements[0].lower()
        assert "t2" in statements[1].lower()

    def test_split_sql_with_block_comments(self, splitter):
        """FR-001: Splitter must handle block comments"""
        sql = "CREATE TABLE t1 (id INT); /* comment with ; */ CREATE TABLE t2 (id INT);"
        statements = splitter.split(sql)
        assert len(statements) == 2
