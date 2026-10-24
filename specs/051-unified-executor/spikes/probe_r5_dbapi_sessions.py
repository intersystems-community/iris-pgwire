"""Phase 0 probe R5 for feature 051: the DBAPI half of the capability set.

KNOWN_LIMITATIONS.md ("Sessions Share One Transaction in the In-IRIS
Deployment") already measures the embedded backend: one process, one
transaction, so one client's COMMIT commits another's work. That section states
DBAPI is different because each session holds its own IRIS connection, but the
counter-measurement is not recorded. R5 needs it, because the values of
``per_session_transactions``, ``max_concurrent_sessions`` and
``isolation_levels_in_force`` are what the capability seam will declare, and a
capability the code asserts but nobody measured is the ``hasattr`` problem in a
new costume.

Run on the HOST against the container's mapped port, in an environment WITHOUT
iris-embedded-python-wrapper (see probe_r1_host_adapters.py for why).

    /tmp/r1clean/bin/python probe_r5_dbapi_sessions.py
"""

import traceback

HOST = "127.0.0.1"
PORT = 2972
NS = "USER"
USER = "_SYSTEM"
PWD = "SYS"

TABLE = "SQLUser.Probe051R5"


def out(key, value):
    print(f"{key}: {value}")


def scalar(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    row = cur.fetchone()
    return row[0] if row else None


def main():
    import iris.dbapi as dbapi

    def connect():
        return dbapi.connect(
            hostname=HOST, port=PORT, namespace=NS, username=USER, password=PWD
        )

    setup = connect()
    for sql in (f"DROP TABLE {TABLE}", f"CREATE TABLE {TABLE} (id INT)"):
        try:
            setup.cursor().execute(sql)
        except Exception as e:  # noqa: BLE001
            out("setup_note", f"{sql!r} -> {type(e).__name__}: {e}")
    setup.close()

    a = connect()
    b = connect()
    out("two_connections_opened", True)
    out("a.autocommit_default", repr(a.autocommit))

    try:
        # Turn autocommit off so A holds an open transaction, the same shape as
        # the embedded measurement in KNOWN_LIMITATIONS.md.
        a.autocommit = False
        out("a.autocommit_after_set", repr(a.autocommit))

        a.cursor().execute(f"INSERT INTO {TABLE} (id) VALUES (1)")
        out("a_inserted_uncommitted", True)

        # The question: does B see A's uncommitted row?
        out("b_sees_uncommitted_count", repr(scalar(b, f"SELECT COUNT(*) FROM {TABLE}")))
        out("a_sees_own_count", repr(scalar(a, f"SELECT COUNT(*) FROM {TABLE}")))

        # Does B's COMMIT commit A's work, as it does on embedded?
        b.commit()
        out("after_b_commit_b_count", repr(scalar(b, f"SELECT COUNT(*) FROM {TABLE}")))

        a.rollback()
        out("after_a_rollback_a_count", repr(scalar(a, f"SELECT COUNT(*) FROM {TABLE}")))
        out("after_a_rollback_b_count", repr(scalar(b, f"SELECT COUNT(*) FROM {TABLE}")))

        verdict = connect()
        out("final_count_fresh_connection", repr(scalar(verdict, f"SELECT COUNT(*) FROM {TABLE}")))
        verdict.close()
        print("  PostgreSQL would report 0 here: A rolled back, B committed nothing of its own.")
    except Exception as e:  # noqa: BLE001
        out("FAILED", f"{type(e).__name__}: {e!r}")
        out("traceback", traceback.format_exc().replace("\n", " | "))
    finally:
        for c in (a, b):
            try:
                c.close()
            except Exception:  # noqa: BLE001, S110
                pass

    print("=== isolation levels: accepted versus in force ===")
    c = connect()
    for level in ("READ UNCOMMITTED", "READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"):
        try:
            c.cursor().execute(f"SET TRANSACTION ISOLATION LEVEL {level}")
            out(f"accepted.{level}", True)
        except Exception as e:  # noqa: BLE001
            out(f"accepted.{level}", f"REJECTED {type(e).__name__}: {e}")
    try:
        out("current_isolation", repr(scalar(c, "SELECT $SYSTEM.SQL.Util.GetOption('IsolationMode')")))
    except Exception as e:  # noqa: BLE001
        out("current_isolation_FAILED", repr(str(e)))
    c.close()

    print("=== how many concurrent DBAPI connections does this licence allow? ===")
    conns = []
    try:
        for i in range(1, 17):
            conns.append(connect())
            out("opened", i)
    except Exception as e:  # noqa: BLE001
        out("max_concurrent_connections", len(conns))
        out("exhaustion_error_type", type(e).__module__ + "." + type(e).__name__)
        out("exhaustion_error_text", repr(str(e)))
    else:
        out("max_concurrent_connections", f"at least {len(conns)} (probe ceiling reached)")
    finally:
        for c in conns:
            try:
                c.close()
            except Exception:  # noqa: BLE001, S110
                pass

    cleanup = connect()
    try:
        cleanup.cursor().execute(f"DROP TABLE {TABLE}")
    except Exception:  # noqa: BLE001, S110
        pass
    cleanup.close()


if __name__ == "__main__":
    main()
