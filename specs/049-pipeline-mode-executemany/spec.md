# Feature Specification: psycopg3 Pipeline Mode + executemany Support

**Feature Branch**: `049-pipeline-mode-executemany`
**Created**: 2026-08-25
**Status**: Draft
**Input**: Bug 2 from SimpleMem fork — psycopg3 pipeline mode + executemany batch execution

## User Scenarios & Testing *(mandatory)*

### User Story 1 - executemany Batch Insert (Priority: P1)

A developer uses psycopg3's `cursor.executemany()` to insert/update many rows at once against iris-pgwire. Currently the server handles each row as a separate Round-Trip, which is slow and can corrupt batch state if ON CONFLICT or RETURNING clauses are not stripped on all rows.

**Why this priority**: Most common use case; executemany is the baseline batch API. Correctness is broken — duplicate key errors crash the entire batch instead of being handled per-row.

**Independent Test**: Run `cursor.executemany("INSERT INTO t VALUES (%s)", [(1,),(2,),(3,)])` via psycopg3 in unit tests using the protocol mock; verify all rows land, no crash on duplicate key.

**Acceptance Scenarios**:

1. **Given** a table `t(id INT PRIMARY KEY)`, **When** `executemany("INSERT INTO t VALUES (%s) ON CONFLICT DO NOTHING", [(1,),(1,),(2,)])`, **Then** rows 1 and 2 land, duplicate silently ignored, no error raised to client.
2. **Given** a batch of 100 rows, **When** `executemany("INSERT INTO t(v) VALUES (%s)", rows)`, **Then** all 100 rows inserted, command tag `INSERT 0 100` returned.
3. **Given** a batch with a genuine PK violation (no ON CONFLICT clause), **When** second row duplicates first, **Then** error propagated correctly to client with SQLSTATE 23505.

---

### User Story 2 - psycopg3 Pipeline Mode (Priority: P2)

A developer uses psycopg3's explicit pipeline context (`with conn.pipeline():`) to send multiple queries without waiting for each response. iris-pgwire must handle the pipelined Flush/Sync sequencing correctly.

**Why this priority**: High-value performance feature; psycopg3 uses pipeline mode internally for `executemany()` calls when the server announces pipeline support. Broken pipeline sync causes client hangs or dropped responses.

**Independent Test**: Run a psycopg3 pipeline block that issues 3 INSERTs and a SELECT; verify all 4 responses arrive in order and the final ReadyForQuery is sent after the pipeline Sync.

**Acceptance Scenarios**:

1. **Given** a pipeline context with 3 INSERT statements, **When** `pipeline.sync()` is called, **Then** server flushes all buffered DML, sends 3 CommandComplete messages and 1 ReadyForQuery.
2. **Given** mixed DML and SELECT in one pipeline, **When** flushed, **Then** DML is executed via executemany, SELECT result arrives with RowDescription + DataRow(s) + CommandComplete, all before ReadyForQuery.
3. **Given** a pipeline where one statement errors, **When** synced, **Then** error response sent for that statement, remaining statements return ErrorResponse with SQLSTATE 25P02 (in_failed_sql_transaction), ReadyForQuery with status `E` sent at end.

---

### Edge Cases

- What happens when executemany is called with an empty parameter list?
- What happens when pipeline Sync arrives before any Execute messages are buffered?
- How does the server handle a Flush message mid-pipeline (partial flush, no ReadyForQuery)?
- What happens if a pipeline batch mixes DDL and DML (DDL must not be batched)?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Server MUST handle `executemany()` calls by executing all parameter sets against the same SQL template, returning a single CommandComplete with the total row count.
- **FR-002**: Server MUST strip ON CONFLICT clauses from batched SQL before each execution, treating duplicate key errors as silent skips (not as batch-aborting errors) when ON CONFLICT DO NOTHING was specified.
- **FR-003**: Server MUST handle psycopg3 pipeline Sync messages by flushing the entire DML batch, sending CommandComplete for each buffered statement, then sending ReadyForQuery.
- **FR-004**: Server MUST handle Flush messages within a pipeline without sending ReadyForQuery (Flush flushes the write buffer only; Sync terminates the pipeline cycle).
- **FR-005**: In pipeline mode, a statement error MUST NOT abort subsequent statements' execution; each statement sends its own response (CommandComplete or ErrorResponse).
- **FR-006**: Server MUST NOT batch DDL statements (CREATE TABLE, ALTER TABLE, etc.) — these must execute immediately and synchronously.
- **FR-007**: Server MUST correctly report row counts in CommandComplete tags when executemany is used (`INSERT 0 N` where N is total rows successfully inserted).

### Key Entities

- **Batch Buffer**: In-memory list of parameter sets accumulated between Bind messages and a Sync/Flush; keyed to a single SQL template.
- **Pipeline Cycle**: The protocol unit starting after a ReadyForQuery and ending with the next Sync message; may contain multiple Parse/Bind/Execute/Describe sequences.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A psycopg3 `executemany()` inserting 1,000 rows completes without error.
- **SC-002**: Pipeline mode batch of 10 mixed DML statements completes with correct per-statement responses.
- **SC-003**: Duplicate key scenario with `ON CONFLICT DO NOTHING` in executemany produces zero errors to the client.
- **SC-004**: Row count in CommandComplete tag matches actual rows inserted (not hard-coded to 0).
- **SC-005**: All existing 5,500+ unit tests continue to pass after changes.

## Assumptions

- psycopg3 pipeline mode is the primary driver; other clients (asyncpg, jdbc) use extended protocol without explicit pipeline mode and are unaffected.
- IRIS does not natively support upsert via executemany — ON CONFLICT stripping + duplicate key suppression is the correct emulation strategy.
- Per-statement error isolation within a pipeline (FR-005) is aspirational for this feature; if complex, it can be deferred to a follow-on spec. The minimum required is correct Sync handling (FR-003/FR-004).
