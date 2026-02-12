# Quickstart: Drizzle ORM DDL Translation

## Overview

This guide shows how to use the Drizzle ORM DDL translation feature in iris-pgwire to run Drizzle-generated PostgreSQL migrations against InterSystems IRIS without manual SQL rewriting.

**What This Enables:**
- ✅ Auto-translate Drizzle migrations (CREATE TABLE, ALTER TABLE, CREATE INDEX)
- ✅ Handle IRIS reserved words automatically (quote `level`, `key`, `trigger`, etc.)
- ✅ Map PostgreSQL types to IRIS equivalents (`text`→`VARCHAR(*)`, `jsonb`→`JSON`, `uuid`→`UUID`)
- ✅ Ensure atomic migrations (all-or-nothing transaction semantics)
- ✅ Prevent concurrent migration conflicts (database-level locking)

---

## Prerequisites

1. **IRIS Database**: InterSystems IRIS instance running with pgwire enabled
2. **Python 3.11+**: With `iris-pgwire` installed
3. **Drizzle Migrations**: Generated via `drizzle-kit generate` from your schema

```bash
# Install iris-pgwire with DDL translation support (after feature implementation)
pip install iris-pgwire>=1.4.0
```

---

## Quick Example

### 1. Your Drizzle Schema (TypeScript)

```typescript
// packages/db/schema.ts
import { pgTable, text, integer, uuid, timestamp } from 'drizzle-orm/pg-core';

export const workflow = pgTable('workflow', {
  id: uuid('id').primaryKey().defaultRandom(),
  name: text('name').notNull(),
  level: integer('level').notNull(),  // "level" is IRIS reserved word
  userId: text('user_id').notNull(),
  createdAt: timestamp('created_at', { withTimezone: true }).defaultNow(),
});
```

### 2. Generate Drizzle Migration

```bash
# In your project root
npx drizzle-kit generate
```

This creates `drizzle/migrations/0001_create_workflow.sql`:

```sql
CREATE TABLE "workflow" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "name" text NOT NULL,
  "level" integer NOT NULL,
  "user_id" text NOT NULL,
  "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX "workflow_user_id_idx" ON "workflow" ("user_id");
```

### 3. Run Migration Against IRIS (Python)

```python
import psycopg
from iris_pgwire.migrations import MigrationExecutor

# Connect via pgwire
conn = psycopg.connect("postgresql://USER:SYS@localhost:55433/USER")

# Create migration executor
executor = MigrationExecutor(
    connection=conn,
    on_progress=lambda msg, current, total: print(f"[{current}/{total}] {msg}")
)

# Ensure journal table exists
executor.create_journal_table()

# Run all pending migrations
results = executor.execute_migrations("./drizzle/migrations")

# Check results
for result in results:
    if result.status == "success":
        print(f"✓ {result.filename} ({result.execution_time_ms}ms)")
    else:
        print(f"✗ {result.filename}: {result.errors}")
```

**What Happens Behind the Scenes:**
1. Executor acquires exclusive lock on `__drizzle_migrations` table
2. Checks if migration already applied (hash lookup in journal)
3. Starts transaction
4. Translates PostgreSQL DDL to IRIS SQL:
   - `text` → `VARCHAR(*)`
   - `uuid` → `UUID`
   - `timestamp with time zone` → `TIMESTAMP`
   - `"level"` → automatically quoted (IRIS reserved word)
5. Executes all statements in migration file
6. On success: COMMIT, update journal, release lock
7. On failure: ROLLBACK, do NOT update journal, release lock

---

## Advanced Usage

### Custom Type Mappings

```python
from iris_pgwire.sql_translator import DDLTranslator

# Override default type mappings
translator = DDLTranslator(
    type_mapping={
        "text": "CLOB",  # Use CLOB instead of VARCHAR(*)
        "jsonb": "%DynamicObject",  # Use native IRIS JSON
    },
    strict_mode=True
)

executor = MigrationExecutor(
    connection=conn,
    translator=translator
)
```

### Dry-Run Mode (Translate Without Executing)

```python
from iris_pgwire.sql_translator import DDLTranslator

translator = DDLTranslator(strict_mode=True)

# Translate migration file
statements = translator.translate_migration_file("drizzle/migrations/0001_init.sql")

for stmt in statements:
    print("Original SQL:")
    print(stmt.raw_sql)
    print("\nTranslated IRIS SQL:")
    print(stmt.translated_sql)
    print("\nWarnings:", stmt.translation_warnings)
    print("-" * 80)
```

### CLI Usage

```bash
# Execute migrations
python -m iris_pgwire.migrations \
  --host localhost \
  --port 55433 \
  --user USER \
  --password SYS \
  --migrations-dir ./drizzle/migrations

# Dry-run (translate but don't execute)
python -m iris_pgwire.migrations \
  --dry-run \
  --migrations-dir ./drizzle/migrations \
  --output translated-migrations/

# Check migration status
python -m iris_pgwire.migrations \
  --status \
  --host localhost \
  --port 55433 \
  --user USER \
  --password SYS
```

**JSON Output** (for scripting):
```bash
python -m iris_pgwire.migrations --status --json
```

```json
{
  "status": "success",
  "migrations_applied": 3,
  "migrations_pending": 1,
  "applied": [
    {"filename": "0001_init.sql", "applied_at": "2026-02-09T10:30:00Z"},
    {"filename": "0002_add_users.sql", "applied_at": "2026-02-09T10:31:15Z"}
  ],
  "pending": [
    {"filename": "0003_add_projects.sql", "checksum": "abc123..."}
  ]
}
```

---

## Configuration Options

### DDLTranslationConfig

```python
from iris_pgwire.config import DDLTranslationConfig
from iris_pgwire.migrations import MigrationExecutor

config = DDLTranslationConfig(
    strict_mode=True,              # Error on unsupported features
    auto_quote_reserved_words=True,  # Automatically quote IRIS reserved words
    validate_precision=True,        # Validate numeric precision against IRIS limits
    lock_timeout_seconds=30,       # Max time to wait for migration lock
    fail_fast=True,                # Stop on first error
    log_warnings=True,             # Log precision loss warnings
)

executor = MigrationExecutor(connection=conn, config=config)
```

---

## Common Scenarios

### Scenario 1: IRIS Reserved Words

**Drizzle Schema:**
```typescript
export const task = pgTable('task', {
  id: uuid('id').primaryKey(),
  level: integer('level').notNull(),  // IRIS reserved word
  key: text('key').notNull(),          // IRIS reserved word
  trigger: text('trigger'),            // IRIS reserved word
});
```

**Automatic Translation:**
```sql
-- Generated Drizzle SQL
CREATE TABLE "task" (
  "id" uuid PRIMARY KEY,
  "level" integer NOT NULL,
  "key" text NOT NULL,
  "trigger" text
);

-- IRIS Translation (automatic quoting)
CREATE TABLE "task" (
  "id" UUID PRIMARY KEY,
  "level" INTEGER NOT NULL,  -- Quoted preserved
  "key" VARCHAR(*) NOT NULL,  -- Quoted preserved
  "trigger" VARCHAR(*)         -- Quoted preserved
);
```

### Scenario 2: Type Precision Validation

**Drizzle Schema:**
```typescript
export const product = pgTable('product', {
  id: uuid('id').primaryKey(),
  price: numeric('price', { precision: 10, scale: 2 }),  // ✓ Within IRIS limits
  bigValue: numeric('big_value', { precision: 100, scale: 50 }),  // ✗ Exceeds IRIS limit
});
```

**Result:**
```python
# price: numeric(10, 2) → NUMERIC(10, 2) ✓
# big_value: numeric(100, 50) → ERROR
DDLTranslationError(
    error_code="TYPE_PRECISION_EXCEEDED",
    message="NUMERIC precision 100 exceeds IRIS limit of 38 digits",
    suggested_fix="Use NUMERIC(38, 19) or alternative data type"
)
```

### Scenario 3: Unsupported Index Features

**Drizzle Schema (with manual raw SQL):**
```typescript
// Don't do this - partial indexes not supported in IRIS
await db.execute(sql`
  CREATE INDEX active_users_idx ON users (email) WHERE active = true;
`);
```

**Result:**
```python
DDLTranslationError(
    error_code="UNSUPPORTED_INDEX_FEATURE",
    message="Partial indexes with WHERE clause not supported in IRIS",
    suggested_fix="Create full index or filter in application queries"
)
```

**Recommended Fix:**
```typescript
// Use full index instead
export const users = pgTable('users', {
  email: text('email').notNull(),
  active: boolean('active').notNull(),
}, (table) => ({
  emailIdx: index('users_email_idx').on(table.email),  // Full index (supported)
}));

// Filter in application code
const activeUsers = await db.select()
  .from(users)
  .where(eq(users.active, true));
```

IRIS only supports plain column lists for indexes. PostgreSQL-specific clauses such as `WHERE` filters, `INCLUDE` columns, or expression-based indexes (e.g., `LOWER(email)`) are rejected with `UNSUPPORTED_INDEX_FEATURE`. Remove those clauses or create separate indexes on the base columns instead.

### Scenario 4: Concurrent Migrations

**Problem:** Two application instances start simultaneously and attempt migrations.

**Solution:** Database-level advisory locking ensures only one proceeds.

```python
# Instance 1
executor1 = MigrationExecutor(connection=conn1)
result1 = executor1.execute_migration("0001_init.sql")  # Acquires lock

# Instance 2 (simultaneous)
executor2 = MigrationExecutor(connection=conn2, lock_timeout_seconds=10)
result2 = executor2.execute_migration("0001_init.sql")  # Waits for lock

# Outcome:
# - Instance 1: Executes migration, updates journal, releases lock
# - Instance 2: Acquires lock, checks journal, sees migration already applied, skips
```

---

## Integration with Docker Compose

### Update docker-compose.yml

```yaml
services:
  migrations:
    image: node:20-alpine
    working_dir: /app
    volumes:
      - ./:/app
    command: |
      sh -c "
        # Install dependencies
        npm install

        # Run Python migrations (replaces Drizzle's native migrate)
        pip install iris-pgwire>=1.4.0
        python -m iris_pgwire.migrations \
          --host iris \
          --port 55433 \
          --user USER \
          --password SYS \
          --migrations-dir ./drizzle/migrations
      "
    depends_on:
      iris:
        condition: service_healthy
```

**Benefits:**
- ✅ No more manual `reconstruct-iris-tables.ts` script
- ✅ Schema stays in sync with Drizzle automatically
- ✅ Standard Drizzle workflow (`drizzle-kit generate` → migrations run automatically)

---

## Troubleshooting

### Issue: "Type precision exceeded" Error

**Symptom:**
```
DDLTranslationError: NUMERIC precision 100 exceeds IRIS limit of 38 digits
```

**Fix:** Adjust Drizzle schema to use IRIS-compatible precision:
```typescript
// Before
price: numeric('price', { precision: 100, scale: 50 }),

// After
price: numeric('price', { precision: 38, scale: 19 }),  // IRIS max
```

### Issue: "Unsupported index feature" Error

**Symptom:**
```
DDLTranslationError: Partial indexes with WHERE clause not supported in IRIS
```

**Fix:** Remove PostgreSQL-specific index features:
```sql
-- Before (Drizzle raw SQL)
CREATE INDEX active_users_idx ON users (email) WHERE active = true;

-- After (standard index)
CREATE INDEX users_email_idx ON users (email);
```

### Issue: "Unsupported index feature" Error for INCLUDE columns

**Symptom:**
```
DDLTranslationError: IRIS does not support INCLUDE columns
```

**Fix:** Create a separate index on the included column or omit the `INCLUDE` clause entirely.

### Issue: "Unsupported index feature" Error for expression indexes

**Symptom:**
```
DDLTranslationError: IRIS does not support expression indexes
```

**Fix:** Create an index on the base column directly or materialize the expression into a computed column before indexing.

### Issue: Migration Hangs (Lock Timeout)

**Symptom:** Migration waits indefinitely for lock.

**Diagnosis:**
```python
# Check for stale locks
executor.get_applied_migrations()  # If this hangs, lock is held
```

**Fix:**
```sql
-- Manually release lock (IRIS SQL)
LOCK TABLE "__drizzle_migrations" IN EXCLUSIVE MODE NOWAIT;
-- If error "table locked", find and terminate blocking session
```

### Issue: Reserved Word Conflicts

**Symptom:**
```
SQL Error: "level" is a reserved word
```

**Fix:** Ensure `auto_quote_reserved_words=True` (default):
```python
translator = DDLTranslator(auto_quote_reserved_words=True)
```

---

## Performance Tips

1. **Batch Migrations**: Run all pending migrations in one session (executor handles locking)
2. **Connection Pooling**: Reuse connection for multiple migration operations
3. **Dry-Run First**: Test translation locally before production:
   ```bash
   python -m iris_pgwire.migrations --dry-run --migrations-dir ./drizzle/migrations
   ```

---

## Testing Your Migrations

### Unit Test Pattern

```python
import pytest
from iris_pgwire.sql_translator import DDLTranslator

def test_workflow_table_translation():
    """Test that workflow table DDL translates correctly."""
    translator = DDLTranslator(strict_mode=True)
    
    sql = '''
        CREATE TABLE "workflow" (
            "id" uuid PRIMARY KEY,
            "level" integer NOT NULL
        );
    '''
    
    statement = translator.translate_statement(sql)
    
    # Verify translation
    assert '"level"' in statement.translated_sql  # Reserved word quoted
    assert 'UUID' in statement.translated_sql      # Type translated
    assert 'INTEGER' in statement.translated_sql   # Type translated
    assert len(statement.translation_warnings) == 0  # No warnings
```

### Integration Test Pattern

```python
def test_migration_execution(iris_connection, tmp_path):
    """Test end-to-end migration execution."""
    from iris_pgwire.migrations import MigrationExecutor
    
    # Create migration file
    migration = tmp_path / "0001_test.sql"
    migration.write_text('''
        CREATE TABLE "test_table" (
            "id" uuid PRIMARY KEY,
            "name" text NOT NULL
        );
    ''')
    
    executor = MigrationExecutor(connection=iris_connection)
    executor.create_journal_table()
    
    # Execute migration
    result = executor.execute_migration(str(migration))
    
    # Verify
    assert result.status == "success"
    assert result.statements_executed == 1
    
    # Verify table created
    cursor = iris_connection.cursor()
    cursor.execute('SELECT COUNT(*) FROM "test_table"')
    assert cursor.fetchone()[0] == 0  # Table exists, empty
```

---

## Next Steps

1. **Read the Spec**: See [spec.md](./spec.md) for full feature details
2. **Review Data Model**: See [data-model.md](./data-model.md) for entity definitions
3. **Check API Contracts**: See [contracts/api-contracts.md](./contracts/api-contracts.md) for detailed API
4. **Run Tests**: See [tests/integration/test_drizzle_migration.py](../../tests/integration/test_drizzle_migration.py)

---

## FAQ

**Q: Does this replace Drizzle's native migration runner?**  
A: Yes, for IRIS targets. You still use `drizzle-kit generate` to create migrations, but run them via `iris-pgwire.migrations` instead of `drizzle-kit migrate`.

**Q: What if I have existing Drizzle migrations already applied?**  
A: The migration executor checks the `__drizzle_migrations` journal table and skips already-applied migrations based on hash matching.

**Q: Can I use this with TypeORM, Prisma, or other ORMs?**  
A: Not directly. This feature is specific to Drizzle's migration file format. However, the DDL translation logic could be adapted for other tools.

**Q: What happens if a migration partially succeeds?**  
A: The entire migration file executes in a single transaction. If any statement fails, the entire migration rolls back (all-or-nothing).

**Q: How do I handle schema changes in development vs production?**  
A: Use standard Drizzle workflow:
```bash
# Development: Generate migration
npx drizzle-kit generate

# Review generated SQL in drizzle/migrations/

# Production: Run migration via iris-pgwire
python -m iris_pgwire.migrations --migrations-dir ./drizzle/migrations
```

---

## Support

- **Issues**: [iris-pgwire GitHub Issues](https://github.com/caretdev/iris-pgwire/issues)
- **Docs**: [IRIS SQL Reference](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL)
- **Community**: [InterSystems Developer Community](https://community.intersystems.com/)
