"""Unit tests for ConstraintTranslator."""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.constraint_translator import ConstraintTranslator
from iris_pgwire.sql_translator.ddl_parser import ConstraintDefinition, ConstraintType


class TestConstraintTranslatorQuoteColumn:
    """Tests for the internal _quote_column helper."""

    def setup_method(self):
        self.translator = ConstraintTranslator()

    def test_plain_column_gets_quoted(self):
        assert self.translator._quote_column("id") == '"id"'

    def test_already_quoted_column_unchanged(self):
        assert self.translator._quote_column('"id"') == '"id"'

    def test_column_with_spaces_stripped_and_quoted(self):
        assert self.translator._quote_column("  col  ") == '"col"'

    def test_empty_string_returns_empty(self):
        assert self.translator._quote_column("") == ""


class TestConstraintTranslatorTranslateConstraint:
    """Tests for translate_constraint()."""

    def setup_method(self):
        self.translator = ConstraintTranslator()

    def test_primary_key_single_column(self):
        constraint = ConstraintDefinition(
            constraint_type=ConstraintType.PRIMARY_KEY,
            columns=("id",),
        )
        result = self.translator.translate_constraint(constraint)
        assert result == 'PRIMARY KEY ("id")'

    def test_primary_key_multiple_columns(self):
        constraint = ConstraintDefinition(
            constraint_type=ConstraintType.PRIMARY_KEY,
            columns=("tenant_id", "record_id"),
        )
        result = self.translator.translate_constraint(constraint)
        assert result == 'PRIMARY KEY ("tenant_id", "record_id")'

    def test_unique_single_column(self):
        constraint = ConstraintDefinition(
            constraint_type=ConstraintType.UNIQUE,
            columns=("email",),
        )
        result = self.translator.translate_constraint(constraint)
        assert result == 'UNIQUE ("email")'

    def test_unique_multiple_columns(self):
        constraint = ConstraintDefinition(
            constraint_type=ConstraintType.UNIQUE,
            columns=("first_name", "last_name"),
        )
        result = self.translator.translate_constraint(constraint)
        assert result == 'UNIQUE ("first_name", "last_name")'

    def test_unsupported_type_returns_empty(self):
        constraint = ConstraintDefinition(
            constraint_type=ConstraintType.CHECK,
            columns=("status",),
        )
        result = self.translator.translate_constraint(constraint)
        assert result == ""

    def test_foreign_key_returns_empty(self):
        constraint = ConstraintDefinition(
            constraint_type=ConstraintType.FOREIGN_KEY,
            columns=("user_id",),
        )
        result = self.translator.translate_constraint(constraint)
        assert result == ""

    def test_empty_columns_returns_empty(self):
        constraint = ConstraintDefinition(
            constraint_type=ConstraintType.PRIMARY_KEY,
            columns=(),
        )
        result = self.translator.translate_constraint(constraint)
        assert result == ""

    def test_already_quoted_columns_not_double_quoted(self):
        constraint = ConstraintDefinition(
            constraint_type=ConstraintType.PRIMARY_KEY,
            columns=('"MyId"',),
        )
        result = self.translator.translate_constraint(constraint)
        assert result == 'PRIMARY KEY ("MyId")'
        assert '""' not in result
