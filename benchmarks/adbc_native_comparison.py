"""iris-pgwire's ADBC path beside the IRIS ADBC driver and the official driver, on the same data.

The data, the checks and the timing method are those of irispython-dx spec 21 phase 0
(`dxlab/adbc_native/phase0.py`), so the official and IRIS ADBC rows can be compared with that
spec's published 2026.2 results. This script adds a third path: the stock PostgreSQL ADBC driver
(`adbc-driver-postgresql`) talking to IRIS through iris-pgwire, in both of its fetch modes.

Paths:
  official    iris_dx over intersystems-irispython: fetchall() into a DataFrame
  native      the IRIS ADBC driver (Jim Nelson's, CL 9762165): fetch_arrow_table()
  pgwire      adbc-driver-postgresql through iris-pgwire, default mode (binary COPY)
  pgwire-rows adbc-driver-postgresql with adbc.postgresql.use_copy=false (binary result rows)

Run in irispython-dx's client image (dxlab-adbc-native-client:1), with that repo's
dxlab/adbc_native at /h (for _adbc.py), the driver build at /drv, the layer at /layer and
adbc-driver-postgresql installed:
    python bench.py check <iris-url> <pg-url>
    python bench.py reads <iris-url> <pg-url> <label> <out.jsonl> [rows,rows] [paths]

check  loads 1,000 seeded rows and reads them back through every path, comparing every value
       with the generator's (the generator is the known answer, not any path's output).
reads  loads 3,000,000 rows, verifies them by server-side sums the generator also computes,
       then times each read: 2 warm-ups and 5 measured runs, wall time, median recorded.
       A connection is opened outside the timing, as in phase0.py.
"""

import datetime as dt
import functools
import json
import random
import statistics
import sys
import time
from decimal import Decimal

import pandas as pd
import polars as pl
import pyarrow as pa

sys.path.insert(0, "/h")

mode, iris_url, pg_url = sys.argv[1], sys.argv[2], sys.argv[3]
label = sys.argv[4] if len(sys.argv) > 4 else ""
out_path = sys.argv[5] if len(sys.argv) > 5 else None

import _adbc  # noqa: E402  irispython-dx's shim for the IRIS ADBC driver
import adbc_driver_postgresql.dbapi as pg  # noqa: E402
import iris_dx.dbapi  # noqa: E402

official = iris_dx.dbapi.connect(url=iris_url)
TABLE = "PGWBench.Bench"

# --- From phase0.py, unchanged, so the rows are the same rows. ---
SCHEMA = pa.schema(
    [
        ("id", pa.int32()),
        ("i1", pa.int32()),
        ("i2", pa.int64()),
        ("n1", pa.decimal128(12, 4)),
        ("n2", pa.decimal128(18, 2)),
        ("f1", pa.float64()),
        ("f2", pa.float64()),
        ("s1", pa.string()),
        ("s2", pa.string()),
        ("ts", pa.timestamp("us")),
        ("d", pa.date32()),
        ("s3", pa.string()),
    ]
)
DDL = (
    "id INT PRIMARY KEY, i1 INT, i2 BIGINT, n1 NUMERIC(12,4), n2 NUMERIC(18,2), f1 DOUBLE, f2 DOUBLE, "
    "s1 VARCHAR(20), s2 VARCHAR(100), ts TIMESTAMP, d DATE, s3 VARCHAR(40)"
)
NAMES = SCHEMA.names
WORDS = ["alpha", "beta", "gamma", "delta", "Zürich", "東京", "naïve", "omega", "kappa", "sigma"]
T0 = dt.datetime(2020, 1, 1)


def rows(start, count, seed=21):
    """Seeded rows id start..start+count-1; about 20% NULLs in i1, n1, f2, s3 and ts."""
    for i in range(start, start + count):
        r = random.Random(seed * 10_000_019 + i)
        null = lambda: r.random() < 0.2  # noqa: E731
        yield {
            "id": i,
            "i1": None if null() else r.randint(-(2**31) + 1, 2**31 - 1),
            "i2": r.randint(-(10**11), 10**11),
            "n1": None if null() else Decimal(r.randint(-(10**11), 10**11)).scaleb(-4),
            "n2": Decimal(r.randint(-(10**9), 10**9)).scaleb(-2),
            "f1": r.uniform(-1e6, 1e6),
            "f2": None if null() else r.random(),
            "s1": r.choice(WORDS),
            "s2": " ".join(r.choice(WORDS) for _ in range(r.randint(1, 12))),
            "ts": None if null() else T0 + dt.timedelta(microseconds=r.randint(0, 10**14)),
            "d": (T0 + dt.timedelta(days=r.randint(0, 3650))).date(),
            "s3": None if null() else f"row {i} ✓",
        }


@functools.cache
def expected_sums(n):
    c = i2 = n2 = s3 = 0
    for r in rows(1, n):
        c, i2, n2, s3 = c + 1, i2 + r["i2"], n2 + r["n2"], s3 + (r["s3"] is not None)
    return c, i2, n2, s3


def sums_match(got, want):
    return (
        got[0] == want[0]
        and int(got[1]) == want[1]
        and Decimal(str(got[2])) == want[2]
        and got[3] == want[3]
    )


# --- End of the part from phase0.py. ---


def populate(n):
    cur = official.cursor()
    try:
        cur.execute(f"DROP TABLE {TABLE}")
    except Exception as exc:  # only "no such table" may pass: any other failure stops the run
        if "-30" not in str(exc) and "not found" not in str(exc).lower():
            raise
    cur.execute(f"CREATE TABLE {TABLE} ({DDL})")
    official.commit()
    for start in range(1, n + 1, 100_000):
        data = pa.Table.from_pylist(list(rows(start, min(100_000, n + 1 - start))), schema=SCHEMA)
        with _adbc.connect(iris_url) as conn, conn.cursor() as c:
            c.adbc_ingest(TABLE.split(".")[1], data, mode="append", db_schema_name=TABLE.split(".")[0])
            conn.commit()
    cur.execute(f"SELECT COUNT(*), SUM(i2), SUM(n2), COUNT(s3) FROM {TABLE}")
    got, want = tuple(cur.fetchone()), expected_sums(n)
    assert sums_match(got, want), (got, want)


def connect(path):
    if path == "native":
        return _adbc.connect(iris_url)
    if path == "pgwire":
        return pg.connect(pg_url)
    if path == "pgwire-rows":
        conn = pg.connect(pg_url)
        conn.adbc_connection.set_options(**{"adbc.postgresql.use_copy": "false"})
        return conn
    return None


def read(path, kind, n, conn):
    select = f"SELECT {', '.join(NAMES)} FROM {TABLE} WHERE id <= {n}"
    if path == "official":
        t = time.perf_counter()
        cur = official.cursor()
        cur.execute(select)
        got = cur.fetchall()
        if kind == "pandas":
            frame = pd.DataFrame.from_records(got, columns=NAMES)
        else:
            frame = pl.DataFrame(got, schema=NAMES, orient="row", infer_schema_length=None)
        return time.perf_counter() - t, frame
    with conn.cursor() as cur:
        t = time.perf_counter()
        cur.execute(select)
        table = cur.fetch_arrow_table()
        frame = table.to_pandas() if kind == "pandas" else pl.from_arrow(table)
        took = time.perf_counter() - t
    conn.commit()  # end the read's transaction, as the next run would otherwise share it
    return took, frame


def normalise(value):
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, dt.datetime) and value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    if isinstance(value, float) and value != value:
        return None
    if value is pd.NaT:
        return None
    return value


def mismatches(want, got):
    """(id, column, wanted, got) for every value that differs from the generator's.

    A float standing in for a decimal counts as a match only if it prints as the same decimal:
    that is what iris-pgwire's embedded backend sends for NUMERIC today (declared float8)."""
    bad = []
    got = sorted(got, key=lambda r: r["id"])
    if len(got) != len(want):
        return [("rows", len(want), len(got))]
    for w, g in zip(want, got, strict=True):
        for name in NAMES:
            gv, wv = normalise(g[name]), w[name]
            if isinstance(wv, dt.date) and not isinstance(wv, dt.datetime) and isinstance(gv, dt.datetime):
                gv = gv.date()
            if gv != wv and not (isinstance(wv, Decimal) and gv is not None and Decimal(str(gv)) == wv):
                bad.append((w["id"], name, wv, gv))
    return bad


def arrow_types(path, conn):
    if path == "official":
        return None
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(NAMES)} FROM {TABLE} WHERE id <= 1")
        schema = cur.fetch_arrow_table().schema
    conn.commit()
    return {f.name: str(f.type) for f in schema}


PATHS = ("official", "native", "pgwire", "pgwire-rows")


def check():
    populate(1_000)
    want = list(rows(1, 1_000))
    failed = False
    for path in PATHS:
        conn = connect(path)
        print(f"types {path:<11} {arrow_types(path, conn)}")
        for kind in ("pandas", "polars"):
            _, frame = read(path, kind, 1_000, conn)
            bad = mismatches(want, frame.to_dict("records") if kind == "pandas" else frame.to_dicts())
            print(f"read  {path:<11} {kind:<6} mismatches={len(bad)} {bad[:3]}")
            failed |= bool(bad)
        if conn is not None:
            conn.close()
    return not failed


def emit(out, entry):
    print(json.dumps(entry), flush=True)
    if out:
        out.write(json.dumps(entry) + "\n")
        out.flush()


def reads(sizes, paths):
    populate(max(sizes))
    out = open(out_path, "a") if out_path else None
    base = {"server": label, "connection": "tcp"}
    for n in sizes:
        for kind in ("pandas", "polars"):
            for path in paths:
                conn = connect(path)
                times = []
                for i in range(7):  # 2 warm-ups, 5 measured
                    took, frame = read(path, kind, n, conn)
                    assert len(frame) == n, (path, kind, len(frame))
                    if i >= 2:
                        times.append(took)
                if conn is not None:
                    conn.close()
                emit(out, {**base, "case": "read", "rows": n, "frame": kind, "path": path,
                           "median_s": round(statistics.median(times), 4),
                           "runs_s": [round(t, 4) for t in times]})  # fmt: skip


if mode == "check":
    sys.exit(0 if check() else 1)
if mode == "reads":
    sizes = [int(x) for x in (sys.argv[6] if len(sys.argv) > 6 else "100000,3000000").split(",")]
    paths = sys.argv[7].split(",") if len(sys.argv) > 7 else PATHS
    reads(sizes, paths)
    sys.exit(0)
sys.exit(f"unknown mode {mode}")
