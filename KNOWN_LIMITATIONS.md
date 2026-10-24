# Known Limitations - IRIS PGWire

This document catalogs known limitations, workarounds, and behavior differences when using IRIS through the PostgreSQL wire protocol.

**Industry Context**: IRIS PGWire follows proven architectural patterns from the PostgreSQL wire protocol ecosystem. Many design decisions (e.g., delegating SSL/TLS to reverse proxy, omitting GSSAPI) match industry leaders like PgBouncer (most deployed connection pooler), YugabyteDB (distributed SQL), and Google Cloud PGAdapter.

**Security Note** _(corrected 2026-10-24)_: Clients authenticate with their IRIS username and password, which the server checks by logging in to IRIS. The password is sent in the clear, so TLS is required unless the operator opts out (`--allow-plaintext-password`, or `--trust` to disable authentication). Earlier versions of this document described OAuth 2.0, IRIS Wallet and SCRAM-SHA-256 as available and the password as never sent in plain text. None of that was true: no version authenticated by any of those methods, and until 2026-10-24 no version authenticated at all. See [Authentication](README.md#authentication). Authentication does not change who a session runs as: every authenticated user has the privileges of the service account, so by default only the service account may log in (`PGWIRE_ALLOWED_USERS` lists others).

**These limitations are pinned by tests.** The divergences that cannot be fixed at the wire layer are asserted rather than only described, so a change in one cannot go unnoticed and leave this document quietly wrong:

```bash
pytest -m pinned_limitation \
  tests/protocol/test_isolation_e2e.py \
  tests/integration/test_in_iris_shared_transaction.py
```

The two files are named rather than the directories because `tests/integration` also holds modules that fail to collect where the optional `sqlalchemy-iris` psycopg dialect is absent, which would stop the run before any pin is reached. A new pin belongs in one of these files, or in this command.

A failure there means the behaviour changed and the corresponding section below needs rewriting — the tests pin these outcomes, they do not endorse them. Run it in its own pytest process: appended to a run of `tests/unit`, the pins that need two independent sessions fail for a reason that has nothing to do with isolation, which `tests/protocol/test_isolation_e2e.py` describes.

---

## ✅ Resolved Limitations (v1.3.0)

The 1.3.0 release (IRIS 2024.2+ compatibility) addresses several previously documented limitations. These items have therefore been removed from this list:

- **Global boolean literals**: PostgreSQL `true`/`false` literals now map to IRIS-compatible values across the entire SQL pipeline.
- **RETURNING emulation**: Multi-column `RETURNING`, `RETURNING *`, and `ON CONFLICT` paths are now emulated with supplemental metadata lookups and session-local logic.
- **DEFAULT keyword handling**: Translator logic now consults IRIS metadata to resolve `DEFAULT` references so INSERT/UPDATE statements stay intact.

---

## 🌐 Industry Comparison: PostgreSQL Wire Protocol Implementations

Based on comprehensive research of 9 major implementations (November 2025):

| Feature             | IRIS PGWire | PgBouncer | YugabyteDB | PGAdapter | QuestDB | CockroachDB | Materialize | ClickHouse | Pattern             |
| ------------------- | ----------- | --------- | ---------- | --------- | ------- | ----------- | ----------- | ---------- | ------------------- |
| **Wire Protocol**   | ✅ v3.0     | ✅ v3.0   | ✅ v3.0    | ✅ v3.0   | ✅ v3.0 | ✅ v3.0     | ✅ v3.0     | ✅ v3.0    | Universal           |
| **SSL/TLS Native**  | ✅ Yes      | ✅ Yes    | ✅ Yes     | ✅ Yes    | ❌ No   | ✅ Yes      | ✅ Yes      | ✅ Yes     | Mixed (7/8 native)  |
| **SCRAM-SHA-256**   | ❌ No       | ✅ Yes    | ✅ Yes     | ✅ Yes    | ❌ No   | ✅ Yes      | —           | ❌ No      | Standard (4/8)      |
| **OAuth/IAM**       | ❌ No       | ❌ No     | ❌ No      | ✅ Yes    | ❌ No   | ❌ No       | ❌ No       | ❌ No      | Rare (1/8)          |
| **Kerberos/GSSAPI** | ❌ No       | ❌ No     | ❌ No      | ❌ No     | ❌ No   | ✅ Yes      | ❌ No       | ❌ No      | **Very Rare (1/8)** |
| **Connection Pool** | ✅ Yes      | ✅ Yes    | ✅ Yes     | ✅ Yes    | ❌ No   | ✅ Yes      | ✅ Yes      | —          | Common (6/8)        |
| **Binary Format**   | ✅ Yes      | ✅ Yes    | ✅ Yes     | ✅ Yes    | ✅ Yes  | ✅ Yes      | ✅ Yes      | ✅ Yes     | Universal           |

**Key Insights**:

1. **GSSAPI Adoption**: Only 1 of 8 implementations (12.5%) - CockroachDB enterprise feature. Even PostgreSQL core has limited adoption in wire protocol adapters.

2. **SSL/TLS Patterns**:
   - **Native**: Most implementations (6 of 8)
   - **Proxy**: IRIS PGWire (reverse proxy pattern)
   - **None**: QuestDB explicitly omits SSL
   - **Network-layer**: Emerging pattern (Tailscale pgproxy)

3. **Authentication Trends**:
   - **SCRAM-SHA-256**: Standard (4 of 8 implementations; not IRIS PGWire)
   - **OAuth/IAM**: Cloud-native pattern (1 of 8 - PGAdapter; not IRIS PGWire)
   - **MD5**: Being deprecated across ecosystem (YugabyteDB migration guide)

4. **IRIS PGWire Position**: Native TLS and a cleartext-password exchange verified against IRIS. It does not offer SCRAM-SHA-256 or OAuth, which most of the others do.

**Technical Reason for GSSAPI Rarity** (from industry research):

> "GSSAPI is an inherently stateful, interactive protocol involving challenge-response exchanges and ticket validation against a centralized Key Distribution Center (KDC). This makes it difficult to implement in connection pooling contexts and cloud-native architectures where authentication delegation is preferred."

**References**:

- Perplexity industry research: PostgreSQL wire protocol ecosystem survey (November 2025)
- CockroachDB, YugabyteDB, PGAdapter, PgBouncer, QuestDB, Materialize, ClickHouse, CrateDB official documentation
- PostgreSQL wire protocol compatibility analysis

---

## 🟢 PostgreSQL DDL Compatibility

**Status**: Enhanced Compatibility ✅
**Feature**: Automated transformations for PostgreSQL-specific DDL

### Capabilities

IRIS PGWire automatically handles several common PostgreSQL DDL constructs that are natively unsupported by IRIS:

- ✅ **Generated Columns**: `GENERATED ALWAYS AS ... STORED` are automatically stripped.
- ✅ **Enum Types**: `CREATE TYPE ... ENUM` are registered and columns mapped to `VARCHAR(64)`.
- ✅ **Storage Parameters**: `WITH (fillfactor = ...)` and `SET (fillfactor)` are stripped/skipped.
- ✅ **Index Methods**: `USING btree` is automatically removed.
- ✅ **Casts**: `'value'::text` syntax in defaults is stripped.
- ✅ **CHECK Constraints**: `ADD CONSTRAINT ... CHECK` are skipped with a warning.

### Configuration

Use the `strict_ddl` flag to control this behavior:

- `strict_ddl = false` (default): Skip/transform with a warning.
- `strict_ddl = true`: Raise an error for unsupported DDL.

---

## 🟡 INFORMATION_SCHEMA Compatibility

**Severity**: Medium
**Affects**: Schema introspection queries

### Issue Description

IRIS uses `INFORMATION_SCHEMA` tables (SQL standard) rather than PostgreSQL's `pg_catalog` system tables. Some PostgreSQL tools expect `pg_catalog`.

### Workaround

PGWire translates common `pg_catalog` queries to `INFORMATION_SCHEMA` equivalents. For unsupported queries, use IRIS native metadata:

```sql
-- PostgreSQL style (may not work)
SELECT * FROM pg_catalog.pg_tables;

-- IRIS equivalent (works)
SELECT * FROM INFORMATION_SCHEMA.TABLES;
```

### Tool Compatibility

- ✅ **Superset**: Works (SQLAlchemy handles INFORMATION_SCHEMA)
- ✅ **DBeaver**: Works (detects INFORMATION_SCHEMA support)
- ⚠️ **pgAdmin**: Partial (some features require pg_catalog)
- ⚠️ **Metabase**: Partial (similar to pgAdmin)

---

## 🟡 Parameterized LIMIT/OFFSET Returns Empty Column Metadata

**Severity**: Medium
**Affects**: PostgreSQL clients that bind LIMIT/OFFSET parameters

### Issue Description

When using parameterized `LIMIT`/`OFFSET` (e.g., `LIMIT $1`) via certain clients (reported with postgres.js), the server returns empty column metadata. The row count is correct, but row objects are empty because `columns` is `[]`.

### Reproduction

```sql
-- Works: literal LIMIT
SELECT "id", "name" FROM "workflow_folder" LIMIT 1;

-- Fails: parameterized LIMIT
SELECT "id", "name" FROM "workflow_folder" LIMIT $1;
```

### Impact

- Drizzle ORM parameterizes `.limit()` by default, breaking result mapping
- Affects clients that rely on column metadata to build row objects

### Workaround

Inline `LIMIT`/`OFFSET` values instead of parameterizing them, or use raw queries with literal limits.

**Reference**: See [LIMIT Parameter Bug Report](docs/LIMIT_PARAMETER_BUG.md) for details.

---

## 🟡 HNSW Index Performance Requirements

**Severity**: Medium
**Affects**: Vector similarity search performance

### Issue Description

HNSW vector indexes provide significant performance benefits only at scale:

| Dataset Size          | HNSW Performance         | Recommendation                |
| --------------------- | ------------------------ | ----------------------------- |
| < 10,000 vectors      | 0.98-1.02× (negligible)  | Use sequential scan           |
| 10,000-99,999 vectors | 1.0-2.0× improvement     | Consider HNSW with testing    |
| ≥ 100,000 vectors     | **5.14× improvement** ✅ | **HNSW strongly recommended** |

### Recommendation

Only create HNSW indexes for datasets with 100K+ vectors:

```sql
-- Only beneficial at scale (≥100K vectors)
CREATE INDEX idx_vec ON vectors(vec) AS HNSW(Distance='Cosine');

-- Always specify Distance parameter (required)
CREATE INDEX idx_vec ON vectors(vec) AS HNSW(Distance='DotProduct');
```

**Reference**: See [HNSW Investigation](docs/HNSW_FINDINGS_2025_10_02.md) for detailed benchmarks.

---

## 🟡 pgvector Operator Support

**Severity**: Medium
**Affects**: pgvector compatibility

### Supported Operators

| pgvector Operator             | IRIS Translation       | Status             |
| ----------------------------- | ---------------------- | ------------------ |
| `<=>` (cosine distance)       | `VECTOR_COSINE()`      | ✅ **Supported**   |
| `<#>` (inner/dot product)     | `VECTOR_DOT_PRODUCT()` | ✅ **Supported**   |
| `<->` (L2/Euclidean distance) | —                      | ❌ Not implemented |

### Example

```sql
-- ✅ Works: Cosine distance
SELECT * FROM vectors ORDER BY embedding <=> %s LIMIT 5;

-- ✅ Works: Dot product (for MIPS - Maximum Inner Product Search)
SELECT * FROM vectors ORDER BY embedding <#> %s LIMIT 5;

-- ❌ Fails: L2 distance (not available in IRIS)
SELECT * FROM vectors ORDER BY embedding <-> %s LIMIT 5;
```

### Workaround

Use cosine distance (`<=>`) or dot product (`<#>`) instead of L2 distance. For normalized embeddings (OpenAI, Cohere, sentence-transformers), cosine similarity is recommended.

---

## 🟡 SQLAlchemy psycopg2 Dialect Compatibility

**Severity**: Medium
**Affects**: SQLAlchemy applications using psycopg2

### Issue Description

SQLAlchemy's psycopg2 dialect queries PostgreSQL system catalogs (`pg_type`) during connection setup to get HSTORE type OIDs. IRIS doesn't have these PostgreSQL-specific system tables.

### Error

```text
IndexError: tuple index out of range
  in psycopg2/extras.py HstoreAdapter.get_oids()
```

### Affected Libraries and Tools

| Tool/Library                 | PGWire Status | IRIS-Native Alternative                                           |
| ---------------------------- | ------------- | ----------------------------------------------------------------- |
| **LangChain PGVector**       | ❌ Fails      | [`langchain-iris`](https://github.com/caretdev/langchain-iris) ✅ |
| **LlamaIndex PGVectorStore** | ❌ Fails      | [`llama-iris`](https://github.com/caretdev/llama-iris) ✅         |
| **Haystack PGVector**        | ❌ Fails      | Custom retriever with psycopg3                                    |
| **SQLAlchemy + psycopg2**    | ❌ Fails      | psycopg3 directly                                                 |
| **Django ORM (psycopg2)**    | ❌ Fails      | psycopg3 directly                                                 |
| **psycopg3 (psycopg)**       | ✅ Works      | —                                                                 |
| **asyncpg**                  | ✅ Works      | —                                                                 |
| **node-postgres (pg)**       | ✅ Works      | —                                                                 |
| **JDBC PostgreSQL**          | ✅ Works      | —                                                                 |

### Recommended: IRIS-Native Packages

For LangChain and LlamaIndex applications, use the IRIS-native packages which connect directly to IRIS (not via PGWire):

```bash
pip install langchain-iris llama-iris
```

**LangChain with IRIS:**

```python
from langchain_iris import IRISVector

db = IRISVector(
    embedding_function=embeddings,
    connection_string="iris://_SYSTEM:SYS@localhost:1972/USER",
    collection_name="my_docs"
)
db.add_texts(["Document 1", "Document 2"])
results = db.similarity_search("query", k=5)
```

**LlamaIndex with IRIS:**

```python
from llama_iris import IRISVectorStore

vector_store = IRISVectorStore.from_params(
    connection_string="iris://_SYSTEM:SYS@localhost:1972/USER",
    table_name="my_vectors",
    embed_dim=384
)
```

### Alternative: psycopg3 via PGWire

For direct PGWire access without ORM:

```python
import psycopg

with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM docs ORDER BY embedding <=> %s LIMIT 5", (query_vec,))
        results = cur.fetchall()
```

---

## 🔴 Transaction Isolation: No MVCC, No Snapshots

**Severity**: High
**Affects**: Every client and ORM that relies on PostgreSQL isolation semantics

This is the largest behavioral difference between IRIS through PGWire and PostgreSQL, and it cannot be fixed at the wire protocol layer. PostgreSQL gives every transaction a snapshot of committed data; IRIS has no MVCC and therefore has no snapshot to give. A query either waits for a lock or reads what is currently in the database, including another transaction's uncommitted writes.

All behavior below was measured against IRIS 2026.2 through PGWire, not inferred.

### Which Levels Exist

| Requested level    | Result                                                           |
| ------------------ | ---------------------------------------------------------------- |
| `READ UNCOMMITTED` | Applied. This is the default — IRIS's default, not PostgreSQL's. |
| `READ COMMITTED`   | Applied, with the documented exceptions below.                   |
| `REPEATABLE READ`  | **Rejected** with `0A000 feature_not_supported`.                 |
| `SERIALIZABLE`     | **Rejected** with `0A000 feature_not_supported`.                 |

`SET TRANSACTION ISOLATION LEVEL`, `SET SESSION CHARACTERISTICS AS TRANSACTION ISOLATION LEVEL`, and the `SET transaction_isolation = '...'` GUC spelling that psycopg and SQLAlchemy send are all forwarded to IRIS. `SHOW transaction_isolation` and `SHOW TRANSACTION ISOLATION LEVEL` report the level IRIS actually accepted for that session — a level is never reported unless it was applied.

The two stronger levels are refused rather than silently downgraded. They are guarantees about what a transaction will not observe, and IRIS has no snapshot mechanism to downgrade them _to_; an error at `SET` is recoverable, silently violated guarantees are not. This follows the same principle as the rejection of L2 vector distance.

### What READ COMMITTED Does Not Cover

`READ COMMITTED` on IRIS is narrower than PostgreSQL's. These are documented exceptions in the InterSystems SQL reference for `SET TRANSACTION`, not defects — but a PostgreSQL client has no way to anticipate them.

Measured with one committed row `(id 1, n 100)` and a second transaction holding an uncommitted `UPDATE` of `n` to `999` plus an uncommitted `INSERT` of `(id 2, n 7)`. A reader at `READ COMMITTED`:

| Query                                  | Committed answer | Actual answer     |
| -------------------------------------- | ---------------- | ----------------- |
| `SELECT n FROM t WHERE id = 1`         | `100`            | **fails**, `-114` |
| `SELECT COUNT(*) FROM t`               | `1`              | `2` — dirty       |
| `SELECT SUM(n) FROM t`                 | `100`            | `999` — dirty     |
| `SELECT n, COUNT(*) FROM t GROUP BY n` | `100`            | `999` — dirty     |
| `SELECT DISTINCT n FROM t`             | `100`            | `999` — dirty     |
| `SELECT %NOLOCK n FROM t WHERE id = 1` | `100`            | `999` — dirty     |

Only the plain row query honored the level, and it did so by _failing_ rather than by returning the last committed value: it waited for the lock and then raised a lock timeout. There is no committed version to fall back on. Aggregates, `GROUP BY` and `DISTINCT` are explicitly documented as unaffected by the isolation level.

A row deleted by an in-progress transaction is never returned, at any level — `READ COMMITTED` keeps inserts and updates consistent, but not deletes.

Note also that `READ VERIFIED` is **not** stronger than `READ COMMITTED` despite the name. It re-checks query _conditions_, not commit state; the same plain row query that raised `-114` at `READ COMMITTED` returned the uncommitted `999` immediately at `READ VERIFIED`.

### ⚠️ An Accepted `READ COMMITTED` Is Not a Guarantee

`SET TRANSACTION ISOLATION LEVEL READ COMMITTED` returning success, and `SHOW transaction_isolation` then reporting `read committed`, do not mean the level is in force for the next read.

Measured against IRIS 2026.1 CE with a writer holding one row uncommitted, a reader whose `SET` was accepted with SQLCODE 0 does one of two things:

| Outcome                                          | Timing         |
| ------------------------------------------------ | -------------- |
| Lock timeout, SQLCODE `-114` → `40001`           | a flat **10s** |
| Returns the writer's uncommitted value, no error | immediate      |

Both shapes were reproduced repeatedly. The trigger for the second was **not** isolated: not the statement text, not how many readers had run before, not whether the `SET` preceded or followed the first read, and not whether a transaction was explicitly open. Six successive fresh connections against a fresh table were deterministic (all ten-second timeouts), while other sequences returned the uncommitted value with no wait at all.

Practical consequences:

- Do not treat an accepted level as a guarantee. Correctness must not depend on `READ COMMITTED` having applied; where it matters, lock explicitly (`SELECT ... FOR UPDATE`) and keep the transaction short.
- Budget more than 10 seconds for any statement that may meet a contended row. A test or health check with a 5-second timeout reports a hang where the database was waiting out its normal lock timeout.

### Sessions Share One Transaction in the In-IRIS Deployment

**This applies to the embedded backend (`BACKEND_TYPE=embedded`), not to DBAPI.** Deployed inside IRIS, every wire session is served by a thread of the same IRIS process, and an IRIS transaction belongs to the process rather than the thread. The isolation a PostgreSQL client assumes between connections therefore does not exist.

Measured inside the container with two threads of one embedded process:

```text
session A: START TRANSACTION; INSERT (id 1)
session B: SELECT COUNT(*)              ->  1     (sees A's uncommitted row)
session B: COMMIT                       ->  A's row is now committed
session A: ROLLBACK                     ->  no effect
afterwards SELECT COUNT(*)              ->  1     (PostgreSQL would say 0)
```

One client's `COMMIT` commits another client's work, and the other client's `ROLLBACK` then has nothing to undo.

What is wrong here is the transaction's **scope**, not the backend's ability to express a transaction. Measured on the same path, single-threaded:

```text
START TRANSACTION; INSERT; ROLLBACK  ->  SELECT COUNT(*)  ->  0   (PostgreSQL: 0)
START TRANSACTION; INSERT; COMMIT    ->  SELECT COUNT(*)  ->  1   (PostgreSQL: 1)
```

So an application driving the embedded backend from one thread gets the transaction semantics it asked for; only concurrency breaks them. Read this section as "the embedded backend cannot do transactions" and you go looking for a missing implementation instead of a process-scoped one.

Any deployment serving more than one concurrent client transaction should use the DBAPI backend, where each session holds its own IRIS connection; the embedded backend is appropriate for single-client or read-mostly use.

### Lock Conflicts Are Reported as Retryable

Because there is no snapshot, a lock timeout is how _all_ conflicts surface. PGWire maps both halves to `40001 serialization_failure`, which is the class PostgreSQL retry helpers act on:

| IRIS SQLCODE | Situation                                                     | SQLSTATE |
| ------------ | ------------------------------------------------------------- | -------- |
| `-110`       | A writer meets a row another transaction holds                | `40001`  |
| `-114`       | A reader at `READ COMMITTED` meets a held row (at fetch time) | `40001`  |

Applications should retry `40001` with backoff, as they would on PostgreSQL. The default lock wait is 10 seconds.

### ⚠️ Optimistic Locking Reports False Conflicts

**This is silent and affects every ORM in the compatibility list.** Optimistic locking — SQLAlchemy `version_id_col`, JPA `@Version`, ActiveRecord `lock_version`, Django's equivalent, and hand-written equivalents — issues `UPDATE t SET ver = 2 WHERE id = ? AND ver = 1` and branches on the row count.

Measured through PGWire, with two sessions and a committed row `(id 3, ver 1)`:

```text
Session A: UPDATE t SET ver=2 WHERE id=3 AND ver=1   ->  rowcount 1, NOT committed
Session B: UPDATE t SET ver=2 WHERE id=3 AND ver=1   ->  rowcount 0, in 0.01s, no error
Session B: the same at READ COMMITTED                ->  rowcount 0, in 0.00s, no error
Session A: ROLLBACK
Committed state afterwards:                              ver = 1  (nothing ever committed)
```

Nothing was committed and no error was raised anywhere, yet B was told zero rows matched. Every framework above reads a zero row count as "another transaction changed this row" and raises `StaleDataError` / `OptimisticLockException`, discarding work that was valid. PostgreSQL 16 in the same scenario blocks B until A settles and then reports rowcount 1.

The mechanism: the version predicate matches no row while A holds the new value, so no row is ever taken for update and nothing contends. The guard that exists to detect a conflict is the reason no conflict is detected. An _unguarded_ `UPDATE ... WHERE id = 3` does contend and correctly raises `-110` → `40001`.

**Workarounds**:

- Prefer pessimistic locking: `SELECT ... FOR UPDATE` at `READ COMMITTED` (it does contend there; at the default level it returns the uncommitted value and buys nothing), then update by key alone.
- Or treat a zero row count from a version-guarded update as inconclusive, re-read the row, and distinguish a real version change from a concurrent holder before raising a stale-data error.

### Related PostgreSQL Statements

Measured through PGWire against IRIS 2026.2:

| Statement                           | Result                               |
| ----------------------------------- | ------------------------------------ |
| `SELECT ... FOR UPDATE`             | Works                                |
| `SELECT ... FOR UPDATE NOWAIT`      | Not supported — `42601 syntax_error` |
| `SELECT ... FOR UPDATE SKIP LOCKED` | Not supported — `42601 syntax_error` |
| `INSERT ... ON CONFLICT DO NOTHING` | Emulated by PGWire                   |
| `UPDATE ... RETURNING`              | Emulated by PGWire                   |

Neither lock modifier is translated, so both reach IRIS as trailing tokens it cannot parse. That means the standard PostgreSQL job-queue pattern (`SELECT ... FOR UPDATE SKIP LOCKED` plus `UPDATE ... RETURNING`) has no direct equivalent — use an IRIS-native queue or a single-consumer design.

---

## 🟡 Two-Phase Commit Not Supported

**Severity**: Medium
**Affects**: Distributed transactions

### Issue Description

PostgreSQL's `PREPARE TRANSACTION` / `COMMIT PREPARED` two-phase commit protocol is not supported via PGWire.

### Workaround

Use single-phase transactions:

```sql
BEGIN;
-- Your operations
COMMIT;  -- Use COMMIT instead of PREPARE TRANSACTION
```

### Impact

Most applications don't require two-phase commit. Affected scenarios:

- Distributed database transactions (XA protocol)
- Some Java EE application servers
- Microservices requiring cross-database consistency

---

## 🟡 Bulk Insert Performance

**Severity**: Medium
**Affects**: Large data imports

### Issue Description

Bulk inserts via `COPY FROM STDIN` are currently limited by row-by-row processing. Performance expectations:

| Operation     | Expected Time | Notes                      |
| ------------- | ------------- | -------------------------- |
| Single INSERT | 6-8ms         | Includes protocol overhead |
| 250-row COPY  | 400-600ms     | ~2.4ms per row             |
| 1000-row COPY | 1.6-2.4s      | Row-by-row processing      |

### Workaround (Large Imports)

For imports > 10,000 rows, use native IRIS bulk load:

```bash
# Export to CSV
\copy data TO '/tmp/data.csv' CSV

# Import via IRIS native
docker exec -i iris irissession IRIS << 'EOF'
set $namespace="USER"
do ##class(%SQL.Statement).%ExecDirect(, "LOAD DATA FROM '/tmp/data.csv' INTO TABLE data")
halt
EOF
```

### Future Enhancement

Planned optimization: Use IRIS `executemany()` for batch operations (projected 4× speedup to 2,400+ rows/sec).

---

## 🟡 VECTOR Type Display (DBAPI Backend)

**Severity**: Low
**Affects**: Type introspection

### Issue Description

When using the DBAPI backend (external Python process), VECTOR columns show as VARCHAR in INFORMATION_SCHEMA metadata queries. Vector operations work correctly despite the display issue.

### Workaround

Use the embedded Python backend for accurate type introspection:

```bash
# Embedded backend (inside IRIS)
export BACKEND_TYPE=embedded
irispython -m iris_pgwire.server --allow-plaintext-password   # or TLS; see README "Authentication"
```

### Impact

- ✅ Vector operations (VECTOR_COSINE, TO_VECTOR) work correctly
- ✅ Vector parameter binding works (up to 188,962 dimensions)
- ⚠️ INFORMATION_SCHEMA.COLUMNS shows VARCHAR instead of VECTOR

---

## 🟢 SSL/TLS: native, required for passwords by default _(rewritten 2026-10-24)_

**Severity**: Low
**Affects**: Connection transport encryption

**Industry Context**: Many PostgreSQL wire protocol implementations omit SSL/TLS support (e.g., QuestDB) or delegate to network-layer security (e.g., Tailscale's pgproxy). This is a common architectural decision for protocol adapters.

### Issue Description

PGWire supports TLS natively: set `PGWIRE_SSL_ENABLED=true` with `PGWIRE_SSL_CERT` and `PGWIRE_SSL_KEY`, and answer `S` to a client's `SSLRequest`. This section previously said the server answered `N` and that TLS was delegated to a proxy. The upgrade did in fact hang until it timed out (fixed 2026-10-24: the server slept between answering `S` and upgrading, so the client's ClientHello was consumed as plain data), so a TLS client connected to nothing before then.

Passwords are sent in the clear (PostgreSQL's cleartext password exchange, checked by logging in to IRIS), so the server requires TLS unless the operator passes `--allow-plaintext-password`. Behind a TLS-terminating proxy that flag is the correct setting. SCRAM-SHA-256, OAuth 2.0 and IRIS Wallet credentials are **not** available.

### Workaround

For production deployments requiring transport encryption:

```bash
# Deploy PGWire behind TLS-terminating reverse proxy
# Example: nginx with TLS → PGWire plain-text (localhost only)

# nginx.conf
upstream pgwire {
    server localhost:5432;
}

server {
    listen 5433 ssl;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://pgwire;
    }
}
```

**Client Connection**:

```bash
# Connect via TLS proxy on port 5433
psql "host=your-server port=5433 sslmode=require user=_SYSTEM dbname=USER"
```

### Impact

- ❌ Wire protocol does not encrypt PostgreSQL traffic
- ✅ Passwords require TLS by default (opt-out: `--allow-plaintext-password`)
- ✅ Workaround available (reverse proxy with TLS termination)
- ⚠️ Database traffic visible to network observers without proxy

---

## 🟡 Kerberos/GSSAPI Authentication Not Supported

**Severity**: Low (enterprise-specific)
**Affects**: Organizations with centralized Kerberos infrastructure

**Industry Context**: GSSAPI is rarely implemented in PostgreSQL wire protocol ecosystem. Of 9 major implementations surveyed (PgBouncer, YugabyteDB, PGAdapter, ClickHouse, QuestDB, Materialize, CrateDB, pgwire, CockroachDB), only 2 support GSSAPI (CockroachDB enterprise + PostgreSQL core).

### Issue Description

IRIS PGWire does not implement Kerberos/GSSAPI authentication. This matches the pattern of most PostgreSQL wire protocol implementations.

**Technical Reason** (from industry research):

> "GSSAPI is an inherently stateful, interactive protocol involving challenge-response exchanges and ticket validation against a centralized Key Distribution Center (KDC). This makes it difficult to implement in connection pooling contexts and cloud-native architectures." - PostgreSQL Wire Protocol Ecosystem Analysis (2025)

### Alternative Authentication Methods

> **Corrected 2026-10-24.** The three methods below were documented as available. None was: SCRAM
> never verified the client's proof, nothing read `PGWIRE_ENABLE_SCRAM`, and the OAuth and Wallet
> code was reachable only through that SCRAM exchange. What exists is a cleartext password checked
> against IRIS, over TLS. The text below describes the design, not the product.

IRIS PGWire was documented as providing enterprise-grade alternatives that match cloud-native patterns:

1. **OAuth 2.0 Token Authentication** (matches Google Cloud PGAdapter approach) _(not available)_
   - Token-based authentication
   - No plain-text passwords
   - 5-minute TTL, automatic refresh
   - Integrated with IRIS security infrastructure

2. **IRIS Wallet** (encrypted credential storage) _(not available)_
   - Credentials encrypted at rest in IRISSECURITY database
   - Automatic password rotation via Wallet API
   - Audit trail of all credential access
   - No plain-text passwords in code or configuration

3. **SCRAM-SHA-256** (industry best practice, YugabyteDB recommended) _(not available)_
   - Challenge-response authentication
   - Cryptographically secure password storage
   - Resistant to replay attacks
   - No plain-text password transmission

### Impact

- ❌ Cannot authenticate using Kerberos tickets
- ❌ No Active Directory SSO integration via GSSAPI
- ⚠️ OAuth 2.0, IRIS Wallet and SCRAM-SHA-256 are not available (see the correction above)
- ✅ Password authentication against IRIS, over TLS by default

### Implementations Comparison

| Implementation      | GSSAPI Support | Notes                                            |
| ------------------- | -------------- | ------------------------------------------------ |
| **PostgreSQL Core** | ✅ Yes         | Native OS Kerberos integration                   |
| **CockroachDB**     | ✅ Yes         | Enterprise feature with keytab management        |
| **PgBouncer**       | ❌ No          | Most deployed connection pooler - GSSAPI omitted |
| **YugabyteDB**      | ❌ No          | Distributed SQL database - uses password auth    |
| **PGAdapter**       | ❌ No          | Google Cloud - uses IAM instead                  |
| **ClickHouse**      | ❌ No          | Analytical database - password only              |
| **QuestDB**         | ❌ No          | Time-series database - no GSSAPI                 |
| **Materialize**     | ❌ No          | Streaming warehouse - standard auth only         |
| **IRIS PGWire**     | ❌ No          | **Matches 6 of 9 implementations**               |

**Pattern**: Only 2 of 9 implementations support GSSAPI (22% adoption rate in ecosystem)

---

## Reporting Issues

Found a new limitation or unexpected behavior?

### Before Reporting

1. Check this document for known issues
2. Test with minimal reproduction case
3. Verify IRIS and PGWire versions

### Report Format

**GitHub Repository**: <https://github.com/isc-tdyar/iris-pgwire/issues>

```markdown
## Issue Description

Brief description of the limitation/bug

## Environment

- IRIS Version: X.X.X
- PGWire Version: X.X.X
- Client: psql/psycopg/other

## Reproduction Steps

1. Step 1
2. Step 2
3. Observe behavior

## Expected Behavior

What should happen

## Actual Behavior

What actually happens

## Workaround (if known)

How to work around the issue
```

---

## Contributing

Help us improve! If you find workarounds or solutions:

1. Fork the repository
2. Create a branch: `fix/limitation-name`
3. Implement fix with tests
4. Submit pull request
5. Update this document

**Priority Contributions Welcome**:

- `pg_catalog` emulation: Add more tables/functions for additional ORMs (e.g., TypeORM, MikrORM)
- Bulk insert optimization: True batching for COPY protocol
- SSL/TLS wire protocol support: Native server-side TLS
- Performance improvements for very large result sets (>1M rows)
