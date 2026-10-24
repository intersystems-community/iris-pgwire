"""Largest vector that binds through TO_VECTOR(%s, DOUBLE, n) via pgwire, checked by value.

Replaces the verification in docs/VECTOR_PARAMETER_BINDING.md, which ran
`SELECT 1 WHERE %s IS NOT NULL` with a Python list. psycopg sends a list as a float8[] array, so
that statement measured array transport, not a vector bind, and never reached TO_VECTOR.

Here the value goes through TO_VECTOR twice and comes back as a scalar, VECTOR_DOT_PRODUCT(q, q),
compared with the same sum computed locally. A scalar is used deliberately: projecting a VECTOR
column through the embedded backend returns zero rows (see research.md), which would make a
read-back check measure that defect instead.

Usage: python probe_to_vector_max_dims.py <port> [label]
"""

import random
import sys

import psycopg

PORT = int(sys.argv[1])
LABEL = sys.argv[2] if len(sys.argv) > 2 else str(PORT)
DIMS = (1024, 4096, 16384, 65535, 65536, 188962)


def main() -> None:
    conn = psycopg.connect(
        host="127.0.0.1", port=PORT, user="_SYSTEM", password="SYS", dbname="USER",
        connect_timeout=10, sslmode="disable", autocommit=True,
    )
    for n in DIMS:
        rng = random.Random(42)
        q = [round(rng.random(), 6) for _ in range(n)]
        text = "[" + ",".join(repr(x) for x in q) + "]"
        expected = sum(x * x for x in q)
        sql = (
            f"SELECT VECTOR_DOT_PRODUCT(TO_VECTOR(%s, DOUBLE, {n}), TO_VECTOR(%s, DOUBLE, {n}))"
        )
        try:
            with conn.cursor() as cur:
                cur.execute(sql, (text, text))
                row = cur.fetchone()
            got = float(row[0]) if row else None
            ok = got is not None and abs(got - expected) <= 1e-6 * expected
            verdict = "OK" if ok else "WRONG"
            print(f"{LABEL}.d{n}: {verdict} bytes={len(text)} got={got} expected={expected:.6f}",
                  flush=True)
        except Exception as e:
            print(f"{LABEL}.d{n}: FAIL bytes={len(text)} {type(e).__name__}: "
                  f"{str(e).splitlines()[0][:140]}", flush=True)
            conn.rollback()
    conn.close()


if __name__ == "__main__":
    main()
