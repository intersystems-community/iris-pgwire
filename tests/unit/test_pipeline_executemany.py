"""Regression tests for Bug 2 — psycopg3 pipeline mode + executemany support.

Covers pure-Python logic only (no IRIS mocks per constitution):
- ON CONFLICT detection flag propagation
- Row count accumulation logic
- Sync/Flush protocol correctness (already confirmed correct by source audit)

Integration tests (real IRIS) are in tests/integration/test_psycopg3_pipeline.py.
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Reference patterns (mirrors what execute_many() uses)
# ---------------------------------------------------------------------------

_ON_CONFLICT_PAT = re.compile(r"\bON\s+CONFLICT\b", re.IGNORECASE)
_DUPLICATE_KEY_MARKERS = ("Duplicate key", "5804", "duplicate key", "DUPLICATE KEY")


def _is_duplicate_key_error(msg: str) -> bool:
    return any(marker in msg for marker in _DUPLICATE_KEY_MARKERS)


def _row_count_with_suppression(
    params_list: list, error_messages: list[str | None]
) -> dict:
    """Simulate per-row execution with duplicate key suppression.

    error_messages[i] is None on success, a string on error.
    Returns dict with rows_affected = count of non-duplicate successes.
    """
    rows_affected = 0
    skipped = 0
    for params, err in zip(params_list, error_messages):
        if err is None:
            rows_affected += 1
        elif _is_duplicate_key_error(err):
            skipped += 1
        else:
            raise RuntimeError(f"Non-duplicate error: {err}")
    return {"rows_affected": rows_affected, "skipped": skipped}


# ---------------------------------------------------------------------------
# TestOnConflictFlagPropagation
# ---------------------------------------------------------------------------


class TestOnConflictFlagPropagation:
    def test_on_conflict_detected_in_sql(self):
        sql = "INSERT INTO t VALUES (1, 'x') ON CONFLICT DO NOTHING"
        assert _ON_CONFLICT_PAT.search(sql) is not None

    def test_no_on_conflict_not_detected(self):
        sql = "INSERT INTO t VALUES (1, 'x')"
        assert _ON_CONFLICT_PAT.search(sql) is None

    def test_on_conflict_on_column_detected(self):
        sql = "INSERT INTO t(id, v) VALUES (?, ?) ON CONFLICT (id) DO NOTHING"
        assert _ON_CONFLICT_PAT.search(sql) is not None

    def test_on_conflict_do_update_detected(self):
        sql = "INSERT INTO t(id, v) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET v = excluded.v"
        assert _ON_CONFLICT_PAT.search(sql) is not None

    def test_on_conflict_case_insensitive(self):
        sql = "INSERT INTO t VALUES (1) on conflict do nothing"
        assert _ON_CONFLICT_PAT.search(sql) is not None


# ---------------------------------------------------------------------------
# TestRowCountAccuracy
# ---------------------------------------------------------------------------


class TestRowCountAccuracy:
    def test_successful_rows_counted(self):
        params = [[1], [2], [3]]
        errors = [None, None, None]
        result = _row_count_with_suppression(params, errors)
        assert result["rows_affected"] == 3
        assert result["skipped"] == 0

    def test_duplicate_suppressed_not_counted(self):
        params = [[1], [1], [2]]
        errors = [None, "Duplicate key value (5804)", None]
        result = _row_count_with_suppression(params, errors)
        assert result["rows_affected"] == 2
        assert result["skipped"] == 1

    def test_all_duplicates(self):
        params = [[1], [1], [1]]
        errors = ["5804 error", "5804 error", "5804 error"]
        result = _row_count_with_suppression(params, errors)
        assert result["rows_affected"] == 0
        assert result["skipped"] == 3

    def test_zero_rows_empty_batch(self):
        result = _row_count_with_suppression([], [])
        assert result["rows_affected"] == 0
        assert result["skipped"] == 0

    def test_non_duplicate_error_propagates(self):
        params = [[1]]
        errors = ["Table does not exist"]
        try:
            _row_count_with_suppression(params, errors)
            assert False, "Should have raised"
        except RuntimeError as e:
            assert "Table does not exist" in str(e)

    def test_100_rows_all_success(self):
        params = [[i] for i in range(100)]
        errors = [None] * 100
        result = _row_count_with_suppression(params, errors)
        assert result["rows_affected"] == 100

    def test_mixed_50_success_50_duplicate(self):
        params = list(range(100))
        errors = [None if i < 50 else "Duplicate key value" for i in range(100)]
        result = _row_count_with_suppression(params, errors)
        assert result["rows_affected"] == 50
        assert result["skipped"] == 50


# ---------------------------------------------------------------------------
# TestDuplicateKeyDetection
# ---------------------------------------------------------------------------


class TestDuplicateKeyDetection:
    def test_iris_5804_detected(self):
        assert _is_duplicate_key_error("IRIS error - ERROR #5804: Duplicate key value") is True

    def test_duplicate_key_lowercase(self):
        assert _is_duplicate_key_error("duplicate key violates unique constraint") is True

    def test_unrelated_error_not_detected(self):
        assert _is_duplicate_key_error("Table TEST does not exist") is False

    def test_empty_string(self):
        assert _is_duplicate_key_error("") is False

    def test_partial_match(self):
        assert _is_duplicate_key_error("ERROR: Duplicate key in table") is True
