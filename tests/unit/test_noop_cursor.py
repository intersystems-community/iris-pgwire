"""Tests for NoopCursor."""
import pytest

from iris_pgwire._noop_cursor import NoopCursor


class TestNoopCursor:
    def test_initial_description_is_none(self):
        cursor = NoopCursor()
        assert cursor.description is None

    def test_initial_rowcount_is_zero(self):
        cursor = NoopCursor()
        assert cursor.rowcount == 0

    def test_close_does_not_raise(self):
        cursor = NoopCursor()
        cursor.close()

    def test_fetchall_returns_empty_list(self):
        cursor = NoopCursor()
        assert cursor.fetchall() == []

    def test_fetchone_returns_none(self):
        cursor = NoopCursor()
        assert cursor.fetchone() is None

    def test_iter_yields_nothing(self):
        cursor = NoopCursor()
        assert list(cursor) == []

    def test_multiple_calls(self):
        cursor = NoopCursor()
        assert cursor.fetchall() == []
        assert cursor.fetchone() is None
        cursor.close()
        assert cursor.rowcount == 0
