"""Phase 0 probe R1 for feature 051, host side.

R1: are the two connection factories used by the two executors one adapter or
two?

  - iris_executor.py:3640       iris.connect(hostname=, port=, namespace=,
                                             username=, password=)
  - dbapi_connection_pool.py:313  iris.dbapi.connect(same keyword arguments)

The keyword arguments are identical. Whether the resulting connection, cursor,
rows, ``description``, rowcount, empty-vs-NULL handling and error wording are
also identical decides whether feature 051 designs for two adapters or three.

Must run on the HOST, not inside the container: under ``irispython`` the
embedded wrapper package owns the name ``iris`` and both factories are
uncallable ``iris.package`` objects. Must also run in an environment WITHOUT
``iris-embedded-python-wrapper``: SDK 5.3.2's ``iris/__init__.py`` hands the
module over to ``iris_ep`` when that package is present, including its
attribute-manufacturing ``__getattr__``, which makes every ``hasattr`` here
meaningless.

    python3 -m venv /tmp/r1clean && /tmp/r1clean/bin/pip install intersystems-irispython==5.3.2
    /tmp/r1clean/bin/python probe_r1_host_adapters.py

Prints one ``KEY: value`` line per measurement. Each line is a fact for
research.md.
"""

import traceback

HOST = "127.0.0.1"
PORT = 2972  # host-mapped port for iris-pgwire-db
NS = "USER"
USER = "_SYSTEM"
PWD = "SYS"

# Three columns whose types are distinguishable: varchar, integer, bit.
STMT_ROWS = "SELECT 'x' AS s, 42 AS i, CAST(1 AS BIT) AS b"
STMT_ZERO = "SELECT 'x' AS s, 42 AS i, CAST(1 AS BIT) AS b WHERE 1=0"
STMT_BAD = "SELECT * FROM SQLUser.NoSuchTable_051"
STMT_PARAM = "SELECT ? AS echoed"

results = {}


def out(key, value):
    results[key] = value
    print(f"{key}: {value}")


def describe(cursor):
    try:
        d = cursor.description
    except Exception as e:  # noqa: BLE001
        return f"RAISED {e!r}"
    if d is None:
        return "None"
    return repr([(c[0], c[1]) for c in d])


def probe(label, connect_fn):
    conn = None
    try:
        conn = connect_fn()
        out(f"{label}.conn_type", type(conn).__module__ + "." + type(conn).__name__)
        out(f"{label}.conn_mro", repr([c.__name__ for c in type(conn).__mro__]))
        out(
            f"{label}.conn_public",
            repr(sorted(a for a in dir(conn) if not a.startswith("_"))),
        )

        cur = conn.cursor()
        out(f"{label}.cursor_type", type(cur).__module__ + "." + type(cur).__name__)
        out(
            f"{label}.cursor_public",
            repr(sorted(a for a in dir(cur) if not a.startswith("_"))),
        )

        cur.execute(STMT_ROWS)
        rows = cur.fetchall()
        out(f"{label}.rows", repr([tuple(r) for r in rows]))
        out(f"{label}.row_type", type(rows[0]).__name__ if rows else "NO ROWS")
        out(f"{label}.description_with_rows", describe(cur))
        out(f"{label}.rowcount_with_rows", repr(cur.rowcount))

        cur2 = conn.cursor()
        cur2.execute(STMT_ZERO)
        out(f"{label}.zero_rows", repr([tuple(r) for r in cur2.fetchall()]))
        out(f"{label}.description_zero_rows", describe(cur2))
        out(f"{label}.rowcount_zero_rows", repr(cur2.rowcount))

        # description BEFORE execute: does the adapter answer describe early?
        cur5 = conn.cursor()
        out(f"{label}.description_before_execute", describe(cur5))

        # Empty string versus NULL, the FR-017 case.
        cur3 = conn.cursor()
        cur3.execute("SELECT '' AS empty, NULL AS nul")
        r = cur3.fetchall()[0]
        out(f"{label}.empty_vs_null", repr((r[0], r[1])))

        # Parameter marker handling: does this adapter take qmark?
        try:
            cur6 = conn.cursor()
            cur6.execute(STMT_PARAM, ["v"])
            out(f"{label}.qmark_param", repr([tuple(x) for x in cur6.fetchall()]))
        except Exception as e:  # noqa: BLE001
            out(f"{label}.qmark_param_FAILED", f"{type(e).__name__}: {e!r}")

        # DDL/DML rowcount, since materialisation differs for non-SELECT.
        try:
            cur7 = conn.cursor()
            cur7.execute("CREATE TABLE SQLUser.Probe051 (id INT, txt VARCHAR(10))")
            out(f"{label}.ddl_rowcount", repr(cur7.rowcount))
            out(f"{label}.ddl_description", describe(cur7))
            cur8 = conn.cursor()
            cur8.execute("INSERT INTO SQLUser.Probe051 (id, txt) VALUES (1, 'a')")
            out(f"{label}.insert_rowcount", repr(cur8.rowcount))
            out(f"{label}.insert_description", describe(cur8))
        except Exception as e:  # noqa: BLE001
            out(f"{label}.ddl_FAILED", f"{type(e).__name__}: {e!r}")
        finally:
            try:
                conn.cursor().execute("DROP TABLE SQLUser.Probe051")
            except Exception:  # noqa: BLE001, S110
                pass

        # Error wording and type, the FR-018 case.
        try:
            cur4 = conn.cursor()
            cur4.execute(STMT_BAD)
            out(f"{label}.error", "NO ERROR RAISED")
        except Exception as e:  # noqa: BLE001
            out(f"{label}.error_type", type(e).__module__ + "." + type(e).__name__)
            out(f"{label}.error_mro", repr([c.__name__ for c in type(e).__mro__]))
            out(f"{label}.error_text", repr(str(e)))
            out(f"{label}.error_args", repr(getattr(e, "args", None)))
            out(f"{label}.error_sqlcode", repr(getattr(e, "sqlcode", "NO ATTR")))

        # Transaction surface, input to the R5 capability question.
        for name in ("autocommit", "isolation_level", "commit", "rollback"):
            out(f"{label}.has_{name}", hasattr(conn, name))
        try:
            out(f"{label}.autocommit_value", repr(conn.autocommit))
        except Exception as e:  # noqa: BLE001
            out(f"{label}.autocommit_value_FAILED", repr(str(e)))

    except Exception as e:  # noqa: BLE001
        out(f"{label}.FAILED", f"{type(e).__name__}: {e!r}")
        out(f"{label}.traceback", traceback.format_exc().replace("\n", " | "))
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001, S110
                pass


def main():
    import iris

    print("=== environment: is this the SDK or the wrapper? ===")
    out("iris.__file__", getattr(iris, "__file__", "?"))
    out("iris.__version__", getattr(iris, "__version__", "?"))
    out("iris_ep_hijacked", "iris_ep" in repr(getattr(iris, "__dict__", {}).keys()))
    try:
        import iris_ep  # noqa: F401

        out("iris_ep_importable", True)
    except ImportError:
        out("iris_ep_importable", False)

    import iris.dbapi as iris_dbapi

    out("iris.dbapi.__file__", getattr(iris_dbapi, "__file__", "?"))
    out("iris.connect", repr(iris.connect))
    out("iris.dbapi.connect", repr(iris_dbapi.connect))
    out("same_function_object", iris.connect is iris_dbapi.connect)
    out("iris.connect.__module__", repr(getattr(iris.connect, "__module__", "?")))
    out("iris.dbapi.connect.__module__", repr(getattr(iris_dbapi.connect, "__module__", "?")))

    print("=== R1: native factory (iris_executor.py:3640) ===")
    probe(
        "native",
        lambda: iris.connect(
            hostname=HOST, port=PORT, namespace=NS, username=USER, password=PWD
        ),
    )

    print("=== R1: dbapi factory (dbapi_connection_pool.py:313) ===")
    probe(
        "dbapi",
        lambda: iris_dbapi.connect(
            hostname=HOST, port=PORT, namespace=NS, username=USER, password=PWD
        ),
    )

    print("=== R1 verdict inputs: which measurements differ? ===")
    keys = sorted(
        {k.split(".", 1)[1] for k in results if k.startswith(("native.", "dbapi."))}
    )
    same, diff, missing = [], [], []
    for k in keys:
        n, d = results.get(f"native.{k}", "<absent>"), results.get(f"dbapi.{k}", "<absent>")
        if n == "<absent>" or d == "<absent>":
            missing.append(k)
        elif n == d:
            same.append(k)
        else:
            diff.append(k)
    out("identical_measurements", repr(same))
    out("differing_measurements", repr(diff))
    out("one_sided_measurements", repr(missing))
    for k in diff:
        print(f"  DIFF {k}:\n    native = {results[f'native.{k}']}\n    dbapi  = {results[f'dbapi.{k}']}")


if __name__ == "__main__":
    main()
