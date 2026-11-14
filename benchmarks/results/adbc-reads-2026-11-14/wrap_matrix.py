import iris.dbapi as d
c = d.connect(hostname="pgwire-release-lab", port=1972, namespace="USER", username="_SYSTEM", password="SYS")
T = "PGWBench.Bench"
QS = ["SELECT 1", "SELECT 1+1", "SELECT 1 AS a, 'x' AS b", "SELECT 'x'", f"SELECT id, id FROM {T} WHERE id < 3",
      f"SELECT COUNT(*) FROM {T}", f"SELECT * FROM {T} ORDER BY id", f"SELECT TOP 5 * FROM {T} ORDER BY id DESC",
      f"WITH c AS (SELECT id FROM {T} WHERE id < 5) SELECT * FROM c",
      f"SELECT id FROM {T} WHERE id < 3 UNION SELECT id FROM {T} WHERE id > 99998",
      f"SELECT s1, COUNT(*) AS n FROM {T} GROUP BY s1", f"SELECT %ID, id FROM {T} WHERE id < 3",
      f"SELECT id FROM {T} WHERE id = ?", f"SELECT b.id, a.n1 FROM {T} a JOIN {T} b ON a.id = b.id WHERE a.id < 3",
      f"SELECT DISTINCT s1 FROM {T}", f"SELECT n1 * 2, UPPER(s1), CAST(d AS VARCHAR(20)) FROM {T} WHERE id < 3",
      f"SELECT id FROM {T} WHERE id < 3 FOR UPDATE", "SELECT $HOROLOG", f"SELECT id AS \"Mixed Case\" FROM {T} WHERE id < 2"]
def desc(sql, params=None):
    cur = c.cursor()
    cur.execute(sql, params) if params else cur.execute(sql)
    out = [tuple(x[:7]) for x in cur.description]; rows = cur.fetchall(); cur.close(); return out, len(rows)
for q in QS:
    p = [1] if "?" in q else None
    try: base, n = desc(q, p)
    except Exception as e: print(f"ORIG FAILS  {q[:60]}: {str(e)[:60]}"); continue
    try:
        w, wn = desc(f"SELECT TOP 1 * FROM ({q}) AS pgwire_describe", p)
        print(("same     " if w == base else "DIFFERENT"), f"{q[:70]}", "" if w == base else f"\n     orig {base}\n     wrap {w}")
    except Exception as e:
        print(f"WRAP FAILS  {q[:70]}: {str(e)[:70]}")
