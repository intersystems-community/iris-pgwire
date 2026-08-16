# Specification Quality Checklist: Local-First Sync for IRIS

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-16
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Validation Notes

### Iteration 1 — issues found and fixed

1. **Implementation detail leaked into the spec title and requirements.** The originating
   description named specific technologies (Electric shapes, Replicache, PGlite, outbox). Rewrote
   the spec to describe *what* syncs and *why*, moving all named technology into `research.md` and
   the Assumptions section. FR-013 now states the compatibility requirement without naming the
   protocol.
2. **Success criteria were written as system internals.** Original drafts included "shape endpoint
   responds in under 200 ms" and "outbox trigger under 1 ms". Restated as user-visible outcomes —
   SC-001 (change visible in a client), SC-003 (developer time-to-first-sync). SC-002 retains a
   millisecond figure deliberately: it is a constitutional budget this feature must not breach, and
   it is measurable without reference to any implementation.
3. **"Never silently stale" was implied but not required.** Promoted to SC-006 as an explicit
   zero-tolerance criterion, and reinforced in the edge cases. This is the failure mode that
   matters most in this feature and it was not previously testable.
4. **Missing dependency on real-IRIS verification.** Added to Dependencies, stating plainly that no
   mock IRIS exists or will be introduced, and that no criterion is evidence-backed until the
   Phase 0 spikes run.

### Iteration 2 — clarifications resolved 2026-08-16

Both markers were answered by the project owner; the spec was updated and re-validated.

- **Q1 (authorization granularity) → table-level v1, row-level as a hard release gate.** FR-023
  updated. User Story 4 is now a named gate rather than a P4 backlog item.
- **Q2 (non-SQL writes) → all writes must be captured.** FR-001 rewritten, FR-001a and FR-025
  added.

### Iteration 3 — Q2 reversed the same day

Q2 was first answered "all writes must be captured", then reversed to "SQL path only, with drift
detection". Both are recorded in the spec rather than the first being erased.

The reversal was correct and the reasoning generalises: mandating capture of non-SQL writes would
have forced a WAL-equivalent substrate (journal CDC) — the exact dependency that makes Electric and
PowerSync unusable against IRIS. Selecting a sync design *because* it avoids database-level
replication, then adding a requirement that reimposes it, cancels the reason for the choice.

Net effect on risk: **materially reduced.** The trigger outbox is sufficient; spikes Q1 and Q2 drop
from blocking to informative; the bulk-PHI exposure of `research.md` §4.5 is avoided rather than
mitigated. The only added mechanism is FR-001a's drift detection, which exists to satisfy SC-006.

### Not yet verifiable

The Phase 0 spikes have **not been executed** against a live IRIS instance — none was reachable in
the authoring environment (container registry blob hosts blocked by egress policy). SC-001, SC-002
and SC-007 carry targets derived from research, not measurement. Q3 gates SC-002 and should run
before implementation begins. No mock IRIS will be introduced to work around this (Constitution
Principle II).
