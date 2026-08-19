# AGENTS.md

iris-pgwire implements the PostgreSQL wire protocol for InterSystems IRIS.
Use it when a client requires a PostgreSQL wire-protocol endpoint — psycopg3,
psycopg2, asyncpg, node-postgres, pgx, Npgsql, JDBC, BI tools (Superset,
Metabase, Grafana), connection poolers (PgBouncer, pgpool-II), or any tooling
that speaks `postgresql://` connection strings.

**Connection string**: `postgresql://user:pass@localhost:5432/USER`

**PyPI**: `pip install iris-pgwire` · package dep: `intersystems-irispython`
(installs as `iris` + `irisnative`), NOT `iris` standalone.

---

## When to Use iris-pgwire

| Scenario                                                    | Use iris-pgwire? |
| ----------------------------------------------------------- | ---------------- |
| Client only speaks PostgreSQL wire protocol                 | ✅ Yes           |
| pgvector-compatible tooling (`<=>`, `<#>`, `<->` operators) | ✅ Yes           |
| Standard connection poolers (PgBouncer, pgpool-II)          | ✅ Yes           |
| BI tools via standard PostgreSQL driver                     | ✅ Yes           |
| Client can use IRIS DBAPI or JDBC directly                  | ❌ Skip          |
| IRIS-native ObjectScript application                        | ❌ Skip          |

---

## Where to Look

| Need                                  | Location                                        |
| ------------------------------------- | ----------------------------------------------- |
| SQL translation logic                 | `src/iris_pgwire/vector_optimizer.py` (primary) |
| Wire protocol encode/decode           | `src/iris_pgwire/protocol.py`                   |
| Backend selection (embedded vs DBAPI) | `src/iris_pgwire/backend_selector.py`           |
| IRIS execution paths                  | `src/iris_pgwire/iris_executor.py`              |
| SQL sub-translators                   | `src/iris_pgwire/sql_translator/`               |
| Authentication (OAuth, Wallet, SCRAM) | `src/iris_pgwire/auth/`                         |
| Integration test client               | `tests/integration/`, `tests/e2e/`              |
| Feature spec detail                   | `specs/<NNN>-<name>/spec.md`                    |
| Current phase / feature status        | `STATUS.md`                                     |
| Pending work / next tasks             | `TODO.md`                                       |
| Known bugs and workarounds            | `KNOWN_LIMITATIONS.md`                          |
| Test strategy and patterns            | `TESTING.md`                                    |

---

## Architecture

```text
TCP → PGWireServer → PGWireProtocol
        ↓ translate_sql()
        VectorQueryOptimizer (vector_optimizer.py) — ALL SQL transformations
        ↓ execute_query()
        IRISExecutor → embedded iris.dbapi  OR  DBAPIExecutor → external IRIS DBAPI
```

Key files:

- `src/iris_pgwire/server.py` — `PGWireServer` asyncio TCP server; entrypoint
- `src/iris_pgwire/protocol.py` — `PGWireProtocol` — 4700-line asyncio handler;
  wire encode/decode, SCRAM auth, query dispatch
- `src/iris_pgwire/vector_optimizer.py` — **ALL SQL rewrites go here**
  (`translator.py` is bypassed at `protocol.py:897-910`)
- `src/iris_pgwire/translator.py` — bypassed; transaction verbs are the one
  exception (`sql_translator/transaction_translator.py`)
- `src/iris_pgwire/sql_translator/` — focused translators: `date_translator.py`,
  `identifier_normalizer.py`, `transaction_translator.py`, `copy_parser.py`, etc.
- `src/iris_pgwire/iris_executor.py` — `IRISExecutor`; embedded-Python path
  (`_execute_embedded_async`) and external-DBAPI path (`_execute_external_async`)
- `src/iris_pgwire/backend_selector.py` — picks `DBAPIExecutor` vs
  `EmbeddedExecutor` from `IRIS_BACKEND` env var

---

## AI Agent Workflows

### Verify a SQL translation against live IRIS

When adding or fixing a rewrite rule in `vector_optimizer.py`:

1. Confirm what IRIS accepts by running the target SQL directly via iad:

   ```python
   # iris-agentic-dev iris_query tool — connection: iris-pgwire-db
   iris_query(sql="SELECT TOP 5 Name FROM SQLUser.MyTable", namespace="USER")
   ```

2. Compare to what iris-pgwire sends — enable trace logging:

   ```bash
   docker exec iris-pgwire bash -c \
     "PGWIRE_LOG_LEVEL=DEBUG python -m iris_pgwire.server"
   ```

3. Add a regression test in `tests/unit/` (no IRIS needed for pure translation
   tests) or `tests/integration/` (requires live container).

### Debug wire protocol issues

1. Set `PGWIRE_LOG_LEVEL=TRACE` in docker-compose.yml to enable packet tracing.
2. Inspect IRIS-side session state via iad:

   ```python
   iris_execute(code='w $zu(67,0)', connection="iris-pgwire-db")
   ```

3. Use `iris_query` to run the exact SQL pgwire would send; compare result/error
   to what the client receives.

### Run integration tests with a live container

```python
# iris-devtester resolves container ports — never hardcode
from iris_devtester import IRISContainer
container = IRISContainer.attach("iris-pgwire-db")
host, port = container.host, container.port
```

```bash
PGWIRE_BACKEND_TYPE=dbapi PGWIRE_POOL_SIZE=1 \
  pytest tests/integration/ tests/e2e/ -v
```

### Add a new SQL translation rule

1. Write a failing unit test in `tests/unit/` (pure translation, no IRIS needed).
2. Add the rewrite rule to `vector_optimizer.py` (or the relevant sub-translator
   in `sql_translator/`).
3. Verify the rewrite produces valid IRIS SQL:

   ```bash
   docker exec iris-pgwire iris session IRIS -U USER
   ```

4. Add a regression test.

---

## IRIS DBAPI Reference

These are the IRIS connection patterns iris-pgwire uses internally. Relevant when
debugging executor paths or writing integration fixtures.

### Embedded Python (irispython — inside Docker only)

```python
import iris
conn = iris.sql.connect()           # embedded, zero-latency
cursor = conn.cursor()
cursor.execute("SELECT %ID, Name FROM SQLUser.MyTable WHERE Name = ?", ["Alice"])
rows = cursor.fetchall()
conn.close()
```

### External DBAPI (TCP — works from host or CI)

```python
import intersystems_iris.dbapi as dbapi
conn = dbapi.connect(
    hostname="localhost",
    port=2972,             # iris-pgwire-db host port
    namespace="USER",
    username="_SYSTEM",
    password="SYS",
)
cursor = conn.cursor()
cursor.execute("SELECT %ID, Name FROM SQLUser.MyTable")
```

### IRIS SQL quirks that affect translation

1. **Semicolons** — IRIS rejects trailing semicolons. Strip them.
2. **ISO dates** — `2025-01-01` rejected in DATE columns. Use `{d '2025-01-01'}`.
3. **DROP TABLE** — comma-separated form rejected; one statement per table.
4. **Mixed-case identifiers** — IRIS upcases unquoted names. Quote with `"colName"`.
5. **pg_catalog** — IRIS has `INFORMATION_SCHEMA` only; rewrite all `pg_catalog.*`.
6. **CREATE TABLE IF NOT EXISTS** — rejected by IRIS; pgwire intercepts the error
   and skips gracefully.
7. **ALTER TABLE ADD COLUMN** — rejects existing columns; treat as no-op.
8. **Privilege check** — use `%CHECKPRIV`, not `has_table_privilege`.

---

## Ecosystem Integration

| Tool                   | Role in iris-pgwire dev                                                              |
| ---------------------- | ------------------------------------------------------------------------------------ |
| iris-agentic-dev (iad) | IRIS introspection: `iris_query`, `iris_execute`, `iris_doc` for live SQL inspection |
| iris-devtester (idt)   | Container lifecycle — `IRISContainer.attach("iris-pgwire-db")` for port resolution   |
| iris-vector-graph      | pgvector-style vector queries over IRIS Vector Search; shares `<=>` operator path    |

**Container**: `iris-pgwire-db` · host port `2972` (IRIS DBAPI) · `52776` (web portal)

Configure iad for iris-pgwire's container in `.iris-agentic-dev.toml`:

```toml
[connections.iris-pgwire-db]
host = "localhost"
web_port = 52776   # iad connects over the Atelier REST API on the WEB port,
                   # not the SQL port. Use the host port mapped to IRIS 52773.
namespace = "USER"
username = "_SYSTEM"
password = "SYS"
```

> **Do not put the SQL port here.** `port` is accepted as an alias for `web_port`, so
> `port = 2972` parses cleanly and silently points iad at the SQL port, producing a confusing
> connection error rather than a config complaint.

---

## Agent Skills

Install `iris-agentic-dev` for IRIS-aware development, then load these skills.
It is a Rust binary and is **not on PyPI** — `pip install iris-pgwire[ai]` does not resolve it
(see [bug report](iris-agentic-dev-bug-report.md)). Use a released binary:

```bash
# Linux x86-64
curl -fsSL https://github.com/intersystems-community/iris-agentic-dev/releases/latest/download/iris-agentic-dev-linux-x86_64 \
  -o /usr/local/bin/iris-agentic-dev && chmod +x /usr/local/bin/iris-agentic-dev

# macOS (Apple Silicon)
brew install https://raw.githubusercontent.com/intersystems-community/iris-agentic-dev/master/Formula/iris-agentic-dev.rb
```

- **iris-connectivity** — IRIS connection patterns (DBAPI, embedded, TCP params)
- **iris-sql** — IRIS SQL quirks that affect pgwire translation (dates, identifiers,
  reserved words, DDL limits)
- **iris-pgwire** — psycopg3 patterns, parameter binding, translation gaps
  (see `skills/iris-pgwire/SKILL.md`)

---

## Docker

```bash
docker compose up --build -d                                     # build + start
docker exec iris-pgwire bash -c 'find /app/src -name "*.pyc" -delete'
docker compose restart iris-pgwire                               # after code changes
```

**Bytecode warning**: `.pyc` files persist across restarts. Delete before testing.

---

## Vector Support (HNSW)

- `Distance=` param is **mandatory** in every HNSW index definition
- ACORN-1 is deprecated — 20-72% slower than HNSW at all scales
- HNSW benefit kicks in at ≥100K vectors (~5× improvement); <10K → sequential scan
- All HNSW work goes in `vector_optimizer.py`

---

## Development

**Test-first**: write tests before implementation.

```bash
pytest tests/unit/ tests/contract/ -v        # fast, no IRIS needed
pytest tests/integration/ -v                 # requires running iris-pgwire-db
pytest tests/e2e/ -v                         # end-to-end with real clients
pytest -m "not slow" -v                      # skip slow tests
```

**SQL fixes workflow**:

1. Reproduce in a unit test (`tests/unit/`)
2. Add rewrite rule to `vector_optimizer.py`
3. Verify with `docker exec` direct IRIS SQL check
4. Add regression test

---

## Quality

```bash
python -m iris_pgwire.quality          # PyPI readiness check
python -m iris_pgwire.quality --verbose
bump2version patch                      # version bump
```
