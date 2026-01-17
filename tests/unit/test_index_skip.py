import pytest

from iris_pgwire.sql_translator.enum_registry import EnumTypeRegistry
from iris_pgwire.sql_translator.skipped_table_set import SkippedTableSet
from iris_pgwire.sql_translator.statement_filter import StatementFilter


def test_index_skip_on_skipped_table():
    registry = EnumTypeRegistry()
    skipped_tables = SkippedTableSet()
    skipped_tables.add("t1")
    sf = StatementFilter(enum_registry=registry, skipped_tables=skipped_tables)

    sql = "CREATE INDEX idx1 ON t1 (col1)"
    result = sf.check(sql)
    assert result.should_skip is True  # Should be skipped


def test_index_no_skip_on_other_table():
    registry = EnumTypeRegistry()
    skipped_tables = SkippedTableSet()
    skipped_tables.add("t1")
    sf = StatementFilter(enum_registry=registry, skipped_tables=skipped_tables)

    sql = "CREATE INDEX idx2 ON t2 (col1)"
    result = sf.check(sql)
    assert result.should_skip is False  # Should NOT be skipped
