<!--
SYNC IMPACT REPORT
==================
Version change: [unfilled template] → 1.0.0
Bump rationale: MAJOR (1.0.0). First ratified constitution. The file previously
  contained only unfilled placeholder tokens while CLAUDE.md cited it as the
  authoritative source of project principles. This establishes the baseline.

Principles established (all derived from existing practice, none invented):
  - I.   Protocol Fidelity              (src/iris_pgwire/constitutional.py: PROTOCOL_FIDELITY)
  - II.  Test-First Development         (constitutional.py: TEST_FIRST_DEVELOPMENT; tests/conftest.py)
  - III. Phased Implementation          (constitutional.py: PHASED_IMPLEMENTATION)
  - IV.  IRIS Integration               (constitutional.py: IRIS_INTEGRATION)
  - V.   Production Readiness           (constitutional.py: PRODUCTION_READINESS)
  - VI.  Vector Performance             (docs reference "Principle VI (Vector Performance)"; CLAUDE.md)

Sections added:
  - Technical Constraints (package naming, container reload, vector operator support)
  - Development Workflow & Quality Gates
  - Governance

Sections removed: none (template placeholders replaced in place)

Numeric thresholds are transcribed from ComplianceRequirement definitions in
src/iris_pgwire/constitutional.py rather than chosen here, so the document and
the runtime compliance checker cannot drift apart silently.

Templates requiring updates:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate now has
     concrete gates to evaluate against (previously "[Gates determined based on
     constitution file]" with no such file content)
  ✅ .specify/templates/spec-template.md — no change required; constitution adds
     no new mandatory spec sections
  ✅ .specify/templates/tasks-template.md — no change required; principle-driven
     task types (E2E-first, real-IRIS verification) already expressible
  ⚠  CLAUDE.md — accurate as written; it names these principles and now resolves
     to real content. No edit required, re-verify on next amendment.

Deferred items:
  - TODO(RATIFICATION_DATE): recorded as 2026-01-21, the repository's first
    commit, because the principles were encoded in constitutional.py from early
    in the project's life but no explicit adoption date is recorded anywhere.
    Correct this if the true adoption date is known.
-->

# IRIS PGWire Constitution

## Core Principles

### I. Protocol Fidelity

The server MUST implement PostgreSQL wire protocol v3 faithfully. Compliance is measured at
100% — partial protocol support is a defect, not a limitation.

Clients MUST NOT need to know they are talking to IRIS. Any behaviour that requires a client
to special-case this server is a violation, and a client workaround is never an acceptable
substitute for a protocol fix.

Where IRIS genuinely cannot express a PostgreSQL construct, the server MUST return a proper
protocol-level error. It MUST NOT silently degrade, silently succeed, or return a plausible
wrong answer. Unsupported is an honest answer; wrong is not.

*Rationale*: The entire value of this project is that unmodified PostgreSQL clients work. Every
fidelity compromise transfers cost from this codebase to every downstream user, invisibly.

### II. Test-First Development (NON-NEGOTIABLE)

Tests MUST be written against **real systems**. There are no mocks of IRIS, no mocks of the
wire protocol, and no fake clients. `tests/conftest.py` states the rule the codebase already
follows: "NO MOCKS — everything tested against real systems."

- E2E tests MUST use real PostgreSQL client libraries against a real IRIS instance.
- E2E test coverage MUST be at or above **90%**.
- The IRIS integration suite MUST pass at **100%** — no skipped or quarantined failures.
- A test MUST NOT be skipped, disabled or quarantined to make a build green. If a test is
  wrong, fix or delete it deliberately and say so.

A feature is not done when its code is written. It is done when a real client exercises it
against a real IRIS instance and passes.

*Rationale*: This project exists at the seam between two systems. A mock of either side tests
only our belief about that side, and the bugs that matter live precisely where that belief is
wrong.

### III. Phased Implementation

Work MUST proceed through structured phases (P0–P6), each with a defined entry state and
demonstrable exit criteria. A phase MUST NOT be declared complete on partial evidence.

Research that gates a design decision MUST be executed, not assumed. Where a spike's result
would change the plan, the plan MUST NOT be committed to until the spike has run against a
real instance.

*Rationale*: Phases exist so that the cost of a wrong architectural assumption is bounded to
one phase instead of discovered at integration.

### IV. IRIS Integration

Integration with IRIS MUST use supported native paths: embedded Python (`irispython`) via the
CallIn service, or the DBAPI connection, selectable at runtime.

- Both backends MUST remain functional. A change that works on only one backend is incomplete.
- Backend selection MUST be configuration, never a code fork.
- IRIS-specific behaviour MUST be isolated behind the executor and translation layers, not
  scattered through protocol handling.

*Rationale*: The dual-backend design is what lets this run both inside and beside IRIS. It
survives only if both paths are exercised continuously.

### V. Production Readiness

The following are measured requirements, not aspirations:

- SQL translation MUST complete within a **5 ms** SLA.
- Error rate MUST remain below **1%**.
- Availability MUST exceed **99.9%**.
- Real-time performance monitoring MUST be present (100% coverage of the request path).
- Debug tracing MUST be available and MUST NOT require a rebuild to enable.

Any feature that adds latency to the query path MUST measure its own cost against the 5 ms
budget before merge. "Probably fast enough" is not a measurement.

*Rationale*: These numbers are enforced at runtime by `src/iris_pgwire/constitutional.py`. A
threshold recorded here that the checker does not enforce, or vice versa, is a defect in one
of the two.

### VI. Vector Performance

Vector operations MUST use HNSW indexing where an index is applicable.

IRIS supports **cosine distance** and **dot product** only:

- `<=>` (cosine) → `VECTOR_COSINE()` — supported
- `<#>` (dot product) → `VECTOR_DOT_PRODUCT()` — supported
- `<->` (L2 / Euclidean) → **MUST be REJECTED with a NOT IMPLEMENTED error**

L2 MUST NOT be emulated, approximated, or silently substituted with another metric. Returning
cosine results for an L2 query would produce plausible, wrong, and undetectable answers.

*Rationale*: This is Principle I applied to vectors, where the failure mode is worst: a
silently substituted distance metric yields results that look correct and are not.

## Technical Constraints

These are properties of the platform, not choices. Violating them produces confusing failures.

- **Package naming**: install `intersystems-irispython`, but import `iris` — never
  `import intersystems_irispython`.
- **Container reload**: Docker containers do **NOT** hot-reload Python changes. Containers MUST
  be restarted after any source change. Test results obtained without a restart are invalid
  and MUST NOT be reported as evidence.
- **Vector metrics**: see Principle VI. IRIS supports cosine and dot product only.
- **Schema mapping**: PostgreSQL `public` maps to the configured IRIS schema (`SQLUser` by
  default). This mapping MUST be applied consistently across DDL, DML and catalog paths.

## Development Workflow & Quality Gates

- Every feature begins as a specification under `specs/###-feature-name/` following the
  spec-kit flow: `spec.md` → `plan.md` → `tasks.md`.
- `plan.md` MUST include a Constitution Check evaluated against this document, both before
  Phase 0 research and again after Phase 1 design.
- A violation MUST be either resolved or explicitly justified in the plan's Complexity Tracking
  section. An unjustified violation blocks merge.
- Performance-affecting changes MUST include a measurement against the Principle V budgets.
- Authorship: all work is attributed to the project owner. Commits, pull requests and
  documentation MUST NOT credit AI assistants or automated tooling.

## Governance

This constitution supersedes other practices and conventions in this repository. Where CLAUDE.md,
AGENTS.md or documentation conflict with this document, this document governs, and the conflicting
file MUST be corrected.

**Amendment procedure**: Amendments MUST be proposed as a change to this file, stating the
principle affected, the rationale, and the migration impact on existing code and specs. An
amendment that changes a measured threshold MUST update `src/iris_pgwire/constitutional.py` in
the same change, so the document and the runtime checker cannot diverge.

**Versioning policy** (semantic):

- **MAJOR** — a principle is removed or redefined incompatibly.
- **MINOR** — a principle or section is added, or guidance materially expanded.
- **PATCH** — clarification, wording, or non-semantic refinement.

**Compliance review**: Pull requests MUST verify compliance with the principles they touch.
Complexity MUST be justified rather than assumed. Runtime compliance is reported by the
governance utilities in `src/iris_pgwire/constitutional.py`; a failing constitutional check is
a release blocker, not a warning.

**Version**: 1.0.0 | **Ratified**: 2026-01-21 | **Last Amended**: 2026-08-16
