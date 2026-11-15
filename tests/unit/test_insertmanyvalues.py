"""SQLAlchemy 2's "insertmanyvalues" INSERT, split into one INSERT per row.

When the ORM flushes several new objects whose keys the database generates, SQLAlchemy 2.0
sends one statement for all of them and matches the RETURNING rows back to the objects by
order (measured on PostgreSQL 16, SQLAlchemy 2.0.54, 2026-11-14)::

    INSERT INTO sqla_orm (name) SELECT p0::VARCHAR FROM (VALUES (%(name__0)s::VARCHAR, 0),
    (%(name__1)s::VARCHAR, 1)) AS imp_sen(p0, sen_counter) ORDER BY sen_counter
    RETURNING sqla_orm.id, sqla_orm.id AS id__1

IRIS has no VALUES list in FROM. The rows are inserted one at a time, in sen_counter order,
which gives the RETURNING rows in the order SQLAlchemy relies on.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.insertmanyvalues import split_insertmanyvalues

# As PGWire's pipeline hands it to the executor (identifiers upper-cased, $n -> ?).
TWO_ROWS = (
    'INSERT INTO SQLUser."SQLA_ORM" (NAME) SELECT P0::VARCHAR FROM (VALUES (CAST(? AS VARCHAR), 0), '
    "(CAST(? AS VARCHAR), 1)) AS IMP_SEN(P0, SEN_COUNTER) ORDER BY SEN_COUNTER "
    "RETURNING SQLA_ORM.ID, SQLA_ORM.ID AS ID__1"
)


def test_two_rows_become_two_single_row_inserts_with_their_own_parameters():
    split = split_insertmanyvalues(TWO_ROWS, ("x", "y"))
    assert split == [
        (
            'INSERT INTO SQLUser."SQLA_ORM" (NAME) VALUES (CAST(? AS VARCHAR)) '
            "RETURNING SQLA_ORM.ID, SQLA_ORM.ID AS ID__1",
            ("x",),
        ),
        (
            'INSERT INTO SQLUser."SQLA_ORM" (NAME) VALUES (CAST(? AS VARCHAR)) '
            "RETURNING SQLA_ORM.ID, SQLA_ORM.ID AS ID__1",
            ("y",),
        ),
    ]


def test_rows_are_inserted_in_sen_counter_order_whatever_order_they_arrive_in():
    sql = (
        "INSERT INTO T (A, B) SELECT P0::INTEGER, P1::VARCHAR FROM (VALUES "
        "(CAST(? AS INTEGER), CAST(? AS VARCHAR), 1), (CAST(? AS INTEGER), CAST(? AS VARCHAR), 0)) "
        "AS IMP_SEN(P0, P1, SEN_COUNTER) ORDER BY SEN_COUNTER RETURNING T.ID"
    )
    split = split_insertmanyvalues(sql, (1, "one", 0, "zero"))
    assert [params for _, params in split] == [(0, "zero"), (1, "one")]
    assert split[0][0] == (
        "INSERT INTO T (A, B) VALUES (CAST(? AS INTEGER), CAST(? AS VARCHAR)) RETURNING T.ID"
    )


def test_lower_case_and_dollar_placeholders_and_a_trailing_semicolon():
    sql = (
        "insert into t (a) select p0::int from (values ($1::int, 0), ($2::int, 1)) "
        "as imp_sen(p0, sen_counter) order by sen_counter returning t.id;"
    )
    split = split_insertmanyvalues(sql, (5, 6))
    assert split == [
        ("insert into t (a) VALUES ($1::int) returning t.id", (5,)),
        ("insert into t (a) VALUES ($1::int) returning t.id", (6,)),
    ]


def test_a_comma_or_paren_inside_a_string_literal_is_not_a_separator():
    sql = (
        "INSERT INTO T (A, B) SELECT P0, P1 FROM (VALUES ('a, (b', CAST(? AS VARCHAR), 0), "
        "('it''s', CAST(? AS VARCHAR), 1)) AS IMP_SEN(P0, P1, SEN_COUNTER) ORDER BY SEN_COUNTER "
        "RETURNING T.ID"
    )
    split = split_insertmanyvalues(sql, ("p", "q"))
    assert [s for s, _ in split] == [
        "INSERT INTO T (A, B) VALUES ('a, (b', CAST(? AS VARCHAR)) RETURNING T.ID",
        "INSERT INTO T (A, B) VALUES ('it''s', CAST(? AS VARCHAR)) RETURNING T.ID",
    ]
    assert [p for _, p in split] == [("p",), ("q",)]


def test_described_without_parameters():
    split = split_insertmanyvalues(TWO_ROWS, None)
    assert [p for _, p in split] == [None, None]


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO T (A) VALUES (?) RETURNING T.ID",
        "INSERT INTO T (A) SELECT A FROM U",
        "SELECT * FROM (VALUES (1, 0)) AS IMP_SEN(P0, SEN_COUNTER)",
        # the select list reorders the VALUES columns: not SQLAlchemy's shape, not rewritten
        "INSERT INTO T (A, B) SELECT P1, P0 FROM (VALUES (1, 2, 0)) AS IMP_SEN(P0, P1, SEN_COUNTER) "
        "ORDER BY SEN_COUNTER",
    ],
)
def test_other_statements_are_not_split(sql):
    assert split_insertmanyvalues(sql, None) is None


def test_a_parameter_count_that_does_not_add_up_is_not_split():
    assert split_insertmanyvalues(TWO_ROWS, ("only one",)) is None
