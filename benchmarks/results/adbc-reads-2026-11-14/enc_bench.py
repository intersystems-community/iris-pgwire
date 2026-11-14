"""Time binary COPY encoding of 100k bench-shaped rows (the DBAPI backend's Python types)."""
import datetime as dt, random, sys, time
from decimal import Decimal
sys.path.insert(0, "/Users/tdyar/ws/iris-pgwire/src")
from iris_pgwire.copy_export import ExportFormat, export_messages, copy_data

WORDS = ["alpha", "beta", "gamma", "delta", "Zürich", "東京", "naïve", "omega", "kappa", "sigma"]
T0 = dt.datetime(2020, 1, 1)
def rows(n):
    out = []
    for i in range(1, n + 1):
        r = random.Random(i); null = lambda: r.random() < 0.2
        out.append((i, None if null() else r.randint(-(2**31) + 1, 2**31 - 1), r.randint(-(10**11), 10**11),
            None if null() else Decimal(r.randint(-(10**11), 10**11)).scaleb(-4), Decimal(r.randint(-(10**9), 10**9)).scaleb(-2),
            r.uniform(-1e6, 1e6), None if null() else r.random(), r.choice(WORDS),
            " ".join(r.choice(WORDS) for _ in range(r.randint(1, 12))),
            None if null() else T0 + dt.timedelta(microseconds=r.randint(0, 10**14)),
            (T0 + dt.timedelta(days=r.randint(0, 3650))).date(), None if null() else f"row {i} ✓"))
    return out
OIDS = [23, 23, 20, 1700, 1700, 701, 701, 1043, 1043, 1114, 1082, 1043]
cols = [{"name": f"c{i}", "type_oid": o} for i, o in enumerate(OIDS)]
data = rows(100_000)
fmt = ExportFormat(kind="binary")
best = 9e9
for _ in range(5):
    t = time.perf_counter()
    total = sum(len(copy_data(p)) for p in export_messages(fmt, cols, data))
    best = min(best, time.perf_counter() - t)
import hashlib
digest = hashlib.sha256(b"".join(export_messages(fmt, cols, data))).hexdigest()[:16]
print(f"encode+frame 100k: best {best:.3f}s, {total} bytes, sha {digest}")
