"""Spec 052 FR-025/FR-026: strict or permissive, and one warning per statement shape.

In permissive mode a statement strict mode would refuse runs as it did in 2.0, and the server logs
one warning per distinct statement shape (data-model.md "Statement shape"): the text with literals
and parameter markers replaced and whitespace collapsed. The set of shapes already warned about
is bounded at 1000, oldest dropped, so it cannot grow without limit.
"""

from __future__ import annotations

import pytest

from iris_pgwire.compat_mode import CompatMode, statement_shape


def test_shape_replaces_literals_markers_and_collapses_whitespace():
    a = statement_shape("SELECT n FROM t\n  WHERE id = 1 AND s = 'x' FOR SHARE")
    b = statement_shape("select n from t where id = 42 and s = 'it''s' for share")
    c = statement_shape("SELECT n FROM t WHERE id = ? AND s = $2 FOR SHARE")
    assert a == b == c
    assert "42" not in b and "it" not in b


def test_shape_keeps_identifiers_apart():
    assert statement_shape("SELECT n FROM t FOR SHARE") != statement_shape(
        "SELECT n FROM u FOR SHARE"
    )
    assert statement_shape('SELECT "a1" FROM t') != statement_shape('SELECT "a2" FROM t')


def test_strict_is_the_default_and_does_not_allow():
    mode = CompatMode("strict")
    assert not mode.permissive


def test_permissive_warns_once_per_shape():
    mode = CompatMode("permissive")
    assert mode.permissive
    assert mode.first_time("SELECT n FROM t WHERE id = 1 FOR SHARE")
    assert not mode.first_time("SELECT n FROM t WHERE id = 2 FOR SHARE")
    assert mode.first_time("SELECT n FROM u WHERE id = 1 FOR SHARE")


def test_the_registry_is_bounded_oldest_dropped():
    mode = CompatMode("permissive", max_shapes=3)
    for table in ("a", "b", "c", "d"):
        assert mode.first_time(f"SELECT * FROM {table} FOR SHARE")
    assert len(mode) == 3
    assert mode.first_time("SELECT * FROM a FOR SHARE")  # dropped, so warned again
    assert not mode.first_time("SELECT * FROM d FOR SHARE")


def test_default_bound_is_1000():
    mode = CompatMode("permissive")
    for i in range(1100):
        mode.first_time(f"SELECT * FROM t{i} FOR SHARE")
    assert len(mode) == 1000


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        CompatMode("lenient")
