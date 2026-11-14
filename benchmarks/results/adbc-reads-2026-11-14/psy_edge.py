import sys, datetime as dt, uuid
from decimal import Decimal
sys.path.insert(0, "/Users/tdyar/ws/iris-pgwire/src")
from iris_pgwire.value_encoding import encode_binary
from psycopg.adapt import Transformer
from psycopg import pq
def psy(oid, v):
    tx = Transformer(); tx.set_dumper_types([oid], pq.Format.BINARY)
    return bytes(tx.dump_sequence([v], [pq.Format.BINARY])[0])
cases = [(20, 2**63), (20, -2**63), (21, 2**15), (21, -2**15-1), (23, -2**31-1), (1700, Decimal("Infinity")), (1700, Decimal("-Infinity")),
         (1700, Decimal("sNaN")), (701, float("nan")), (701, float("inf")), (25, "a\udcffb"), (25, "nul\x00byte"), (1043, ""),
         (1082, dt.date(1,1,1)), (1082, dt.date(9999,12,31)), (1114, dt.datetime(1,1,1)), (1114, dt.datetime.max),
         (1184, dt.datetime(2026,1,1)), (16, True), (17, b"\x00\xff"), (2950, uuid.uuid4()), (1700, Decimal("1E+400")), (1700, Decimal("1E-400"))]
for oid, v in cases:
    try: ours = encode_binary(oid, v).hex()
    except Exception as e: ours = f"RAISE {type(e).__name__}"
    try: theirs = psy(oid, v).hex()
    except Exception as e: theirs = f"RAISE {type(e).__name__}"
    print("same" if ours == theirs else "DIFF", oid, repr(v)[:28], "| ours", ours[:24], "| psy", theirs[:24])
