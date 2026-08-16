# Feature Specification: Local-First Sync for IRIS

**Feature Branch**: `043-local-first-sync` (developed on `claude/iris-pglite-replicache-3ysrqe`)
**Created**: 2026-08-16
**Status**: Draft — 2 clarifications outstanding
**Input**: User description: "Local-first sync for IRIS: an Electric-shape-compatible read path and Replicache-style write path over a transactional outbox change feed, letting PGlite clients hold a live, offline-capable partial replica of IRIS data."

**Research**: [`research.md`](research.md) — landscape analysis, four candidate change-feed
substrates, ECP lessons, and seven open questions. **Phase 0 spikes** in [`spikes/`](spikes/) gate
several requirements below; see Dependencies.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Live partial replica in the client (Priority: P1)

An application developer declares that their app needs a subset of an IRIS table — say, the open
orders for one region. The subset arrives in the app's local database, and from then on stays
current on its own: when someone changes an order in IRIS, the developer's app sees the change
without asking for it and without writing any polling or refresh code.

**Why this priority**: This is the whole premise. A developer who gets only this already has
something they cannot get today — instant local reads and automatic freshness over IRIS data. Every
other story builds on the change feed this one requires.

**Independent Test**: Point a stock local-first client at a declared subset of an IRIS table.
Confirm the initial rows arrive, then change rows directly in IRIS and confirm the client reflects
inserts, updates and deletes without a client-initiated refresh.

**Acceptance Scenarios**:

1. **Given** an IRIS table with existing rows and a declared subset, **When** a client subscribes for
   the first time, **Then** it receives exactly the rows in that subset and an explicit signal that
   it is now current.
2. **Given** a subscribed client, **When** a row is inserted, updated or deleted in IRIS by any
   ordinary application path, **Then** the client reflects that change without polling.
3. **Given** a client that has been disconnected and reconnects, **When** it resumes from its last
   known position, **Then** it receives only the changes it missed, not the whole subset again.
4. **Given** a client whose last known position is older than the retained history, **When** it
   reconnects, **Then** it is told to discard and re-sync, and recovers to a correct state.

---

### User Story 2 — Offline writes that survive and reconcile (Priority: P2)

The developer's app lets a user change data while offline — on a train, in a hospital basement. The
change appears immediately in the UI. When connectivity returns, it reaches IRIS exactly once, and
if IRIS rejects or alters it, the UI corrects itself rather than silently diverging.

**Why this priority**: Offline reads alone serve dashboards; offline writes are what make the
category worth adopting. It depends on P1's feed to confirm writes back to the client.

**Independent Test**: Take a client offline, perform several writes, confirm they display
immediately, restore connectivity, and verify each write lands in IRIS exactly once — including
after a forced client restart mid-queue.

**Acceptance Scenarios**:

1. **Given** an offline client, **When** the user performs a write, **Then** it is visible locally
   immediately and retained across an app restart.
2. **Given** a queue of offline writes, **When** connectivity returns, **Then** each is applied to
   IRIS exactly once, in the order the user made them.
3. **Given** a write the server rejects (validation, permission, conflict), **Then** the client's
   optimistic version is withdrawn and the authoritative state is shown instead.
4. **Given** a write that is retried because its response was lost, **Then** it is not applied twice.

---

### User Story 3 — Declaring the subset that syncs (Priority: P3)

The developer narrows what syncs: only certain rows, only certain columns. Sensitive or irrelevant
data never leaves IRIS, and the client stays small on a phone.

**Why this priority**: P1 is demonstrable with whole small tables. Filtering is what makes the
feature usable on real tables and is a precondition for the authorization story.

**Independent Test**: Declare a subset with a row filter and a column projection; confirm excluded
rows and columns are absent from the client, and that a row edited *into* or *out of* the filter
appears or disappears accordingly.

**Acceptance Scenarios**:

1. **Given** a subset with a row filter, **When** a client subscribes, **Then** only matching rows
   arrive.
2. **Given** a subscribed client, **When** a row is edited so it newly matches the filter, **Then**
   it arrives as an addition; when edited so it no longer matches, **Then** it is removed.
3. **Given** a subset with a column projection, **When** rows arrive, **Then** unlisted columns are
   absent — including from change notifications, not only the initial load.

---

### User Story 4 — Only authorized data reaches the client (Priority: P4)

An administrator constrains what any client may request, so a developer's subset declaration cannot
be used to pull data that user is not entitled to see.

**Why this priority**: Required before any deployment carrying regulated data, but it presupposes
P3's filtering machinery. Sequenced last, not optional.

**Independent Test**: Attempt to subscribe to a subset outside the caller's entitlement and confirm
refusal; confirm an entitled caller receives exactly their permitted rows.

**Acceptance Scenarios**:

1. **Given** a caller with limited entitlement, **When** they request a subset beyond it, **Then**
   the request is refused rather than silently narrowed.
2. **Given** a subscribed client, **When** the caller's entitlement is revoked, **Then** they stop
   receiving further changes for the affected data.

---

### Edge Cases

- **A client is offline longer than history is retained.** It must be told to discard and re-sync
  rather than resuming into a gap. Silent gaps are the worst failure mode here — a client that
  believes it is current but has missed changes.
- **The subset definition changes** (filter or columns edited) while clients are subscribed. Clients
  must converge on the new definition rather than keeping a stale mixture.
- **A write path bypasses the change feed.** Bulk loads and non-SQL writes may not raise change
  events (see Clarification Q2). Any such path must either be captured or be documented as
  unsupported — never silently dropped.
- **The same user has several devices**, each with its own queue. Writes from all of them must
  converge, and each device must learn the outcome of the others' writes.
- **Two clients edit the same row while both offline.** IRIS is authoritative; the losing client's
  optimistic state must be withdrawn, not merged.
- **The client's local storage is evicted** by the browser mid-session.
- **Change volume outruns a client's connection.** Slow clients must not degrade IRIS or other
  clients.
- **The sync service restarts** with clients mid-stream; positions must remain valid.
- **A row's primary key is reused** after deletion.

---

## Requirements *(mandatory)*

### Functional Requirements

**Change capture**

- **FR-001**: System MUST capture inserts, updates and deletes to registered IRIS tables as an
  ordered, replayable stream of row-level change events.
- **FR-002**: Each change event MUST carry enough information to apply it to a replica: the
  operation, the row's identity, and the affected column values.
- **FR-003**: Change events MUST be ordered consistently with the order the changes committed in
  IRIS, and MUST become visible to subscribers only after the originating transaction commits.
- **FR-004**: A change MUST NOT be recorded if its transaction rolls back.
- **FR-005**: System MUST expose a durable position marker such that a subscriber presenting a
  previous position receives exactly the changes committed since it.
- **FR-006**: System MUST retain change history for a configurable window, and MUST tell a
  subscriber whose position predates the window to discard and re-sync rather than serving a gap.
- **FR-007**: Registering a table for capture MUST be an explicit, reversible, per-table act.

**Read path**

- **FR-008**: Developers MUST be able to declare a subset of a registered table by row filter and
  column projection.
- **FR-009**: A subscribing client MUST receive the current contents of its subset, followed by an
  explicit signal that it has caught up.
- **FR-010**: After catching up, a client MUST receive subsequent changes without issuing repeated
  requests on a timer.
- **FR-011**: A client MUST be able to resume from a stored position after disconnection and receive
  only what it missed.
- **FR-012**: A row edited into or out of a subset's filter MUST be delivered as an addition or a
  removal respectively.
- **FR-013**: The read path MUST be consumable by existing local-first client libraries without
  modifications to those libraries (see Assumptions).

**Write path**

- **FR-014**: Clients MUST be able to submit writes while disconnected and have them retained across
  application restarts.
- **FR-015**: Submitted writes MUST be applied to IRIS **exactly once**, even when a client retries
  because it did not observe the outcome.
- **FR-016**: Writes from one client MUST be applied in the order that client submitted them.
- **FR-017**: The server MUST be authoritative: it MUST be able to reject or alter a submitted
  write, and the client MUST converge on the server's result.
- **FR-018**: A client MUST be able to determine which of its writes have been confirmed.
- **FR-019**: Each write MUST be applied within a single IRIS transaction — fully or not at all.

**Operational**

- **FR-020**: System MUST record change-capture overhead and sync latency so both can be verified
  against Success Criteria.
- **FR-021**: System MUST remain available to other clients when one client is slow, stalled or
  abandoned.
- **FR-022**: Administrators MUST be able to see which tables are registered, which subsets are
  active, and how far each is behind.
- **FR-023**: System MUST refuse a subset request that a caller is not entitled to, rather than
  narrowing it silently.
- **FR-024**: Data excluded by a column projection MUST NOT leave IRIS through this feature.

### Key Entities

- **Registered Table**: an IRIS table opted in to change capture. Knows its identity columns and
  whether capture is active.
- **Change Event**: one committed row-level change — operation, row identity, values, and a position
  in the ordered stream.
- **Position Marker**: an opaque, durable, monotonic marker a client stores and presents to resume.
- **Subset Definition**: a named declaration of what a client may sync — table, row filter, column
  projection. Has an identity that changes when the definition changes.
- **Subscription**: one client's live attachment to a subset, holding its current position.
- **Pending Write**: a client-submitted change awaiting application, carrying an identity that makes
  retries safe and an ordering within its originating client.
- **Client Identity**: distinguishes devices and groups those belonging to one user, so write
  ordering and confirmation are tracked per device.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A change committed in IRIS is visible in a connected client in **under 1 second** at
  the 95th percentile, on a local network with 100 subscribed clients.
- **SC-002**: Registering a table for capture adds **under 1 millisecond** to a write, and in no
  case more than the project's 5 ms overhead budget.
- **SC-003**: A developer can take an unmodified stock local-first client, point it at IRIS, and
  have a table subset syncing **within 30 minutes**, using only written documentation.
- **SC-004**: A client offline for **up to 7 days** resumes without a full re-sync, receiving only
  what it missed.
- **SC-005**: **100%** of writes submitted while offline are applied exactly once — verified across
  at least 1,000 writes including forced restarts and duplicated submissions.
- **SC-006**: **Zero** silent divergences: in every test where a client's view differs from IRIS, the
  client is either corrected automatically or explicitly told to re-sync. No test may end with a
  client that believes it is current while holding stale data.
- **SC-007**: A single sync service supports **at least 100 concurrent subscribed clients** without
  IRIS write throughput degrading more than 10% against an unsubscribed baseline.
- **SC-008**: A subset's column projection is honoured in **100%** of delivered events — no excluded
  column value appears in any payload, initial or incremental.
- **SC-009**: Recovery from a forced sync-service restart completes with **no client requiring a full
  re-sync**, provided each client's position is inside the retention window.

---

## Assumptions

- **Compatibility over invention (FR-013)**: the read path targets an existing, documented sync
  protocol so stock clients work unmodified, rather than a bespoke protocol requiring a bespoke
  client. `research.md` §2.2 identifies the target; that analysis is assumed to hold.
- **The server is authoritative; no automatic merge.** Conflicts resolve by the server winning and
  the client rebasing (`research.md` §5.5). Field-level or CRDT merge is out of scope.
- **History retention defaults to 7 days**, consistent with SC-004, and is configurable.
- **Clients are untrusted.** Every subset request and write is authorized server-side regardless of
  what the client claims.
- **A client may hold a subset of a table, not a subset of a database.** Cross-table transactional
  consistency in the client is not promised in this feature.
- **Initial scale target is 100 concurrent clients per service instance**; multi-instance fanout is
  designed for but not delivered here.
- **Text-shaped and numeric data are in scope**; large binary streams are not.

---

## Dependencies

- **A running IRIS instance is required for all verification.** There is no mock IRIS and none will
  be introduced — the project tests against real systems (`tests/conftest.py`: "NO MOCKS —
  everything tested against real systems"). Every requirement above is verified against a live
  instance or it is not verified.
- **Phase 0 spikes gate parts of this spec.** Q3 (write-path cost) gates SC-002. Q1 (resumable
  journal tailing) and Q2 (global-to-row resolution) gate whether FR-001 can be satisfied for
  non-SQL writes — see Clarification Q2 below. The spikes exist in [`spikes/`](spikes/) but **have
  not been executed**; no result in this spec is evidence-backed until they run.
- Existing iris-pgwire capability is assumed for SQL translation, type formatting, catalog
  introspection and authentication (`research.md` §3).

---

## Out of Scope

- Syncing IRIS data to anything other than a client-side replica (no server-to-server replication,
  no data warehouse feed).
- Automatic conflict merge or CRDT semantics.
- Schema migration of the client replica.
- Syncing vector or large-object columns.
- Replacing or modifying the PostgreSQL wire protocol server itself.

---

## Clarifications Needed

### Q1: Authorization granularity for the first release

**Context**: FR-023, FR-024 and User Story 4. `research.md` §7 Q6 leaves this open.

**What we need to know**: Must the first release enforce **row-level** entitlement on subsets, or is
**table-level** sufficient with row-level deferred?

| Option | Answer | Implications |
|--------|--------|--------------|
| A | Table-level only in v1 | Fastest to ship. Suitable for trusted-tenant or single-user deployments only. Blocks regulated-data pilots. |
| B | Row-level required in v1 | Deployable in regulated settings from day one. Adds an authorization layer to every subset request and every change event, materially enlarging P1 and P3. |
| C | Table-level in v1, row-level as a hard gate before any production use | Ships early, keeps the regulated door open, and makes the constraint explicit rather than implied. |
| Custom | Provide your own answer | — |

**Your choice**: _[awaiting]_

---

### Q2: Must non-SQL writes be captured?

**Context**: FR-001 and the "write path bypasses the change feed" edge case. `research.md` §4
establishes that a trigger-based feed sees SQL writes only; direct global writes and some bulk paths
bypass it. Capturing those requires the journal-based substrate, whose feasibility is unproven
(Q1 spike) and which carries a bulk-PHI exposure concern (`research.md` §4.5).

**What we need to know**: Is capturing non-SQL writes a **requirement** of this feature, or may they
be documented as unsupported?

| Option | Answer | Implications |
|--------|--------|--------------|
| A | SQL writes only; non-SQL documented as unsupported | Unblocks the whole feature immediately. Any application writing globals directly gets silently stale clients unless it adopts the SQL path. |
| B | All writes must be captured | Makes the Q1 journal spike **blocking**: if seek-resume proves impossible, the feature cannot be built as specified. Also inherits the PHI exposure question. |
| C | SQL writes in v1, with a documented detection mechanism that warns when a registered table is modified outside the captured path | Ships on the outbox while making the gap loud instead of silent. Costs a consistency check. |
| Custom | Provide your own answer | — |

**Your choice**: _[awaiting]_
