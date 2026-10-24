# Using the ADBC PostgreSQL driver

`adbc-driver-postgresql` (Apache Arrow ADBC) can connect to IRIS through iris-pgwire and read query
results as Arrow tables. It is the driver behind the Postgres paths in pandas, Polars and DuckDB, and
behind dbt Fusion's Postgres adapter.

```python
import adbc_driver_postgresql.dbapi as pg

with pg.connect("postgresql://_SYSTEM:SYS@localhost:5432/USER?sslmode=disable") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT CAST('2026-10-24' AS DATE) AS d, 'hello' AS s")
        print(cur.fetch_arrow_table())
```

Use `sslmode=require` against a server running with TLS, which is what the server expects unless it
was started with `--allow-plaintext-password` (see [Authentication](../README.md#authentication)).

## What works

Verified against adbc-driver-postgresql 1.12.0, on the embedded and the DBAPI backend:

- connecting, including the driver's type-resolution query against `pg_catalog.pg_type`;
- `cursor.execute(...)` and `fetch_arrow_table()` for `integer`, `bigint`, `smallint`, `double`,
  `varchar` (UTF-8), `date`, `timestamp`, `bit` (as Arrow `bool`) and NULLs, including empty results
  and results with several rows and columns;
- both of the driver's ways to fetch, `adbc.postgresql.use_copy` true (the default, and the only mode
  dbt Fusion uses: every result arrives as a binary `COPY`) and false (binary result format);
- `commit()` and `rollback()`, and recovery after a failing statement;
- `adbc_get_info()` and `adbc_get_table_types()`.

The same `COPY (query) TO STDOUT` works for any client, in `text` (the default, as in PostgreSQL),
`csv` and `binary` formats, over both the simple and the extended protocol. Its output matches
PostgreSQL 16 byte for byte, message boundaries included.

## What does not work yet

| Feature                                       | Why                                                                                                                                      |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `adbc_get_objects()`                          | needs `pg_database`, `pg_table_is_visible`, `unnest(conkey)` and the `!~` operator; returns an empty result                              |
| `adbc_get_table_schema()`                     | the driver's query casts to `regclass`, which is not supported                                                                           |
| `adbc_ingest()` (bulk load)                   | fails first at `SELECT CURRENT_SCHEMA()`, which is not supported; the binary `COPY ... FROM STDIN` it would run next has no decoder here |
| `time` columns                                | declared `varchar`, so Arrow gets a string; the embedded backend returns seconds since midnight (`'45296'`)                              |
| `numeric` columns on the **embedded** backend | declared `float8`, so Arrow gets a `double`; the DBAPI backend correctly reports `numeric`                                               |

The last two are wrong _type declarations_ in the result materialiser, not wrong values. They are
pinned by strict expected-failure tests in `tests/e2e/test_adbc.py` and belong to feature 051.

## Running the suite

The embedded backend runs inside the IRIS container, so run the tests where they can reach it (a
container on the same network works) and where the driver is installed:

```bash
pip install adbc-driver-postgresql pyarrow pytest
PGWIRE_E2E_TARGETS="embedded=127.0.0.1:5434,dbapi=host.docker.internal:5441" \
    pytest --noconftest tests/e2e/test_adbc.py
```

Start a server with `python tests/e2e/_auth_server.py <port> password [embedded|dbapi]`. The embedded
backend runs inside the IRIS container.
