"""Which ways of learning a query's columns without reading all its rows leave the connection usable?"""
import time
import iris.dbapi as d
COLS = "id, i1, i2, n1, n2, f1, f2, s1, s2, ts, d, s3"
Q = f"SELECT {COLS} FROM PGWBench.Bench WHERE id <= 100000"

def connect():
    return d.connect(hostname="pgwire-release-lab", port=1972, namespace="USER", username="_SYSTEM", password="SYS")

def variant(name, describe):
    c = connect()
    try:
        t = time.perf_counter(); desc = describe(c); took = time.perf_counter() - t
        ok = []
        for _ in range(3):  # the connection must keep working, and give right answers
            cur = c.cursor(); cur.execute("SELECT 42"); ok.append(cur.fetchall()[0][0]); cur.close()
            cur = c.cursor(); cur.execute(Q); ok.append(len(cur.fetchall())); cur.close()
        print(f"{name:<34} {took:.3f}s cols={len(desc) if desc else None} after={ok}")
    except Exception as e:
        print(f"{name:<34} FAILED: {str(e)[:90]}")
    finally:
        try: c.close()
        except Exception: pass

def no_fetch_close(c):
    cur = c.cursor(); cur.execute(Q); desc = cur.description; cur.close(); return desc
def no_fetch_no_close(c):
    cur = c.cursor(); cur.execute(Q); return cur.description
def fetchone_nextset_close(c):
    cur = c.cursor(); cur.execute(Q); desc = cur.description; cur.fetchone(); cur.nextset(); cur.close(); return desc
def top1_wrap(c):
    cur = c.cursor(); cur.execute(f"SELECT TOP 1 * FROM ({Q}) AS q"); desc = cur.description; cur.fetchall(); cur.close(); return desc
def top0_wrap(c):
    cur = c.cursor(); cur.execute(f"SELECT TOP 0 * FROM ({Q}) AS q"); desc = cur.description; cur.fetchall(); cur.close(); return desc
def where_false(c):
    cur = c.cursor(); cur.execute(f"SELECT * FROM ({Q}) AS q WHERE 1=0"); desc = cur.description; cur.fetchall(); cur.close(); return desc
def full(c):
    cur = c.cursor(); cur.execute(Q); desc = cur.description; cur.fetchall(); cur.close(); return desc

for name, fn in [("full fetch (today)", full), ("execute, description, close", no_fetch_close),
                 ("execute, description, no close", no_fetch_no_close),
                 ("fetchone, nextset, close", fetchone_nextset_close),
                 ("TOP 1 wrapper", top1_wrap), ("TOP 0 wrapper", top0_wrap), ("WHERE 1=0 wrapper", where_false)]:
    variant(name, fn)
# Does a wrapper report the same column types?
c = connect()
def types(sql):
    cur = c.cursor(); cur.execute(sql); t = [tuple(x[:2]) + tuple(x[2:7]) for x in cur.description]; cur.fetchall(); cur.close(); return t
base = types(Q)
for w in (f"SELECT TOP 1 * FROM ({Q}) AS q", f"SELECT TOP 0 * FROM ({Q}) AS q"):
    print("same description as the query:", types(w) == base, w[:20])
print(base[:3])
