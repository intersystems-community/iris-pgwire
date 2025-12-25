# Quickstart: Prisma Introspection Validation

**Feature**: 031-prisma-catalog-support
**Purpose**: Step-by-step validation that Prisma `db pull` works with IRIS PGWire
**Created**: 2025-12-23

---

## Prerequisites

- Docker Desktop running
- Node.js 18+ installed
- npm or yarn installed
- IRIS PGWire container running with catalog support

---

## Step 1: Start IRIS PGWire Container

```bash
# From repository root
cd /Users/tdyar/ws/iris-pgwire-gh

# Start container
docker-compose up -d

# Verify container is running
docker ps | grep iris-pgwire

# Check PGWire is listening on port 5432
docker logs iris-pgwire 2>&1 | grep -i "listening"
```

**Expected Output**:
```
iris-pgwire is running
PGWire listening on port 5432
```

---

## Step 2: Create Test Tables in IRIS

Connect to IRIS and create sample tables for introspection testing.

```bash
# Connect via psql (or any PostgreSQL client)
psql -h localhost -p 5432 -U _SYSTEM -d USER

# Or use the IRIS Management Portal SQL execution
```

**Create test schema**:
```sql
-- Users table
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create unique constraint on email
CREATE UNIQUE INDEX users_email_unique ON users(email);

-- Products table
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    description TEXT,
    is_active BIT DEFAULT 1
);

-- Orders table with foreign key
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    total DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Order items table with composite foreign key
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price DECIMAL(10, 2) NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id),
    FOREIGN KEY (product_id) REFERENCES products(id)
);

-- Verify tables created
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'SQLUser';
```

**Expected Output**:
```
TABLE_NAME
-----------
users
products
orders
order_items
```

---

## Step 3: Initialize Prisma Project

Create a new Prisma project to test introspection.

```bash
# Create test directory
mkdir -p /tmp/prisma-iris-test
cd /tmp/prisma-iris-test

# Initialize npm project
npm init -y

# Install Prisma
npm install prisma --save-dev
npm install @prisma/client

# Initialize Prisma
npx prisma init --datasource-provider postgresql
```

---

## Step 4: Configure Prisma Connection

Edit the `.env` file:

```bash
# /tmp/prisma-iris-test/.env
DATABASE_URL="postgresql://_SYSTEM:SYS@localhost:5432/USER?schema=public"
```

Edit `prisma/schema.prisma`:

```prisma
// prisma/schema.prisma
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}
```

---

## Step 5: Run Prisma Introspection

Execute `prisma db pull` to introspect the IRIS database.

```bash
cd /tmp/prisma-iris-test
npx prisma db pull
```

**Expected Behavior**:
- Command completes without errors
- `prisma/schema.prisma` is updated with model definitions

**If Errors Occur**:
- Check container logs: `docker logs iris-pgwire`
- Verify connection: `psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 1"`
- Check catalog queries in PGWire debug logs

---

## Step 6: Validate Generated Schema

Check the generated `prisma/schema.prisma` file:

```bash
cat prisma/schema.prisma
```

**Expected Schema** (approximately):

```prisma
generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model users {
  id         Int       @id
  email      String    @unique @db.VarChar(255)
  name       String?   @db.VarChar(100)
  created_at DateTime? @default(now())
  orders     orders[]
}

model products {
  id          Int           @id
  name        String        @db.VarChar(255)
  price       Decimal       @db.Decimal(10, 2)
  description String?
  is_active   Boolean?      @default(true)
  order_items order_items[]
}

model orders {
  id          Int           @id
  user_id     Int
  total       Decimal       @db.Decimal(10, 2)
  status      String?       @default("pending") @db.VarChar(50)
  created_at  DateTime?     @default(now())
  user        users         @relation(fields: [user_id], references: [id])
  order_items order_items[]
}

model order_items {
  id         Int      @id
  order_id   Int
  product_id Int
  quantity   Int      @default(1)
  unit_price Decimal  @db.Decimal(10, 2)
  order      orders   @relation(fields: [order_id], references: [id])
  product    products @relation(fields: [product_id], references: [id])
}
```

---

## Step 7: Validation Checklist

Use this checklist to verify successful introspection:

### Tables Discovered
- [ ] `users` model present
- [ ] `products` model present
- [ ] `orders` model present
- [ ] `order_items` model present

### Primary Keys
- [ ] `users.id` has `@id` annotation
- [ ] `products.id` has `@id` annotation
- [ ] `orders.id` has `@id` annotation
- [ ] `order_items.id` has `@id` annotation

### Column Types
- [ ] `VARCHAR` mapped to `String` with `@db.VarChar(n)`
- [ ] `INTEGER` mapped to `Int`
- [ ] `DECIMAL` mapped to `Decimal` with `@db.Decimal(p, s)`
- [ ] `TIMESTAMP` mapped to `DateTime`
- [ ] `TEXT` mapped to `String`
- [ ] `BIT` mapped to `Boolean`

### Constraints
- [ ] `users.email` has `@unique` annotation
- [ ] NOT NULL columns are non-optional (no `?`)
- [ ] Nullable columns are optional (have `?`)
- [ ] Default values present with `@default(...)`

### Foreign Keys
- [ ] `orders.user` relation to `users`
- [ ] `order_items.order` relation to `orders`
- [ ] `order_items.product` relation to `products`
- [ ] Reverse relations present (`users.orders`, `products.order_items`, etc.)

---

## Step 8: Generate Prisma Client

Validate the schema by generating the Prisma Client:

```bash
npx prisma generate
```

**Expected Output**:
```
✔ Generated Prisma Client (vX.X.X) to ./node_modules/@prisma/client in XXms
```

---

## Step 9: Test Basic Query (Optional)

Create a simple test script to verify the client works:

```javascript
// test.js
const { PrismaClient } = require('@prisma/client');

const prisma = new PrismaClient();

async function main() {
  // Count users
  const userCount = await prisma.users.count();
  console.log(`User count: ${userCount}`);

  // List tables (via raw query)
  const tables = await prisma.$queryRaw`
    SELECT relname FROM pg_class WHERE relkind = 'r'
  `;
  console.log('Tables:', tables);
}

main()
  .catch(console.error)
  .finally(() => prisma.$disconnect());
```

```bash
node test.js
```

---

## Troubleshooting

### Error: "relation pg_class does not exist"
**Cause**: Catalog emulation not enabled or not working
**Fix**: Check PGWire catalog module is loaded, verify `iris_executor.py` intercepts catalog queries

### Error: "could not connect to server"
**Cause**: Container not running or port mismatch
**Fix**: Verify `docker ps` shows container, check port 5432 is mapped

### Error: "Unknown type" or "Invalid OID"
**Cause**: Type mapping incomplete
**Fix**: Check `pg_type` catalog returns correct OIDs for IRIS types

### Error: "relation does not exist" for user tables
**Cause**: Schema mapping not working (public → SQLUser)
**Fix**: Verify schema mapper translates `public` to `SQLUser` in catalog queries

### Prisma shows empty schema
**Cause**: No tables in mapped schema, or query returns empty
**Fix**: Verify tables exist in SQLUser schema, check catalog query results

---

## Performance Baseline

Record these metrics for regression testing:

| Metric | Target | Actual |
|--------|--------|--------|
| `prisma db pull` time | <30s | ___s |
| Tables discovered | 4 | ___ |
| Relationships discovered | 4 | ___ |
| Errors | 0 | ___ |

---

## Cleanup

```bash
# Remove test project
rm -rf /tmp/prisma-iris-test

# Remove test tables from IRIS (optional)
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS users;
"
```

---

## Next Steps

After successful validation:
1. Document any deviations from expected schema
2. File issues for missing features
3. Run with larger test datasets (50+ tables)
4. Test with real application schemas
