# Implementation Plan: psycopg3 Pipeline Mode + executemany Support

**Branch**: `049-pipeline-mode-executemany` | **Date**: 2026-08-25 | **Spec**: [spec.md](spec.md)

## Summary

Fix psycopg3 pipeline mode + executemany to correctly handle batch DML execution: strip ON CONFLICT on every row, suppress duplicate key errors when ON CONFLICT DO NOTHING is present, correctly report row counts, and handle pipeline Sync/Flush message sequencing.

## Technical Context

**Language/Version**: Python 3.11 (irispython and CPython both supported)
**Primary Dependencies**: asyncio, iris (intersystems-irispython), psycopg3 (client test), pytest
**Storage**: InterSystems IRIS (SQL via CallIn / DBAPI)
**Testing**: pytest; unit tests mock wire-protocol; integration tests use real IRIS container
**Target Platform**: Linux/macOS server (Docker container for IRIS)
**Project Type**: Single project
**Performance Goals**: executemany batch of 1,000 rows completes without error; no latency regression on single-row path
**Constraints**: Must not break existing 5,500+ tests; changes isolated to `protocol.py` and `iris_executor.py`
**Scale/Scope**: Fixes the execute_many / flush_batch / handle_sync_message code paths

## Constitution Check

| # | Principle | Gate | Status |
|---|-----------|------|--------|
| I | Protocol Fidelity | Server correctly handles pipeline Sync/Flush sequencing per PostgreSQL wire protocol v3 | PASS |
| II | Test-First Development | Unit tests written first; integration tests use real psycopg3 against real IRIS | PASS |
| III | Phased Implementation | Phase 1: unit tests + ON CONFLICT fix; Phase 2: row count fix; Phase 3: pipeline Sync/Flush | PASS |
| IV | IRIS Integration | Changes in iris_executor.py affect both embedded Python and DBAPI paths equally | PASS |
| V | Production Readiness | No latency impact on single-row path; batch path measured | PASS |
| VI | Vector Performance | N/A — no vector operations involved | N/A |

## Project Structure

### Documentation (this feature)

```text
specs/049-pipeline-mode-executemany/
├── spec.md
├── plan.md          ← this file
├── research.md
└── tasks.md
```

### Source Code

```text
src/iris_pgwire/
├── protocol.py           # flush_batch(), handle_sync_message(), execute_many buffering
├── iris_executor.py      # execute_many() — ON CONFLICT strip, row count tracking

tests/unit/
├── test_pipeline_executemany.py   # NEW — unit tests for pipeline/executemany fixes

tests/integration/
└── (psycopg3 pipeline test — requires IRIS container; skip-guarded)
```

## Phases

### Phase 1: ON CONFLICT stripping + row count accuracy (unit-testable, no IRIS required)

**Exit Criteria**: `test_pipeline_executemany.py` all pass; `execute_many()` strips ON CONFLICT on every row and returns correct row counts.

Changes:
- `iris_executor.py`: `execute_many()` — already strips ON CONFLICT once (from 048); verify it re-strips per-row if SQL changes mid-batch (defensive). Add row-count accumulation and return total.
- `iris_executor.py`: Catch `IRIS duplicate key` / `SQLSTATE 23505` errors during executemany when original SQL had ON CONFLICT DO NOTHING — suppress those errors, continue batch.
- Unit tests first: `TestExecuteManyOnConflict`, `TestExecuteManyRowCount`.

### Phase 2: Pipeline Sync/Flush message sequencing

**Exit Criteria**: Protocol correctly handles Flush (no ReadyForQuery) vs Sync (flush batch + ReadyForQuery); existing sync tests pass.

Changes:
- `protocol.py`: `handle_sync_message()` — ensure `flush_batch()` is called before ReadyForQuery; verify all buffered CommandCompletes are sent.
- `protocol.py`: `handle_flush_message()` — flush the asyncio write buffer but do NOT send ReadyForQuery.
- Unit tests: mock protocol sessions to verify Sync sends ReadyForQuery and Flush does not.

### Phase 3: Integration test (requires IRIS container)

**Exit Criteria**: psycopg3 `executemany()` of 100 rows works end-to-end.

- Add `tests/integration/test_psycopg3_pipeline.py` with skip guard if no IRIS container.
- Test: `executemany("INSERT INTO t VALUES (%s) ON CONFLICT DO NOTHING", rows)` with 50 unique + 50 duplicate rows → 50 rows land, no error.

## Research Notes

- psycopg3 pipeline mode: client sends Parse/Bind/Execute without waiting for response. Server must buffer CommandCompletes and send them in order. ReadyForQuery is sent only after Sync.
- Current `flush_batch()` already handles the buffer flush; the gap is in duplicate key suppression and row count reporting.
- IRIS duplicate key error message: `"IRIS error - ERROR #5804: Duplicate key value"` or similar — need to grep actual error text in `iris_executor.py`.
- `execute_many()` currently calls `iris_executor.executemany(sql, params_list)` — if IRIS raises on any row, the whole batch fails. Need per-row execution or catch+suppress pattern.
