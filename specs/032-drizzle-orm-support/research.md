# Research: Drizzle ORM Support

**Feature**: 032-drizzle-orm-support
**Date**: 2025-12-25

## Executive Summary

Drizzle ORM does **NOT** natively support InterSystems IRIS. There is no JDBC, ODBC, or native driver support for IRIS in Drizzle. The only way to use Drizzle with IRIS is through **PostgreSQL wire protocol emulation** (IRIS PGWire), which is exactly what this feature validates.

This research confirms that Feature 032 is valuable and necessary - it enables Drizzle ORM users to work with IRIS databases using existing PostgreSQL compatibility.

---

## Research Question 1: Does Drizzle Already Support IRIS?

### Decision: NO - IRIS PGWire is the only path

### Findings

**Drizzle ORM officially supports only:**
- PostgreSQL (including Neon, Supabase, AWS Data API)
- MySQL (including PlanetScale)
- SQLite (including Turso, Cloudflare D1, LiteFS)
- SingleStore

**IRIS-specific findings:**
- No native IRIS driver exists for Drizzle
- No JDBC/ODBC adapter for Drizzle (it uses native Node.js drivers only)
- No community plugins for Drizzle-IRIS integration
- InterSystems has experimental TypeORM support (`typeorm-iris`), but NOT Drizzle

### Rationale for PGWire Approach

Since Drizzle connects via PostgreSQL wire protocol drivers (postgres.js, node-postgres), IRIS PGWire provides the compatibility layer. Drizzle doesn't know or care that it's talking to IRIS - it just speaks PostgreSQL protocol.

### Alternatives Considered

| Alternative | Rejected Because |
|-------------|------------------|
| Native IRIS driver for Drizzle | Would require forking Drizzle, maintaining custom dialect |
| JDBC bridge | Drizzle doesn't support JDBC, only native Node.js drivers |
| ODBC bridge | Same as JDBC - no ODBC support in Drizzle |
| TypeORM instead | Different ORM, doesn't address Drizzle users |

---

## Research Question 2: Drizzle Introspection Queries

### Decision: Drizzle uses standard PostgreSQL catalogs (similar to Prisma)

### Findings

Drizzle-kit introspect queries:
- **information_schema**: tables, columns, constraints
- **pg_catalog**: pg_class, pg_attribute, pg_index, pg_constraint, pg_namespace
- Fetches: tables, columns, indexes, foreign keys, enums, views

**Evidence from drizzle-kit output:**
```
Pulling from ['public'] list of schemas
Using 'pg' driver for database querying...
[✓] X tables fetched
[✓] X columns fetched
[✓] X indexes fetched
[✓] X foreign keys fetched
```

This output pattern indicates separate queries for each metadata type, matching the catalog emulation we implemented in Feature 031.

### Verification Approach

Enable PostgreSQL logging during drizzle-kit introspect to capture exact queries:
```sql
SET log_statement = 'all';
SET log_min_duration_statement = 0;
```

Then compare captured queries against our catalog emulation coverage.

---

## Research Question 3: Driver Selection

### Decision: Use `postgres.js` for IRIS PGWire compatibility

### Comparison

| Aspect | postgres.js | node-postgres (pg) |
|--------|-------------|-------------------|
| Wire protocol | Pure implementation | Native bindings available |
| Custom DB compatibility | Better (fewer PG-specific assumptions) | Good (but more assumptions) |
| Serverless | Optimized | Heavier |
| Drizzle adapter | `drizzle-orm/postgres-js` | `drizzle-orm/node-postgres` |

### Rationale

`postgres.js` is recommended for custom PostgreSQL-compatible databases because:
1. Pure JavaScript - no native bindings that might expect PostgreSQL internals
2. Simpler wire protocol implementation with fewer PostgreSQL-specific assumptions
3. Works well with protocol-compatible databases (CockroachDB, etc.)

However, we should test both drivers to ensure compatibility.

---

## Research Question 4: Drizzle vs Prisma Differences

### Decision: Minimal differences - existing catalog support should work

### Findings

| Aspect | Prisma | Drizzle |
|--------|--------|---------|
| Introspection command | `prisma db pull` | `drizzle-kit introspect` |
| Schema format | schema.prisma (DSL) | schema.ts (TypeScript) |
| Catalog queries | pg_catalog + info_schema | pg_catalog + info_schema |
| RETURNING support | Yes (implicit) | Yes (explicit `.returning()`) |
| Migration tool | `prisma migrate` | `drizzle-kit push/migrate` |

**Key insight**: Both ORMs query the same PostgreSQL system catalogs. Our Feature 031 implementation covers the requirements.

### Potential Differences to Test

1. **Array parameters**: Drizzle may use different array serialization
2. **Query patterns**: JOIN structures may differ slightly
3. **Type expectations**: Drizzle may expect specific type OIDs

---

## Research Question 5: Transaction Support

### Decision: Existing transaction support should work

### Drizzle Transaction Pattern

```typescript
await db.transaction(async (tx) => {
  await tx.insert(users).values({ name: 'Alice' });
  await tx.update(users).set({ name: 'Bob' }).where(eq(users.id, 1));
});
```

### IRIS PGWire Support

- BEGIN/COMMIT/ROLLBACK: Supported
- Savepoints: Supported
- Transaction isolation: Supported

No additional work expected for transaction support.

---

## Gaps Identified

### Potential Issues to Verify

1. **Drizzle-specific catalog queries**: May need to capture and analyze exact queries
2. **Type serialization**: Drizzle may have different type expectations
3. **Error message format**: Drizzle may parse error messages differently

### Low-Risk Areas (Already Covered)

1. RETURNING clause emulation (Feature 031)
2. pg_catalog tables (Feature 031)
3. information_schema views (Feature 031)
4. Schema mapping public ↔ SQLUser (Feature 030)
5. Parameter placeholder translation $N → ? (existing)

---

## Conclusions

1. **IRIS PGWire is the ONLY way** to use Drizzle with IRIS - no native support exists
2. **Existing catalog emulation** (Feature 031) should cover Drizzle's requirements
3. **postgres.js driver** recommended for best compatibility
4. **Verification testing** is the main work - minimal new implementation expected
5. **Feature is valuable** - enables entire Drizzle ecosystem for IRIS users

---

## References

- Drizzle ORM documentation: https://orm.drizzle.team
- Drizzle-kit introspect: https://orm.drizzle.team/docs/kit-overview
- postgres.js driver: https://github.com/porsager/postgres
- Feature 031 (Prisma Catalog Support): ../031-prisma-catalog-support/
