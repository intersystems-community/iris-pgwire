# Requirements Quality Checklist: Catalog Emulation as IRIS Views

**Purpose**: Unit tests for the *requirements* of feature 044 — do they say enough, clearly enough,
consistently enough, to be implemented and verified? This checks what is **written**, not whether the
code works.
**Created**: 2026-08-17
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [tasks.md](../tasks.md)
**Prompted by**: `/speckit.analyze`, which found 82% requirement coverage, a scope boundary the
implementation had already crossed, and a plan that referenced this file without it existing.

**Focus** (from the request): coverage of SC-006 / SC-008 / FR-013 / FR-014; the FR-015 scope
boundary added 2026-08-17; measurability of the success criteria.
**Depth**: gate — this feature is mid-flight with Phase 3 unstarted, and the constitution makes an
unjustified violation a merge blocker.
**Audience**: reviewer, at each phase exit.

---

## Requirement Completeness

- [ ] CHK001 Is a requirement stated for every success criterion, so that no SC depends on an
      unwritten requirement? [Completeness, Spec §Success Criteria]
- [ ] CHK002 Are requirements defined for the catalog tables Phase 3 and 4 will add — `pg_constraint`,
      `pg_index`, `pg_type`, `pg_attrdef`, `pg_enum`, `pg_extension` — beyond naming them as entities?
      **Partially closed 2026-08-17**: `pg_constraint` is now specified as FR-016…FR-021, written from
      the query a client actually sends rather than from the whole PostgreSQL catalog. `pg_index` and
      the Phase 4 tables remain unspecified. [Gap, Spec §Key Entities]
- [ ] CHK003 Does any requirement state what a *partially migrated* catalog must do when a query
      joins a view-backed table to a handler-backed one? FR-010 permits coexistence and FR-011
      demands one path per table, but neither covers a query spanning both. [Gap, Spec §FR-010/011]
- [ ] CHK004 Is the required behaviour written down for a catalog table with **no** view and **no**
      handler? **Now demonstrated, not hypothetical** (2026-08-17): with `pg_constraint` served by a
      view, `prisma db pull` reaches `pg_views`, which has neither, and the router's fallback answers
      it with **pg_class's 32 columns** — so the client fails on `relfrozenxid` typed `xid` exactly as
      it did for constraints. The wrong-column-set defect belongs to this gap, not to any one table.
      T015a. [Gap, Spec §Edge Cases]
- [ ] CHK005 Are requirements stated for the read-only guarantee — what happens when a client
      attempts a catalog **write**? Out of Scope says the surface is read-only but no requirement says
      how an attempt is answered. [Gap, Spec §Out of Scope]
- [ ] CHK006 Is there a requirement covering *who* installs the catalog objects and *when*, or is
      startup installation only described in the plan? [Traceability, Plan §4 vs Spec §FR-009]

## Requirement Clarity

- [ ] CHK007 Is "match what PostgreSQL clients expect" in FR-004 defined against a named authority
      (a PostgreSQL version's `pg_catalog` column list), or left to the reader? [Clarity, Spec §FR-004]
- [ ] CHK008 Does FR-004 say whether "types" means the wire type OID, the declared IRIS type, or
      both? T011g turned on exactly this distinction and the requirement does not disambiguate it.
      [Ambiguity, Spec §FR-004]
- [x] CHK009 **Resolved 2026-08-17.** "Cannot be satisfied" was the ambiguous phrase and is gone.
      FR-008 now turns on whether the query can be *evaluated*, split into FR-008a/b/c, measured
      against PostgreSQL 15. [Ambiguity, Spec §FR-008]
- [ ] CHK010 Is "fail loudly and early" in FR-009 quantified — refuse to start, or start degraded and
      log? [Clarity, Spec §FR-009]
- [ ] CHK011 Does FR-015's "well enough for a catalog query to reach IRIS and be answered" state a
      test for *whether a construct is in scope*, or does "bounded by evidence" leave it to
      judgement? [Ambiguity, Spec §FR-015]
- [ ] CHK012 Is "identical" in FR-012 defined — same rows, same column order, same type OIDs, same
      errors? [Clarity, Spec §FR-012]

## Requirement Consistency

- [ ] CHK013 Do FR-015 and Out of Scope now agree, after the 2026-08-17 amendment, on which
      translation work belongs to this feature? [Consistency, Spec §FR-015 vs §Out of Scope]
- [ ] CHK014 Is the vocabulary for the OID routine consistent across spec, plan and code, now that
      "SqlProc" has been replaced by an installed SQL function? [Consistency, Plan §Design 1]
- [ ] CHK015 Do the spec's Assumptions still hold as written, given the `.cls` approach they were
      verified against has been replaced? [Consistency, Spec §Assumptions]
- [x] CHK016 **Resolved 2026-08-17** by FR-008d: no conflict. Principle I constrains *our* behaviour
      — an error surfaced as an error satisfies it, whatever its origin. [Constitution §I, Spec §FR-008d]
- [ ] CHK017 Are the phase exits in plan.md and the task groupings in tasks.md consistent after
      Phase 2b and Phase 3.5 were inserted? [Consistency, Plan §Phases vs Tasks]

## Acceptance Criteria Quality (Measurability)

- [ ] CHK018 Is SC-001's "100% of the user tables present" measurable without ambiguity about which
      tables count — user tables only, or views and system tables too? [Measurability, Spec §SC-001]
- [ ] CHK019 Does SC-004's "measured across the conformance suite" name a suite that exists? No such
      suite is identified in plan.md or tasks.md. [Measurability, Gap, Spec §SC-004]
- [ ] CHK020 Is SC-005's "two independent ORMs" specific enough to know when it is met — are the two
      named, and does Prisma count as one? [Clarity, Spec §SC-005]
- [ ] CHK021 Is SC-007's "50-table schema" defined enough to reproduce — 50 tables of what shape, how
      many columns, on what hardware? [Measurability, Spec §SC-007]
- [ ] CHK022 Does SC-008's "passes unchanged" state a baseline commit or test count, so "unchanged"
      is checkable rather than remembered? [Measurability, Spec §SC-008]
- [ ] CHK023 Is SC-009's 25% share expressed against a stated query shape, given the measured cost
      varies 7× between a plain and a paren-heavy statement? [Measurability, Spec §SC-009]
- [ ] CHK024 Is every success criterion traceable to at least one task, and every task to at least
      one requirement? `/speckit.analyze` measured 82% and 7 unmapped tasks before FR-015 was added.
      [Traceability]

## Scenario Coverage

- [ ] CHK025 Are requirements written for the **primary** flow (introspect a populated schema)?
      [Coverage, Spec §US1]
- [x] CHK026 **Resolved 2026-08-17.** No longer a conflict: US1 scenario 3 is an evaluable query
      with no matching rows, so FR-008b requires zero rows and the scenario is consistent as written.
      [Coverage, Spec §US1 vs §FR-008b]
- [ ] CHK027 Are requirements written for the **exception** flow where the catalog objects cannot be
      created? [Coverage, Spec §FR-009]
- [ ] CHK028 Are **recovery** requirements written — if installation fails midway, what state is the
      catalog left in, and is a partially installed catalog detectable on the next start?
      [Gap, Recovery]
- [ ] CHK029 Are requirements written for a client that connects **during** installation?
      [Gap, Coverage]
- [ ] CHK030 Is the SC-006 live-catalog scenario stated as a requirement, not only as a success
      criterion and a user story? FR-003 implies it; nothing requires the no-restart property
      explicitly. [Gap, Spec §SC-006, §FR-003]

## Edge Case Coverage

- [ ] CHK031 Are requirements defined for names differing only by case, given IRIS and PostgreSQL
      differ here — and does "differing only by case" cover schema names, table names, or both?
      [Coverage, Spec §Edge Cases]
- [ ] CHK032 Is the required treatment of an IRIS object with no PostgreSQL equivalent stated as
      "omitted" or "mapped", rather than offering both without a rule? [Ambiguity, Spec §Edge Cases]
- [ ] CHK033 Are requirements defined for identifier collision — what the system does when two
      objects hash to the same OID, as opposed to requiring that they do not? [Coverage, Spec §Edge Cases]
- [ ] CHK034 Are requirements defined for a catalog object whose name exceeds PostgreSQL's identifier
      length, or for non-ASCII identifiers? [Gap, Edge Case]
- [ ] CHK035 Are requirements defined for an empty-string value where a client expects NULL, given
      IRIS spells the empty string as `$CHAR(0)`? [Gap, Edge Case]

## Non-Functional Requirements

- [ ] CHK036 Is the performance requirement expressed for both the introspection path (SC-007) and
      the per-statement translation path (SC-009), so neither is left implicit? [Completeness, Spec §SC-007/009]
- [ ] CHK037 Are requirements stated for the privileges the deployment needs, precisely enough to
      check before install — `CREATE VIEW` in a `pg_catalog` schema, `CREATE FUNCTION` in a `PGWire`
      schema? Dependencies says "privileges to create schema objects". [Clarity, Spec §Dependencies]
- [ ] CHK038 Are observability requirements stated for the catalog path, given Principle V requires
      monitoring across 100% of the request path? [Gap, Constitution §V]
- [ ] CHK039 Are concurrency requirements stated — two sessions introspecting while a third installs
      or alters the catalog? [Gap, Non-Functional]
- [ ] CHK040 Is a security requirement stated about what the catalog surface exposes, given it
      reveals every table name in the namespace to any authenticated client? [Gap, Non-Functional]

## Dependencies & Assumptions

- [ ] CHK041 Is each Assumption marked with how it was validated, and are the ones marked "verified
      by spike" traceable to a named probe? [Traceability, Spec §Assumptions]
- [ ] CHK042 Is the dependency on `schema_mapper.py`'s `public` ↔ IRIS-schema mapping stated as a
      requirement on that mapping's behaviour, or only as a file reference? Two defects came from this
      mapping. [Clarity, Spec §Dependencies]
- [ ] CHK043 Is the minimum IRIS version an explicit dependency? The plan names 2026.2 as the test
      platform; `JSON_TABLE`-based alternatives would imply 2024.1+. [Gap, Plan §Technical Context]
- [ ] CHK044 Is the assumption that "introspection is a development-time operation" recorded as a
      constraint others can rely on, given it justifies the latency trade-off? [Assumption, Spec §Assumptions]

## Ambiguities & Conflicts to Resolve

- [x] CHK045 **Resolved 2026-08-17.** Neither wins; the requirements had failed to draw a
      distinction. **Empty is an answer, error is a refusal, and the question's shape decides —
      never the row count.** Grounded in what real PostgreSQL 15 does rather than in preference
      (`spikes/probe_pg_empty_vs_error.py`): 5/5 evaluable-but-non-matching shapes return empty,
      5/5 unanswerable shapes error. The enforceable half is FR-008c — pgwire must never *fabricate*
      an empty result, which is what all three original defects did. [Conflict, resolved]
- [x] CHK046 **Resolved 2026-08-17: passing it through is acceptable** (FR-008d). Two things the
      decision does *not* license, both now written down: it does not excuse a **wrong answer**
      (T011d returns 0 rows where 5 is correct when untranslated — measured, so it stays), and it
      does not excuse **misattributing blame** — pgwire reported an IRIS fatal with the same
      SQLSTATE 42000 as the client's own bad SQL. FR-008e and T027, both now closed: 9/9 over the
      wire, 13/13 on the embedded backend. The blame half turned out to be worse than recorded here
      — the query path reported `08000` (connection failure), not `42000` — and backend-dependent:
      the embedded backend carries no SQLCODE at all. [Resolved]
- [ ] CHK047 Resolve CHK011: state the admission test for FR-015 scope, so the next construct does
      not need a judgement call. [Ambiguity, Spec §FR-015]
- [ ] CHK048 Is a requirement/AC ID scheme established and used consistently — FR-*, SC-*, T* are in
      use, but tasks T011a–T011g use a suffix convention no requirement references. [Traceability]

---

## Notes

Items CHK019, CHK024, CHK030, CHK036 correspond directly to the coverage gaps `/speckit.analyze`
found and to the tasks added for them (T023–T026). The rest are new to this pass.

CHK045 and CHK046 are the two that most deserve a decision before Phase 3: both are cases where the
requirements as written point in two directions, and Phase 3 will hit them (a constraints query on a
table with no constraints is *legitimately* empty).
