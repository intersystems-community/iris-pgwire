"""Unit tests for reserved_words module."""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.reserved_words import (
    IRIS_RESERVED_WORDS,
    ReservedWordChecker,
)


class TestIrisReservedWordsConstant:
    """Tests for the IRIS_RESERVED_WORDS frozenset."""

    def test_is_frozenset(self):
        assert isinstance(IRIS_RESERVED_WORDS, frozenset)

    def test_contains_select(self):
        assert "SELECT" in IRIS_RESERVED_WORDS

    def test_contains_rowid(self):
        assert "ROWID" in IRIS_RESERVED_WORDS

    def test_does_not_contain_lowercase(self):
        # The set holds uppercase only
        assert "select" not in IRIS_RESERVED_WORDS

    def test_non_reserved_word_absent(self):
        assert "FOOBAR" not in IRIS_RESERVED_WORDS


class TestReservedWordCheckerIsReserved:
    """Tests for ReservedWordChecker.is_reserved()."""

    def setup_method(self):
        self.checker = ReservedWordChecker()

    def test_empty_string_is_not_reserved(self):
        assert self.checker.is_reserved("") is False

    def test_reserved_word_uppercase_returns_true(self):
        assert self.checker.is_reserved("SELECT") is True

    def test_reserved_word_lowercase_returns_true(self):
        assert self.checker.is_reserved("select") is True

    def test_reserved_word_mixed_case_returns_true(self):
        assert self.checker.is_reserved("SeLeCt") is True

    def test_non_reserved_word_returns_false(self):
        assert self.checker.is_reserved("my_column") is False

    def test_rowid_is_reserved(self):
        assert self.checker.is_reserved("rowid") is True


class TestReservedWordCheckerQuoteIfNeeded:
    """Tests for ReservedWordChecker.quote_if_needed()."""

    def setup_method(self):
        self.checker = ReservedWordChecker()

    def test_reserved_word_gets_quoted(self):
        assert self.checker.quote_if_needed("SELECT") == '"SELECT"'

    def test_reserved_word_lowercase_gets_quoted(self):
        assert self.checker.quote_if_needed("select") == '"select"'

    def test_non_reserved_word_unchanged(self):
        assert self.checker.quote_if_needed("my_column") == "my_column"

    def test_already_quoted_identifier_unchanged(self):
        assert self.checker.quote_if_needed('"SELECT"') == '"SELECT"'

    def test_already_quoted_non_reserved_unchanged(self):
        assert self.checker.quote_if_needed('"my_column"') == '"my_column"'
