"""The SQLGlot corpus export: PostgreSQL-in / IRIS-out pairs taken from the translator's tests.

The exporter keeps a pair only when a test asserts the exact output and re-running the
translation now gives that output, so the corpus holds hand-written answers, never the
translator's own output standing in for one.
"""

from __future__ import annotations

import importlib.util
import json
import textwrap
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_sqlglot_corpus.py"
_spec = importlib.util.spec_from_file_location("export_sqlglot_corpus", _SCRIPT)
_exporter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_exporter)
CORPUS, extract_pairs, verify_corpus = (
    _exporter.CORPUS,
    _exporter.extract_pairs,
    _exporter.verify_corpus,
)

_MODULE = textwrap.dedent("""
    import pytest

    def shout(sql):
        return sql.upper()

    def test_direct():
        assert shout("select 1") == "SELECT 1"

    def test_through_a_name():
        out = shout("select 2")
        assert out == "SELECT 2"

    def test_reversed_sides():
        assert "SELECT 3" == shout("select 3")

    @pytest.mark.parametrize("pg, iris", [("select 4", "SELECT 4"), ("select 5", "SELECT 5")])
    def test_parametrized(pg, iris):
        assert shout(pg) == iris

    def test_wrong_expectation_is_dropped():
        assert shout("select 6") == "select 6"

    def test_shape_only_is_dropped():
        assert "SELECT" in shout("select 7")

    def test_not_sql_is_dropped():
        assert shout("abc") == "ABC"

    class TestOnAnInstance:
        def setup_method(self):
            self.f = shout

        def test_method(self):
            assert self.f("select 8") == "SELECT 8"

        @pytest.fixture
        def loud(self):
            return self.f

        def test_a_class_fixture_is_resolved(self, loud):
            assert loud("select 13") == "SELECT 13"

    def test_a_builtin_fixture_is_skipped(tmp_path):
        assert shout("select 9") == "SELECT 9"

    @pytest.fixture
    def translator():
        return shout

    @pytest.fixture
    def wrapped(translator):
        yield translator

    def test_a_module_fixture_is_resolved(wrapped):
        assert wrapped("select 10") == "SELECT 10"

    def command_tag(sql):
        return sql.split()[0].upper()

    def test_a_non_sql_result_is_dropped():
        assert command_tag("select 11") == "SELECT"

    def column_label(sql):
        return "?column?"

    def test_a_label_is_dropped():
        assert column_label("select 12") == "?column?"
    """)


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "test_fake_translator.py"
    path.write_text(_MODULE)
    return path


def test_it_keeps_exact_assertions_that_hold_today(tmp_path):
    pairs = extract_pairs([_write(tmp_path)])
    assert sorted((p["pg"], p["iris"]) for p in pairs) == [
        ("select 1", "SELECT 1"),
        ("select 10", "SELECT 10"),
        ("select 13", "SELECT 13"),
        ("select 2", "SELECT 2"),
        ("select 3", "SELECT 3"),
        ("select 4", "SELECT 4"),
        ("select 5", "SELECT 5"),
        ("select 8", "SELECT 8"),
    ]


def test_each_pair_names_its_test_and_stage(tmp_path):
    pairs = {p["pg"]: p for p in extract_pairs([_write(tmp_path)])}
    assert pairs["select 1"]["note"] == "test_fake_translator.py::test_direct; stage: shout"
    assert pairs["select 8"]["note"] == (
        "test_fake_translator.py::TestOnAnInstance::test_method; stage: self.f"
    )
    assert "iris_version" not in pairs["select 1"]


def test_the_committed_corpus_still_holds():
    """Every pair in the committed file is re-derived from today's tests: none is stale."""
    lines = CORPUS.read_text().splitlines()
    assert lines, "the corpus is empty"
    assert all(set(json.loads(line)) <= {"pg", "iris", "note", "iris_version"} for line in lines)
    assert verify_corpus() == []


_FRAGMENTS = textwrap.dedent("""
    def shout(sql):
        return sql.upper().replace("LIMIT 5", "TOP 5")

    def test_fragments():
        out = shout("select a from t limit 5")
        assert "TOP 5" in out
        assert "SELECT A" in out
        assert "LIMIT" not in out

    def test_a_fragment_that_fails_today_drops_the_case():
        out = shout("select b limit 5")
        assert "TOP 5" in out
        assert "LIMIT 5" in out

    def test_direct_call():
        assert "FROM U" in shout("select c from u")

    def test_exact_only_is_not_a_fragment_case():
        assert shout("select d") == "SELECT D"

    def command_tag(sql):
        return "SELECT 1"

    def test_a_non_translation_is_dropped():
        assert "SELECT" in command_tag("select e")
""")


def test_fragment_cases_group_a_tests_assertions_on_one_output(tmp_path):
    path = tmp_path / "test_fake_fragments.py"
    path.write_text(_FRAGMENTS)
    cases = sorted(_exporter.extract_fragments([path]), key=lambda c: c["pg"])
    assert cases == [
        {
            "pg": "select a from t limit 5",
            "iris_contains": ["TOP 5", "SELECT A"],
            "iris_excludes": ["LIMIT"],
            "note": "test_fake_fragments.py::test_fragments; stage: shout",
        },
        {
            "pg": "select c from u",
            "iris_contains": ["FROM U"],
            "iris_excludes": [],
            "note": "test_fake_fragments.py::test_direct_call; stage: shout",
        },
    ]


def test_the_committed_fragments_still_hold():
    lines = _exporter.FRAGMENTS.read_text().splitlines()
    assert lines, "the fragment file is empty"
    assert _exporter.verify_fragments() == []
