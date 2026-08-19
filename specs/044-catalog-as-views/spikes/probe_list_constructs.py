"""T011a follow-up: documented IRIS constructs for a variable-length match set.

Prompted by the community's own idiom for %INLIST and by the SQL list-function
reference. Three candidates, all built in, versus the PGWire.PG_ARRAY function
currently installed:

  C1  %INLIST $LISTFROMSTRING(?, delim)  -- one documented SQL function, no
      install at all. Suspect: the delimiter can occur in a value.
  C2  = ANY (SELECT ... FROM JSON_TABLE(?, ...)) -- `ANY (subquery)` is standard
      SQL that IRIS parses natively, and JSON escaping is a solved problem, so
      this would need NO installed code whatsoever. The open questions are
      whether JSON_TABLE accepts a *parameter* as its document (Describe has to
      prepare the statement with nothing bound) and what it costs.
  C3  %INLIST PGWire.PG_ARRAY(?)         -- what is shipped today.

Run against raw DBAPI so pgwire's translation is out of the picture; what is
being measured is IRIS's behaviour, not ours.
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

VIEW = "pg_catalog.pg_namespace"

# Deliberately awkward values: a comma and a quote break delimiter-based
# splitting, and the astral character is what broke code-point length counting.
NASTY = ["public", "has,comma", 'has"quote', "café", "x😀"]


def connect():
    import iris.dbapi as dbapi

    return dbapi.connect(
        hostname=os.environ.get("IRIS_HOST", "localhost"),
        port=int(os.environ.get("IRIS_PORT", "1972")),
        namespace=os.environ.get("IRIS_NAMESPACE", "USER"),
        username=os.environ.get("IRIS_USER", "_SYSTEM"),
        password=os.environ.get("IRIS_PASSWORD", "SYS"),
    )


def attempt(cur, label, sql, params=None):
    try:
        cur.execute(sql, params) if params is not None else cur.execute(sql)
        rows = sorted(str(r[0]) for r in cur.fetchall())
        print(f"  {label:52} -> {rows}")
        return rows
    except Exception as exc:  # noqa: BLE001 — every failure mode is a result here
        print(f"  {label:52} -> FAILED {type(exc).__name__}: {str(exc)[:120]}")
        return None


JSON_SUBQUERY = "SELECT v FROM JSON_TABLE(?, '$[*]' COLUMNS (v VARCHAR(4000) PATH '$'))"


def main() -> int:
    conn = connect()
    cur = conn.cursor()

    print("C0  is `ANY (subquery)` really native? (assumed by the rewrite's guard)")
    attempt(
        cur,
        "= ANY (SELECT nspname FROM pg_namespace)",
        f"SELECT nspname FROM {VIEW} WHERE nspname = ANY (SELECT nspname FROM {VIEW})",
    )

    print("\nC1  %INLIST $LISTFROMSTRING(?, ',')")
    attempt(
        cur,
        "two clean values",
        f"SELECT nspname FROM {VIEW} WHERE nspname %INLIST $LISTFROMSTRING(?, ',')",
        ("public,pg_catalog",),
    )
    attempt(
        cur,
        "a value containing the delimiter",
        f"SELECT nspname FROM {VIEW} WHERE nspname %INLIST $LISTFROMSTRING(?, ',')",
        ("has,comma",),
    )

    print("\nC2  = ANY (SELECT ... FROM JSON_TABLE(?, ...))")
    attempt(
        cur,
        "one value",
        f"SELECT nspname FROM {VIEW} WHERE nspname = ANY ({JSON_SUBQUERY})",
        (json.dumps(["public"]),),
    )
    attempt(
        cur,
        "two values",
        f"SELECT nspname FROM {VIEW} WHERE nspname = ANY ({JSON_SUBQUERY})",
        (json.dumps(["public", "pg_catalog"]),),
    )
    attempt(
        cur,
        "empty array",
        f"SELECT nspname FROM {VIEW} WHERE nspname = ANY ({JSON_SUBQUERY})",
        (json.dumps([]),),
    )
    attempt(
        cur,
        "awkward values",
        f"SELECT nspname FROM {VIEW} WHERE nspname = ANY ({JSON_SUBQUERY})",
        (json.dumps(NASTY),),
    )
    attempt(
        cur,
        "NULL parameter (what Describe binds)",
        f"SELECT nspname FROM {VIEW} WHERE nspname = ANY ({JSON_SUBQUERY})",
        (None,),
    )
    attempt(
        cur,
        "IN (...) instead of = ANY",
        f"SELECT nspname FROM {VIEW} WHERE nspname IN ({JSON_SUBQUERY})",
        (json.dumps(["public"]),),
    )
    attempt(
        cur,
        "negated",
        f"SELECT nspname FROM {VIEW} WHERE NOT (nspname = ANY ({JSON_SUBQUERY}))",
        (json.dumps(["public"]),),
    )
    attempt(
        cur,
        "numeric column, string elements",
        f"SELECT nspname FROM {VIEW} WHERE oid = ANY ({JSON_SUBQUERY})",
        (json.dumps(["2200"]),),
    )

    print("\nC2b JSON_TABLE round-trip of the awkward values, on its own")
    attempt(
        cur,
        "elements JSON_TABLE produces",
        "SELECT v FROM JSON_TABLE(?, '$[*]' COLUMNS (v VARCHAR(4000) PATH '$'))",
        (json.dumps(NASTY),),
    )

    print("\nC3  %INLIST PGWire.PG_ARRAY(?)  (what is shipped)")
    from iris_pgwire.sql_translator.pg_array import encode_pg_array

    attempt(
        cur,
        "awkward values",
        f"SELECT nspname FROM {VIEW} WHERE nspname %INLIST PGWire.PG_ARRAY(?)",
        (encode_pg_array(NASTY),),
    )

    print("\nPreparability with nothing bound (Describe's requirement)")
    for label, sql in (
        (
            "JSON_TABLE subquery",
            f"SELECT nspname FROM {VIEW} WHERE nspname = ANY ({JSON_SUBQUERY})",
        ),
        ("PG_ARRAY", f"SELECT nspname FROM {VIEW} WHERE nspname %INLIST PGWire.PG_ARRAY(?)"),
        (
            "$LISTFROMSTRING",
            f"SELECT nspname FROM {VIEW} WHERE nspname %INLIST $LISTFROMSTRING(?, ',')",
        ),
    ):
        attempt(cur, f"{label} with NULL bound", sql, (None,))

    print("\nCost, 300 executions each (one value)")
    timings = {
        "JSON_TABLE subquery": (
            f"SELECT nspname FROM {VIEW} WHERE nspname = ANY ({JSON_SUBQUERY})",
            json.dumps(["public"]),
        ),
        "PG_ARRAY": (
            f"SELECT nspname FROM {VIEW} WHERE nspname %INLIST PGWire.PG_ARRAY(?)",
            encode_pg_array(["public"]),
        ),
        "plain IN ('public')": (
            f"SELECT nspname FROM {VIEW} WHERE nspname IN ('public')",
            None,
        ),
    }
    for label, (sql, arg) in timings.items():
        try:
            start = time.perf_counter()
            for _ in range(300):
                cur.execute(sql, (arg,)) if arg is not None else cur.execute(sql)
                cur.fetchall()
            per = (time.perf_counter() - start) / 300 * 1000
            print(f"  {label:24} {per:7.3f} ms/query")
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:24} FAILED {str(exc)[:80]}")

    print("\nCached queries minted across differing list lengths")
    for label, build in (
        (
            "JSON_TABLE",
            lambda vals: (
                f"SELECT nspname FROM {VIEW} WHERE nspname = ANY ({JSON_SUBQUERY})",
                json.dumps(vals),
            ),
        ),
        (
            "PG_ARRAY",
            lambda vals: (
                f"SELECT nspname FROM {VIEW} WHERE nspname %INLIST PGWire.PG_ARRAY(?)",
                encode_pg_array(vals),
            ),
        ),
    ):
        before = cached_count(cur)
        for vals in (["a"], ["a", "b"], ["a", "b", "c"], ["a", "b", "c", "d"]):
            sql, arg = build(vals)
            cur.execute(sql, (arg,))
            cur.fetchall()
        print(f"  {label:24} added {cached_count(cur) - before}")

    conn.close()
    return 0


def cached_count(cur) -> int:
    try:
        cur.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATEMENTS "
            "WHERE Statement LIKE '%PG_NAMESPACE%'"
        )
        return cur.fetchone()[0]
    except Exception:  # noqa: BLE001
        return -1


if __name__ == "__main__":
    raise SystemExit(main())
