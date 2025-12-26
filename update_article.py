
import os
path = 'docs/articles/developer-community-article.md'

with open(path, 'r') as f:
    text = f.read()

# 1. Update Quick Demo Section
old_demo = """### Quick Demo: From Zero to Analytics

Once your container is up, you’re not just connected to a database—you’re connected to an ecosystem.

**1. The Classic Handshake (psql)**
```bash
psql -h localhost -p 5432 -U _SYSTEM -d USER
```

**2. Standard SQL, IRIS Power**
```sql
-- This runs on IRIS, but feels like Postgres
SELECT COUNT(*) FROM MyPatients WHERE category = "Follow-up";
```

**3. The "Killer Feature": pgvector Syntax on IRIS**
This is where it gets interesting. You can use standard `pgvector` distance operators, and IRIS PGWire translates them into native IRIS vector functions on the fly:

```sql
-- Semantic search using the pgvector <=> (cosine distance) operator
SELECT id, content 
FROM medical_notes 
ORDER BY embedding <=> TO_VECTOR("[0.1, 0.2, 0.3...]", DOUBLE) 
LIMIT 5;
```
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
```"""

new_demo = """### Quick Demo: From Zero to Analytics

Once your container is up, you’re not just connected to a database—you’re connected to an ecosystem.

**1. The Classic Handshake (psql)**
```bash
psql -h localhost -p 5432 -U _SYSTEM -d USER
```

**2. Standard SQL, IRIS Power (with Schema Mapping)**
Thanks to automatic schema mapping, you can use the `public` schema just like in PostgreSQL. It maps seamlessly to `SQLUser` in IRIS:

```sql
-- This runs on IRIS, but feels like Postgres
SELECT COUNT(*) FROM public.MyPatients WHERE category = 'Follow-up';
```

**3. The "Killer Feature": pgvector Syntax on IRIS**
This is where it gets interesting. You can use standard `pgvector` distance operators, and IRIS PGWire translates them into native IRIS vector functions on the fly:

```sql
-- Semantic search using the pgvector <=> (cosine distance) operator
SELECT id, content 
FROM medical_notes 
ORDER BY embedding <=> '[0.1, 0.2, 0.3...]' 
LIMIT 5;
```"""

text = text.replace(old_demo, new_demo)

# 2. Update Impossible Connection Section
old_conn = """### The "Impossible" Connection: No IRIS Driver? No Problem.

This isn’t just about making things *easier*—it’s about making things *possible*.

Take **Metabase Cloud** or **Prisma ORM**.

- **Metabase Cloud** is a beautiful, managed BI tool. You can’t upload an IRIS JDBC driver to their cloud servers. You are limited to their pre-installed list.
- **Prisma** is the standard ORM for modern TypeScript developers. It uses a custom engine that doesn’t (yet) speak IRIS.

Without a wire protocol adapter, these tools are locked out of your IRIS data. With **IRIS PGWire**, they just see a high-performance PostgreSQL database.

**Demo: Prisma with InterSystems IRIS**
Just point your `schema.prisma` at the PGWire port:

```prisma
datasource db {
  provider = "postgresql"
  url      = "postgresql://_SYSTEM:SYS@localhost:5432/USER"
}
```

Now you can use Prisma’s world-class CLI and type-safety:
```bash
npx prisma db pull
npx prisma generate
```"""

new_conn = """### The "Impossible" Connection: No IRIS Driver? No Problem.

This isn’t just about making things *easier*—it’s about making things *possible*.

Take **Node.js**. The IRIS Native API for Node.js is great for Globals, but it **does not support SQL**. Usually, you'd need to install and configure a system-level ODBC driver. With **IRIS PGWire**, you just use the standard `pg` library you already know.

| Approach | SQL Support | Setup Complexity | Ecosystem Access |
|----------|-------------|------------------|------------------|
| IRIS Native API | **No** (Globals only) | Medium | Proprietary only |
| node-odbc | Yes | **High** (ODBC driver) | Limited |
| **PGWire + pg** | **Yes** | **Low** (`npm install pg`) | **Full PostgreSQL** |

**Demo: Node.js with InterSystems IRIS**
Just install the standard PostgreSQL client and connect:

```bash
npm install pg
```

```javascript
const { Client } = require('pg');
const client = new Client("postgresql://_SYSTEM:SYS@localhost:5432/USER");

await client.connect();
// Querying 'public.MyPatients' maps to 'SQLUser.MyPatients' automatically!
const res = await client.query("SELECT name FROM public.MyPatients LIMIT 5");
console.log(res.rows);
```

### The "North Star": Prisma and Metabase

This architectural bridge enables tools that were previously "impossible" to use with IRIS:

- **Metabase Cloud**: A beautiful BI tool that doesn't allow custom JDBC driver uploads. Point it at PGWire, and it thinks it's talking to Postgres.
- **Prisma ORM**: The standard for modern TypeScript. We are currently implementing the `pg_catalog` and `information_schema` views required for Prisma introspection."""

text = text.replace(old_conn, new_conn)

# 3. Update Specs Section
old_specs = """└── 027-open-exchange/               # This publication!
    ├── spec.md                      # Package requirements
    ├── research.md                  # Market analysis
    ├── plan.md                      # Publication strategy
    └── tasks.md                     # Implementation steps"""

new_specs = """├── 027-open-exchange/               # This publication!
├── 028-readme-performance/          # Community benchmarks
└── 030-pg-schema-mapping/           # public ↔ SQLUser translation"""

text = text.replace(old_specs, new_specs)

with open(path, 'w') as f:
    f.write(text)
print("Updated article successfully.")
