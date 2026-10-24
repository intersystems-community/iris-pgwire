"""TO_VECTOR(?) parameter binding through pgwire, end to end, with psycopg3.

Settles a contradiction between specs/013-vector-query-optimizer/E2E_FINDINGS.md (2025-10-02:
"cannot bind" a 21 KB 1,024-dim string) and docs/VECTOR_PARAMETER_BINDING.md ("fully functional"
to 188,962 dims, verified by a statement that never calls TO_VECTOR).

Real client, real server, real IRIS: psycopg3 binds server-side over the extended protocol, so
each %s below arrives at pgwire as a $n parameter, not as text spliced into the SQL.

For each dimension, inserts ROWS random unit vectors through TO_VECTOR(%s, DOUBLE, n), reads them
back, then ranks them against a query vector near row TARGET through
ORDER BY VECTOR_COSINE(v, TO_VECTOR(%s, DOUBLE, n)) DESC, and compares the full order with the
order computed locally. Extra forms (2-arg, untyped, pgvector <=>, LIMIT %s) are diagnostics.

Usage: python probe_to_vector_binding.py <port> [label]
Prints one KEY: value line per measurement.
"""

import math
import random
import sys

import psycopg

PORT = int(sys.argv[1])
LABEL = sys.argv[2] if len(sys.argv) > 2 else str(PORT)
DIMS = (1024, 4096)
ROWS = 6
TARGET = 3


def emit(key: str, value) -> None:
    print(f"{LABEL}.{key}: {value}", flush=True)


def unit(rng: random.Random, n: int) -> list[float]:
    v = [rng.uniform(-1.0, 1.0) for _ in range(n)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


def as_text(v: list[float]) -> str:
    return "[" + ",".join(repr(x) for x in v) + "]"


def short(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"


def run(conn, n: int) -> None:
    rng = random.Random(n)
    rows = [unit(rng, n) for _ in range(ROWS)]
    query = [x + rng.gauss(0, 0.02) for x in rows[TARGET]]
    expected = sorted(range(ROWS), key=lambda i: cosine(rows[i], query), reverse=True)
    qtext = as_text(query)
    table = f"Probe051TV{n}"
    emit(f"d{n}.param_bytes", len(as_text(rows[0])))

    with conn.cursor() as cur:
        try:
            cur.execute(f"DROP TABLE {table}")
        except Exception:
            pass
        cur.execute(f"CREATE TABLE {table} (id INT PRIMARY KEY, v VECTOR(DOUBLE, {n}))")

        # 1. INSERT through TO_VECTOR(%s, DOUBLE, n)
        try:
            for i, v in enumerate(rows):
                cur.execute(
                    f"INSERT INTO {table} (id, v) VALUES (%s, TO_VECTOR(%s, DOUBLE, {n}))",
                    (i, as_text(v)),
                )
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            emit(f"d{n}.insert_3arg", f"OK rows={cur.fetchone()[0]}")
        except Exception as e:
            emit(f"d{n}.insert_3arg", f"FAIL {short(e)}")
            return

        # 2. Read back and compare values
        try:
            cur.execute(f"SELECT v FROM {table} WHERE id = %s", (TARGET,))
            got = cur.fetchone()[0]
            vals = [float(x) for x in str(got).strip("[]").split(",")]
            err = max(abs(a - b) for a, b in zip(vals, rows[TARGET], strict=True))
            emit(f"d{n}.readback", f"len={len(vals)} max_abs_err={err:.3e}")
        except Exception as e:
            emit(f"d{n}.readback", f"FAIL {short(e)}")

        # 3. Ranking, in the requested form and the diagnostic forms
        forms = {
            "rank_3arg": (
                f"SELECT TOP {ROWS} id FROM {table} "
                f"ORDER BY VECTOR_COSINE(v, TO_VECTOR(%s, DOUBLE, {n})) DESC",
                (qtext,),
            ),
            "rank_2arg": (
                f"SELECT TOP {ROWS} id FROM {table} "
                f"ORDER BY VECTOR_COSINE(v, TO_VECTOR(%s, DOUBLE)) DESC",
                (qtext,),
            ),
            "rank_untyped": (
                f"SELECT TOP {ROWS} id FROM {table} "
                f"ORDER BY VECTOR_COSINE(v, TO_VECTOR(%s)) DESC",
                (qtext,),
            ),
            "rank_pgvector_limit_param": (
                f"SELECT id FROM {table} ORDER BY v <=> %s LIMIT %s",
                (qtext, ROWS),
            ),
        }
        for name, (sql, params) in forms.items():
            try:
                cur.execute(sql, params)
                order = [r[0] for r in cur.fetchall()]
                verdict = "MATCH" if order == expected else "MISMATCH"
                emit(f"d{n}.{name}", f"{verdict} got={order} expected={expected}")
            except Exception as e:
                emit(f"d{n}.{name}", f"FAIL {short(e)}")
                conn.rollback()

        try:
            cur.execute(f"DROP TABLE {table}")
        except Exception as e:
            emit(f"d{n}.cleanup", f"FAIL {short(e)}")


def main() -> None:
    conn = psycopg.connect(
        host="127.0.0.1", port=PORT, user="_SYSTEM", password="SYS", dbname="USER",
        connect_timeout=10, sslmode="disable", autocommit=True,
    )
    emit("server_version", conn.info.parameter_status("server_version"))
    for n in DIMS:
        run(conn, n)
    conn.close()


if __name__ == "__main__":
    main()
