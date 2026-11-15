"""Spec 052 US4 (research R7): which ON CONFLICT statements IRIS's INSERT OR UPDATE expresses.

INSERT OR UPDATE matches on any unique key and writes every supplied column. That is
PostgreSQL's `ON CONFLICT (target) DO UPDATE` only when the target is the table's only unique key
and the update sets every inserted column from EXCLUDED, with no WHERE (FR-013). The suite's E3
table measured each other form differing. The classifier labels a statement `exact`, with the
rewrite, or names the inexact form so it can be refused by name (FR-014).
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.on_conflict import TableKeys, classify_on_conflict
from iris_pgwire.sql_translator.returning_plan import ReturningPlan

T = 'SQLUser."OC_M"'
PK_ONLY = TableKeys(unique_keys=(frozenset({"k"}),), columns=("k", "v", "w"))
TWO_KEYS = TableKeys(unique_keys=(frozenset({"k"}), frozenset({"v"})), columns=("k", "v", "w"))


def classify(sql, keys=PK_ONLY):
    return classify_on_conflict(ReturningPlan.from_sql(sql), keys)


def test_not_an_upsert_is_none():
    assert classify(f"INSERT INTO {T} (K, V, W) VALUES (?, ?, ?)") is None


def test_the_exact_form_is_rewritten_to_insert_or_update():
    decision = classify(
        f"INSERT INTO {T} (K, V, W) VALUES (?, ?, ?) "
        "ON CONFLICT (K) DO UPDATE SET V = EXCLUDED.V, W = EXCLUDED.W"
    )
    assert decision.form == "exact"
    assert decision.sql == f"INSERT OR UPDATE {T} (K, V, W) VALUES (?, ?, ?)"
    assert decision.message is None


def test_exact_without_a_column_list_uses_every_column():
    decision = classify(
        f"INSERT INTO {T} VALUES (1, 9, 9) ON CONFLICT (K) DO UPDATE "
        "SET V = EXCLUDED.V, W = EXCLUDED.W"
    )
    assert decision.form == "exact"
    assert decision.sql == f"INSERT OR UPDATE {T} VALUES (1, 9, 9)"


def test_exact_may_also_set_the_key_from_excluded():
    decision = classify(
        f"INSERT INTO {T} (K, V) VALUES (?, ?) ON CONFLICT (K) DO UPDATE "
        "SET K = EXCLUDED.K, V = EXCLUDED.V"
    )
    assert decision.form == "exact"


def test_lower_case_and_quoted_names():
    decision = classify(
        'insert into oc_m ("k", "v", "w") values ($1, $2, $3) '
        'on conflict ("k") do update set "v" = excluded."v", w = EXCLUDED.w'
    )
    assert decision.form == "exact"
    assert decision.sql == 'INSERT OR UPDATE oc_m ("k", "v", "w") values ($1, $2, $3)'


def test_returning_is_kept_out_of_the_rewrite():
    decision = classify(
        f"INSERT INTO {T} (K, V, W) VALUES (?, ?, ?) ON CONFLICT (K) DO UPDATE "
        "SET V = EXCLUDED.V, W = EXCLUDED.W RETURNING K, V"
    )
    assert decision.form == "exact"
    assert decision.sql == f"INSERT OR UPDATE {T} (K, V, W) VALUES (?, ?, ?)"


@pytest.mark.parametrize(
    "sql, keys, form",
    [
        (
            f"INSERT INTO {T} VALUES (1, 9, 9) ON CONFLICT (K) DO UPDATE SET V = EXCLUDED.V",
            PK_ONLY,
            "set_subset",
        ),
        (
            f"INSERT INTO {T} VALUES (1, 9, 9) ON CONFLICT (K) DO UPDATE "
            "SET V = OC_M.V + EXCLUDED.V, W = EXCLUDED.W",
            PK_ONLY,
            "set_not_from_excluded",
        ),
        (
            f"INSERT INTO {T} VALUES (1, 9, 9) ON CONFLICT (K) DO UPDATE "
            "SET V = EXCLUDED.W, W = EXCLUDED.V",
            PK_ONLY,
            "set_not_from_excluded",
        ),
        (
            f"INSERT INTO {T} (K, V) VALUES (1, 9) ON CONFLICT (K) DO UPDATE "
            "SET V = EXCLUDED.V, W = 0",
            PK_ONLY,
            "set_not_from_excluded",
        ),
        (
            f"INSERT INTO {T} VALUES (1, 9, 9) ON CONFLICT (K) DO UPDATE "
            "SET V = EXCLUDED.V, W = EXCLUDED.W WHERE OC_M.V > 100",
            PK_ONLY,
            "do_update_where",
        ),
        (
            f"INSERT INTO {T} VALUES (2, 1, 9) ON CONFLICT (K) DO UPDATE "
            "SET V = EXCLUDED.V, W = EXCLUDED.W",
            TWO_KEYS,
            "second_unique_key",
        ),
        (
            f"INSERT INTO {T} VALUES (1, 1, 9) ON CONFLICT (V) DO UPDATE "
            "SET K = EXCLUDED.K, W = EXCLUDED.W",
            PK_ONLY,
            "target_not_the_key",
        ),
        (f"INSERT INTO {T} VALUES (1, 1, 9) ON CONFLICT DO NOTHING", PK_ONLY, "do_nothing"),
        (f"INSERT INTO {T} VALUES (1, 1, 9) ON CONFLICT (K) DO NOTHING", PK_ONLY, "do_nothing"),
        (
            f"INSERT INTO {T} VALUES (1, 9, 9) ON CONFLICT ON CONSTRAINT OC_M_PKEY DO UPDATE "
            "SET V = EXCLUDED.V, W = EXCLUDED.W",
            PK_ONLY,
            "on_constraint",
        ),
        (
            f"INSERT INTO {T} (K, V, W) VALUES (1, 9, 9), (2, 9, 9) ON CONFLICT (K) DO UPDATE "
            "SET V = EXCLUDED.V, W = EXCLUDED.W",
            PK_ONLY,
            "multi_row",
        ),
        (
            f"INSERT INTO {T} (K, V, W) SELECT K, V, W FROM X ON CONFLICT (K) DO UPDATE "
            "SET V = EXCLUDED.V, W = EXCLUDED.W",
            PK_ONLY,
            "insert_select",
        ),
        (
            f"INSERT INTO {T} VALUES (1, 9, 9) ON CONFLICT (K) DO UPDATE "
            "SET V = EXCLUDED.V, W = EXCLUDED.W",
            TableKeys(unique_keys=(), columns=("k", "v", "w")),
            "target_not_the_key",
        ),
    ],
)
def test_inexact_forms_are_named(sql, keys, form):
    decision = classify(sql, keys)
    assert decision.form == form
    assert decision.sql is None
    assert decision.message and "IRIS" in decision.message
    assert "PGWIRE_TXN_COMPAT=permissive" in decision.message


def test_a_composite_target_matches_a_composite_key():
    keys = TableKeys(unique_keys=(frozenset({"a", "b"}),), columns=("a", "b", "v"))
    decision = classify(
        "INSERT INTO t (A, B, V) VALUES (?, ?, ?) ON CONFLICT (B, A) DO UPDATE SET V = EXCLUDED.V",
        keys,
    )
    assert decision.form == "exact"
    assert decision.sql == "INSERT OR UPDATE t (A, B, V) VALUES (?, ?, ?)"


def test_a_comma_inside_a_value_is_not_a_second_row():
    decision = classify(
        f"INSERT INTO {T} (K, V, W) VALUES (1, COALESCE(?, 2), ',') ON CONFLICT (K) "
        "DO UPDATE SET V = EXCLUDED.V, W = EXCLUDED.W"
    )
    assert decision.form == "exact"


def test_the_message_names_the_form():
    decision = classify(f"INSERT INTO {T} VALUES (1, 1, 9) ON CONFLICT DO NOTHING")
    assert "DO NOTHING" in decision.message


class TestInsertRowExpressions:
    """The permissive emulation reads the one VALUES row (2.0 read bound parameters only, so an
    upsert written with literals updated nothing and reported success)."""

    def test_literals_and_markers(self):
        from iris_pgwire.sql_translator.on_conflict import insert_row_expressions

        assert insert_row_expressions(f"INSERT INTO {T} VALUES (1, 'a,b', ?, COALESCE(?, 2))") == [
            "1",
            "'a,b'",
            "?",
            "COALESCE(?, 2)",
        ]

    def test_not_one_row(self):
        from iris_pgwire.sql_translator.on_conflict import insert_row_expressions

        assert insert_row_expressions(f"INSERT INTO {T} VALUES (1), (2)") is None
        assert insert_row_expressions(f"INSERT INTO {T} SELECT 1") is None
