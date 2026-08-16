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

- [ ] No [NEEDS CLARIFICATION] markers remain
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

### Outstanding — blocks `/speckit.plan` completion

**Two [NEEDS CLARIFICATION] markers remain**, both scope-defining, both retained deliberately
rather than guessed:

- **Q1 (authorization granularity)** — security/compliance impact. Guessing wrong either ships an
  unusable-in-regulated-settings feature or doubles the size of P1 and P3.
- **Q2 (must non-SQL writes be captured)** — determines whether the unproven journal substrate is
  *required*. If it is, the Q1 spike becomes blocking and the feature may not be buildable as
  specified. No reasonable default exists: option A silently strands direct-global writers, option
  B stakes the feature on unproven capability.

Per the flow's limit of 3 markers, both were kept and all other gaps were resolved with documented
assumptions.

### Not yet verifiable

`research.md` and the Phase 0 spikes are unexecuted against a live IRIS instance. SC-001, SC-002 and
SC-007 carry target numbers derived from the research, not from measurement. They should be
re-confirmed — and adjusted if wrong — once the spikes run.
