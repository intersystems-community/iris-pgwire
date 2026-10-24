"""Phase 0 probes R1 and R2 for feature 051.

R1: Are ``iris.connect`` (used by IRISExecutor._execute_external_async,
    iris_executor.py:3640) and ``iris.dbapi.connect`` (used by the DBAPI pool,
    dbapi_connection_pool.py:313) the same adapter, or two?

R2: Can the embedded backend report per-column type metadata by ANY route?
    Measured previously: the iris.sql.exec result object has no ``_meta`` and
    every type code is None. Feature 045 left ``%SQL.Statement`` unverified.

Run inside the iris-pgwire-db container with irispython so both the embedded
and the driver surfaces are reachable in one process:

    docker cp probe_r1_r2_adapters.py iris-pgwire-db:/tmp/
    docker exec iris-pgwire-db /usr/irissys/bin/irispython /tmp/probe_r1_r2_adapters.py

Prints one ``KEY: value`` line per measurement. Every line is a fact for
research.md; nothing here is inferred.
"""

import traceback

HOST = "127.0.0.1"
PORT = 1972  # inside the container
NS = "USER"
USER = "_SYSTEM"
PWD = "SYS"

# Three columns whose types are distinguishable: varchar, integer, bit.
STMT_ROWS = "SELECT 'x' AS s, 42 AS i, CAST(1 AS BIT) AS b"
STMT_ZERO = "SELECT 'x' AS s, 42 AS i, CAST(1 AS BIT) AS b WHERE 1=0"
STMT_BAD = "SELECT * FROM SQLUser.NoSuchTable_051"


def out(key, value):
    print(f"{key}: {value}")


def describe(cursor):
    d = cursor.description
    if d is None:
        return "None"
        # A driver that reports nothing is a legitimate answer (spec FR-004).
    return repr([(c[0], c[1]) for c in d])


def probe_driver(label, connect_fn):
    """Run the R1 comparison for one connection factory."""
    conn = None
    try:
        conn = connect_fn()
        out(f"{label}.conn_type", type(conn).__module__ + "." + type(conn).__name__)
        cur = conn.cursor()
        out(f"{label}.cursor_type", type(cur).__module__ + "." + type(cur).__name__)

        cur.execute(STMT_ROWS)
        rows = cur.fetchall()
        out(f"{label}.rows", repr([tuple(r) for r in rows]))
        out(f"{label}.description_with_rows", describe(cur))
        out(f"{label}.rowcount_with_rows", cur.rowcount)

        cur2 = conn.cursor()
        cur2.execute(STMT_ZERO)
        z = cur2.fetchall()
        out(f"{label}.zero_rows", repr([tuple(r) for r in z]))
        out(f"{label}.description_zero_rows", describe(cur2))

        # Empty string versus NULL, the FR-017 case.
        cur3 = conn.cursor()
        cur3.execute("SELECT '' AS empty, NULL AS nul")
        r = cur3.fetchall()[0]
        out(f"{label}.empty_vs_null", repr((r[0], r[1])))

        # Error wording, the FR-018 case.
        try:
            cur4 = conn.cursor()
            cur4.execute(STMT_BAD)
            out(f"{label}.error", "NO ERROR RAISED")
        except Exception as e:  # noqa: BLE001 - the wording is the measurement
            out(f"{label}.error_type", type(e).__name__)
            out(f"{label}.error_text", repr(str(e)))
    except Exception as e:  # noqa: BLE001
        out(f"{label}.FAILED", repr(str(e)))
        out(f"{label}.traceback", traceback.format_exc().replace("\n", " | "))
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001, S110
                pass


def main():
    import iris

    print("=== R1: is iris.connect the same adapter as iris.dbapi.connect? ===")
    out("iris.__file__", getattr(iris, "__file__", "?"))
    out("iris.version", getattr(iris, "__version__", "?"))
    out("hasattr(iris,'dbapi')", hasattr(iris, "dbapi"))

    try:
        from iris import dbapi as iris_dbapi

        out("from iris import dbapi", "OK")
    except Exception as e:  # noqa: BLE001
        out("from iris import dbapi", f"FAILED {e!r}")
        iris_dbapi = None

    if iris_dbapi is not None:
        out("iris.connect is iris.dbapi.connect", iris.connect is iris_dbapi.connect)
        out("iris.connect", repr(iris.connect))
        out("iris.dbapi.connect", repr(iris_dbapi.connect))

    probe_driver("native", lambda: iris.connect(HOST, PORT, NS, USER, PWD))
    if iris_dbapi is not None:
        probe_driver(
            "dbapi",
            lambda: iris_dbapi.connect(
                hostname=HOST, port=PORT, namespace=NS, username=USER, password=PWD
            ),
        )

    print("=== R2: can the embedded backend report per-column types at all? ===")
    try:
        rs = iris.sql.exec(STMT_ROWS)
        out("embedded.result_type", type(rs).__module__ + "." + type(rs).__name__)
        out("embedded.dir", repr([a for a in dir(rs) if not a.startswith("__")]))
        out("embedded.has_meta", hasattr(rs, "_meta"))
        out("embedded.has_description", hasattr(rs, "description"))
        if hasattr(rs, "description"):
            out("embedded.description", repr(rs.description))
        embedded_rows = [list(r) for r in rs]
        out("embedded.rows", repr(embedded_rows))
    except Exception as e:  # noqa: BLE001
        out("embedded.FAILED", repr(str(e)))

    # R2's real question: is metadata reachable through %SQL.Statement, which
    # feature 045 flagged as unverified?
    try:
        stmt = iris.cls("%SQL.Statement")._New()
        sc = stmt.prepare(STMT_ROWS)
        out("sqlstatement.prepare_status", repr(sc))
        md = stmt.getvalue("%Metadata") if hasattr(stmt, "getvalue") else None
        out("sqlstatement.metadata_obj", repr(md))
        try:
            cols = stmt._GetColumnCount() if hasattr(stmt, "_GetColumnCount") else None
            out("sqlstatement.column_count", repr(cols))
        except Exception as e:  # noqa: BLE001
            out("sqlstatement.column_count_FAILED", repr(str(e)))
        for idx in (1, 2, 3):
            try:
                name = stmt._GetColumnName(idx)
                out(f"sqlstatement.col{idx}.name", repr(name))
            except Exception as e:  # noqa: BLE001
                out(f"sqlstatement.col{idx}.name_FAILED", repr(str(e)))
            try:
                sqltype = stmt._GetColumnSQLType(idx)
                out(f"sqlstatement.col{idx}.sqltype", repr(sqltype))
            except Exception as e:  # noqa: BLE001
                out(f"sqlstatement.col{idx}.sqltype_FAILED", repr(str(e)))
    except Exception as e:  # noqa: BLE001
        out("sqlstatement.FAILED", repr(str(e)))
        out("sqlstatement.traceback", traceback.format_exc().replace("\n", " | "))

    # Embedded empty string versus NULL, the measured inversion in FR-017.
    try:
        rs = iris.sql.exec("SELECT '' AS empty, NULL AS nul")
        row = [list(r) for r in rs][0]
        out("embedded.empty_vs_null", repr((row[0], row[1])))
    except Exception as e:  # noqa: BLE001
        out("embedded.empty_vs_null_FAILED", repr(str(e)))

    # Embedded error wording, for FR-018.
    try:
        rs = iris.sql.exec(STMT_BAD)
        list(rs)
        out("embedded.error", "NO ERROR RAISED")
    except Exception as e:  # noqa: BLE001
        out("embedded.error_type", type(e).__name__)
        out("embedded.error_text", repr(str(e)))


if __name__ == "__main__":
    main()
