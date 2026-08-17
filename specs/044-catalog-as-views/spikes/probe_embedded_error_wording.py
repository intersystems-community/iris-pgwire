"""T027: do the two backends word IRIS errors the same way? (They do not.)

`verify_sqlstate_e2e.py` measures the SQLSTATE a client receives over the wire,
but only against whichever backend the server is running. The classifier reads
the error *text*, and the text is backend-specific: DB-API delivers
`[SQLCODE: <-30>:<Table or view not found>]`, while the embedded backend
(`iris.sql.exec`) raises `Table 'SQLUSER.X' not found` with no SQLCODE anywhere.
Classifying only the DB-API wording would silently degrade to `42000` on the
default backend — which is exactly what the first run of this probe showed (2/5).

Run inside the IRIS container, where `irispython` provides the embedded API:

    docker cp src/iris_pgwire/sql_translator/sqlstate.py <container>:/tmp/sqlstate.py
    docker cp specs/044-catalog-as-views/spikes/probe_embedded_error_wording.py \\
        <container>:/tmp/probe.py
    docker exec <container> /usr/irissys/bin/irispython /tmp/probe.py

The classifier is loaded from `/tmp/sqlstate.py` rather than imported, because
the package is not installed in `irispython`.
"""

import importlib.util

import iris

spec = importlib.util.spec_from_file_location("sqlstate", "/tmp/sqlstate.py")
sqlstate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sqlstate)

TABLE = "SQLUser.T027Probe"

SETUP = [
    f"DROP TABLE IF EXISTS {TABLE}",
    f"CREATE TABLE {TABLE} (id INT NOT NULL PRIMARY KEY, name VARCHAR(10))",
    f"INSERT INTO {TABLE} (id, name) VALUES (1, 'a')",
]

# (label, sql, expected SQLSTATE) — expectations are what PostgreSQL 15 returns
# for the same shape, except where IRIS gives no way to tell two conditions
# apart (see the 22000 note in sqlstate.py).
CASES = [
    ("undefined table", "SELECT * FROM no_such_table_xyz", "42P01"),
    ("no such schema", "SELECT * FROM nosuchschema.nosuchtable", "42P01"),
    ("undefined column", f"SELECT no_such_col FROM {TABLE}", "42703"),
    ("undefined function", "SELECT no_such_function_xyz(1)", "42883"),
    ("syntax, reserved word", "SELECT FROM WHERE", "42601"),
    ("syntax, trailing input", f"SELECT 1 FROM {TABLE} ) extra", "42601"),
    ("syntax, dangling comma", f"SELECT id, FROM {TABLE}", "42601"),
    ("syntax, unbalanced quote", f"SELECT 'abc FROM {TABLE}", "42601"),
    ("unique violation", f"INSERT INTO {TABLE} (id, name) VALUES (1, 'b')", "23505"),
    ("not null violation", f"INSERT INTO {TABLE} (name) VALUES ('c')", "23502"),
    ("value too long", f"INSERT INTO {TABLE} (id, name) VALUES (2, 'way too long')", "22000"),
    ("bad numeric", f"INSERT INTO {TABLE} (id, name) VALUES ('notanint', 'd')", "22000"),
    ("internal failure", "SELECT $LISTGET('not a list', 1)", "XX000"),
]


def main():
    for sql in SETUP:
        try:
            iris.sql.exec(sql)
        except Exception as exc:
            print("  setup: %-40s %s" % (sql[:40], str(exc)[:70]))

    print("Embedded backend (iris.sql.exec) error wording -> SQLSTATE\n")
    passed = 0
    for label, sql, expected in CASES:
        try:
            list(iris.sql.exec(sql))
        except Exception as exc:
            text = str(exc).replace("\n", " ")
            state, _ = sqlstate.classify_iris_error(text)
            ok = state == expected
            passed += ok
            print(
                "  %s %-24s %-6s (want %s)  %s"
                % ("PASS" if ok else "FAIL", label, state, expected, text[:56])
            )
        else:
            print("  FAIL %-24s no error raised; the probe no longer measures anything" % label)

    try:
        iris.sql.exec(f"DROP TABLE IF EXISTS {TABLE}")
    except Exception:
        pass

    print("\n%d/%d classified as on the DB-API backend" % (passed, len(CASES)))
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
