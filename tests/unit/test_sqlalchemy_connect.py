"""What SQLAlchemy 2's postgresql+psycopg dialect sends while connecting and reflecting.

Measured with ``create_engine(..., echo=True)`` and a psycopg cursor trace against PostgreSQL 16
(iris-pgwire-pgref) on 2026-11-14. ``engine.connect()`` sends, in order:

    select pg_catalog.version()
    select current_schema()
    show transaction isolation level
    show standard_conforming_strings
    SELECT typname AS name, oid, typarray AS array_oid, oid::regtype::text AS regtype,
           typdelim AS delimiter FROM pg_type t WHERE t.oid = to_regtype($1) ORDER BY t.oid
                                                    -- psycopg's TypeInfo.fetch(conn, "hstore")

and ``MetaData.create_all()`` asks ``has_table`` with ``relkind = ANY (ARRAY[$2::VARCHAR, ...])``
and ``pg_catalog.pg_table_is_visible(pg_class.oid)``. PostgreSQL's answers are the expectations
here; the SQL is given in the shape PGWire's translation pipeline hands to the executor
(``$n`` -> ``?``, casts as ``CAST``, identifiers upper-cased), which is what the interceptor and
the rewrites see.
"""

from __future__ import annotations

import time

import pytest

from iris_pgwire.catalog.type_info import resolve_regtype
from iris_pgwire.sql_translator.array_params import rewrite_any_array_constructor
from iris_pgwire.sql_translator.interceptor import SQLInterceptor
from iris_pgwire.sql_translator.pg_functions import (
    has_pg_function_call,
    rewrite_pg_function_calls,
)


class FakeExecutor:
    iris_namespace = "USER"


@pytest.fixture
def interceptor():
    return SQLInterceptor(FakeExecutor())


def _answer(interceptor, sql, params=None):
    result = interceptor.intercept(sql, params)
    assert result.intercepted, f"not intercepted: {sql!r}"
    return result.result


# ---------------------------------------------------------------------------
# current_schema() / current_schemas(bool)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "select current_schema()",
        "SELECT CURRENT_SCHEMA()",
        "SELECT CURRENT_SCHEMA();",
        "select pg_catalog.current_schema()",
        "SELECT PG_CATALOG.CURRENT_SCHEMA ( )",
        "select current_schema",
        "  select current_schema ;",
    ],
)
def test_current_schema_is_public(interceptor, sql):
    """PostgreSQL 16 answers `public`. PGWire reports the IRIS schema as `public` everywhere else
    (pg_namespace via PGWire.PG_PUBLIC_SCHEMA(), information_schema's reverse map), so the
    schema unqualified names resolve to has to be called `public` too."""
    answer = _answer(interceptor, sql)
    assert answer["rows"] == [["public"]]
    assert [c["name"] for c in answer["columns"]] == ["current_schema"]
    assert answer["columns"][0]["type_oid"] == 19  # name


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("select current_schemas(false)", "{public}"),
        ("SELECT CURRENT_SCHEMAS(FALSE)", "{public}"),
        ("SELECT CURRENT_SCHEMAS(TRUE);", "{pg_catalog,public}"),
        ("select pg_catalog.current_schemas(true)", "{pg_catalog,public}"),
        ("SELECT CURRENT_SCHEMAS(0)", "{public}"),
        ("SELECT CURRENT_SCHEMAS(1)", "{pg_catalog,public}"),
    ],
)
def test_current_schemas_lists_the_search_path(interceptor, sql, expected):
    """PostgreSQL 16: current_schemas(false) = {public}, current_schemas(true) =
    {pg_catalog,public}, typed name[] (OID 1003)."""
    answer = _answer(interceptor, sql)
    assert answer["rows"] == [[expected]]
    assert [c["name"] for c in answer["columns"]] == ["current_schemas"]
    assert answer["columns"][0]["type_oid"] == 1003


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT CURRENT_SCHEMA() AS S, 1",
        "SELECT * FROM CURRENT_SCHEMA_LOG",
        "SELECT NSPNAME FROM PG_NAMESPACE WHERE NSPNAME = CURRENT_SCHEMA()",
    ],
)
def test_current_schema_inside_a_larger_statement_is_not_answered_whole(interceptor, sql):
    assert not interceptor.intercept(sql).intercepted


@pytest.mark.parametrize(
    "sql, rewritten",
    [
        (
            "SELECT NSPNAME FROM PG_NAMESPACE WHERE NSPNAME = CURRENT_SCHEMA()",
            "SELECT NSPNAME FROM PG_NAMESPACE WHERE NSPNAME = PGWire.PG_PUBLIC_SCHEMA()",
        ),
        (
            "select n.nspname from pg_namespace n where n.nspname = pg_catalog.current_schema( )",
            "select n.nspname from pg_namespace n where n.nspname = PGWire.PG_PUBLIC_SCHEMA()",
        ),
    ],
)
def test_embedded_current_schema_calls_the_pgwire_function(sql, rewritten):
    """Inside a statement IRIS evaluates, current_schema() becomes PGWire.PG_PUBLIC_SCHEMA(),
    the function pg_namespace already uses for the same name."""
    assert has_pg_function_call(sql)
    assert rewrite_pg_function_calls(sql) == rewritten


def test_a_column_named_like_current_schema_is_left_alone():
    sql = "SELECT MY_CURRENT_SCHEMA(1), T.CURRENT_SCHEMA FROM T"
    assert rewrite_pg_function_calls(sql) == sql


# ---------------------------------------------------------------------------
# SHOW
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql, column",
    [
        ("show transaction_read_only", "transaction_read_only"),
        ("SHOW TRANSACTION_READ_ONLY;", "transaction_read_only"),
        ("show transaction_deferrable", "transaction_deferrable"),
    ],
)
def test_show_transaction_read_only_and_deferrable_are_off(interceptor, sql, column):
    """PostgreSQL 16 answers `off` for both outside a READ ONLY / DEFERRABLE transaction.
    PGWire never starts one, so `off` is the truth, not the generic `unknown`."""
    answer = _answer(interceptor, sql)
    assert answer["rows"] == [["off"]]
    assert answer["columns"][0]["name"] == column


def test_show_standard_conforming_strings_is_still_on(interceptor):
    assert _answer(interceptor, "show standard_conforming_strings")["rows"] == [["on"]]


# ---------------------------------------------------------------------------
# psycopg's TypeInfo.fetch() query
# ---------------------------------------------------------------------------

# As psycopg 3.3 sends it, and as PGWire's pipeline hands it to the executor.
TYPE_INFO_RAW = (
    "SELECT\n    typname AS name, oid, typarray AS array_oid,\n"
    "    oid::regtype::text AS regtype, typdelim AS delimiter\nFROM pg_type t\n"
    "WHERE t.oid = to_regtype($1)\nORDER BY t.oid\n"
)
TYPE_INFO_TRANSLATED = (
    "SELECT TYPNAME AS NAME, OID, TYPARRAY AS ARRAY_OID, OID::TEXT AS REGTYPE, "
    'TYPDELIM AS DELIMITER FROM PG_CATALOG."PG_TYPE" T WHERE T.OID = TO_REGTYPE(?) ORDER BY T.OID'
)
TYPE_INFO_COLUMNS = [
    ("name", 19),
    ("oid", 26),
    ("array_oid", 26),
    ("regtype", 25),
    ("delimiter", 18),
]


@pytest.mark.parametrize("sql", [TYPE_INFO_RAW, TYPE_INFO_TRANSLATED, TYPE_INFO_TRANSLATED + ";"])
def test_type_info_for_hstore_is_empty(interceptor, sql):
    """No hstore extension, so PostgreSQL 16 returns no row; SQLAlchemy then turns native hstore
    off and carries on. An error here aborts engine.connect()."""
    answer = _answer(interceptor, sql, ["hstore"])
    assert answer["rows"] == []
    assert [(c["name"], c["type_oid"]) for c in answer["columns"]] == TYPE_INFO_COLUMNS


@pytest.mark.parametrize(
    "name, row",
    [
        # Each row is PostgreSQL 16's own answer (oid::regtype::text included), except vector's
        # OIDs, which PGWire's pg_type renumbers to 16388/16389.
        ("vector", ["vector", 16388, 16389, "vector", ","]),
        ("int4", ["int4", 23, 1007, "integer", ","]),
        ("integer", ["int4", 23, 1007, "integer", ","]),
        ("INT4", ["int4", 23, 1007, "integer", ","]),
        ("pg_catalog.int4", ["int4", 23, 1007, "integer", ","]),
        ('"int4"', ["int4", 23, 1007, "integer", ","]),
        ("int4[]", ["_int4", 1007, 0, "integer[]", ","]),
        ("double precision", ["float8", 701, 1022, "double precision", ","]),
        ("character varying(10)", ["varchar", 1043, 1015, "character varying", ","]),
        ("timestamptz", ["timestamptz", 1184, 1185, "timestamp with time zone", ","]),
        ("jsonb", ["jsonb", 3802, 3807, "jsonb", ","]),
    ],
)
def test_type_info_resolves_names_like_to_regtype(interceptor, name, row):
    answer = _answer(interceptor, TYPE_INFO_TRANSLATED, [name])
    assert answer["rows"] == [row]


@pytest.mark.parametrize("name", ["hstore", "public.hstore", "no_such_type", "", None])
def test_resolve_regtype_returns_none_for_unknown_types(name):
    assert resolve_regtype(name) is None


def test_type_info_described_without_parameters_has_the_columns(interceptor):
    """Describe runs the statement before any value is bound."""
    answer = _answer(interceptor, TYPE_INFO_TRANSLATED, None)
    assert answer["rows"] == []
    assert [(c["name"], c["type_oid"]) for c in answer["columns"]] == TYPE_INFO_COLUMNS


def test_other_to_regtype_queries_are_not_answered_with_type_info_columns(interceptor):
    """psycopg's EnumInfo and CompositeInfo queries also call to_regtype() but project other
    columns. Answering them with TypeInfo's five would be a confidently wrong shape."""
    enum_query = (
        "SELECT NAME, OID, ARRAY_OID, ARRAY_AGG(LABEL) AS LABELS FROM (SELECT T.TYPNAME AS NAME, "
        "T.OID AS OID, T.TYPARRAY AS ARRAY_OID, E.ENUMLABEL AS LABEL FROM PG_TYPE T LEFT JOIN "
        "PG_ENUM E ON E.ENUMTYPID = T.OID WHERE T.OID = TO_REGTYPE(?) ORDER BY E.ENUMSORTORDER) X "
        "GROUP BY NAME, OID, ARRAY_OID"
    )
    assert not interceptor.intercept(enum_query, ["mood"]).intercepted


# ---------------------------------------------------------------------------
# has_table: ANY (ARRAY[...]) and pg_table_is_visible()
# ---------------------------------------------------------------------------

HAS_TABLE = (
    "SELECT PG_CATALOG.PG_CLASS.RELNAME FROM PG_CATALOG.PG_CLASS JOIN PG_CATALOG.PG_NAMESPACE "
    "ON PG_CATALOG.PG_NAMESPACE.OID = PG_CATALOG.PG_CLASS.RELNAMESPACE WHERE "
    "PG_CATALOG.PG_CLASS.RELNAME = CAST(? AS VARCHAR) AND PG_CATALOG.PG_CLASS.RELKIND = ANY "
    "(ARRAY[CAST(? AS VARCHAR), CAST(? AS VARCHAR), CAST(? AS VARCHAR), CAST(? AS VARCHAR), "
    "CAST(? AS VARCHAR)]) AND PG_CATALOG.PG_TABLE_IS_VISIBLE(PG_CATALOG.PG_CLASS.OID) AND "
    "PG_CATALOG.PG_NAMESPACE.NSPNAME != CAST(? AS VARCHAR)"
)


def test_any_of_an_array_constructor_becomes_in():
    rewritten = rewrite_any_array_constructor(HAS_TABLE)
    assert (
        "PG_CATALOG.PG_CLASS.RELKIND IN (CAST(? AS VARCHAR), CAST(? AS VARCHAR), "
        "CAST(? AS VARCHAR), CAST(? AS VARCHAR), CAST(? AS VARCHAR)) AND" in rewritten
    )
    assert "ARRAY" not in rewritten
    assert rewritten.count("?") == HAS_TABLE.count("?")  # parameter positions do not move


@pytest.mark.parametrize(
    "sql, rewritten",
    [
        ("select 1 where x = any (array[1, 2])", "select 1 where x IN (1, 2)"),
        ("SELECT 1 WHERE X = ANY(ARRAY[$1, $2])", "SELECT 1 WHERE X IN ($1, $2)"),
        ("SELECT 1 WHERE X = ANY(ARRAY[F(1, 2), G(3)])", "SELECT 1 WHERE X IN (F(1, 2), G(3))"),
        ("SELECT 1 WHERE X = ANY(ARRAY[])", "SELECT 1 WHERE X IN (NULL)"),
    ],
)
def test_any_array_constructor_shapes(sql, rewritten):
    assert rewrite_any_array_constructor(sql) == rewritten


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 WHERE X = ANY(?)",  # a bound array: %INLIST's job
        "SELECT 1 WHERE X = ANY('{a,b}')",  # an array literal: expand_array_literals' job
        "SELECT 1 WHERE X = ANY(SELECT Y FROM T)",  # standard SQL IRIS runs itself
        "SELECT ARRAY[1, 2]",  # no membership test
    ],
)
def test_other_any_forms_are_left_alone(sql):
    assert rewrite_any_array_constructor(sql) == sql


def test_pg_table_is_visible_in_a_predicate_is_true():
    """Every relation PGWire's pg_class lists is in `public`, which is on the search path and is
    the only schema that holds user relations, so PostgreSQL would answer true for each one."""
    rewritten = rewrite_pg_function_calls(rewrite_any_array_constructor(HAS_TABLE))
    assert "PG_TABLE_IS_VISIBLE" not in rewritten.upper()
    assert "CAST(? AS VARCHAR)) AND 1 = 1 AND PG_CATALOG.PG_NAMESPACE.NSPNAME" in rewritten


@pytest.mark.parametrize(
    "sql",
    [
        "select c.relname from pg_class c where pg_table_is_visible(c.oid)",
        "select c.relname from pg_class c where c.relkind = 'r' or pg_catalog.pg_table_is_visible(c.oid)",
    ],
)
def test_pg_table_is_visible_after_where_or_or(sql):
    rewritten = rewrite_pg_function_calls(sql)
    assert "pg_table_is_visible" not in rewritten.lower()
    assert rewritten.endswith("1 = 1")


def test_pg_table_is_visible_outside_a_predicate_is_left_for_iris_to_refuse():
    """A projected boolean has no IRIS spelling here; leaving it is an honest error."""
    sql = "select pg_table_is_visible(c.oid) from pg_class c"
    assert rewrite_pg_function_calls(sql) == sql


# ---------------------------------------------------------------------------
# Cost: the 5 ms translation budget
# ---------------------------------------------------------------------------


def test_the_new_checks_cost_well_under_the_budget(interceptor):
    plain = (
        'INSERT INTO SQLUser."SQLA_CORE" (ID, NAME) VALUES (CAST(? AS INTEGER), CAST(? AS VARCHAR))'
    )
    started = time.perf_counter()
    for _ in range(1000):
        interceptor.intercept(plain, [1, "a"])
        rewrite_any_array_constructor(plain)
        rewrite_pg_function_calls(plain)
        rewrite_pg_function_calls(rewrite_any_array_constructor(HAS_TABLE))
    per_query_ms = (time.perf_counter() - started) * 1000 / 1000
    assert per_query_ms < 1.0


# ---------------------------------------------------------------------------
# insertmanyvalues: `p0::VARCHAR` is a column reference, not the literal 0
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql, expected",
    [
        ("SELECT p0::VARCHAR FROM t", "SELECT p0::VARCHAR FROM t"),
        ("SELECT t.c1::int FROM t", "SELECT t.c1::int FROM t"),
        ("SELECT 10::int", "SELECT CAST(10 AS INTEGER)"),
        ("SELECT x, 0::int", "SELECT x, CAST(0 AS INTEGER)"),
    ],
)
def test_a_cast_on_a_name_ending_in_digits_is_not_a_cast_on_a_number(sql, expected):
    """SQLAlchemy's ORM insert projects `p0::VARCHAR` from its VALUES list; the cast rewrite read
    the `0` as a number and produced `PCAST(0 AS VARCHAR)`."""
    from iris_pgwire.sql_translator.normalizer import SQLTranslator

    assert SQLTranslator().translate_postgres_parameters(sql) == expected
