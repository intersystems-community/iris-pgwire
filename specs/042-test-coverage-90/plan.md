# Implementation Plan: Test Coverage 90%

**Branch**: `042-test-coverage-90` | **Date**: 2026-06-24 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/042-test-coverage-90/spec.md`

## Summary

Increase `tests/unit/ + tests/contract/` coverage from 47% to ≥90% by: (1) fixing 85
failing tests via stale-API updates and 4 code bug fixes, (2) adding unit tests for 10
zero-coverage modules totalling ~1,027 statements, and (3) mocking OAuth/Wallet contract
tests to remove live-IRIS dependency.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: pytest, pytest-cov, pytest-asyncio, unittest.mock
**Storage**: N/A (all test-only or mock)
**Testing**: pytest with `--cov=src/iris_pgwire --cov-fail-under=90`
**Target Platform**: macOS / Linux CI, no IRIS container required
**Project Type**: Single project — `src/iris_pgwire/`, `tests/unit/`, `tests/contract/`
**Performance Goals**: Full unit+contract suite completes in under 5 minutes
**Constraints**: No live IRIS container; all contract tests must pass in isolation
**Scale/Scope**: ~1,151 tests → target ≥90% line coverage

## Constitution Check

No project-specific constitution defined. Standard test-first practices apply:
- All new test files written before or alongside implementation fixes
- No existing passing test may be broken
- Gate: `pytest tests/unit/ tests/contract/ --cov-fail-under=90` exits 0

## Project Structure

### Documentation (this feature)

```text
specs/042-test-coverage-90/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # N/A — no new entities
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code Changes

```text
src/iris_pgwire/
├── quality/
│   └── security_validator.py          # Fix: check_license_compatibility list input
├── dbapi_executor.py                   # Fix: strftime microseconds → milliseconds
└── sql_translator/
    └── boolean_translator.py          # Investigate: BooleanTranslator.translate() test failures

tests/unit/
├── test_ddl_parser.py                  # NEW: DDLParser coverage
├── test_ddl_translator.py              # NEW: DDLTranslator coverage
├── test_migrations_executor.py         # NEW: MigrationExecutor coverage (mock DBAPI)
├── test_type_translator.py             # NEW: TypeTranslator coverage
├── test_type_mapping.py                # NEW: _type_mapping coverage
├── test_constraint_translator.py       # NEW: ConstraintTranslator coverage
├── test_index_validator.py             # NEW: IndexValidator coverage
├── test_reserved_words.py              # NEW: ReservedWordChecker coverage
└── test_config.py                      # NEW: DDLTranslationConfig coverage

tests/contract/
├── test_translation_contracts.py       # FIX: SQLTranslator.translate → normalize_sql
├── test_vector_optimizer_validation.py # FIX: add validate_sql() to VectorQueryOptimizer
├── test_benchmark_timeouts.py          # FIX: add execute_with_timeout() to PGWireExecutor
├── test_boolean_defaults.py            # FIX: BooleanTranslator API alignment
├── test_oauth_bridge_contract.py       # FIX: mock iris.cls calls
├── test_wallet_credentials_contract.py # FIX: mock iris.cls calls
├── test_security_contract.py           # FIX: after security_validator bug fix
└── test_async_dialect_contract.py      # FIX: guard sqlalchemy_iris.psycopg import
```

## Phase 0: Research

See [research.md](research.md).

## Phase 1: Design

No new entities or API contracts. This feature is purely test + bug-fix.

Key decisions from research:

| Item | Decision |
|------|----------|
| `SQLTranslator.translate` | Add `translate(request)` wrapper in `sql_translator/__init__.py` that delegates to `IRISSQLNormalizer.normalize_sql()` |
| `VectorQueryOptimizer.validate_sql` | Add `validate_sql(sql)` method returning a `ValidationResult` dataclass |
| `PGWireExecutor.execute_with_timeout` | Add method to `benchmarks/executors/pgwire_executor.py` |
| `check_license_compatibility` | Change param from `str` to `str | list[str]`; loop when list |
| Timestamp strftime | Replace `utc.strftime(fmt)` with explicit millisecond truncation |
| OAuth/Wallet mocks | `@patch("iris_pgwire.auth.oauth_bridge.iris")` and same for wallet |
| `sqlalchemy_iris.psycopg` | Wrap import in `try/except ImportError`; skip test if not available |

## Implementation Phases

### Phase A — Bug Fixes (unblocks most failing tests)

1. **security_validator.py**: `check_license_compatibility(self, license_name: str)` →
   `check_license_compatibility(self, licenses: str | list[str])`. When list, iterate and
   call existing logic per item; return combined result.

2. **dbapi_executor.py `_convert_iso_timestamp`**: After UTC conversion, strip
   microseconds to milliseconds:
   ```python
   result = utc.strftime(fmt)
   # Truncate 6-digit microseconds to 3-digit milliseconds
   if "." in result:
       parts = result.rsplit(".", 1)
       result = parts[0] + "." + parts[1][:3]
   return result
   ```

3. **sql_translator/__init__.py**: Add `translate()` alias/wrapper for
   `TranslationRequest`/`TranslationResult` contract.

4. **vector_optimizer.py**: Add `validate_sql(sql) -> ValidationResult` method.

5. **benchmarks/executors/pgwire_executor.py**: Add `execute_with_timeout(sql,
   timeout_seconds)` method.

6. **async_dialect_contract**: Guard `from sqlalchemy_iris.psycopg import ...` with
   `try/except ImportError; pytest.skip(...)`.

### Phase B — New Unit Tests (zero-coverage modules)

One test file per module. Each achieves ≥80% line coverage.
All use only stdlib + pytest — no IRIS connection.

Priority order (by statement count):
1. `test_ddl_parser.py` — 449 stmts
2. `test_ddl_translator.py` — 178 stmts
3. `test_migrations_executor.py` — 145 stmts (mock `connection`)
4. `test_type_translator.py` — 95 stmts
5. `test_type_mapping.py` — 88 stmts
6. `test_constraint_translator.py` — 20 stmts
7. `test_index_validator.py` — 21 stmts
8. `test_reserved_words.py` — 16 stmts
9. `test_config.py` — 9 stmts

### Phase C — Contract Test Fixes (mock OAuth/Wallet)

Patch `iris` module at the point it is imported in `oauth_bridge.py` and
`wallet_credentials.py`. Use `@pytest.fixture` with `unittest.mock.patch` context
so each test gets a fresh mock.

### Phase D — Coverage Gate

Run `pytest tests/unit/ tests/contract/ --cov=src/iris_pgwire --cov-fail-under=90`
and confirm exit 0.
