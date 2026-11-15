"""String columns PGWire creates get IRIS's exact collation, so they compare as PostgreSQL's do.

IRIS's default for a string column is `%SQLUPPER`: `=`, `IN`, `LIKE` and unique keys ignore case.
PostgreSQL's collations are case-sensitive, so a `CREATE TABLE` or `ALTER TABLE ... ADD` through
PGWire declares each character column `COLLATE %EXACT` (measured on IRIS 2026.2: equality, `IN`,
`LIKE` and unique keys then match PostgreSQL). A PostgreSQL `COLLATE "name"` becomes `%EXACT` too;
an IRIS collation (`%SQLUPPER`) the client wrote is kept.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.string_collation import exact_string_collation as fix


@pytest.mark.parametrize(
    "sql, expected",
    [
        (
            'CREATE TABLE SQLUser."T" (ID INT PRIMARY KEY, C VARCHAR(20), N INT)',
            'CREATE TABLE SQLUser."T" (ID INT PRIMARY KEY, C VARCHAR(20) COLLATE %EXACT, N INT)',
        ),
        (
            "create table t (c varchar(20) not null, d char(3) default 'x', e character varying(9))",
            "create table t (c varchar(20) COLLATE %EXACT not null, d char(3) COLLATE %EXACT "
            "default 'x', e character varying(9) COLLATE %EXACT)",
        ),
        (
            "create table t (c varchar, d character(2), e nvarchar(5), f char varying(4))",
            "create table t (c varchar COLLATE %EXACT, d character(2) COLLATE %EXACT, "
            "e nvarchar(5) COLLATE %EXACT, f char varying(4) COLLATE %EXACT)",
        ),
        (
            'create table if not exists "My T" ("Name" VARCHAR(20) UNIQUE, "v" int)',
            'create table if not exists "My T" ("Name" VARCHAR(20) COLLATE %EXACT UNIQUE, "v" int)',
        ),
        (
            "ALTER TABLE t ADD COLUMN c VARCHAR(10)",
            "ALTER TABLE t ADD COLUMN c VARCHAR(10) COLLATE %EXACT",
        ),
        (
            "alter table t add c varchar(10) not null",
            "alter table t add c varchar(10) COLLATE %EXACT not null",
        ),
    ],
)
def test_character_columns_get_exact_collation(sql, expected):
    assert fix(sql) == expected


@pytest.mark.parametrize(
    "sql, expected",
    [
        (
            'create table t (a VARCHAR(20) collate "C", b varchar(5) COLLATE "en_US")',
            "create table t (a VARCHAR(20) COLLATE %EXACT, b varchar(5) COLLATE %EXACT)",
        ),
        (
            'create table t (a varchar(20) collate pg_catalog."default")',
            "create table t (a varchar(20) COLLATE %EXACT)",
        ),
        (
            "create table t (a varchar(20) COLLATE %SQLUPPER, b varchar(3) collate %sqlstring)",
            "create table t (a varchar(20) COLLATE %SQLUPPER, b varchar(3) collate %sqlstring)",
        ),
    ],
)
def test_a_written_collation_is_postgres_or_kept(sql, expected):
    assert fix(sql) == expected


@pytest.mark.parametrize(
    "sql",
    [
        "create table t (id int, b text, j json, v vector(float, 3), d date, n numeric(10, 2))",
        "create table t as select c from u",
        "select c from t where c = 'varchar(20)'",
        "insert into t values ('create table x (c varchar(1))')",
        "create index i on t (c)",
        "alter table t drop column c",
        "alter table t add constraint u unique (c)",
        "create view v as select cast(c as varchar(10)) from t",
    ],
)
def test_everything_else_is_untouched(sql):
    assert fix(sql) == sql


def test_types_inside_defaults_checks_and_constraints_are_untouched():
    sql = (
        "create table t (id int, c varchar(10) default cast('a' as varchar(3)) "
        "check (c <> cast('b' as char(1))), "
        "constraint k unique (c), primary key (id), foreign key (c) references u (c))"
    )
    assert fix(sql) == (
        "create table t (id int, c varchar(10) COLLATE %EXACT default cast('a' as varchar(3)) "
        "check (c <> cast('b' as char(1))), "
        "constraint k unique (c), primary key (id), foreign key (c) references u (c))"
    )


def test_a_column_named_like_a_type_is_not_a_type():
    sql = 'create table t (varchar int, "char" varchar(2), text_col text)'
    assert (
        fix(sql) == 'create table t (varchar int, "char" varchar(2) COLLATE %EXACT, text_col text)'
    )


def test_an_array_of_strings_is_left_alone():
    sql = "create table t (tags varchar(10)[], c varchar(5))"
    assert fix(sql) == "create table t (tags varchar(10)[], c varchar(5) COLLATE %EXACT)"


def test_a_statement_without_ddl_costs_one_check():
    """Hot path: every statement passes through this; a SELECT must not be scanned (budget)."""
    import time

    sql = "SELECT id, name FROM users WHERE id = ? " + "AND name <> 'x' " * 200
    started = time.perf_counter()
    for _ in range(10000):
        fix(sql)
    per_call_us = (time.perf_counter() - started) / 10000 * 1e6
    assert per_call_us < 2, f"{per_call_us:.2f} us"


def test_whitespace_after_the_verb_can_be_any():
    assert (
        fix("ALTER\tTABLE t ADD c varchar(3)") == "ALTER\tTABLE t ADD c varchar(3) COLLATE %EXACT"
    )
    assert fix("CREATE\nTABLE t (c varchar(3))") == "CREATE\nTABLE t (c varchar(3) COLLATE %EXACT)"
