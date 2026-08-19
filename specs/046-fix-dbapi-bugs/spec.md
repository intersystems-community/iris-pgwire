# Feature Specification: Fix DBAPI Backend Bugs

**Feature Branch**: `046-fix-dbapi-bugs`
**Created**: 2026-08-19
**Status**: Draft
**Input**: User description: "Fix DBAPI backend bugs from Issue #2"
**Source**: <https://github.com/intersystems-community/iris-pgwire/issues/2>

## User Scenarios & Testing _(mandatory)_

### User Story 1 - DBAPI Backend Executes Queries Without Crashing (Priority: P1)

A developer running iris-pgwire in DBAPI backend mode (`IRIS_BACKEND=dbapi`) issues any SQL
query through a standard PostgreSQL client. Today the query fails immediately with a TypeError
because `execute_query` does not accept the `session_id` keyword argument that the protocol
handler passes, and the result returned is a raw list of tuples rather than the structured dict
the protocol expects.

**Why this priority**: The DBAPI backend is completely non-functional for any query today — this
is a crash-level regression that affects every user of this mode.

**Independent Test**: Start iris-pgwire with `IRIS_BACKEND=dbapi`, connect with psql, run
`SELECT 1`. Expect a result row, not a traceback.

**Acceptance Scenarios**:

1. **Given** iris-pgwire is running in DBAPI mode, **When** a client sends `SELECT 1`, **Then**
   the server returns one row containing `1` with no errors.
2. **Given** iris-pgwire is running in DBAPI mode, **When** a client sends a parameterised query
   (`SELECT $1::int`), **Then** the server returns the correct value with no TypeError.
3. **Given** iris-pgwire is running in DBAPI mode, **When** a client sends a DML statement
   (`INSERT`, `UPDATE`, `DELETE`), **Then** the server returns the correct command tag.

---

### User Story 2 - Connection Pool Stays Healthy Over Time (Priority: P2)

An operator running iris-pgwire in DBAPI mode needs the connection pool to track connection age
accurately. Today a crash occurs the first time pool maintenance code runs because connection
timestamps are created without timezone information while the age calculation uses a
timezone-aware clock — causing a TypeError that can bring down the pool health loop.

**Why this priority**: A crashing health loop silently leaks connections and eventually exhausts
the pool, causing all queries to hang. It is a slow-burn reliability bug on top of the P1 crash.

**Independent Test**: Start iris-pgwire in DBAPI mode, let it run for the pool health-check
interval (default 30 s), confirm no TypeError in logs and the pool reports correct connection ages.

**Acceptance Scenarios**:

1. **Given** a connection is created, **When** the pool checks its age, **Then** the age is
   computed without error and reflects the correct elapsed time.
2. **Given** the pool has been running for several minutes, **When** health-check fires,
   **Then** no TypeError appears in the logs.

---

### User Story 3 - ORM Introspection Works on Community Edition (Priority: P3)

A developer using IRIS Community Edition (limited to 1 external connection) runs an ORM
(Drizzle, SQLAlchemy, Prisma) against iris-pgwire in DBAPI mode. Today the Describe-message
handler opens a second connection to gather column metadata, which IRIS CE refuses with
"Unable to allocate a license", causing a silent hang and then a timeout.

**Why this priority**: Community Edition is the primary local-development target for the DBAPI
backend. A hang on every prepared-statement introspection makes the ORM path unusable for the
largest audience of DBAPI-mode users.

**Independent Test**: Start iris-pgwire against an IRIS CE instance with `IRIS_BACKEND=dbapi`,
run an ORM introspection query (e.g. `SELECT * FROM pg_tables`). Expect a result within 2 s
without "license" errors.

**Acceptance Scenarios**:

1. **Given** iris-pgwire is connected to IRIS CE (1-connection limit), **When** a client sends a
   Describe message, **Then** the server responds without opening a second connection and without
   hanging.
2. **Given** the Describe handler runs on an already-open connection, **When** it finishes,
   **Then** that connection is returned to the pool rather than left open.

---

### User Story 4 - Community Edition Mode Prevents License Exhaustion (Priority: P4)

A developer deploying against IRIS Community Edition wants a single configuration flag that
constrains iris-pgwire to one IRIS connection at all times, so no code path can accidentally
exhaust the CE license.

**Why this priority**: Even after the Describe fix, other future code paths could introduce
second-connection usage. A hard cap at the pool level is a safety net rather than a series of
per-callsite patches.

**Independent Test**: Set `IRIS_MAX_CONNECTIONS=1` (or equivalent CE-mode flag), verify the
pool starts with one connection and refuses to open a second even under concurrent load.

**Acceptance Scenarios**:

1. **Given** CE mode is enabled, **When** 10 concurrent clients connect, **Then** queries are
   serialised through a single IRIS connection — none receive a license error.
2. **Given** CE mode is enabled, **When** the pool is inspected, **Then** the reported maximum
   connection count is 1.
3. **Given** CE mode is not configured, **When** the server starts, **Then** pool behaviour is
   unchanged from today (no performance regression).

---

### Edge Cases

- What happens when `session_id` is `None` vs a non-None string — both must be accepted.
- What happens when `execute_query` is called with positional-only args (no keyword) — must
  still work for call sites that already match the old signature.
- What happens when the pool age calculation runs at exactly midnight (date rollover) — must not
  produce a negative age.
- What happens when CE mode is set and a Describe message arrives while the one connection is in
  use — must queue, not open a second connection or raise.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: `DBAPIExecutor.execute_query` MUST accept `session_id` as an optional keyword
  argument and silently ignore it (DBAPI connections are not session-scoped).
- **FR-002**: `DBAPIExecutor.execute_query` MUST return a structured result dict with at minimum
  a `rows` key containing a list of row values, matching the shape `IRISExecutor` returns.
- **FR-003**: Connection timestamps in the DBAPI connection pool MUST be timezone-aware so that
  age calculations do not raise a TypeError.
- **FR-004**: The Describe-message handler MUST NOT open a second IRIS connection when running
  in DBAPI mode; it MUST reuse the existing pool connection.
- **FR-005**: The server MUST support a single-connection configuration flag that caps the DBAPI
  pool at one IRIS connection, serialising all queries through it.
- **FR-006**: When the single-connection cap is active, the server MUST surface a clear
  indication in its startup log so operators know CE mode is in effect.
- **FR-007**: All existing DBAPI-mode behaviour that already works MUST continue to work after
  these changes (no regressions in the embedded backend or in previously passing DBAPI tests).

### Assumptions

- `session_id` carries no meaning for DBAPI connections (it is an embedded-Python concept);
  accepting and ignoring it is the correct fix, not forwarding it.
- The structured result dict shape is defined by the existing `IRISExecutor` return contract
  (`rows`, `columns`, `command`, `row_count`); both executors must agree on this shape.
- The pool health-check interval and other pool parameters remain configurable; CE mode only
  changes the maximum connection count.
- "CE mode" is implemented as an existing or new environment variable / config key, not a
  separate binary or build.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: A SELECT query issued against iris-pgwire in DBAPI mode returns a result row in
  under 500 ms with zero errors — verified from a cold start with no prior connections.
- **SC-002**: The connection pool runs for 5 minutes in DBAPI mode without any TypeError
  appearing in logs related to datetime arithmetic.
- **SC-003**: An ORM introspection sequence (connect → Describe → Execute → disconnect) against
  IRIS Community Edition completes in under 2 s and opens exactly one IRIS connection.
- **SC-004**: With CE mode enabled, 20 concurrent client queries all receive correct results;
  zero "license allocation" errors appear in logs.
- **SC-005**: All unit and contract tests that passed before this feature continue to pass after
  it (zero regressions).
