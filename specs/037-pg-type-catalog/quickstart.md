# Quickstart: Verifying pg_type Emulation

## Setup

Ensure you have a running InterSystems IRIS instance and the `iris-pgwire` server started.

```bash
# Example start command
python -m iris_pgwire.server --port 5432 --iris-host localhost --iris-user _SYSTEM --iris-password SYS
```

## Verification Steps

### 1. Manual SQL Verification
Connect using `psql` or any PostgreSQL client and run the following query:

```sql
SELECT oid, typname, typnamespace, typtype, typcategory 
FROM pg_catalog.pg_type 
WHERE typname IN ('int4', 'bool', 'varchar', 'vector');
```

**Expected Result**:
- `int4`: OID 23, category N
- `bool`: OID 16, category B
- `varchar`: OID 1043, category S
- `vector`: OID 16388, category U

### 2. Drizzle ORM Test
If you have a Next.js/Node.js project with Drizzle:

```bash
npx drizzle-kit push
```

**Expected Result**:
The migration should complete (or report "No changes") without failing on the `pg_type` query.

### 3. Extension Check
Verify `pg_extension` interception:

```sql
SELECT * FROM pg_catalog.pg_extension;
```

**Expected Result**:
Empty result set (0 rows) with no errors.
