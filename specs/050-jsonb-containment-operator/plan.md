# Implementation Plan: JSONB Containment Operator (@>) Support

**Branch**: `050-jsonb-containment-operator` | **Date**: 2026-08-25 | **Spec**: [spec.md](spec.md)

## Summary

Translate PostgreSQL `@>` and `<@` jsonb containment operators to `PGWire.JSONB_CONTAINS(left, right)` calls in the SQL normalization pipeline, and implement the `JSONB_CONTAINS` ObjectScript stored procedure in the `PGWire` package on IRIS.

## Technical Context

**Language/Version**: Python 3.11 (SQL rewriter); ObjectScript (IRIS stored procedure)
**Primary Dependencies**: re (regex rewriter in normalizer.py); existing PGWire package in IRIS
**Storage**: InterSystems IRIS (JSONB_CONTAINS stored procedure installed in USER namespace)
**Testing**: pytest unit tests for rewriter; integration test uses real IRIS with real JSON column
**Target Platform**: Linux/macOS server (Docker container for IRIS)
**Project Type**: Single project
**Performance Goals**: Rewrite overhead ≤ 1ms per query; `JSONB_CONTAINS` procedure ≤ 5ms for typical JSON documents
**Constraints**: Must not affect queries that don't use `@>` / `<@`; ObjectScript procedure must be idempotent on install

## Constitution Check

| # | Principle | Gate | Status |
|---|-----------|------|--------|
| I | Protocol Fidelity | `@>` returns correct rows, not an error or degraded result; unsupported JSON patterns return a clear error | PASS |
| II | Test-First Development | Rewriter unit tests written before implementation; integration test uses real IRIS + psycopg3 | PASS |
| III | Phased Implementation | Phase 1: rewriter + unit tests; Phase 2: ObjectScript procedure; Phase 3: integration test | PASS |
| IV | IRIS Integration | Rewriter is SQL-level (language-agnostic); JSONB_CONTAINS installed via existing CatalogViewInstaller / DDL path | PASS |
| V | Production Readiness | Translation overhead measured; procedure latency tested | PASS |
| VI | Vector Performance | N/A — no vector operations involved | N/A |

## Project Structure

### Documentation (this feature)

```text
specs/050-jsonb-containment-operator/
├── spec.md
├── plan.md          ← this file
├── research.md
└── tasks.md
```

### Source Code

```text
src/iris_pgwire/sql_translator/
├── normalizer.py                  # Add _translate_jsonb_containment() + call in pipeline
├── pg_functions.py                # Reference only — pattern established here for @> rewrite

src/iris_pgwire/catalog/
└── catalog_installer.py           # Install JSONB_CONTAINS procedure on startup (existing DDL runner)

tests/unit/
├── test_jsonb_containment.py      # NEW — rewriter unit tests (5+ scenarios)

tests/integration/
└── test_jsonb_ops.py              # NEW — end-to-end with real IRIS JSON column (skip-guarded)
```

### ObjectScript (IRIS)

```text
PGWire.JSONB_CONTAINS(left As %String, right As %String) As %Integer
  Install via SQL: CREATE PROCEDURE PGWire.JSONB_CONTAINS(left VARCHAR, right VARCHAR)
                   RETURNS INTEGER LANGUAGE OBJECTSCRIPT { ... }
  Already precedented by PGWire.FORMAT2, PGWire.JSONB_BUILD_OBJECT4, etc.
```

## Phases

### Phase 1: SQL rewriter (unit-testable, no IRIS required)

**Exit Criteria**: `test_jsonb_containment.py` all pass; `@>` and `<@` rewritten correctly in all patterns.

Changes:
- `normalizer.py`: Add `_JSONB_CONTAINS_PATTERN` regex matching `(expr)::jsonb @> (expr)::jsonb` and bare `col @> val` forms.
- `normalizer.py`: Add `_translate_jsonb_containment(sql)` function — rewrites to `PGWire.JSONB_CONTAINS(left_no_cast, right_no_cast)`.
- Insert call in `normalize_sql_with_result()` pipeline (same location as ILIKE, boolean translators).
- Handle `<@` by swapping arguments.
- Unit tests first: `TestJsonbContainmentRewrite` with 8+ test cases.

### Phase 2: ObjectScript JSONB_CONTAINS procedure

**Exit Criteria**: Procedure installed and returns correct results for basic, nested, and array JSON containment.

Implementation strategy:
- `JSONB_CONTAINS(left, right)`: Parse `right` as JSON; for each key-value in `right`, verify same key-value exists in `left`. Use `$$$JSONGetValue` / `%DynamicObject` ObjectScript APIs.
- Install via `CREATE OR REPLACE PROCEDURE` DDL in `catalog_installer.py` (consistent with existing `PGWire.FORMAT2` install pattern).
- Unit tests (ObjectScript-level): call procedure directly via `iris_execute` to verify containment logic.

### Phase 3: Integration test (requires IRIS container)

**Exit Criteria**: psycopg3 query with `@>` returns correct rows against a real IRIS table with JSON column.

- Add `tests/integration/test_jsonb_ops.py` with skip guard.
- Test: CREATE TABLE, INSERT rows with JSON, SELECT with `@>`, verify result set.

## Research Notes

- Pattern precedent: ILIKE rewriter in `normalizer.py` — regex + `re.sub()`, inserted after boolean translation, before returning result.
- ObjectScript JSON API: `%DynamicObject` with `%FromJSON()`, iterate keys via `%GetIterator()`. For nested objects, recurse. For arrays, check membership.
- `::jsonb` cast strip: can be done as part of the rewrite regex or via the existing `_strip_type_casts()` helper — check if that helper exists.
- `$1` / `?` parameter placeholders on the RHS: the rewrite must not consume placeholders. The regex should match balanced parentheses or use a simpler `col @> val` pattern without requiring `::jsonb` on both sides.
