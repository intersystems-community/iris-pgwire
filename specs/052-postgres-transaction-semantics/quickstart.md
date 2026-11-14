# Quickstart: checking spec 052 by hand and with the suite

## Preconditions

- `pgwire-release-lab` up on 127.0.0.1:2992 (IRIS 2026.2), `iris-pgwire-pgref` up on 127.0.0.1:55433.
- Nothing listening on 5442, `pgwire-bench-dbapi` stopped: one PGWire server at a time on a Community Edition IRIS.

## The gate

```bash
make isolation          # fresh DBAPI server on 5442, suite against it and PostgreSQL 16, ~25 min
.venv/bin/python -m pytest tests/unit -q -p no:randomly   # in its own process
```

Every check this spec adds expects PostgreSQL's answer. A remaining IRIS difference is pinned in
`tests/e2e/isolation/known_differences.py` with its reason; a check whose pin this spec makes obsolete must have it
removed.

## By hand

Start a server on its own (`make isolation-server`), then with psql:

```sql
-- US1: the abort rule
BEGIN;
CREATE TABLE qs (id int PRIMARY KEY);   -- run once, outside the transaction, if it does not exist
INSERT INTO qs VALUES (1);
INSERT INTO qs VALUES (1);              -- ERROR 23505
INSERT INTO qs VALUES (2);              -- ERROR 25P02, current transaction is aborted
COMMIT;                                 -- ROLLBACK
SELECT count(*) FROM qs;                -- 0

-- US2: savepoints
BEGIN;
INSERT INTO qs VALUES (1);
SAVEPOINT s;
INSERT INTO qs VALUES (2);
ROLLBACK TO s;
INSERT INTO qs VALUES (3);
ROLLBACK TO s;                          -- still works: s survives
RELEASE s;
COMMIT;
SELECT id FROM qs ORDER BY id;          -- 1
```

psycopg, the case that loses data on 2.0.1:

```python
import psycopg

with psycopg.connect("host=127.0.0.1 port=5442 user=_SYSTEM password=SYS dbname=USER") as conn:
    with conn.transaction():
        conn.execute("insert into qs values (10)")
        with conn.transaction():              # exits normally: RELEASE "_pg3_1"
            conn.execute("insert into qs values (11)")
    print(conn.execute("select id from qs where id >= 10 order by id").fetchall())  # [(10,), (11,)]
```

## Settings

```bash
PGWIRE_DEFAULT_ISOLATION="read uncommitted"   # 2.0 behaviour: sessions start at READ UNCOMMITTED
PGWIRE_TXN_COMPAT=permissive                  # refusals run as in 2.0, with a warning per statement shape
```
