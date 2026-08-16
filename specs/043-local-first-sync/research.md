# Research: Local-First Sync for IRIS (PGlite + Replicache-class sync)

**Feature**: 043-local-first-sync
**Status**: Research — no implementation decisions ratified yet
**Date**: 2026-08-16
**Author**: Thomas Dyar

---

## 1. Executive summary

The goal: let a browser or edge app hold a **live, queryable, offline-capable partial replica of IRIS
data**, the way PGlite + Electric/Replicache do for PostgreSQL — and get there by building on
iris-pgwire rather than beside it.

Five findings shape everything below.

1. **Replicache is archived.** Rocicorp sunset it and moved to **Zero** (1.0, June 2026). Building
   "a Replicache for IRIS" as a product target aims at a dead runtime. Its *protocol design* —
   push/pull, client-group mutation IDs, CVR-diffed patches — is still the best-documented,
   most database-agnostic write path in the field, and that is what we should borrow.

2. **Zero is the wrong thing to clone.** Zero's `zero-cache` ingests **PostgreSQL logical
   replication** into a SQLite replica. IRIS has no WAL and no logical decoding. Reimplementing
   `zero-cache` means reimplementing IVM over ZQL *and* inventing our own change feed. That is a
   multi-year effort with no ecosystem payoff.

3. **The leverage is Electric's shape protocol.** Electric's sync wire format is a plain, well-specified,
   cacheable **HTTP** protocol (`GET /v1/shape`, offsets, handles, long-poll, JSON op log). If we serve
   *that*, the existing client ecosystem — `@electric-sql/pglite-sync` (0.6.6), `@electric-sql/client`
   (1.5.26), TanStack DB — works against IRIS **unmodified**. This is precisely the iris-pgwire trick,
   one layer up: instead of "speak the Postgres wire protocol so Postgres clients work," it is
   "speak the shape protocol so sync clients work."

4. **The one real gap is a change feed.** iris-pgwire today has no `LISTEN`/`NOTIFY` (only a
   swallowed `UNLISTEN` no-op at `src/iris_pgwire/protocol.py:1448`), no logical replication, no CDC.
   Everything else the sync service needs — SQL translation, type mapping, `pg_catalog`, auth,
   an asyncio server, dual backends — already exists in this repo. **The change feed is the project.**

5. **ECP is a design teacher, not a transport.** It is a 30-year-production distributed cache
   coherence protocol, and its lessons map onto sync engine design with unusual precision — but it is
   a private binary protocol between trusted LAN peers with block-level granularity and no browser
   client. See §5 for what it genuinely gives us (including one concrete, non-obvious reuse).

**Recommended shape of the system**: a trigger-based transactional outbox inside IRIS feeding an
Electric-compatible shape service that runs alongside iris-pgwire, with a Replicache-style
server-authoritative push endpoint for writes. Phased plan in §8.

---

## 2. Landscape

### 2.1 PGlite

WASM build of Postgres — **not** a Linux VM, not a reimplementation. Real Postgres compiled to
WASM, 3 MB gzipped, running in browser (IndexedDB or OPFS persistence), Node, Bun and Deno.
Supports extensions including pgvector and PostGIS. Grown from 1M to 13M weekly downloads in
twelve months; Electric has since joined Databricks.

Relevant capabilities:

| Capability | Package | Note |
|---|---|---|
| Embedded Postgres | `@electric-sql/pglite` 0.5.5 | The local database |
| Live/reactive queries | `@electric-sql/pglite/live` | Re-runs a query when its inputs change |
| Sync-into-tables | `@electric-sql/pglite-sync` 0.6.6 | Applies an Electric shape stream into local tables |
| Shape client | `@electric-sql/client` 1.5.26 | Framework-agnostic shape consumer |

For us, PGlite is a **consumer**, not something to port. It runs unchanged. Notably, pgvector in
PGlite means client-side vector search over a synced subset of IRIS vector data — a differentiated
story given this repo's existing vector work, and one where IRIS's cosine/dot-product-only
constraint (see `CLAUDE.md`) does *not* bind the client.

### 2.2 Electric's shape protocol (the wire format worth adopting)

Verified against `electric-sql/electric` `website/electric-api.yaml` (OpenAPI 1.7.x).

**Request**: `GET /v1/shape` with

- `table` — required; the shape's base table
- `offset` — position in the shape log; `-1` means "from the start"
- `handle` — ephemeral shape identifier, required whenever `offset != -1`
- `live` — `true` switches to long-polling for real-time updates
- `live_sse` — SSE instead of long-poll (only valid with `live=true`)
- `cursor` — server-generated, works around CDN request-coalescing
- `where` + `params[n]` — server-side row filter with safe positional interpolation
- `columns`, `queryable_columns` — projection and a client-controllable allow-list
- `replica` — `default` (changed columns only) or `full` (includes `old_value`)
- `subset__where` / `subset__order_by` / `subset__limit` / `subset__offset` — snapshot subsetting

**Response headers**: `electric-handle`, `electric-offset`, `electric-schema` (column type map,
non-live only), `electric-cursor`, `electric-up-to-date`, plus `etag` in the form
`{handle}:{start_offset}:{end_offset}` and a `cache-control` with `max-age` / `stale-while-revalidate`.

**Body**: a JSON array of messages. Each is either a **control message**
(`up-to-date`, `must-refetch`, `snapshot-end`) or an **operation** with
`headers.operation` ∈ {`insert`, `update`, `delete`}, `key` (row ID), `value` (full row on insert;
PK + changed columns on update; PK only on delete), optional `old_value`, and stream metadata
`lsn`, `op_position`, `last`, `txids`.

**Resumption**: client stores `(handle, offset)`. A `409` means the offset is gone — resync from
`offset=-1` under the new handle. `must-refetch` means discard local shape data and start over.

Two properties matter enormously for an IRIS implementation:

- **It is ordinary cacheable HTTP.** No custom transport, no WebSocket state machine, CDN-friendly.
- **The `must-refetch` escape hatch is first-class.** Any state we cannot reconstruct — journal
  purged, outbox trimmed, shape definition changed — has a defined, correct, already-implemented
  client behavior. This dramatically lowers the bar for a v1 change feed.

### 2.3 Replicache (archived) — what to keep

Replicache's repo is archived; it is no longer a viable dependency. Its design, though, is the
**only** mainstream sync design that assumes nothing about the backing database:

- **Pull**: client sends `cookie` + `clientGroupID`; server returns a new `cookie`, a `patch`
  (`put` / `del` / `clear` ops), and `lastMutationIDChanges`.
- **Cookie**: opaque server-state marker used to compute the next diff.
- **CVR (Client View Record)**: per-pull snapshot of `clientID → lastMutationID` and
  `key → version`, held in ephemeral storage; the diff between the request cookie's CVR and now
  *is* the patch.
- **Mutation IDs**: a mutation is confirmed only when a pull returns `lastMutationID >= its ID`;
  until then the client retries. This gives **exactly-once effects over an at-least-once channel** —
  the property that makes offline writes safe.
- **Server-authoritative mutators**: the client runs an optimistic version; the server runs the real
  one and can disagree. The client rebases.

Its "Row Version Strategy" (per-row `version` column + CVR diffing) is directly implementable in
IRIS with `$INCREMENT` — no WAL required. **This is the write path we should adopt.**

### 2.4 Zero — why not

Zero pairs a client library with `zero-cache`, which maintains a SQLite replica fed by **Postgres
logical replication**, runs ZQL queries with hydrate-once-then-push-diffs IVM, and routes writes
through custom mutators to a `/push` endpoint. Synced queries are server-authorized named queries.

It is excellent and it is the state of the art. It is also the *most* Postgres-coupled option in the
field: its ingest is logical replication, full stop. Nothing in Zero's architecture is reachable for
IRIS without first solving the change-feed problem — and once we have solved that, the
Electric-shape route gives us a working client ecosystem far sooner. **Revisit Zero only after a
change feed exists**, at which point a `zero-cache` ingest adapter becomes a plausible follow-on.

---

## 3. What iris-pgwire already gives us

Inventory of reusable assets in this repo:

| Asset | Location | Reuse in sync |
|---|---|---|
| asyncio TCP server, one coroutine/connection | `server.py` (349 LoC) | Same process can host the shape HTTP service |
| PG wire protocol v3 | `protocol.py` (4,505 LoC) | Mutators execute over the existing SQL path |
| Dual backend (embedded Python / DBAPI) | `backend_selector.py`, `iris_executor.py`, `dbapi_executor.py` | **Embedded mode runs *inside* IRIS** — direct global and journal access |
| PG↔IRIS SQL translation | `sql_translator/` | Shape `where` clauses are PG syntax; reuse as-is |
| PG type OIDs and value formatting | `type_mapping.py`, `_type_mapping.py`, `conversions/` | Shape log values must be PG-formatted; `electric-schema` needs OIDs |
| `pg_catalog` emulation | `catalog/` | Shape validation and column introspection |
| Schema mapping `public` ↔ `SQLUser` | `schema_mapper.py` | Shape `table` param resolution |
| SCRAM / OAuth 2.0 / IRIS Wallet | `auth/` | Shape endpoint authn; gateway authz |
| FastAPI already a dependency | `sql_translator/api.py` | HTTP surface with no new dependency |
| Connection pooling, health checks, backoff | `dbapi_connection_pool.py`, `health_checker.py` | Feed reader resilience |

What is **missing**, confirmed by inspection:

- No `LISTEN` / `NOTIFY`. `protocol.py:1448` swallows `UNLISTEN` as an asyncpg reset no-op; there is
  no publish path.
- No logical replication, no replication slots, no `START_REPLICATION`.
- No CDC of any kind, no change feed, no outbox.
- No HTTP surface on the main server (FastAPI exists only for the translator API).

**Conclusion: ~85% of the plumbing exists. The change feed is the actual work.**

---

## 4. The change feed: four candidate substrates in IRIS

This is the crux. Postgres gives Electric and Zero a totally-ordered, transaction-consistent,
replayable stream for free. IRIS gives us four imperfect options.

### 4.1 Trigger-based transactional outbox — **recommended for v1**

IRIS SQL `AFTER INSERT/UPDATE/DELETE` triggers write a row into an outbox, sequenced by
`$INCREMENT` on a counter global.

```
^PGWireSync.Seq                → monotonic sequence (via $INCREMENT, atomic, no lock)
^PGWireSync.Log(seq)           → $LB(table, op, pk, txid, timestamp)
^PGWireSync.Log(seq,"value")   → changed column values
^PGWireSync.Idx(table,seq)     → per-table index for shape filtering
```

| | |
|---|---|
| **Pros** | Row-level and schema-aware from day one — no global-to-row reverse mapping. Writes commit in the same transaction as the data, so the outbox can never diverge. Ordinary SQL/ObjectScript, no privileged access, no `%SYS` dependency. `$INCREMENT` maps cleanly onto Electric's `offset`/`lsn`. Works identically on both iris-pgwire backends. Trimming the outbox has a defined client behavior (`must-refetch`). |
| **Cons** | Requires DDL per synced table — an explicit opt-in, and a migration story. Write amplification on hot tables. Bulk paths that bypass SQL (direct global sets, `%NOJOURN`, some `COPY` fast paths — see `bulk_executor.py`) will bypass triggers too. |
| **Risk** | Trigger overhead on the write path must be measured against the constitution's 5 ms translation budget. |

### 4.2 Journal-based CDC — the WAL analog, right answer eventually

IRIS journals are the true structural analog of the Postgres WAL: totally ordered, durable,
transaction-aware. `%SYS.Journal.File` and `%SYS.Journal.Record` expose them programmatically;
`%SYS.Journal.SetKillRecord` carries `GlobalNode` (as `MyGlobal(subscripts)`), record type
(`S` for SET, `K` for KILL), `Address` (byte offset — a natural LSN), `DatabaseName`, `ProcessID`,
`InTransaction`, and `TimeStamp`. `SYS.MirrorDejournal::RunFilter` demonstrates the per-record
interception pattern InterSystems itself uses.

| | |
|---|---|
| **Pros** | Zero write-path overhead, zero DDL. Captures *everything*, including non-SQL and bulk writes. `Address` is a genuine monotonic LSN. Transaction boundaries are present — we can emit `last` and `txids` honestly. |
| **Cons** | **Global-level, not row-level.** We must reverse-map `^Global(sub…)` → `(table, pk, column)`. For DDL-created tables IRIS uses **hashed global names** like `^EW3K.B3vA.1`, so the mapping must be read from `DataLocation` in `%Dictionary.StorageDefinition` / `%Dictionary.CompiledStorage` and re-read on every DDL change. Index globals must be filtered out. Requires `%SYS` / `%DB_%DEFAULT` privileges — a real deployment constraint. Journal purge is a hard horizon (→ `must-refetch`). Tailing throughput is **unmeasured** and is the single biggest unknown in this document. |
| **Risk** | Storage-definition reverse mapping is fiddly and version-sensitive. Prove it in a spike before committing. |

### 4.3 Version-column polling — fallback only

A `_sync_version BIGINT` column maintained by `$INCREMENT`, polled with `WHERE _sync_version > ?`.
Trivial to build, works anywhere, and **cannot represent deletes** without a tombstone table — at
which point it is a worse §4.1. Useful as a compatibility path for tables we cannot add triggers to.

### 4.4 Interoperability / Kafka production — not for v1

IRIS Interoperability can publish changes to Kafka, and there is community demand for
CDC-to-Kafka as a first-class SQL feature. This is a heavyweight dependency for a browser sync
engine, but it is the natural integration point if a deployment already runs Interoperability.

### Recommendation

**Build v1 on the outbox (§4.1) behind a `ChangeFeed` interface**, and spike the journal reader
(§4.2) in parallel. The two produce the same op stream; the interface lets us swap substrates
without touching the shape service. Journal-based CDC is the better long-term answer precisely
because it needs no DDL and catches non-SQL writes — but it must not block v1.

---

## 5. What ECP teaches us

ECP (Enterprise Cache Protocol) is InterSystems' distributed caching architecture: a tier of
**application servers**, each with its own database cache, sitting in front of a single **data
server**, with caches kept coherent automatically and locks managed centrally. It is configuration,
not code — "you do not have to use special code or development techniques to create distributed
database applications."

Strip away the transport and ECP *is* a sync engine, and a battle-tested one. Six lessons transfer.

### 5.1 Coherence is server-driven invalidation, not client polling

ECP application servers do not poll for staleness; the data server pushes invalidation when a
cached block is modified elsewhere. Our default posture should match: the shape service pushes via
long-poll/SSE, and the client never polls on a timer. Electric's `live=true` long-poll is exactly
this shape. **Design consequence**: the change feed must be *push-capable* end to end — an outbox
we poll every 500 ms silently reintroduces the thing ECP spent thirty years avoiding. Use IRIS
process-to-process signalling (`%SYSTEM.Event`) or a blocking global-tail to wake the feed reader,
not a sleep loop.

### 5.2 Granularity determines false sharing — choose it deliberately

ECP's known load-balancing pathology: spread users across application servers and *each* may
request the same data, so "blocks are modified on one application server and refreshed across
other application servers" — invalidation traffic amplified by **block** granularity when the
application only cared about one row. ECP pays this because blocks are its unit of storage.

We are not forced to. **Sync at row granularity within a shape, and treat the shape as the
subscription unit.** This is also the argument against journal-based CDC as the *only* substrate:
journals are global-and-block-shaped, and a naive journal reader inherits ECP's false sharing.
The reverse mapping in §4.2 is not merely a convenience — it is what buys us out of this problem.

### 5.3 An explicit connection state machine with a bounded trouble window

ECP does not model a connection as up/down. On interruption the application server "notices the
connection is nonresponsive and blocks new network requests," and once it resumes, blocked
processes send their pending requests. If TCP resets, the data server waits for reconnection for
the **Time interval for Troubled state** (default one minute); if the application server does not
reconnect in that window, the data server resets the connection, **rolls back open transactions,
and releases locks**.

This is the correct model for an offline-capable client, and it is more rigorous than most sync
engines ship with. Our client should have the same states — Normal / Troubled / Recovering /
Failed — with an explicit, configurable trouble window, and a defined transition into
`must-refetch` on expiry. **ECP gives us a proven state machine to copy rather than invent, and
Electric gives us the wire-level primitive (`must-refetch`) to express its terminal state.**

### 5.4 Recovery guarantees are a written contract, not an emergent property

InterSystems documents ECP recovery as an explicit list of guaranteed-recoverable semantics *and*
their limitations. Concretely: rollbacks are **synchronous** while commits are usually asynchronous,
"because the rollback will change blocks that the application server should be notified of before
surrendering any locks"; if any process completes a network request between rollback and TCommit,
"the transaction is guaranteed to roll back on all data servers that are part of the transaction";
and "any transactions that cannot be recovered are rolled back in a way that preserves lock
semantics."

The transferable discipline: **write the guarantee list first**, including the limitations. For our
sync engine that means stating up front what survives a disconnect (queued mutations, local reads),
what does not (in-flight uncommitted server mutations), what ordering is preserved, and under
exactly which conditions a client is forced to refetch. Replicache's mutation-ID contract (§2.3)
is the mechanism; ECP's documentation style is the standard of rigor to hold it to.

### 5.5 A single authority for ordering and locks

ECP centralizes lock management on the data server; the data server "does not perform any data
operations that violate the ordering constraints defined by lock semantics." Distributed caches do
not vote — one node is authoritative.

This validates the server-authoritative mutator model over CRDT-style merge for this system: IRIS
is the authority, the client's optimistic mutation is a *prediction*, and disagreement is resolved
by rebasing the client. Given IRIS's typical deployment domains — healthcare, finance — a design
where the server can unconditionally reject a client's optimistic write is not a limitation, it is a
requirement.

### 5.6 Queue during the outage; do not fail the caller

ECP blocks and queues pending requests through an interruption rather than erroring, and replays
them on reconnect. Our offline mutation queue is the same idea moved to the browser, with the
mutation-ID contract providing the idempotency ECP gets from its session state.

### 5.7 What ECP cannot give us — and the one thing it can

**Cannot**:

- It is a **private binary protocol** over TCP between trusted servers. No public specification, no
  JS client, no browser transport, and no path to one.
- It assumes **datacenter-grade latency and reliability** between peers. A phone on cellular is not
  a troubled ECP connection; it is a permanently troubled one.
- It has **no authorization model for untrusted clients**. ECP peers are mutually trusted
  infrastructure; a browser is neither.
- **Block granularity leaks physical layout** to the cache (§5.2) — unacceptable across a public API.
- InterSystems has published **client instability advisories** for ECP; it is a system to configure
  carefully, not one to casually extend.

So: **ECP is not the transport to the browser, and no part of this project should attempt to make
it one.**

**Can** — one concrete, non-obvious reuse: if the shape service is deployed as **multiple
instances** for fanout (which any real deployment will need), running those instances as **ECP
application servers over a single IRIS data server** gives us coherent caching and distributed lock
coordination *for free, as configuration*. Competing sync engines have to build that tier
themselves — Zero self-hosting is largely a story about replica management. We would inherit it.
That is a genuine architectural advantage of building this on IRIS specifically, and it is worth
validating early because it shapes the deployment story we can advertise.

---

## 6. Proposed architecture

```
┌──────────────────── Browser / Edge ────────────────────┐
│  App                                                    │
│   ├── PGlite (WASM Postgres, IndexedDB/OPFS)            │
│   │     ├── live queries          @electric-sql/pglite/live
│   │     └── shape apply           @electric-sql/pglite-sync
│   └── mutation queue + optimistic apply    [ours, small]│
└───────┬──────────────────────────────┬──────────────────┘
        │ GET /v1/shape (read path)    │ POST /push (write path)
        │ Electric-compatible          │ Replicache-style
┌───────▼──────────────────────────────▼──────────────────┐
│  irissync — shape + mutation service   [NEW]            │
│   ├── Shape registry: table, where, columns, handle     │
│   ├── Shape log: offsets, snapshot, live long-poll/SSE  │
│   ├── Mutation router: named server mutators            │
│   ├── lastMutationID tracking per client group          │
│   └── Auth: reuses iris_pgwire.auth                     │
└───────┬──────────────────────────────┬──────────────────┘
        │ ChangeFeed interface         │ SQL (mutators)
┌───────▼──────────────────────────────▼──────────────────┐
│  iris-pgwire  [EXISTING]                                │
│   translation · type mapping · pg_catalog · auth · pool │
└───────┬──────────────────────────────┬──────────────────┘
        │                              │
┌───────▼──────────────────────────────▼──────────────────┐
│  InterSystems IRIS                                      │
│   ├── application tables                                │
│   ├── ^PGWireSync.Log  (outbox, v1)                     │
│   └── journals         (CDC substrate, v2)              │
└─────────────────────────────────────────────────────────┘
       [multi-instance irissync ⇒ ECP app-server tier §5.7]
```

**Read path**: client requests a shape → service serves an initial snapshot from IRIS via
iris-pgwire → switches to `live=true` → the `ChangeFeed` wakes the service on commit → matching ops
are appended to the shape log and returned → `pglite-sync` applies them into local tables →
live queries re-run.

**Write path**: client calls a named mutator → applies optimistically to PGlite → enqueues →
`POST /push` with `clientGroupID`, `clientID`, `mutationID` → server runs the authoritative mutator
against IRIS through iris-pgwire in a transaction → bumps `lastMutationID` → the resulting change
flows back through the read path → client sees confirmation and drops its optimistic layer.

---

## 7. Key decisions and open questions

| # | Decision | Recommendation | Confidence |
|---|---|---|---|
| D1 | Wire protocol for reads | Electric shape protocol, wire-compatible | High — unlocks the whole client ecosystem |
| D2 | Wire protocol for writes | Replicache push semantics (mutation IDs, server-authoritative) | High — DB-agnostic by design |
| D3 | v1 change feed | Trigger outbox behind a `ChangeFeed` interface | Medium-high — journal spike may change the order |
| D4 | Deployment | Sidecar service; embedded-in-IRIS mode as an option | Medium |
| D5 | Client library | Use PGlite + pglite-sync unmodified; ship only a thin mutator/queue package | High |
| D6 | Conflict model | Server-authoritative rebase, no CRDTs | High — §5.5 |
| D7 | Multi-instance fanout | Validate ECP app-server tier early | Medium — differentiator if it holds |

**Open questions requiring spikes**, in priority order:

- **Q1 — Journal tailing throughput.** Can `%SYS.Journal.Record` iteration keep up with a
  realistic write rate, and what is the latency floor? *This is the highest-value unknown.*
- **Q2 — Global→row reverse mapping.** Can we reliably resolve hashed globals (`^EW3K.B3vA.1`) to
  `(table, pk, column)` via `%Dictionary.CompiledStorage`, across IRIS versions and after DDL?
- **Q3 — Trigger overhead.** What does the outbox cost on the write path, measured against the
  constitution's 5 ms budget?
- **Q4 — Client compatibility.** Does unmodified `@electric-sql/pglite-sync` work against our
  endpoint? Conformance-test against Electric's own OpenAPI spec (already fetched).
- **Q5 — Type formatting fidelity.** Shape values must be strings in Postgres display format
  (`bytea_output=hex`, `DateStyle='ISO, DMY'`, `TimeZone=UTC`, `IntervalStyle=iso_8601`,
  `extra_float_digits=1`). How much does `conversions/` already cover, and what does IRIS
  `%PosixTime` / `$HOROLOG` need? (Note the prior art in `specs/040-fix-posixtime-timestamp`.)
- **Q6 — Authorization granularity.** Shapes need row-level authorization. Electric's
  `queryable_columns` allow-list plus a gateway is the intended pattern; how does that compose with
  IRIS row-level security and this repo's existing auth?
- **Q7 — ECP tier viability.** Does the multi-instance ECP story hold under test, and is ECP
  licensed/available in target deployments?

---

## 8. Phased plan

**Phase 0 — Spikes (answer Q1–Q3 before committing).** Journal tailing benchmark; hashed-global
reverse mapping; trigger overhead measurement. Deliverable: a go/no-go on the v1 substrate.

**Phase 1 — Change feed.** `ChangeFeed` interface + outbox implementation + IRIS-side DDL helpers
(`irissync.register_table`). Deliverable: an ordered, replayable op stream with a stable sequence.

**Phase 2 — Shape service, read path.** `GET /v1/shape` with `table`/`offset`/`handle`/`live`,
snapshot + log, `must-refetch` on horizon loss. Conformance-tested against the Electric OpenAPI
spec. Deliverable: unmodified `@electric-sql/pglite-sync` syncing an IRIS table into PGlite.

**Phase 3 — Write path.** `POST /push`, client groups, mutation IDs, named server mutators over
iris-pgwire, offline queue. Deliverable: an offline-capable round trip.

**Phase 4 — Shape expressiveness.** `where` + `params`, `columns`/`queryable_columns`, `replica=full`,
SSE, then authorization.

**Phase 5 — Scale.** Multi-instance fanout, the ECP tier experiment (Q7), journal-based feed
promoted if Phase 0 justified it.

Phases 1–3 are the minimum viable product: one table, syncing live into PGlite, writable offline.

---

## 9. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Journal reverse-mapping proves unreliable across IRIS versions | Kills §4.2 | Outbox is v1; journal is an upgrade, not a dependency |
| Electric changes its protocol under us | Compatibility drift | Pin to a spec version; vendor the OpenAPI file; conformance tests in CI |
| Trigger overhead breaches the 5 ms budget | Forces §4.2 early | Measure in Phase 0, not Phase 3 |
| Chasing a moving local-first ecosystem | Wasted effort | Compatibility is with a *protocol*, not a vendor's runtime — the reason to reject the Zero clone |
| ECP unavailable or unlicensed in target deployments | Loses §5.7 advantage | Treat as an optimization, never a requirement |
| Scope: this is a second product, not a feature | Delivery risk | Ship Phases 1–3 as a separate installable alongside iris-pgwire |

---

## 10. Sources

- [PGlite](https://pglite.dev/) · [electric-sql/pglite](https://github.com/electric-sql/pglite) · [Live Queries](https://pglite.dev/docs/live-queries)
- [Electric HTTP API](https://electric-sql.com/docs/api/http) · [electric-api.yaml (OpenAPI, fetched)](https://github.com/electric-sql/electric/blob/main/website/electric-api.yaml) · [Client development guide](https://electric-sql.com/docs/guides/client-development)
- [Electric joins Databricks](https://www.databricks.com/blog/electric-joins-databricks-bring-wasm-postgres-ai-agent-sandboxes)
- [rocicorp/replicache (archived)](https://github.com/rocicorp/replicache) · [How Replicache Works](https://doc.replicache.dev/concepts/how-it-works) · [Pull Endpoint](https://doc.replicache.dev/reference/server-pull) · [Push Endpoint](https://doc.replicache.dev/reference/server-push) · [Row Version Strategy](https://doc.replicache.dev/strategies/row-version)
- [Zero 1.0 (InfoQ)](https://www.infoq.com/news/2026/06/zero-version-1/) · [Zero docs](https://zero.rocicorp.dev/docs/synced-queries) · [Self-Hosting Zero](https://zero.rocicorp.dev/docs/self-host)
- [Overview of Distributed Caching (ECP)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSCALE_ecp_oview) · [ECP Recovery Process, Guarantees, and Limitations](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSCALE_ecp_recovery) · [Developing Distributed Cache Applications](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSCALE_ecp_develop) · [ECP Client Instability advisory](https://www.intersystems.com/support/product-alerts-advisories/ecp-client-instability/)
- [%SYS.Journal.Record](https://docs.intersystems.com/irislatest/csp/documatic/%25CSP.Documatic.cls?LIBRARY=%25SYS&CLASSNAME=%25SYS.Journal.Record) · [%SYS.Journal.File](https://docs.intersystems.com/irislatest/csp/documatic/%25CSP.Documatic.cls?LIBRARY=%25SYS&PRIVATE=1&CLASSNAME=%25SYS.Journal.File) · [SYS.MirrorDejournal](https://docs.intersystems.com/irislatest/csp/documatic/%25CSP.Documatic.cls?LIBRARY=%25SYS&CLASSNAME=SYS.MirrorDejournal) · [Journaling Overview](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GCDI_journal)
- [Choose an SQL Table Storage Layout (hashed globals)](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSOD_storage) · [Using Triggers](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=GSQL_triggers) · [CDC from IRIS to Kafka (Ideas)](https://ideas.intersystems.com/ideas/DPI-I-343)
