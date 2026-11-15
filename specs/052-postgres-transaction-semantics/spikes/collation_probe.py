"""Case-sensitivity of string comparisons: PGWire (tables created through PGWire) vs PostgreSQL 16.

Needs a PGWire DBAPI server on 5442 (`make isolation-server`) and iris-pgwire-pgref on 55433. Measured
2026-11-15 on pgwire-release-lab (IRIS 2026.2.0.221.0com); results in the investigation doc, section 5.
"""

import json

import psycopg

DSNS = {
    "pgwire": "host=127.0.0.1 port=5442 user=_SYSTEM password=SYS dbname=USER sslmode=disable",
    "postgres": "host=127.0.0.1 port=55433 user=postgres password=pgref dbname=postgres sslmode=disable",
}
SETUP = [
    "drop table if exists coll_probe_j",
    "drop table if exists coll_probe",
    "create table coll_probe (id int primary key, c varchar(20), t text)",
    "insert into coll_probe values (1, 'red', 'red')",
    "insert into coll_probe values (2, 'Red', 'Red')",
    "insert into coll_probe values (3, 'RED', 'RED')",
    "insert into coll_probe values (4, 'blue', 'blue')",
    "create table coll_probe_j (k varchar(20))",
    "insert into coll_probe_j values ('Red')",
]
QUERIES = {
    "eq_varchar": "select id from coll_probe where c = 'RED' order by id",
    "eq_text": "select id from coll_probe where t = 'RED' order by id",
    "eq_param": ("select id from coll_probe where c = %s order by id", ["RED"]),
    "ne": "select id from coll_probe where c <> 'red' order by id",
    "in_list": "select id from coll_probe where c in ('RED', 'Blue') order by id",
    "like": "select id from coll_probe where c like 'R%' order by id",
    "range_gt": "select id from coll_probe where c > 'bz' order by id",
    "order_by": "select c from coll_probe order by c, id",
    "distinct": "select distinct c from coll_probe order by c",
    "count_distinct": "select count(distinct c) from coll_probe",
    "group_by": "select c, count(*) from coll_probe group by c order by c",
    "min_max": "select min(c), max(c) from coll_probe",
    "join": "select id from coll_probe join coll_probe_j on c = k order by id",
    "upper_eq": "select id from coll_probe where upper(c) = 'RED' order by id",
    "case_expr": "select id, case when c = 'RED' then 1 else 0 end from coll_probe order by id",
}


def run(dsn):
    out = {}
    with psycopg.connect(dsn, autocommit=True) as conn:
        for sql in SETUP:
            conn.execute(sql)
        for name, q in QUERIES.items():
            sql, params = q if isinstance(q, tuple) else (q, None)
            try:
                out[name] = [list(r) for r in conn.execute(sql, params).fetchall()]
            except Exception as e:
                out[name] = f"ERROR {getattr(e, 'sqlstate', '')} {str(e)[:90]}"
        # a unique key on the column: PostgreSQL allows 'x' and 'X'
        conn.execute("drop table if exists coll_probe_u")
        conn.execute("create table coll_probe_u (c varchar(20) unique)")
        conn.execute("insert into coll_probe_u values ('x')")
        try:
            conn.execute("insert into coll_probe_u values ('X')")
            out["unique_x_X"] = "both accepted"
        except Exception as e:
            out["unique_x_X"] = f"ERROR {getattr(e, 'sqlstate', '')}"
        for t in ("coll_probe_u", "coll_probe_j", "coll_probe"):
            conn.execute(f"drop table {t}")
    return out


res = {name: run(dsn) for name, dsn in DSNS.items()}
for k in list(QUERIES) + ["unique_x_X"]:
    same = res["pgwire"][k] == res["postgres"][k]
    print(
        f"{'same' if same else 'DIFF':4} {k:15} pgwire={res['pgwire'][k]}  postgres={res['postgres'][k]}"
    )
json.dump(res, open("/tmp/collation-probe/results.json", "w"), indent=1)
