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

**Q2's answer materially changed the feature's risk profile**, and the checklist should say so
plainly: the trigger outbox alone no longer satisfies FR-001, the journal substrate becomes
required, and Phase 0 spikes Q1 and Q2 move from *informative* to *blocking*. If journal
seek-resume proves impossible, this specification is not buildable and Q2 must be reopened. That
is a real possibility, not a formality — no working seek mechanism has been found documented
anywhere.

### Not yet verifiable — unchanged and now more consequential

The Phase 0 spikes have **not been executed** against a live IRIS instance. SC-001, SC-002 and
SC-007 carry targets derived from research, not measurement. With Q1/Q2 now blocking, the spec
cannot progress beyond planning until they run. Re-confirm and adjust these figures once they do.
