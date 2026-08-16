# ORM introspection against iris-pgwire — test results and defects

**Status**: 🔎 OPEN — four defects, none fixed
**Tested**: 2026-08-16, IRIS 2026.2 (Build 221U), `intersystems/iris-community:latest-cd`
**Backends**: both — embedded (irispython, port 5432) and DBAPI (external, port 15432)
**Clients**: Prisma 6.19.3 (the version this repo targets) and Prisma 7.9.1

> Motivation: schema introspection is the root of the code-generation chain that
> [`specs/043-local-first-sync/research.md`](../specs/043-local-first-sync/research.md) §1c depends
> on — typed client → Zod → generated forms → generated admin all derive from it. It was tested
> rather than assumed, and it does not currently work.

## Summary

| # | Defect | Embedded | DBAPI | Severity |
|---|--------|----------|-------|----------|
| 1 | `public` schema invisible to introspection — Prisma tries to `CREATE SCHEMA "public"` | ✗ | ✗ | **Blocker** |
| 2 | Scalar session functions unhandled on the DBAPI backend | ✅ works | ✗ | **High** |
| 3 | Some `pg_catalog` query shapes return a malformed protocol response | ✗ | ✗ | High |
| 4 | `current_setting('server_version_num')` returns `off` | ✗ | ✗ | Medium |

**Ordinary SQL works on both backends**, including joins across foreign keys — this is specifically
the introspection path.

---

## Defect 1 — the `public` schema is invisible to introspection (BLOCKER)

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
