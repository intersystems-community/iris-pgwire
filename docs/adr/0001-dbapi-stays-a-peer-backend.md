# ADR-0001: The DBAPI backend stays a peer, not a fallback

- **Status**: Accepted
- **Date**: 2026-09-20
- **Deciders**: Thomas Dyar
- **Relates to**: `specs/051-unified-executor/`, Constitution Principle IV, `CONTEXT.md`

## Context

`PGWIRE_BACKEND_TYPE` selects between two connection adapters: **embedded** (`iris.sql.exec` under
`irispython`, in-process) and **DBAPI** (a pooled DBAPI connection over 1972). They are not
equivalent, and each is better than the other at something that matters:

- **Embedded is the only in-IRIS deployment.** It runs inside the IRIS process with no network hop,
  which is the whole point of shipping this as something you can install into IRIS.
- **DBAPI is the only one that can serve concurrent client transactions.** Measured and recorded in
  `KNOWN_LIMITATIONS.md:366-391`: an IRIS transaction belongs to the _process_, not the thread, so
  under the embedded adapter two frontends share one transaction. That document's own conclusion:
  _"Any deployment serving more than one concurrent client transaction should use the DBAPI
  backend."_
- **Each reaches column types by a different route.** Measured on IRIS 2026.2: the DBAPI cursor's
  `description` reports distinct ODBC codes (`12` varchar, `-7` bit, `4` integer), byte-identical at
  10 rows and 0 rows. The `iris.sql.exec` result object this project used on the embedded side has no
  `_meta` at all and reports `None` for every column type.

  **Corrected 2026-09-20 by 051's R2.** The original claim here — "only DBAPI reports per-column
  types" — was wrong. IRIS reports them on the embedded side too, via
  `%SQL.Statement._Prepare` → `._Metadata` → `.columns.GetAt(i).ODBCType`, and the codes agree with
  DBAPI's exactly. What is true is narrower and still an asymmetry worth naming: the two adapters
  reach the same answer by different routes, and only embedded can Describe without executing. The
  earlier `None`s were a property of the route this project happened to use, not of the platform. The
  Decision below does not move — it rests on transaction ownership and deployment shape, which R5
  re-measured and confirmed.

A recurring temptation is to resolve the asymmetry by demoting one: make DBAPI a fallback used only
when embedded is unavailable, or treat embedded as legacy. Both were considered while planning
feature 051.

## Decision

Both adapters are peers. Neither is a fallback for the other, and neither is deprecated.

Concretely:

1. A defect fixed for one adapter is not fixed until it is fixed for both, or until the difference
   is entered in the divergence ledger as a pin with its measurement.
2. Neither adapter may be the only one a feature works on. A feature that works on one is
   incomplete, per Constitution Principle IV.
3. The choice between them is configuration, and the configuration is legitimate in both
   directions — not a workaround.
4. Where an adapter genuinely cannot support a configuration (a second concurrent transaction on
   embedded; a pool larger than the licence units available), the refusal is loud and happens at
   startup. It is not silently degraded and it is not grounds for demoting the adapter.

## Consequences

**Good.** The two deployment shapes this project exists to serve — inside IRIS and beside it — both
stay first-class. The peer relationship is also what makes the differential corpus meaningful: two
adapters that must agree are an oracle, whereas a primary plus a fallback is just one implementation
with a spare.

**Costs.** Every observable behaviour needs deciding twice or pinning once, which is strictly more
work than picking a winner. Verification requires both adapters to be exercised, and the CE licence
pool — **7 concurrent connections, measured after this ADR was written** — means the container-backed
suites cannot run in parallel. Verification is also intrinsically two-environment: measured, the DBAPI
adapter is not callable under `irispython` and the embedded adapter is not reachable from the host, so
no single process can compare them.

**What this does not license.** Peer status is about the _adapters_, not about duplicated logic
above them. The measured history is that two executor classes drifted — of the last 300 commits
touching either, 15 touched both, 44 only `iris_executor.py`, 3 only `dbapi_executor.py`. Keeping
the backends as peers is the reason to have _one_ implementation above them, not two. That is
feature 051.

## Alternatives rejected

- **Make DBAPI the fallback, embedded the default.** Fixes the vector demo by defaulting users onto
  the adapter with the measured cross-session transaction leak. Trades a visible bug for an
  invisible one, which inverts Principle I.
- **Deprecate embedded, DBAPI only.** Removes the in-IRIS deployment, which is the differentiating
  capability, and forfeits the only oracle that can catch a one-sided fix.
