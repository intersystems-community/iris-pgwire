# CONTEXT.md

Domain glossary for iris-pgwire. Names defined here are the names used in specs, ADRs, commit
messages and code. A term enters this file when a module is named after it, so that the name means
one thing across the repo.

Architecture vocabulary (module, interface, implementation, depth, seam, adapter, leverage,
locality) is defined in the `codebase-design` skill and deliberately not redefined here.

## Wire and protocol

- **Frontend** — the PostgreSQL client. Anything speaking the v3 wire protocol at us: `psql`,
  `psycopg`, `asyncpg`, Prisma, SQLAlchemy, a BI tool.
- **Statement** — one unit of SQL as the frontend sent it, before any rewriting. The thing a
  divergence is measured about.
- **Command tag** — the string returned in `CommandComplete` (`SELECT 3`, `INSERT 0 1`). Part of
  observable behaviour, so subject to the divergence ledger.

## Statement lifecycle

These five terms name the phases the core module owns. They are sequential and each has a defined
input and output.

- **Preparation** — turning a frontend statement into a **prepared statement**. Covers
  normalisation, translation, identifier mapping, vector-operator rewriting, placeholder
  translation and catalog routing. Preparation is one path; there is not a preparation-for-embedded
  and a preparation-for-DBAPI.
- **Prepared statement** — the outcome of preparation. Either _answered locally_ (the core can
  produce the result itself: a catalog view, a canned reply, a refusal) or _sent to the adapter_
  (IRIS-executable SQL plus ordered parameters). "Answered locally" is why catalog routing does not
  need to call back into the front door.
- **Raw result** — what a **connection adapter** hands back, in the driver's own terms: rows,
  driver-reported per-column types (or the declared absence of them), affected-row count, and the
  unparsed error if one occurred. Deliberately narrow: an adapter may not invent a type it was not
  told, and `driver_types = None` is a legitimate answer, not a failure.
- **Materialisation** — turning a raw result into rows plus **column metadata**. One
  implementation, reached by every adapter. (Feature 045's original scope.)
- **Column metadata** — per output column: name, PostgreSQL type OID, size, type modifier, format
  code. What `RowDescription` carries and what the `DataRow` encoding must match. Its **metadata
  source** is the statement text, the driver's report, or — last and only when nothing else
  settles it — the row values.

## Backends and adapters

- **Backend** — a user-facing configuration choice, selected by `PGWIRE_BACKEND_TYPE`. Not a class
  and not a code path. Constitution Principle IV: _"Backend selection MUST be configuration, never
  a code fork."_
- **Connection adapter** — the implementation behind a backend: it owns a connection to IRIS and
  can execute prepared SQL, returning a raw result. **Exactly two exist**: **embedded**
  (`%SQL.Statement` / `iris.sql.exec` under `irispython`, in-process) and **DBAPI** (a pooled DBAPI
  connection over 1972). An adapter contains driver knowledge and nothing else; no SQL rewriting, no
  type decisions, no protocol.
  - `iris.connect` and `iris.dbapi.connect` are the **same adapter under two names** — measured, 29
    of 29 observations identical. "External" is not a third adapter, and code that treats it as one is
    a duplicate to delete.
  - The two adapters are available in **disjoint environments**: under `irispython` neither factory is
    callable, so DBAPI cannot be reached from an embedded process, and embedded cannot be reached from
    the host. Any comparison between them is therefore a two-environment exercise.
- **Capability** — a fact about an adapter that the core must respect and cannot work around.
  Declared, not discovered. Current set: `per_session_transactions` (false on embedded, because an
  IRIS transaction belongs to the process, not the thread), `cross_session_dirty_reads` (true on
  both), `max_concurrent_sessions` (1 on embedded; on DBAPI the smaller of the pool size and the
  licence, measured at 7 on CE), `isolation_levels_accepted`, `isolation_levels_in_force` (**empty on
  both**), `reports_column_types` (true on both), `describe_without_execute` (true on embedded only)
  and `available_under_irispython` (false on DBAPI). A configuration the declared capabilities cannot
  support is refused at startup, loudly, rather than degraded — the same rule that rejects L2 `<->`
  and refuses `REPEATABLE READ`.
  - `..._accepted` and `..._in_force` are separate because IRIS accepts levels it does not enforce.
    Collapsing them is the mistake that produced a retracted isolation model once already.

## Authentication

- **Login user** — the IRIS user whose name and password a client presents to connect. It
  establishes that the client knows that user's password. It does not decide what the session may
  do: that is the **service account**'s.
- **Service account** — the IRIS user the server executes every statement as, whichever login user
  connected. Configured by the operator; never chosen by a client. Every login user therefore has
  the service account's privileges, whatever their own.
- **Authentication mode** — either **password** (the default: a client must prove a login user's
  password) or **trust** (no proof at all). Trust is an explicit opt-in for local development and
  is never what an unconfigured server does.
- **Allowed login users** — the login users permitted to connect. Unless the operator lists others,
  the service account alone. A listed set replaces that default; it does not extend it.
- **Password check** — verifying a login user's password by logging in to IRIS with it. IRIS is the
  only store of users and passwords; the server keeps no copy and no verifier. A check has three
  answers, not two: accepted, denied, and **could not check**. An unreachable IRIS is never a
  wrong password.

## Verification

- **Divergence** — any observable difference in behaviour between two connection adapters for the
  same statement.
- **Divergence ledger** — the record of every known divergence, each classified as a **pin** (kept
  deliberately, with the measurement that forces it), a **fix** (a defect with an owner), or **no
  reference answer** (an IRIS construct PostgreSQL cannot adjudicate — `SELECT TOP`, `%ID`,
  `$SYSTEM.`, `SQLUser.` schema references, `VECTOR(...)`). Unclassified divergence is a test failure.
  Constitution Principle IV requires agreement or a recorded reason; the ledger is where the reason
  lives.
- **Differential corpus** — a fixed set of statements executed through every connection adapter,
  with the raw results compared. It runs below the wire protocol, so it is cheap, and it is the
  oracle every later refactor is gated on.
- **Reference** — a real pgvector-enabled PostgreSQL 16, which decides what correct means wherever it
  has an opinion (type OIDs, `RowDescription` shape, empty-string versus NULL, row counts, command
  tags). Where PostgreSQL has no answer for an IRIS construct, the incumbent embedded behaviour is the
  reference and the entry is classified `no reference answer`, not `pin`. The image must carry pgvector
  or the `<=>` operator falls out of the reference's opinion for an avoidable reason.
