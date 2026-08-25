# Feature Specification: psycopg3 Pipeline Mode + executemany Support

**Feature Branch**: `049-pipeline-mode-executemany`
**Created**: 2026-08-25
**Status**: Draft
**Input**: Bug 2 from SimpleMem fork — psycopg3 pipeline mode + executemany batch execution

## User Scenarios & Testing _(mandatory)_

### User Story 1 - executemany Batch Insert (Priority: P1)

A developer uses psycopg3's `cursor.executemany()` to insert/update many rows at once against iris-pgwire. The server currently crashes the entire batch on a duplicate key error instead of handling it per-row, and ON CONFLICT clauses are not stripped before IRIS receives the SQL.

**Why this priority**: executemany is the baseline batch API; duplicate key crashes are the most common failure mode.

**Independent Test**: Run `cursor.executemany("INSERT INTO t VALUES (%s)", [(1,),(2,),(3,)])` via psycopg3; verify all rows land, no crash on duplicate key.

**Acceptance Scenarios**:

1. **Given** a table `t(id INT PRIMARY KEY)`, **When** `executemany("INSERT INTO t VALUES (%s) ON CONFLICT DO NOTHING", [(1,),(1,),(2,)])`, **Then** rows 1 and 2 land, duplicate silently ignored, no error raised to client.
2. **Given** a batch of 100 rows, **When** `executemany("INSERT INTO t(v) VALUES (%s)", rows)`, **Then** all 100 rows inserted, command tag `INSERT 0 100` returned.
3. **Given** a batch with a genuine PK violation (no ON CONFLICT clause), **When** second row duplicates first, **Then** error propagated to client with SQLSTATE 23505.

---

### User Story 2 - psycopg3 Pipeline Mode (Priority: P2)

A developer uses psycopg3's explicit pipeline context (`with conn.pipeline():`) to send multiple queries without waiting for each response. iris-pgwire must handle Flush/Sync sequencing correctly.

**Why this priority**: psycopg3 uses pipeline mode internally for `executemany()` calls; broken Sync sequencing causes client hangs.

**Independent Test**: Run a psycopg3 pipeline block with 3 INSERTs and a SELECT; verify all 4 responses arrive in order and ReadyForQuery is sent after the pipeline Sync.

**Acceptance Scenarios**:

1. **Given** a pipeline context with 3 INSERT statements, **When** `pipeline.sync()` is called, **Then** server flushes all buffered DML, sends 3 CommandComplete messages and 1 ReadyForQuery.
2. **Given** mixed DML and SELECT in one pipeline, **When** flushed, **Then** DML executes via executemany, SELECT result arrives with RowDescription + DataRow(s) + CommandComplete, all before ReadyForQuery.
3. **Given** a pipeline where one statement errors, **When** synced, **Then** error response sent for that statement, remaining statements return ErrorResponse with SQLSTATE 25P02, ReadyForQuery with status `E` sent at end.

---

### Edge Cases

- executemany called with an empty parameter list.
- Pipeline Sync arrives before any Execute messages are buffered.
- Flush message mid-pipeline (partial flush, no ReadyForQuery).
- Pipeline batch mixes DDL and DML (DDL must not be batched).

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: Server MUST handle `executemany()` by executing all parameter sets against the same SQL template and returning a single CommandComplete with the total row count.
- **FR-002**: Server MUST strip ON CONFLICT clauses from batched SQL and treat per-row duplicate key errors as silent skips when ON CONFLICT DO NOTHING was specified.
- **FR-003**: Server MUST handle pipeline Sync by flushing the DML batch, sending CommandComplete for each buffered statement, then sending ReadyForQuery.
- **FR-004**: Server MUST handle Flush without sending ReadyForQuery (Flush drains the write buffer; Sync terminates the pipeline cycle).
- **FR-005**: In pipeline mode, a statement error SHOULD NOT abort subsequent statements. _(Aspirational; full per-statement error isolation deferred to a follow-on spec.)_
- **FR-006**: Server MUST NOT batch DDL statements — execute immediately and synchronously.
- **FR-007**: Server MUST correctly report row counts in CommandComplete tags (`INSERT 0 N` where N is rows successfully inserted).

### Key Entities

- **Batch Buffer**: In-memory list of parameter sets accumulated between Bind messages and a Sync/Flush, keyed to a single SQL template.
- **Pipeline Cycle**: The protocol unit from ReadyForQuery to the next Sync, containing multiple Parse/Bind/Execute/Describe sequences.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: `executemany()` inserting 1,000 rows completes without error.
- **SC-002**: Pipeline batch of 10 mixed DML statements completes with correct per-statement responses.
- **SC-003**: `ON CONFLICT DO NOTHING` in executemany produces zero errors to the client.
- **SC-004**: Row count in CommandComplete matches actual rows inserted.
- **SC-005**: All existing 5,500+ unit tests continue to pass.

## Assumptions

- psycopg3 pipeline mode is the primary driver; other clients (asyncpg, jdbc) use extended protocol without pipeline mode and are unaffected.
- IRIS has no native upsert; ON CONFLICT stripping + duplicate key suppression is the correct emulation strategy.
