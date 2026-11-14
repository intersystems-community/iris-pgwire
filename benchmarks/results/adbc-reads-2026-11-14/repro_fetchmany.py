import iris.dbapi as d
c = d.connect(hostname="pgwire-release-lab", port=1972, namespace="USER", username="_SYSTEM", password="SYS")
COLS = "id, i1, i2, n1, n2, f1, f2, s1, s2, ts, d, s3"
for n in (10, 1000, 100000):
    cur = c.cursor(); cur.execute(f"SELECT {COLS} FROM PGWBench.Bench WHERE id <= {n}")
    first = cur.fetchmany(1)
    try: cur.close(); print(n, "close ok")
    except Exception as e: print(n, "close FAILED:", e)
    try:
        cur = c.cursor(); cur.execute("SELECT 42"); print(n, "next statement:", cur.fetchall()); cur.close()
    except Exception as e:
        print(n, "next statement FAILED:", e); break
