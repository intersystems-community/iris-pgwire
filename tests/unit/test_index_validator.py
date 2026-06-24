"""Unit tests for IndexValidator."""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.ddl_parser import IndexDefinition
from iris_pgwire.sql_translator.ddl_translator import DDLTranslationError
from iris_pgwire.sql_translator.index_validator import IndexValidator


class TestIndexValidatorIsSimpleColumn:
    """Tests for the internal _is_simple_column helper."""

    def setup_method(self):
        self.validator = IndexValidator()

    def test_plain_identifier_is_simple(self):
        assert self.validator._is_simple_column("col") is True

    def test_uppercase_identifier_is_simple(self):
        assert self.validator._is_simple_column("MYCOLUMN") is True

    def test_underscore_identifier_is_simple(self):
        assert self.validator._is_simple_column("my_col") is True

    def test_quoted_identifier_is_simple(self):
        assert self.validator._is_simple_column('"MyCol"') is True

    def test_schema_qualified_is_simple(self):
        assert self.validator._is_simple_column("schema.col") is True

    def test_expression_is_not_simple(self):
        assert self.validator._is_simple_column("lower(col)") is False

    def test_empty_is_not_simple(self):
        assert self.validator._is_simple_column("") is False

    def test_whitespace_only_is_not_simple(self):
        assert self.validator._is_simple_column("   ") is False

    def test_cast_expression_is_not_simple(self):
        assert self.validator._is_simple_column("col::text") is False

    def test_identifier_with_spaces_stripped_is_simple(self):
        # strip() is called, so leading/trailing whitespace is fine
        assert self.validator._is_simple_column("  col  ") is True


class TestIndexValidatorValidateIndex:
    """Tests for validate_index()."""

    def setup_method(self):
        self.validator = IndexValidator()

    def _make_index(
        self,
        columns=("id",),
        where_clause=None,
        include_columns=None,
    ) -> IndexDefinition:
        return IndexDefinition(
            name="idx_test",
            table="my_table",
            columns=columns,
            unique=False,
            where_clause=where_clause,
            include_columns=include_columns,
        )

    def test_valid_simple_index_passes(self):
        defn = self._make_index(columns=("id",))
        # Should not raise
        self.validator.validate_index(defn, "CREATE INDEX idx_test ON my_table (id)")

    def test_valid_multi_column_index_passes(self):
        defn = self._make_index(columns=("first_name", "last_name"))
        self.validator.validate_index(defn, "CREATE INDEX ...")

    def test_where_clause_raises(self):
        defn = self._make_index(where_clause="active = true")
        with pytest.raises(DDLTranslationError) as exc_info:
            self.validator.validate_index(defn, "CREATE INDEX ... WHERE active = true")
        assert "partial" in str(exc_info.value).lower()

    def test_include_columns_raises(self):
        defn = self._make_index(include_columns=("name",))
        with pytest.raises(DDLTranslationError) as exc_info:
            self.validator.validate_index(defn, "CREATE INDEX ... INCLUDE (name)")
        assert "INCLUDE" in str(exc_info.value)

    def test_expression_column_raises(self):
        defn = self._make_index(columns=("lower(email)",))
        with pytest.raises(DDLTranslationError) as exc_info:
            self.validator.validate_index(defn, "CREATE INDEX ... ON t (lower(email))")
        assert "expression" in str(exc_info.value).lower()

    def test_ddl_translation_error_has_code(self):
        defn = self._make_index(where_clause="x = 1")
        with pytest.raises(DDLTranslationError) as exc_info:
            self.validator.validate_index(defn, "CREATE INDEX ... WHERE x = 1")
        err = exc_info.value
        # DDLTranslationError stores the error code as first arg
        assert "UNSUPPORTED_INDEX_FEATURE" in str(err.args)
