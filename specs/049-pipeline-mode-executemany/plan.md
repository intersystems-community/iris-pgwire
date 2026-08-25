# Implementation Plan: psycopg3 Pipeline Mode + executemany Support

**Branch**: `049-pipeline-mode-executemany` | **Date**: 2026-08-25 | **Spec**: [spec.md](spec.md)

## Summary

Fix executemany batch execution: per-row duplicate key suppression when ON CONFLICT DO NOTHING is stripped, accurate row count reporting, and pipeline Sync/Flush sequencing.

## Technical Context

**Language/Version**: Python 3.11 (irispython and CPython both supported)
**Primary Dependencies**: asyncio, iris (intersystems-irispython), psycopg3 (client test), pytest
**Storage**: InterSystems IRIS (SQL via CallIn / DBAPI)
**Testing**: pytest; unit tests cover pure-Python logic only (no mocks of IRIS or wire protocol); integration tests use real psycopg3 + real IRIS container (skip-guarded)
**Target Platform**: Linux/macOS server (Docker container for IRIS)
**Performance Goals**: executemany batch of 1,000 rows completes without error; no latency regression on single-row path
**Constraints**: Must not break existing 5,500+ tests; changes isolated to `protocol.py` and `iris_executor.py`

## Constitution Check

| #   | Principle              | Gate                                                                                        | Status |
| --- | ---------------------- | ------------------------------------------------------------------------------------------- | ------ |
| I   | Protocol Fidelity      | Server correctly handles pipeline Sync/Flush sequencing per PostgreSQL wire protocol v3     | PASS   |
| II  | Test-First Development | Unit tests written first; integration tests use real psycopg3 against real IRIS             | PASS   |
| III | Phased Implementation  | Phase 1: unit tests + ON CONFLICT fix; Phase 2: row count fix; Phase 3: pipeline Sync/Flush | PASS   |
| IV  | IRIS Integration       | Changes in iris_executor.py affect both embedded Python and DBAPI paths equally             | PASS   |
| V   | Production Readiness   | No latency impact on single-row path; batch path measured                                   | PASS   |
| VI  | Vector Performance     | N/A                                                                                         | N/A    |

## Project Structure

### Documentation (this feature)

```text
specs/049-pipeline-mode-executemany/
├── spec.md
├── plan.md          ← this file
└── tasks.md
```

### Source Code

```text
src/iris_pgwire/
├── protocol.py           # flush_batch(), handle_sync_message(), execute_many buffering
├── iris_executor.py      # execute_many() — ON CONFLICT strip, row count tracking

tests/unit/
├── test_pipeline_executemany.py   # NEW

tests/integration/
└── test_psycopg3_pipeline.py      # NEW — skip-guarded, requires IRIS container
```

## Phases

### Phase 1: ON CONFLICT stripping + row count accuracy

**Exit Criteria**: `test_pipeline_executemany.py` all pass; `execute_many()` suppresses duplicate key errors per row and returns correct row counts.

- `iris_executor.py` `execute_many()`: record `_had_on_conflict` before stripping; route to per-row fallback with `suppress_duplicate_keys=True` when set.
- `_execute_many_inline_fallback()` / `_execute_many_embedded_async()`: catch errors containing "Duplicate key" or "5804" per row when flag is set; accumulate `skipped` counter; return `rows_affected = total - skipped`.

### Phase 2: Pipeline Sync/Flush sequencing

**Exit Criteria**: Flush sends no ReadyForQuery; Sync flushes batch then sends ReadyForQuery.

Source audit result: both `handle_sync_message()` (protocol.py:3532) and `handle_flush_message()` (protocol.py:3597) are already correct. Phase 2 is integration test confirmation only.

### Phase 3: Integration test

**Exit Criteria**: psycopg3 `executemany()` of 100 rows works end-to-end against real IRIS.

- `tests/integration/test_psycopg3_pipeline.py`: `executemany("INSERT … ON CONFLICT DO NOTHING", rows)` with 50 unique + 50 duplicate rows → 50 rows land, no error.

## Research Notes

- psycopg3 pipeline mode: client sends Parse/Bind/Execute without waiting for response; ReadyForQuery only after Sync.
- `flush_batch()` (protocol.py:2393) already handles buffer flush on Sync.
- IRIS duplicate key error text: `"IRIS error - ERROR #5804: Duplicate key value"`.
- Native `executemany()` has no per-row error isolation; per-row suppression requires the inline fallback path.
