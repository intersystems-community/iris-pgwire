# Implementation Plan: JSONB Containment Operator (@>) Support

**Branch**: `050-jsonb-containment-operator` | **Date**: 2026-08-25 | **Spec**: [spec.md](spec.md)

## Summary

Translate PostgreSQL `@>` and `<@` jsonb containment operators to `PGWire.JSONB_CONTAINS(left, right)` calls in the SQL normalization pipeline, and implement the `JSONB_CONTAINS` ObjectScript stored procedure in the `PGWire` package on IRIS.

## Technical Context

**Language/Version**: Python 3.11 (SQL rewriter); ObjectScript (IRIS stored procedure)
**Primary Dependencies**: `re` (normalizer.py); existing `PGWire` package in IRIS
**Storage**: InterSystems IRIS (`JSONB_CONTAINS` stored procedure in USER namespace)
**Testing**: pytest unit tests (no IRIS required); skip-guarded integration test uses real IRIS + psycopg3
**Target Platform**: Linux/macOS server (Docker container for IRIS)
**Performance Goals**: Rewrite overhead ≤ 1ms per query; `JSONB_CONTAINS` procedure ≤ 5ms per call
**Constraints**: Must not affect queries without `@>` / `<@`; procedure install is idempotent

## Constitution Check

| #   | Principle              | Gate                                                                                          | Status |
| --- | ---------------------- | --------------------------------------------------------------------------------------------- | ------ |
| I   | Protocol Fidelity      | `@>` returns correct rows; unsupported JSON patterns return a clear error                     | PASS   |
| II  | Test-First Development | Rewriter unit tests written before implementation; integration test uses real IRIS + psycopg3 | PASS   |
| III | Phased Implementation  | Phase 1: rewriter + unit tests; Phase 2: ObjectScript procedure; Phase 3: integration test    | PASS   |
| IV  | IRIS Integration       | Rewriter is SQL-level; `JSONB_CONTAINS` installed via `catalog/functions.py` DDL path         | PASS   |
| V   | Production Readiness   | Translation overhead measured; procedure latency tested                                       | PASS   |
| VI  | Vector Performance     | N/A                                                                                           | N/A    |

## Project Structure

```text
specs/050-jsonb-containment-operator/
├── spec.md
├── plan.md
├── research.md
└── tasks.md

src/iris_pgwire/sql_translator/
└── normalizer.py          # _translate_jsonb_containment() added to pipeline

src/iris_pgwire/catalog/
└── functions.py           # JSONB_CONTAINS CatalogFunction definition

tests/unit/
└── test_jsonb_containment.py

tests/integration/
└── test_jsonb_ops.py      # skip-guarded
```

## Phases

### Phase 1: SQL rewriter

**Exit Criteria**: `test_jsonb_containment.py` all pass; `@>` and `<@` rewritten in all patterns.

- `normalizer.py`: add `_JSONB_CONTAINS_PATTERN` and `_JSONB_CONTAINED_BY_PATTERN` regexes.
- `normalizer.py`: add `_translate_jsonb_containment(sql)` — rewrites to `PGWire.JSONB_CONTAINS(lhs, rhs)`, strips `::jsonb` casts, swaps args for `<@`.
- Insert after ILIKE translation line in `normalize_sql_with_result()`.
- Unit tests first: `TestJsonbContainmentRewrite` with 8+ cases.

### Phase 2: ObjectScript JSONB_CONTAINS procedure

**Exit Criteria**: Procedure returns correct results for object, array, and scalar containment.

- Add `JSONB_CONTAINS` `CatalogFunction` to `catalog/functions.py` following `JSONB_BUILD_OBJECT4` pattern.
- Body: parse both args with `%DynamicAbstractObject.%FromJSON()`; iterate right-side keys; compare values in left; handle arrays by checking each element.

### Phase 3: Integration test

**Exit Criteria**: psycopg3 query with `@>` returns correct rows against real IRIS.

- `tests/integration/test_jsonb_ops.py` with skip guard (IRIS_HOST env var).

## Research Notes

- ILIKE rewriter in `normalizer.py` is the direct precedent: module-level regex + `re.sub()`, one line added to pipeline.
- ObjectScript `%DynamicObject.%FromJSON()` + `%GetIterator()` for key iteration; `%DynamicArray` for array traversal.
- `$1` / `?` placeholders on the RHS: regex must match without consuming them as part of a cast expression.
