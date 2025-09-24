
# Implementing a PostgreSQL (pgwire) Server for InterSystems IRIS  
**Date:** 2025-09-24

This document lays out two pragmatic implementation tracks for a PostgreSQL wire‑protocol (pgwire) server for **InterSystems IRIS**:

1. **Embedded Python track** — protocol in Python (`asyncio`), with optional native acceleration for hot paths.  
2. **Rust‑only track** — end‑to‑end Rust server (Tokio + `pgwire` crate), calling IRIS via your internal **rzf** ObjectScript↔Rust bridge.

Both tracks cover: protocol handshake, TLS/SCRAM auth, cancel, extended query protocol, type/OID mapping, `pg_catalog` shims, vector search support, COPY streaming, backpressure, and test strategy.

---

## Executive Summary

- **Goal:** Speak pgwire **v3** well enough that standard Postgres clients (psql, psycopg, JDBC, Npgsql, pgx) can connect and run queries, while executing **IRIS SQL** behind the scenes and returning results with the types/semantics those clients expect.
- **Non‑goal:** Emulate all of PostgreSQL’s SQL dialect. This is **protocol compatibility**, not SQL dialect compatibility (akin to ClickHouse / CrateDB / CockroachDB).

---

## Part A — Embedded Python Track (with optional C++/Rust acceleration)

### A1. High‑Level Architecture

```
TCP:5432 (listener)
   └── asyncio loop (single process, many coroutines)
        ├─ accept → read 8‑byte probe → SSLRequest? 'S'→TLS / 'N'→plain
        ├─ per‑connection coroutine (session state machine)
        │    ├─ StartupMessage → (SASL SCRAM) → ParameterStatus + BackendKeyData → ReadyForQuery
        │    ├─ Simple Query:  Query → IRIS exec → RowDescription/DataRow/CommandComplete
        │    ├─ Extended:      Parse/Bind/Describe/Execute/Sync/Close/Flush
        │    ├─ CancelRequest: separate short‑lived socket → cancel running statement
        │    └─ CopyIn/CopyOut: stream
        └─ observability (metrics/logs/slow query/tracing)
```
**IRIS execution path:** Use the Embedded Python `iris` module to execute SQL and fetch rows. Keep blocking calls off the event loop using `asyncio.to_thread()` or a small native shim to release the GIL.

**Hot loops to consider for native acceleration:** row encoding to wire frames, SCRAM hashing, bulk COPY streaming.

---

### A2. Protocol Handshake & Session Lifecycle (minimum viable)

1. **SSL probe**: Read 8 bytes at connect; reply `'S'` (wrap with TLS) or `'N'`.  
2. **StartupMessage**: parse parameters (user, database, application_name, client_encoding).  
3. **Auth**: start with **SASL SCRAM‑SHA‑256** (avoid MD5).  
4. **ParameterStatus**: send standard keys:  
   `server_version`, `client_encoding=UTF8`, `DateStyle=ISO, MDY`, `integer_datetimes=on`, `standard_conforming_strings=on`, `TimeZone`, `application_name` (echo), etc.  
5. **BackendKeyData**: (pid, secret) — required for cancel.  
6. **ReadyForQuery**: with correct txn status byte (`I` idle, `T` in txn, `E` failed txn).

> Tip: Many drivers behave purely based on **ParameterStatus** + a few `pg_catalog` probes; invest here early.

---

### A3. Simple vs Extended Query Protocol

- **Simple Query** (`Query`): parse & execute the SQL string in IRIS; stream rows; end with `CommandComplete` → `ReadyForQuery`.
- **Extended Protocol**: `Parse` (named statement), `Bind` (portal + formats), `Describe`, `Execute`, `Close`, `Sync`.  
  - On any error after `Bind`, **discard** until `Sync`, then reply `ReadyForQuery` with accurate txn state.
  - Start with **text format** for all columns; add binary selectively later.

---

### A4. Authentication & Transport Security

- **TLS** via Python `ssl.SSLContext` after SSLRequest probe.
- **SASL SCRAM‑SHA‑256** (optionally `-PLUS` when you add channel binding). Store verifiers safely or delegate to IRIS auth if available.
- Enforce **TLS required** in production. Disable legacy MD5.

---

### A5. Cancel, Timeouts, and Termination

- Send `BackendKeyData` on login. Maintain `{secret → session}`.
- Implement **CancelRequest** on a new socket: verify pid/secret → call IRIS **`CANCEL QUERY`** (optionally with statement id).  
- Add **statement timeout** (server‑side); interrupt the running task; ensure correct ReadyForQuery status.

---

### A6. Types, OIDs, and Row Encoding

- Start with **text format** universally; clients interoperate well in text.  
- Maintain a **type map** for common OIDs (e.g., `bool=16`, `bytea=17`, `int4=23`, `text=25`, `float8=701`, `timestamptz=1184`).  
- `RowDescription` must include: name, table OID (0 if unknown), type OID, typmod, format code (0=text).  
- Add binary encoders later for hot types if needed.

---

### A7. `pg_catalog` Shim (small but crucial)

- Intercept a handful of common probes (connection startup and ORMs):  
  - `SELECT version()`, `SHOW standard_conforming_strings`, `SHOW DateStyle`, `SHOW TimeZone`  
  - Minimal `pg_type` OID lookups for your exposed types (including your pseudo‑type `vector`).  
- Return consistent values aligned with your `ParameterStatus` announcements.

---

### A8. Vector Support (IRIS VECTOR / EMBEDDING types)

- Use IRIS native **VECTOR** / **EMBEDDING** storage and similarity functions to execute queries.  
- **Wire behavior:** expose a pseudo‑type `vector` with your chosen OID in the `pg_type` shim; **encode values as text** initially (e.g., `'[0.12, -0.34, ...]'`).  
- **Operator compatibility:** provide either:  
  1) A **SQL rewriter** in the server to translate pgvector operators (`<->`, `<#>`, `<=>`, etc.) into equivalent IRIS functions; or  
  2) An **IRIS compatibility package** exporting pgvector‑like **functions** (operators are harder cross‑DB).  
- **ANN indexes:** surface IRIS’s vector indexing story via standard DDL. Document any differences with pgvector’s IVFFlat/HNSW naming.

---

### A9. COPY Streaming (optional, nice‑to‑have)

- Implement `CopyOutResponse`/`CopyInResponse` and stream data with `CopyData` chunks.  
- For bulk export/import via `psql`, COPY support improves real usability.

---

### A10. Observability & Backpressure

- Log state transitions (Startup→Auth→Ready), auth outcomes, slow queries, result sizes, and socket backpressure events.  
- Pause IRIS fetches when socket buffers back up; resume when `drain()` completes.  
- Add connection/session metrics and tracing hooks.

---

### A11. Concurrency & Scale (1k+ connections)

- **Evented**: one coroutine per connection on `asyncio`.  
- Use a bounded **ThreadPoolExecutor** (or native shim) for the **blocking** IRIS calls.  
- Pre‑allocate buffers and reuse `bytearray`/`memoryview` for DataRow encoding.  
- Enforce per‑session memory caps; avoid unbounded result buffering.

---

### A12. Deployment in IRIS

- Package the server as an IRIS class method that starts/stops the asyncio event loop (or as an Interoperability Production business service).  
- Use the **Flexible Python Runtime** pattern for Python versioning and third‑party wheels (e.g., C extensions for speed).

---

### A13. Phased Delivery (Python)

**P0 – Handshake skeleton**  
TLS probe → Startup → (temporary trust or password) → ParameterStatus → BackendKeyData → ReadyForQuery.

**P1 – Simple Query**  
`Query` → IRIS exec → `RowDescription`/`DataRow`/`CommandComplete`/`ReadyForQuery`. Add `pg_catalog` shim.

**P2 – Extended Protocol**  
`Parse/Bind/Describe/Execute/Sync/Close/Flush`. Verify error+Sync semantics.

**P3 – Auth hardening**  
SASL SCRAM‑SHA‑256 (+ channel binding later). TLS‑only in prod.

**P4 – Cancel & timeouts**  
`BackendKeyData` + `CancelRequest` → IRIS `CANCEL QUERY`. Statement timeout.

**P5 – Types & vectors**  
Stable OIDs; `vector` pseudo‑type (text encoding); operator rewrite or compat functions.

**P6 – COPY**  
CopyIn/CopyOut.

**P7 – Perf**  
Native encoder for DataRow; SCRAM hashing native; bulk COPY fast‑path.

---

## Part B — Rust‑Only Track (Tokio + `pgwire` + rzf)

### B1. Why Rust‑only can be cleaner

- Wire protocol, TLS, SCRAM, backpressure, and streaming are **hot paths** — Rust fits well.  
- The **rzf** bridge narrows the language boundary to one place: “execute SQL / fetch rows / cancel”.  
- Fewer context switches in the hot loop; easier to reason about performance & memory.

---

### B2. High‑Level Architecture

```
Tokio TcpListener :5432
  └─ accept → read SSLRequest → reply 'S' (TLS) or 'N' (plain)
     └─ per-connection task (pgwire session)
         ├─ Startup → SASL SCRAM → ParameterStatus, BackendKeyData → ReadyForQuery
         ├─ Simple / Extended protocol
         ├─ CancelRequest on separate socket → cancel via rzf
         ├─ CopyIn/CopyOut
         └─ Observability (tracing, metrics)
```
- **Protocol core:** use the **`pgwire` crate** (MIT/Apache‑2.0) for parsing/encoding & session protocol.  
- **Codec/types:** optionally pull helpers from **`postgres-protocol`** and **`postgres-types`** (MIT/Apache‑2.0).  
- **TLS:** **tokio‑rustls**. Remember to **flush** TLS buffers (important for backpressure).

---

### B3. IRIS Execution via rzf

Define a small trait for execution; the session calls only this interface:

```rust
trait IrisExecutor {
    fn exec_simple(&self, sql: &str) -> Result<IrisRows, IrisErr>;
    fn exec_prepared(&self, stmt: &StmtKey, binds: &[IrisValue]) -> Result<IrisRows, IrisErr>;
    fn begin(&self) -> Result<(), IrisErr>;
    fn commit(&self) -> Result<(), IrisErr>;
    fn rollback(&self) -> Result<(), IrisErr>;
    fn cancel(&self, pid: i32, stmt_id: Option<i64>) -> Result<(), IrisErr>;
}
```

- Map transactions to IRIS semantics; ensure **ReadyForQuery** status reflects `I/T/E` correctly.  
- Expose the current IRIS **process id** to wire up cancel routing cleanly.

---

### B4. Types, OIDs, Vectors

- Same type strategy as Python: start **text‑only**; maintain the standard OIDs for common types.  
- Add a `vector` pseudo‑type OID in your `pg_type` shim; encode as text.  
- Optionally define binary encoders for core types later (leave vectors text until a stable binary layout is required).

---

### B5. `pg_catalog` & Startup Probes

- Emit ParameterStatus keys as in Part A; include `server_version`, `client_encoding`, `standard_conforming_strings`, etc.  
- Provide minimal `pg_catalog` tables/answers in memory to satisfy driver probes.

---

### B6. Cancel & Timeouts

- On login, send **BackendKeyData**; on **CancelRequest**, match `(pid, secret)` and call **rzf** → IRIS **`CANCEL QUERY`**.  
- Implement **statement timeout** via Tokio timers; abort the running execution and return an error + correct `ReadyForQuery` state.

---

### B7. COPY

- Wire `CopyOutResponse`/`CopyInResponse` with chunked streaming via Tokio I/O.

---

### B8. Performance Notes

- Use `BytesMut`/`Bytes` for minimal copies; pool row buffers.  
- Respect TLS buffering — call `flush()` at sensible boundaries.  
- Cap per‑connection buffers; backpressure by pausing IRIS fetches when socket slow‑writes are detected.

---

### B9. Phased Delivery (Rust)

**P0 – Handshake + Ready**  
SSL probe → TLS (if configured) → Startup → SCRAM (or temporary trust) → ParameterStatus → BackendKeyData → ReadyForQuery.

**P1 – Simple Query**  
Query path + row streaming.

**P2 – Extended Protocol**  
Prepared statements & portals, strict `Sync`/error rules.

**P3 – Auth hardening**  
SCRAM‑SHA‑256 (`-PLUS` later), TLS‑only in prod.

**P4 – Cancel & timeouts**  
Implement CancelRequest; statement timeout with Tokio.

**P5 – Types & vectors**  
Stable OIDs; `vector` pseudo‑type (text); operator rewrite or compat package.

**P6 – COPY**  
CopyIn/CopyOut streaming.

**P7 – Perf**  
Zero‑copyish encoding; pooled buffers; native SIMD for simple encoders if useful.

---

## Appendix: Practical Checklists

### C1. ParameterStatus keys (typical set)
- `server_version=16` (or similar), `client_encoding=UTF8`, `DateStyle=ISO, MDY`, `integer_datetimes=on`, `standard_conforming_strings=on`, `TimeZone=UTC` (or local), `IntervalStyle=postgres`, `is_superuser=off`, `server_encoding=UTF8`, `application_name` (echo).

### C2. Minimal `pg_catalog` shims to satisfy common clients
- `SELECT version()` → something like `InterSystems IRIS (pgwire-compatible) based on PostgreSQL 16 semantics`  
- Minimal rows in `pg_type` for types you advertise (e.g., base types + `vector`)  
- `SHOW standard_conforming_strings`, `SHOW DateStyle`, `SHOW TimeZone`  
- Optionally, lightweight answers for `pg_namespace`, `pg_proc` when ORMs probe functions

### C3. Common OIDs you’ll need early
- `bool=16`, `bytea=17`, `int2=21`, `int4=23`, `int8=20`, `text=25`, `float4=700`, `float8=701`, `numeric=1700`, `date=1082`, `time=1083`, `timestamp=1114`, `timestamptz=1184`, `json=114`, `jsonb=3802`  
- Pick an internal OID for `vector` and list it in your shim.

### C4. Test Matrix
- **Clients:** psql, psycopg3, JDBC, Npgsql, pgx  
- **Scenarios:** Startup handshake; ParameterStatus; Simple/Extended; prepared statements; COPY IN/OUT; CancelRequest; statement timeout; transaction state transitions; vector queries (ORDER BY distance, LIMIT); large result sets; backpressure.  
- **Wire‑level assertions:** After an error during extended protocol, the server must discard until `Sync`, then issue `ReadyForQuery` with the correct status byte. Ensure `BackendKeyData` sent. Ensure SSL probe behavior exactly matches spec.  

---

## Clickable References

### PostgreSQL Protocol (official)
- Message flow: https://www.postgresql.org/docs/current/protocol-flow.html
- Message formats (incl. SSLRequest, CancelRequest): https://www.postgresql.org/docs/current/protocol-message-formats.html
- SASL / SCRAM authentication: https://www.postgresql.org/docs/current/sasl-authentication.html
- ReadyForQuery status / historical context: https://www.postgresql.org/docs/7.3/protocol-protocol.html
- SSLRequest magic (discussion; 1234/5679, 80877103): https://www.postgresql.org/message-id/160042095164.14056.845885391728089260%40wrigleys.postgresql.org
- Practical SSL probe note: https://github.com/mholt/caddy-l4/issues/187

### Cancel
- libpq cancel: https://www.postgresql.org/docs/current/libpq-cancel.html

### PGWire server libraries / codecs (Rust)
- `pgwire` crate (MIT/Apache-2.0): https://github.com/sunng87/pgwire
- `pgwire` docs.rs: https://docs.rs/pgwire/latest/pgwire/
- `postgres-protocol` crate: https://docs.rs/postgres-protocol
- `postgres-types` crate: https://docs.rs/postgres-types/latest/postgres_types/

### Rust async / TLS
- Tokio runtime: https://tokio.rs/
- tokio-rustls: https://docs.rs/tokio-rustls/latest/tokio_rustls/
- Tokio docs.rs: https://docs.rs/tokio/latest/tokio/
- rustls: https://docs.rs/rustls/latest/rustls/
- Bridging sync/async in Tokio: https://tokio.rs/tokio/topics/bridging

### InterSystems IRIS
- Embedded Python intro: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=AFL_epython
- Call InterSystems IRIS from Embedded Python: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GEPYTHON_calliris
- IRIS Python module reference: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GEPYTHON_reference_core
- CANCEL QUERY (SQL): https://docs.intersystems.com/irislatest/csp/docbook/platforms/DocBook.UI.Page.cls?KEY=RSQL_cancelquery
- Vector search (VECTOR/EMBEDDING): https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_vecsearch
- EMBEDDING function: https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=RSQL_embedding
- Callin C API (for Rust FFI route): https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=BXCI_CALLIN

### pgvector (context)
- Repo: https://github.com/pgvector/pgvector
- Operators overview (pgxn page): https://pgxn.org/dist/vector/
- Quantization background: https://jkatz05.com/post/postgres/pgvector-scalar-binary-quantization/
- Binary protocol type details (client ask; not fully specified in public docs): https://github.com/pgvector/pgvector/issues/829

### Other DBs speaking pgwire (precedent)
- ClickHouse PG wire: https://clickhouse.com/docs/interfaces/postgresql
- CrateDB PG wire v3: https://cratedb.com/docs/crate/reference/en/latest/interfaces/postgres.html
- CockroachDB PG compatibility: https://www.cockroachlabs.com/docs/stable/postgresql-compatibility

---

## License Notes (safe reuse)

- Favor **MIT/Apache‑2.0** sources for embedded code: `pgwire`, `postgres-protocol`, `postgres-types`, `tokio-rustls`, `tokio`.  
- Avoid GPL/AGPL sources in server core.  
- Using official PostgreSQL docs for protocol details is fine (documentation license).

---

## Quick Recommendations

- For the **first working system**, ship the **Rust‑only** track: Tokio + `pgwire` + rzf for execution, text‑only encoders, tiny `pg_catalog` shim, cancel + timeouts.  
- Maintain the **Embedded Python** variant as a reference path and for teams that prefer Python extensibility; accelerate hot paths via C++/Rust if needed.

