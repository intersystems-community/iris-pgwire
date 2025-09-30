# IRIS PGWire Implementation TODO

## Phase Implementation Plan (P0-P6)

Based on the embedded Python track from `docs/iris_pgwire_plan.md`, this tracks the systematic implementation of a PostgreSQL wire protocol server for InterSystems IRIS.

### P0 - Handshake Skeleton ⏳ IN PROGRESS
**Goal**: Basic connection establishment and session setup

- [ ] **SSL Probe Handler**
  - [ ] Read 8-byte SSL request probe
  - [ ] Respond with 'S' (TLS) or 'N' (plain text)
  - [ ] Implement TLS upgrade using Python ssl.SSLContext

- [ ] **StartupMessage Processing**
  - [ ] Parse startup parameters (user, database, application_name, client_encoding)
  - [ ] Validate required parameters
  - [ ] Store session parameters

- [ ] **Authentication Framework**
  - [ ] Implement basic trust authentication (temporary)
  - [ ] Prepare SCRAM-SHA-256 infrastructure (for P3)

- [ ] **ParameterStatus Emission**
  - [ ] Send required status parameters: server_version, client_encoding=UTF8
  - [ ] Send DateStyle=ISO, MDY, integer_datetimes=on
  - [ ] Send standard_conforming_strings=on, TimeZone, application_name

- [ ] **BackendKeyData Generation**
  - [ ] Generate unique (pid, secret) pair for cancel operations
  - [ ] Store in session registry for CancelRequest handling

- [ ] **ReadyForQuery State**
  - [ ] Send ReadyForQuery with correct transaction status ('I' idle)
  - [ ] Implement basic state machine

**Success Criteria**: Client can connect, receive startup sequence, and reach ready state

---

### P1 - Simple Query Protocol 🔄 PENDING
**Goal**: Execute basic SQL queries against IRIS

- [ ] **Query Message Handler**
  - [ ] Parse Query message format
  - [ ] Extract SQL string from wire format

- [ ] **IRIS SQL Execution**
  - [ ] Integrate with IRIS embedded Python (`iris` module)
  - [ ] Execute SQL using `iris.sql.exec()` or equivalent
  - [ ] Handle blocking calls with `asyncio.to_thread()`

- [ ] **Row Data Encoding**
  - [ ] Implement RowDescription message (column metadata)
  - [ ] Implement DataRow messages (text format initially)
  - [ ] Handle NULL values and empty results

- [ ] **Query Completion**
  - [ ] Send CommandComplete with row count/command tag
  - [ ] Return to ReadyForQuery state
  - [ ] Handle basic error conditions

- [ ] **pg_catalog Shims**
  - [ ] Intercept `SELECT version()`
  - [ ] Intercept `SHOW` commands (standard_conforming_strings, DateStyle, TimeZone)
  - [ ] Basic pg_type table for common OIDs

**Success Criteria**: `psql -c "SELECT 1"` works successfully

---

### P2 - Extended Protocol 🔄 PENDING
**Goal**: Support prepared statements and parameter binding

- [ ] **Parse Message**
  - [ ] Parse statement name and SQL string
  - [ ] Store prepared statements in session
  - [ ] Handle unnamed statements

- [ ] **Bind Message**
  - [ ] Parse portal name and statement reference
  - [ ] Handle parameter formats (text initially)
  - [ ] Bind parameters to prepared statement

- [ ] **Describe Message**
  - [ ] Return statement/portal descriptions
  - [ ] Parameter and result column metadata

- [ ] **Execute Message**
  - [ ] Execute bound portal against IRIS
  - [ ] Handle row limits and suspension

- [ ] **Close/Flush Messages**
  - [ ] Close named statements/portals
  - [ ] Flush buffered messages

- [ ] **Sync Error Handling**
  - [ ] Discard messages until Sync after errors
  - [ ] Maintain correct ReadyForQuery status

**Success Criteria**: psycopg prepared statements work correctly

---

### P3 - Authentication Hardening 🔬 RESEARCHED
**Goal**: Secure authentication with SCRAM-SHA-256

- [x] **SCRAM-SHA-256 Research**
  - [x] PostgreSQL SASL authentication message flow analysis
  - [x] SCRAM challenge-response mechanism understanding
  - [x] Cryptographic operations mapping (HMAC, SHA-256, PBKDF2)
  - [x] AuthenticationSASL/Continue/Final message types documented
  - [x] Integration patterns with existing authentication systems

- [ ] **SASL SCRAM-SHA-256 Implementation**
  - [ ] Implement 5-step SASL authentication message flow
  - [ ] Generate and verify authentication exchanges
  - [ ] Store password verifiers securely (ClientKey, ServerKey, StoredKey)
  - [ ] Handle nonce generation and verification
  - [ ] Implement channel binding with tls-server-end-point

- [ ] **TLS Integration**
  - [ ] Require TLS in production mode
  - [ ] Proper certificate handling
  - [ ] Disable legacy MD5 authentication
  - [ ] Channel binding integration for SCRAM-SHA-256-PLUS

- [ ] **IRIS Authentication**
  - [ ] Delegate to IRIS user authentication if available
  - [ ] Map PostgreSQL users to IRIS users
  - [ ] Handle authentication failures gracefully
  - [ ] Meet 5ms SLA for authentication flows (constitutional compliance)

**Success Criteria**: Secure connections with proper SCRAM-SHA-256 authentication

---

### P4 - Cancel & Timeouts 🔄 PENDING
**Goal**: Query cancellation and timeout handling

- [ ] **CancelRequest Protocol**
  - [ ] Handle separate socket connections for cancel
  - [ ] Verify (pid, secret) pairs
  - [ ] Route to appropriate session

- [ ] **IRIS Query Cancellation**
  - [ ] Integrate with IRIS `CANCEL QUERY` functionality
  - [ ] Map session to IRIS process/statement IDs
  - [ ] Handle cancellation during execution

- [ ] **Statement Timeouts**
  - [ ] Implement configurable query timeouts
  - [ ] Interrupt long-running queries
  - [ ] Return proper error messages and ReadyForQuery status

**Success Criteria**: Ctrl+C in psql cancels running queries

---

### P5 - Types & Vector Support 🔄 PENDING
**Goal**: Robust type system with IRIS vector integration

- [ ] **PostgreSQL Type System**
  - [ ] Implement standard OID mappings (bool=16, int4=23, text=25, etc.)
  - [ ] Type conversion between IRIS and PostgreSQL formats
  - [ ] Binary format support for key types

- [ ] **IRIS Vector Integration**
  - [ ] Define custom `vector` pseudo-type with unique OID
  - [ ] Text encoding for vector values: `'[0.12, -0.34, ...]'`
  - [ ] Integrate with IRIS VECTOR/EMBEDDING types

- [ ] **Vector Operator Support**
  - [ ] SQL rewriter for pgvector operators (`<->`, `<#>`, `<=>`)
  - [ ] Map to equivalent IRIS similarity functions
  - [ ] Support for ANN index operations

- [ ] **Enhanced pg_catalog (Based on caretdev SQLAlchemy patterns)**
  - [ ] Use IRIS INFORMATION_SCHEMA mapping from caretdev implementation
  - [ ] Implement proven OID mappings for IRIS types (BIGINT=20, VARCHAR=1043, etc.)
  - [ ] Add VECTOR type with OID 16388 (avoid PostgreSQL conflicts)
  - [ ] Map IRIS vector functions: vector_cosine, vector_dot_product, vector_l2
  - [ ] Handle IRIS-specific behaviors: Horolog dates, 1/0 booleans, VARCHAR(50) defaults

**Success Criteria**: Vector similarity queries work with pgvector syntax

---

### P6 - COPY & Performance 🔄 PENDING
**Goal**: Bulk operations and performance optimization

- [ ] **COPY Protocol**
  - [ ] CopyOutResponse for data export
  - [ ] CopyInResponse for data import
  - [ ] CopyData streaming with proper chunking

- [ ] **Performance Optimization**
  - [ ] Native C extensions for hot paths (DataRow encoding)
  - [ ] Memory pool for buffer reuse
  - [ ] Backpressure handling for large result sets

- [ ] **Concurrency & Scale**
  - [ ] Connection pooling optimization
  - [ ] ThreadPoolExecutor for IRIS calls
  - [ ] Memory limits per session

**Success Criteria**: `\copy` commands in psql work efficiently

---

## Development Infrastructure

### Testing Strategy
- [ ] **Unit Tests**: Message parsing, type conversion, protocol state machine
- [ ] **Integration Tests**: IRIS connectivity, SQL execution, authentication
- [ ] **Protocol Tests**: Wire-level compatibility with multiple clients
- [ ] **Performance Tests**: Connection scaling, throughput benchmarks

### Docker Integration
- [ ] **IRIS Container**: Reuse kg-ticket-resolver IRIS build 127 setup
- [ ] **Network Integration**: Connect to existing Docker network
- [ ] **Development Environment**: Hot reload for development

### Documentation
- [ ] **API Documentation**: Protocol implementation details
- [ ] **Client Examples**: Connection examples for popular drivers
- [ ] **Deployment Guide**: Production deployment instructions

## Current Priority
**Focus**: Complete P0 handshake skeleton to establish basic connectivity foundation.

## Notes
- Leverage existing IRIS Docker setup from kg-ticket-resolver
- Use build 127 IRIS image: `containers.intersystems.com/intersystems/iris:latest-preview`
- Follow embedded Python approach with asyncio for concurrency
- Start with text format for all types, add binary selectively