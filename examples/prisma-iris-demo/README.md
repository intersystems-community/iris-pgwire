# IRIS PGWire Demo - Node.js PostgreSQL Clients

Demonstrates how standard PostgreSQL clients can connect to InterSystems IRIS via the PGWire protocol with automatic schema mapping.

## Why PGWire for Node.js?

**The IRIS Native API for Node.js does NOT support SQL queries.** It only provides:
- Direct Globals access (`iris.set()`, `iris.get()`)
- ObjectScript method calls

| Approach | SQL Support | Setup | Ecosystem Access |
|----------|-------------|-------|------------------|
| IRIS Native API | **No** | Medium | Proprietary only |
| node-odbc | Yes | High (driver install) | Limited |
| **PGWire + pg** | **Yes** | **Low** (`npm install pg`) | **Full PostgreSQL** |

PGWire enables the entire Node.js PostgreSQL ecosystem to work with IRIS:
- Standard `pg` client
- ORMs (Sequelize, TypeORM, Knex)
- Database tools (pgAdmin, DBeaver)

## Quick Start

```bash
# Install dependencies
npm install

# Run the Node.js demo
node node-postgres-demo.js
```

## What This Demonstrates

### Feature 030: PostgreSQL Schema Mapping

IRIS stores tables in the `SQLUser` schema, but PostgreSQL clients expect the `public` schema. PGWire automatically maps between them:

- **Input**: `SELECT * FROM public.users` → Executes as `SQLUser.users`
- **Output**: `table_schema='SQLUser'` → Returns as `table_schema='public'`

### Working Demo (node-postgres)

The `node-postgres-demo.js` demonstrates:

1. **Schema Mapping** - Query `information_schema.tables WHERE table_schema = 'public'`
2. **Public Schema Syntax** - Use `public.tablename` to reference IRIS tables
3. **CRUD Operations** - CREATE TABLE, INSERT, SELECT, DELETE
4. **Parameterized Queries** - Prepared statements with `$1` placeholders
5. **Transactions** - BEGIN, COMMIT, ROLLBACK

### Sample Output

```
🔌 IRIS PGWire Demo - Node.js PostgreSQL Client

============================================================
✅ Connected to IRIS via PostgreSQL wire protocol

📋 Demo 1: Schema Mapping (public → SQLUser)
------------------------------------------------------------
Query: SELECT ... FROM information_schema.tables WHERE table_schema = 'public'
Result (IRIS SQLUser tables shown as "public"):
  - ASYNC_BULK_TEST (schema: public)
  - DEMO_VECTORS (schema: public)
  - MEDICAL_NOTES (schema: public)

📋 Demo 2: Query with public.tablename Syntax
------------------------------------------------------------
Query: SELECT COUNT(*) FROM public.DEMO_VECTORS
Result: 1 rows

...

🎉 Demo Complete! IRIS is accessible via PostgreSQL protocol.
```

## Prisma Status

Prisma ORM introspection (`prisma db pull`) requires additional PostgreSQL system catalogs that are not yet fully implemented in PGWire:

- `pg_namespace` - Partially implemented
- Array parameter serialization - In progress
- `pg_class`, `pg_constraint` - Not yet implemented

**Workaround**: Use node-postgres directly for now:

```javascript
const { Client } = require('pg');

const client = new Client({
    host: 'localhost',
    port: 5432,
    database: 'USER',
    user: '_SYSTEM',
    password: 'SYS',
});

await client.connect();
const result = await client.query('SELECT * FROM public.my_table');
```

## Connection Details

| Parameter | Value |
|-----------|-------|
| Host | localhost |
| Port | 5432 |
| Database | USER |
| User | _SYSTEM |
| Password | SYS |
| Schema | public (maps to SQLUser) |

## Files

- `node-postgres-demo.js` - Working demo with node-postgres client
- `prisma/schema.prisma` - Prisma schema (introspection in progress)
- `.env` - Connection string configuration

## Requirements

- IRIS PGWire server running (port 5432)
- Node.js 18+
- npm packages: `pg`
