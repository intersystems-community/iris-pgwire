"""T011a spike, part 3: does `%INLIST` behave like `= ANY(array)`?

Preparability is settled (SpikeT011a.cls) and $LIST bytes bind from both Python
paths (probe_inlist_python.py). What is left is whether the construct is a
faithful substitute in the places pgwire would put it:

  S1  NULL parameter -- Describe runs the query with a dummy NULL to discover
      the row description. It must return columns, not an error.
  S2  integer elements -- `oid = ANY($1::int[])` is as common as the text case.
  S3  negation -- `<> ALL($1)` maps to `NOT (col %INLIST ?)`.
  S4  a joined query, which is the shape ORMs actually emit.
  S5  cached-query reuse -- the documented advantage over IN, and the reason
      not to keep inlining literals.
  S6  encoder parity -- our $LIST encoder against the driver's own IRISList.

Runs against the DBAPI from the host; the embedded half is covered by
probe_inlist_python.py, which showed the same $LIST bytes work there.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

VIEW = "pg_catalog.pg_namespace"


def connect():
    import iris.dbapi as dbapi

    return dbapi.connect(
        hostname=os.environ.get("IRIS_HOST", "localhost"),
        port=int(os.environ.get("IRIS_PORT", "1972")),
        namespace=os.environ.get("IRIS_NAMESPACE", "USER"),
        username=os.environ.get("IRIS_USER", "_SYSTEM"),
        password=os.environ.get("IRIS_PASSWORD", "SYS"),
    )


def show(cur, label: str, sql: str, params=None):
    try:
        cur.execute(sql, params) if params is not None else cur.execute(sql)
        rows = cur.fetchall()
        desc = [d[0] for d in (cur.description or [])]
        preview = rows[:4]
        print(f"  {label}: {len(rows)} rows, columns={desc}, first={preview}")
        return rows
    except Exception as exc:  # noqa: BLE001
        print(f"  {label}: FAILED {type(exc).__name__}: {exc}")
        return None


def main() -> int:
    from iris_pgwire.sql_translator.iris_list import encode_iris_list

    conn = connect()
    cur = conn.cursor()

    print("S1  NULL parameter at Describe time, and the empty array")
    show(cur, "%INLIST NULL", f"SELECT nspname, oid FROM {VIEW} WHERE nspname %INLIST ?", (None,))
    # Expected to FAIL with SQLCODE -400 <LIST>: an empty $LIST is zero bytes
    # and IRIS will not take it. This is why an empty array binds as None.
    show(
        cur,
        "%INLIST empty $LIST (expected failure)",
        f"SELECT nspname, oid FROM {VIEW} WHERE nspname %INLIST ?",
        (encode_iris_list([]),),
    )

    print("\nS2  integer elements")
    show(
        cur,
        "oid %INLIST $LB(2200)",
        f"SELECT nspname, oid FROM {VIEW} WHERE oid %INLIST ?",
        (encode_iris_list([2200]),),
    )
    show(
        cur,
        "oid %INLIST $LB('2200') as text",
        f"SELECT nspname, oid FROM {VIEW} WHERE oid %INLIST ?",
        (encode_iris_list(["2200"]),),
    )

    print("\nS3  negation")
    show(
        cur,
        "NOT (nspname %INLIST ?)",
        f"SELECT nspname FROM {VIEW} WHERE NOT (nspname %INLIST ?)",
        (encode_iris_list(["public"]),),
    )

    print("\nS4  the shape an ORM emits")
    show(
        cur,
        "join + filter",
        "SELECT c.relname, n.nspname FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname %INLIST ? AND c.relkind %INLIST ?",
        (encode_iris_list(["public"]), encode_iris_list(["r", "v"])),
    )

    print("\nS5  cached-query reuse across differing list lengths")
    before = cached_query_count(cur)
    for values in (["public"], ["public", "pg_catalog"], ["a", "b", "c"], ["a", "b", "c", "d"]):
        cur.execute(
            f"SELECT nspname FROM {VIEW} WHERE nspname %INLIST ?", (encode_iris_list(values),)
        )
        cur.fetchall()
    after_inlist = cached_query_count(cur)
    for values in (["public"], ["public", "pg_catalog"], ["a", "b", "c"], ["a", "b", "c", "d"]):
        inlined = ", ".join("'" + v + "'" for v in values)
        cur.execute(f"SELECT nspname FROM {VIEW} WHERE nspname IN ({inlined})")
        cur.fetchall()
    after_inline = cached_query_count(cur)
    print(
        f"  cached queries: start={before} after 4x %INLIST={after_inlist} "
        f"after 4x inlined IN={after_inline}"
    )
    print(
        f"  -> %INLIST added {after_inlist - before}, inlining added {after_inline - after_inlist}"
    )

    print("\nS6  encoder parity with the driver's IRISList")
    parity_ok = True
    import iris

    for values in (
        [],
        [""],
        ["public"],
        ["public", "pg_catalog"],
        ["café"],
        ["a" * 253],
        ["a" * 254],
        ["a" * 300],
        [42],
        [-7],
        [2**40],
        ["a", 1],
    ):
        lst = iris.IRISList()
        for v in values:
            lst.add(v)
        expected = lst.getBuffer()
        actual = encode_iris_list(values)
        mark = "ok " if actual == expected else "MISMATCH"
        if actual != expected:
            parity_ok = False
            print(f"  {mark} {values!r:40} driver={expected!r} ours={actual!r}")
        else:
            print(f"  {mark} {values!r:40} ({len(actual)} bytes)")
    print(f"  parity: {'PASS' if parity_ok else 'FAIL'}")

    conn.close()
    return 0


def cached_query_count(cur) -> int:
    """How many cached queries IRIS holds for statements touching pg_namespace.

    The documented advantage of %INLIST over IN is that varying the number of
    values does not mint a new cached query. This counts them so the claim is
    measured rather than quoted.
    """
    try:
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATEMENTS "
            "WHERE Statement LIKE '%PG_NAMESPACE%'"
        )
        return cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001
        print(f"  (cached-query count unavailable: {type(exc).__name__}: {exc})")
        return -1


if __name__ == "__main__":
    raise SystemExit(main())
