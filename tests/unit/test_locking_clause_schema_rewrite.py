"""Spec 052 US3: the schema rewrite leaves a row-locking clause alone.

`translate_input_schema` qualifies the word after `UPDATE` as a table, which is right for
`UPDATE t SET ...` and wrong for `FOR UPDATE NOWAIT`: it became `FOR UPDATE SQLUser."NOWAIT"`,
and `FOR UPDATE OF a` became `FOR UPDATE SQLUser."OF" A` (measured 2026-11-14), so the locking
clause could no longer be recognised.
"""

from __future__ import annotations

import pytest

from iris_pgwire.schema_mapper import translate_input_schema


@pytest.mark.parametrize(
    "tail",
    [
        "FOR UPDATE NOWAIT",
        "FOR UPDATE SKIP LOCKED",
        "FOR UPDATE OF lock_c",
        "FOR NO KEY UPDATE NOWAIT",
        "for update nowait",
    ],
)
def test_the_word_after_for_update_is_not_a_table(tail):
    out = translate_input_schema(f"SELECT n FROM lock_c WHERE id = 1 {tail}")
    assert out.endswith(tail), out
    assert 'SQLUser."LOCK_C"' in out


def test_a_plain_update_is_still_qualified():
    assert translate_input_schema("UPDATE lock_c SET n = 1").startswith('UPDATE SQLUser."LOCK_C"')


@pytest.mark.parametrize("tail", ["FOR UPDATE", "FOR SHARE NOWAIT", "WINDOW w AS (ORDER BY n)"])
def test_group_by_wrapping_stops_at_a_locking_clause(tail):
    """The GROUP BY collation rewrite wrapped the clause too: `GROUP BY %EXACT(N FOR UPDATE)`."""
    from iris_pgwire.sql_translator.refiner import RefinerConfig, SQLRefiner

    refined = SQLRefiner(RefinerConfig(enforce_exact_collation=True)).refine(
        f"SELECT n FROM t GROUP BY n {tail}"
    )
    assert refined.endswith(f"%EXACT(n) {tail}"), refined
