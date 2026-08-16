"""T011a spike, Python half: can a $LIST be bound to `%INLIST ?` from Python?

ObjectScript already proved `%INLIST ?` is preparable and that a bound $LIST of
1, 2 or 0 elements returns the right rows (SpikeT011a.cls). What is still open
is whether either Python path pgwire actually uses can produce a value IRIS
accepts as a $LIST -- a plain string is rejected with SQLCODE -400.

Run under irispython inside the container for the embedded path, and under any
Python with intersystems-irispython for the DBAPI path. It auto-detects.
"""

from __future__ import annotations

import sys

SQL = "SELECT nspname FROM pg_catalog.pg_namespace WHERE nspname %INLIST ?"
VALUES = ["public", "pg_catalog"]


def report(label: str, fn) -> None:
    try:
        print(f"  {label}: {fn()}")
    except Exception as exc:  # noqa: BLE001 - a spike reports every failure mode
        print(f"  {label}: FAILED {type(exc).__name__}: {exc}")


def candidates() -> list[tuple[str, object]]:
    """Every plausible way to hand IRIS a $LIST from Python."""
    out: list[tuple[str, object]] = []

    out.append(("python list", VALUES))
    out.append(("python tuple", tuple(VALUES)))

    for modname in ("intersystems_iris", "iris"):
        try:
            module = __import__(modname)
            cls = getattr(module, "IRISList", None)
            if cls is None:
                continue
            lst = cls()
            for v in VALUES:
                lst.add(v)
            out.append((f"{modname}.IRISList", lst))
            if hasattr(lst, "_buffer"):
                out.append((f"{modname}.IRISList._buffer", lst._buffer))
        except Exception as exc:  # noqa: BLE001
            print(f"  ({modname}.IRISList unavailable: {exc})")

    # Hand-built $LIST wire format: each element is <len+1><type=1><bytes>.
    encoded = b"".join(bytes([len(v.encode()) + 2, 1]) + v.encode() for v in VALUES)
    out.append(("hand-encoded $LIST bytes", encoded))
    out.append(("hand-encoded $LIST latin-1 str", encoded.decode("latin-1")))

    return out


def probe_embedded() -> None:
    import iris

    print("\n[embedded] iris.sql.prepare / execute")
    try:
        stmt = iris.sql.prepare(SQL)
    except Exception as exc:  # noqa: BLE001
        print(f"  PREPARE FAILED {type(exc).__name__}: {exc}")
        return
    print("  PREPARE OK")

    for label, value in candidates():

        def run(value=value):
            rs = stmt.execute(value)
            return sorted(r[0] for r in rs)

        report(label, run)

    print("\n[embedded] $LIST built inside IRIS via a classmethod, for comparison")

    def via_objectscript():
        # Proves the transport, not Python: ask IRIS itself to build the list.
        rs = iris.sql.exec(
            "SELECT nspname FROM pg_catalog.pg_namespace "
            "WHERE nspname %INLIST $LISTFROMSTRING(?, ',')",
            ",".join(VALUES),
        )
        return sorted(r[0] for r in rs)

    report("$LISTFROMSTRING(?, ',')", via_objectscript)


def probe_dbapi() -> None:
    # Package is intersystems-irispython; the DBAPI module is iris.dbapi.
    import os

    import iris.dbapi as dbapi

    print("\n[dbapi] cursor.execute")
    conn = dbapi.connect(
        hostname=os.environ.get("IRIS_HOST", "localhost"),
        port=int(os.environ.get("IRIS_PORT", "1972")),
        namespace=os.environ.get("IRIS_NAMESPACE", "USER"),
        username=os.environ.get("IRIS_USER", "_SYSTEM"),
        password=os.environ.get("IRIS_PASSWORD", "SYS"),
    )
    cur = conn.cursor()

    for label, value in candidates():

        def run(value=value):
            cur.execute(SQL, (value,))
            return sorted(r[0] for r in cur.fetchall())

        report(label, run)

    def via_listfromstring():
        cur.execute(
            "SELECT nspname FROM pg_catalog.pg_namespace "
            "WHERE nspname %INLIST $LISTFROMSTRING(?, ',')",
            (",".join(VALUES),),
        )
        return sorted(r[0] for r in cur.fetchall())

    report("$LISTFROMSTRING(?, ',')", via_listfromstring)
    conn.close()


def main() -> int:
    embedded = False
    try:
        import iris

        embedded = hasattr(iris, "sql") and hasattr(iris.sql, "prepare")
    except ImportError:
        pass

    print(f"python: {sys.version.split()[0]}  embedded={embedded}")
    print(f"expected rows: {sorted(VALUES)}")

    if embedded:
        probe_embedded()
    else:
        probe_dbapi()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
