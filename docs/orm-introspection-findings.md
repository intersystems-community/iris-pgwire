# ORM introspection against iris-pgwire — test results and defects

**Status**: 🟡 PARTIAL — five defects **fixed, verified on both backends, and covered by regression
tests**; one remains (5b), and it is the largest
**Tested**: 2026-08-16, IRIS 2026.2 (Build 221U), `intersystems/iris-community:latest-cd`
**Backends**: both — embedded (irispython, port 5432) and DBAPI (external, port 15432)
**Clients**: Prisma 6.19.3 (the version this repo targets) and Prisma 7.9.1

> Motivation: schema introspection is the root of the code-generation chain that
> [`specs/043-local-first-sync/research.md`](../specs/043-local-first-sync/research.md) §1c depends
> on — typed client → Zod → generated forms → generated admin all derive from it. It was tested
> rather than assumed, and it does not currently work.

## Summary

| # | Defect | Status | Severity |
|---|--------|--------|----------|
| 3 | Malformed `CommandComplete` tag (`SELECT 0 0`) broke every emulated catalog query | ✅ **FIXED** — both backends | High |
| 1a | `pg_namespace` handler rejected the schema-qualified form clients actually emit | ✅ **FIXED** — both backends | **Blocker** |
| 1b | Catalog router stole Prisma's schema probe from the handler built to answer it | ✅ **FIXED** — both backends | **Blocker** |
| 2 | Scalar session functions unhandled on the DBAPI backend (Principle IV violation) | ✅ **FIXED** | **High** |
| 5a | `pg_class` returned zero rows — handler's own query was swallowed by the router | ✅ **FIXED** — tables now enumerate | **Blocker** |
| 5b | Catalog emulators ignore projections, aliases and JOINs | ❌ **OPEN** — now the blocker | **Blocker** |

Defect 4 (`current_setting('server_version_num')` returning `off`) resolved as a side effect: the
purpose-built handler now answers the probe and returns `160000`.

### Where introspection gets to now

| Stage | Before | After |
|---|---|---|
| `SELECT version()` | DBAPI: hard SQL error | ✅ both backends |
| Schema probe `EXISTS(… pg_namespace …)` | returns nothing → Prisma issues `CREATE SCHEMA "public"` | ✅ `exists = t`, `version`, `160000` |
| Table enumeration via `pg_class` | never reached | ✅ real tables returned |
| Prisma's aliased JOIN over `pg_class` | never reached | ❌ **projection ignored — current blocker** |

`prisma db pull` no longer dies on its first query or tries to create the `public` schema. It now
runs the full introspection sequence and reports `P4001` because table enumeration comes back
empty.

**Ordinary SQL works on both backends**, including joins across foreign keys — this is specifically
the introspection path.

---

## ✅ FIXED — Defects 1a / 1b / 3: the catalog path

Three separate bugs stacked on top of each other; all three had to go before introspection could
advance past its second query.

**Defect 3 — malformed `CommandComplete`.** `catalog_router._build_success_response` emits
`command_tag = "SELECT 0"` with the count already in it, while
`protocol._send_command_complete` treated its argument as a bare verb and appended the count
again. `"SELECT 0".upper() != "SELECT"`, so it fell to the else branch and produced
**`"SELECT 0 0"`** — not a valid tag. Clients rejected the entire result with
`could not interpret result from server`, so *every* emulated catalog query failed at the protocol
level. Fixed by detecting a count that is already present. The change is surgical — verified
against representative inputs, only strings already carrying a count behave differently, and in
every such case the old output was malformed:

| input | old | new |
|---|---|---|
| `SELECT` / 5 | `SELECT 5` | `SELECT 5` |
| `SELECT 0` / 0 | `SELECT 0 0` ✗ | `SELECT 0` ✓ |
| `INSERT 0 1` / 1 | `INSERT 0 1 1` ✗ | `INSERT 0 1` ✓ |
| `CREATE TABLE` / 0 | `CREATE TABLE 0` | `CREATE TABLE 0` |

**Defect 1a — qualified names rejected.** `is_simple_pg_namespace` required
`\bFROM\s+PG_NAMESPACE\b`, which does not match `FROM pg_catalog.pg_namespace` — the form real
clients emit. Qualified queries fell to the router's empty fallback and returned zero rows. Fixed
by accepting an optional `PG_CATALOG.` prefix.

**Defect 1b — the router stole Prisma's probe.** `SQLInterceptor` already had
`_handle_prisma_schema_check`, registered for `EXISTS.*PG_NAMESPACE.*VERSION`, returning
`schema_exists = True` — exactly right. It was never reached: the catalog router runs first and
intercepted the query, returning raw namespace rows for something that asked for a boolean. The row
emulators can project and filter columns but cannot evaluate `EXISTS(...)` or scalar functions, so
the router now declines those shapes at its entry point and lets them fall through. Putting the
guard in one handler was not enough — the router's *empty fallback* still caught them.

### Verified after the fix, both backends

```console
$ psql -c "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='public'), version()"
 exists |               version               | numeric_version
--------+-------------------------------------+-----------------
 t      | PostgreSQL 16.0 (InterSystems IRIS) |          160000
```

---

## ✅ FIXED — Defect 5a: `pg_class` enumerated no tables

`_build_pg_class_response` answers by asking IRIS for `INFORMATION_SCHEMA.TABLES` **through the
executor**. That inner query re-entered the catalog router, which has no
`information_schema.tables` handler — so the **empty fallback swallowed it and returned zero rows**.
The handler then had no tables to report, and `pg_class` was permanently empty. A self-inflicted
wound: the emulator's own data source was being intercepted by the emulator.

Fixed with a re-entrancy guard. It is a `ContextVar`, not an instance flag, so it is scoped to the
asyncio task: one session's internal query cannot suppress interception for a concurrent session.
That property is covered by a test.

```console
$ psql -tAc "SELECT relname FROM pg_class"
3909377549|customer|2200|...
3157564129|customerorder|2200|...
1128014727|orderline|2200|...
```

Real tables, in namespace 2200 (`public`).

---

## ❌ OPEN — Defect 5b: emulators ignore projections, aliases and JOINs (current blocker)

`prisma db pull` still reports `P4001`. Its table-enumeration query is not a flat select:

```sql
SELECT tbl.relname AS table_name, namespace.nspname AS namespace
FROM pg_class tbl
JOIN pg_namespace namespace ON namespace.oid = tbl.relnamespace
WHERE tbl.relkind = 'r' AND namespace.nspname = 'public'
```

The emulator returns **all 32 raw `pg_class` columns** regardless of what was asked for, performs no
join, and applies no aliases. Prisma reads results by column name, finds no `table_name`, and
concludes there are no tables.

**This is a materially larger piece of work than everything above it** — it needs enough query
evaluation over emulated rows to satisfy real introspection SQL: projections, aliases, joins across
catalog tables, and `WHERE` predicates on columns like `relkind`. Prisma's later queries add CTEs.

### Spike: project `pg_catalog` as real IRIS views — **all six unknowns cleared**

Run 2026-08-16 against IRIS 2026.2. Every question that could have killed the views approach came
back positive.

| # | Question | Result |
|---|---|---|
| 1 | Does IRIS SQL support CTEs? Prisma emits `WITH rawindex AS (…)` | ✅ `WITH t AS (…) SELECT COUNT(*) FROM t` → 4 |
| 2 | Can a schema literally named `pg_catalog` be created? | ✅ `CREATE VIEW pg_catalog.pg_class_v` succeeded |
| 3 | Projection + alias + `WHERE` over the view? | ✅ `SELECT v.relname AS table_name … WHERE …` |
| 4 | JOIN across two catalog views with aliases? | ✅ returned rows |
| 5 | Can the deterministic OID be computed in SQL? | ✅ via `SqlProc` — see below |
| 6 | Are the views visible to `INFORMATION_SCHEMA`? | ✅ 2 objects reported under `pg_catalog` |

**The OID was the one real risk and it is solved.** Calling `$SYSTEM.Encryption.SHA1Hash(...)`
inline in SQL fails with `SQLCODE -12` (a parse error — ObjectScript system functions are not SQL
callable). Exposing it as a `SqlProc` class method works:

```objectscript
ClassMethod PgOid(identity As %String) As %Integer [ SqlName = PG_OID, SqlProc ]
{
    set hash = $SYSTEM.Encryption.SHA1Hash($zconvert(identity,"L"))
    set n = 0
    for i = 1:1:4 { set n = (n * 256) + $ascii(hash, i) }
    quit 16384 + (n # 4278190080)
}
```

Verified: stable across calls (`733435086` twice), distinct for different inputs, inside the user
OID range (≥ 16384), and — the part that matters — **usable inside a `CREATE VIEW` definition**.

**The decisive test.** Prisma's exact table-enumeration shape, run against real views with *no
interception code in the path at all*:

```sql
SELECT tbl.relname AS table_name, ns.nspname AS namespace
FROM pg_catalog.pg_class_v tbl
JOIN pg_catalog.pg_namespace_test ns ON ns.oid = tbl.relnamespace
WHERE tbl.relkind = 'r' AND ns.nspname = 'public'
```

```
customer in public
customerorder in public
iadcheck in public
orderline in public
```

Four rows, correct aliases, correct join — the query the emulator could not answer, answered by
IRIS itself.

### Firm recommendation

**Project `pg_catalog` as real IRIS views over `INFORMATION_SCHEMA`, with OIDs from a `SqlProc`.**

Projections, aliases, joins, `WHERE` predicates and CTEs stop being features anyone implements —
they are the database's job, and IRIS already does them. Both backends inherit it because it lives
server-side. It generalises to Drizzle, SQLAlchemy, PostgREST and anything else, rather than to one
client's query shapes.

The alternative — extending shape-matching — recreates precisely the fragility that produced
defects 1a, 1b and 5a: three of the six defects in this document, all of which failed *silently*,
returning empty results rather than errors.

**Migration is incremental and low-risk.** Views and the router can coexist: add a view for one
catalog table, have the router decline that table, verify, move to the next. No big-bang cutover.

Remaining work to scope (none of it blocking, all of it ordinary):

- Define views for the ten emulated tables, matching PostgreSQL column names and order.
- Decide where they are created — namespace setup, IPM install, or first connection.
- Confirm type OIDs and `relkind` mapping match what clients expect.
- `regclass` casts and PG-specific operators still need the existing translation layer.

---

## Original analysis — Defect 1 as first diagnosed

On the **embedded** backend, `prisma db pull` runs to completion and reports:

```
P4001 The introspected database was empty:
prisma db pull could not create any models in your schema.prisma file
```

Three tables with foreign keys existed at the time (`Customer`, `CustomerOrder`, `OrderLine`).

The server log shows why. Prisma's final two statements were:

```sql
SET search_path = "public";
CREATE SCHEMA "public"
```

**Prisma concluded that `public` does not exist and tried to create it.** Because it believes the
schema is absent, it enumerates no tables and reports the database as empty.

`schema_mapper.py` maps `public` ↔ `SQLUser` for DDL and DML, but that mapping is evidently not
reflected in whatever catalog surface introspection uses to enumerate schemas. Introspection asks
"does `public` exist?" and gets "no".

Prisma 7 makes the same deduction and surfaces it more loudly:

```
Error: ERROR: Schema 'public' already exists
```

That error comes from `CREATE SCHEMA "public"` being translated to `SQLUser`, which does exist. So
the mapper is working on the DDL path while the introspection path disagrees with it — the two
views of "what schemas exist" are inconsistent.

**No side effect**: `INFORMATION_SCHEMA.SCHEMATA` confirms no stray `public` schema was created.

**Fix direction**: make `public` visible as an existing schema to whatever introspection queries,
consistent with the existing `public` → `SQLUser` mapping. Until then no ORM introspection can
succeed, on either backend.

---

## Defect 2 — scalar session functions unhandled on the DBAPI backend

Same probes, both backends:

| Query | Embedded | DBAPI |
|---|---|---|
| `SELECT version()` | `PostgreSQL 16.0 (InterSystems…)` | **SQL error** |
| `SELECT current_database()` | `USER` | **SQL error** |
| `SELECT current_setting('server_version_num')` | `off` (see defect 4) | **SQL error** |
| `SELECT current_schema()` | **SQL error** | **SQL error** |
| `SELECT 42` | `42` | `42` |

DBAPI failures pass straight through to IRIS SQL, which resolves them as user functions:

```
[SQLCODE: <-359>] User defined SQL function 'SQLUSER.VERSION' does not exist
```

`current_user` and `session_user` fail differently (SQLCODE `-12`, a parse error) because they are
bare keywords rather than calls.

### Cause — confirmed in code

`SQLInterceptor` (`sql_translator/interceptor.py`) registers handlers for exactly these:

```python
self.register(r"CURRENT_DATABASE", self._handle_current_database)
self.register(r"VERSION\(\)|SELECT\s+VERSION", self._handle_version)
```

It is wired into **only one** executor:

```console
$ grep -c "sql_interceptor" src/iris_pgwire/dbapi_executor.py src/iris_pgwire/iris_executor.py
src/iris_pgwire/dbapi_executor.py:0
src/iris_pgwire/iris_executor.py:2
```

`iris_executor.py:991` calls `self.sql_interceptor.intercept(...)` immediately after the catalog
router; `dbapi_executor.py:186` calls the catalog router and then goes straight to translation.

**This violates Constitution Principle IV** — both backends must remain functional, and a change
that works on only one backend is incomplete.

**Fix direction**: instantiate and call `SQLInterceptor` in `DBAPIExecutor` at the same point in the
pipeline. Separately, add `current_schema()`, which is missing from the interceptor and therefore
fails on *both* backends.

---

## Defect 3 — some `pg_catalog` query shapes return a malformed protocol response

On **both** backends:

```console
$ psql -c "SELECT COUNT(*) FROM pg_catalog.pg_class"
could not interpret result from server: SELECT 0 0

$ psql -c "SELECT relname FROM pg_catalog.pg_class LIMIT 3"
could not interpret result from server: SELECT 0 0
```

The router *does* engage — the log shows `Intercepting pg_class query` — but the reply the client
receives cannot be parsed. This is a protocol violation rather than an error: the client is left
unable to interpret the response at all, which under Principle I is worse than an honest failure.

### Scope — stated deliberately

These are **my** query shapes, not Prisma's. The emulator may only ever have been built for the
specific shapes real ORMs emit, in which case `COUNT(*)` and bare `LIMIT` projections were never in
scope and this is a missing-shape gap rather than a broken emulator. What is *not* acceptable
regardless is the failure mode: an unsupported shape should produce a clean error, never a reply
the client cannot parse.

Not yet established: which shapes are supported, and whether Prisma's own catalog queries would
succeed once defect 1 is fixed.

---

## Defect 4 — `current_setting('server_version_num')` returns `off`

On embedded the call succeeds but returns the string `off`. PostgreSQL returns a numeric version
such as `160000`, and clients use it to choose which introspection SQL dialect to emit. A
non-numeric answer risks a client either failing to parse it or silently selecting the wrong query
set.

---

## Prisma 7 support — scoping

Prisma 7.9.1 was tested alongside 6.19.3. **Supporting it is mostly the same work**, plus
documentation changes.

### What changed in Prisma 7

| Area | Prisma 6 | Prisma 7 |
|---|---|---|
| Connection URL | `url = env("DATABASE_URL")` in `schema.prisma` | **Removed.** Requires `prisma.config.ts` with `datasource.url` |
| Generator | `provider = "prisma-client-js"` | `provider = "prisma-client"` + explicit `output` |
| Runtime driver | Built-in Rust query engine | **Driver adapters** — `@prisma/adapter-pg` over `pg` |
| `.env` loading | Automatic | **Not** auto-loaded into `prisma.config.ts`; inline the URL or import `dotenv/config` |

Attempting `db pull` with a Prisma 6-style schema fails before touching the database:

```
Error code: P1012
error: The datasource property `url` is no longer supported in schema files.
```

### What this means for iris-pgwire

1. **Introspection is the same blocker.** Prisma 7 still uses the Rust introspection engine and
   makes the identical `CREATE SCHEMA "public"` deduction. Fixing defect 1 fixes both versions.
   Prisma 7 is arguably the better test target because it surfaces the failure as a hard error
   rather than a misleading "database was empty".

2. **The runtime path may get *easier*, not harder.** Prisma 7's client talks through
   `@prisma/adapter-pg`, i.e. **node-postgres** — a client this repo already verifies at 100%. That
   removes Prisma's bespoke engine from the query path and replaces it with a driver we know works.
   Worth testing once introspection succeeds; it may be that Prisma 7 runtime support is closer
   than Prisma 6 runtime support.

3. **Docs and test fixtures need updating** for the config format. Anything in the repo pinning
   `prisma@^6.19` should gain a Prisma 7 variant rather than being replaced, since both are in the
   field.

### Recommended sequence

1. Fix defect 1 (`public` visible to introspection) — unblocks everything.
2. Fix defect 2 (wire `SQLInterceptor` into `DBAPIExecutor`; add `current_schema()`).
3. Re-run `db pull` on both Prisma versions and both backends; capture the generated schema as a
   fixture.
4. Fix defect 4, then defect 3's failure mode.
5. Then test the Prisma 7 runtime over `@prisma/adapter-pg`.

## Reproduction

```bash
docker run -d --name iris-pgwire-db -p 1972:1972 -p 52773:52773 \
  intersystems/iris-community:latest-cd --check-caps false
# reset the community image password, enable %Service_CallIn for embedded mode

# DBAPI backend
IRIS_HOST=localhost IRIS_PORT=1972 IRIS_USERNAME=_SYSTEM IRIS_PASSWORD=SYS \
IRIS_NAMESPACE=USER PGWIRE_BACKEND_TYPE=dbapi PGWIRE_PORT=15432 \
  python3 -m iris_pgwire.server

# Embedded backend (inside the container; irispython is Python 3.12, so cp312 wheels)
docker exec -d iris-pgwire-db bash -c 'cd /app_src && \
  PGWIRE_BACKEND_TYPE=embedded PGWIRE_PORT=5432 \
  /usr/irissys/bin/irispython -m iris_pgwire.server'

npx prisma db pull   # against either
```

**Environment note**: `irispython` is **Python 3.12.3** while the host image here is 3.11 — wheels
with compiled extensions must be built for cp312. Copying modules from a 3.11 host silently
produces `ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'`.

## Related

- [`specs/043-local-first-sync/research.md`](../specs/043-local-first-sync/research.md) §1c — why
  this blocks the generation chain
- `specs/031-prisma-catalog-support` — the feature that built the catalog emulation
- `src/iris_pgwire/sql_translator/interceptor.py`, `src/iris_pgwire/dbapi_executor.py`
