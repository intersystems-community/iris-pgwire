"""Each stage of a DBAPI-backend 100k-row read, timed in the server's own container."""
import asyncio, time, statistics
import iris.dbapi as d
from iris_pgwire.dbapi_executor import DBAPIExecutor
from iris_pgwire.models.backend_config import BackendConfig
from iris_pgwire.copy_export import export_messages, resolve_export_format
from iris_pgwire.sql_translator.copy_parser import CSVOptions

SQL = "SELECT id, i1, i2, n1, n2, f1, f2, s1, s2, ts, d, s3 FROM PGWBench.Bench WHERE id <= 100000"
def med(f, n=5):
    ts = [];
    for _ in range(n):
        t = time.perf_counter(); out = f(); ts.append(time.perf_counter() - t)
    return statistics.median(ts), out

c = d.connect(hostname="pgwire-release-lab", port=1972, namespace="USER", username="_SYSTEM", password="SYS")
def raw():
    cur = c.cursor(); cur.execute(SQL); r = cur.fetchall(); cur.close(); return r
t, rows = med(raw); print(f"official fetchall alone:   {t:.3f}s")

ex = DBAPIExecutor(BackendConfig(backend_type="dbapi", iris_hostname="pgwire-release-lab", iris_password="SYS"))
loop = asyncio.new_event_loop()
t, res = med(lambda: loop.run_until_complete(ex.execute_query(SQL, session_id=None)))
print(f"executor.execute_query:    {t:.3f}s rows={len(res['rows'])}")
fmt = resolve_export_format(CSVOptions(format="binary", explicit=frozenset({"format"})))
t, n = med(lambda: sum(len(p) for p in export_messages(fmt, res["columns"], res["rows"])))
print(f"binary COPY encode:        {t:.3f}s bytes={n}")
print("column oids:", [(c['name'], c['type_oid']) for c in res['columns']])
