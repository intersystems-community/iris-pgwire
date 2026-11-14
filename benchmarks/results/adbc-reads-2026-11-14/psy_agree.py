import sys, random, datetime as dt
from decimal import Decimal
sys.path.insert(0, "/Users/tdyar/ws/iris-pgwire/src"); sys.path.insert(0, "/Users/tdyar/ws/iris-pgwire")
from tests.unit.binary_value_fixtures import CASES
from iris_pgwire.value_encoding import encode_binary
from psycopg.adapt import Transformer
from psycopg import pq
def psy(oid, v):
    tx = Transformer(); tx.set_dumper_types([oid], pq.Format.BINARY)
    b = tx.dump_sequence([v], [pq.Format.BINARY])[0]
    return bytes(b)
dis = {}
for label, oid, hexv, vals in CASES:
    for v in vals:
        try: got = psy(oid, v).hex()
        except Exception as e: got = f"RAISE {type(e).__name__}"
        if got != hexv: dis.setdefault((oid, type(v).__name__), []).append((label, repr(v)[:30], got[:30]))
for k, v in dis.items(): print("DIFF", k, v[:2])
tz = dt.datetime(2026,10,24,14,34,56,tzinfo=dt.timezone(dt.timedelta(hours=2)))
for oid in (1114, 1184):
    try: print(oid, "aware:", psy(oid, tz) == encode_binary(oid, tz))
    except Exception as e: print(oid, "aware raises", type(e).__name__)
r = random.Random(5); bad = 0
for _ in range(20000):
    d = Decimal(r.choice((1,-1))*r.randint(0, 10**r.randint(0,30))).scaleb(-r.randint(-6,24))
    if psy(1700, d) != encode_binary(1700, d): bad += 1; ex = d
print("numeric sweep disagreements:", bad, ex if bad else "")
for d in [Decimal("-0"), Decimal("0.00"), Decimal("1E+14"), Decimal("NaN")]:
    print(d, psy(1700,d) == encode_binary(1700,d))
for v in [2**31, True, 3.0]:
    try: print("int4", repr(v), psy(23, v).hex())
    except Exception as e: print("int4", repr(v), "raises", type(e).__name__)
print("str in int4 col:", end=" ")
try: print(psy(23, "5").hex())
except Exception as e: print("raises", type(e).__name__)
