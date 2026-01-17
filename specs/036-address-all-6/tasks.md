# Tasks: DDL Compatibility Enhancements for PostgreSQL → IRIS

**Input**: Design documents from `/specs/036-address-all-6/`
**Prerequisites**: plan.md (required), research.md, data-model.md

## Phase 1: Setup
- [ ] T001 Add `strict_ddl` flag to `Config` class in `src/iris_pgwire/sql_translator/config.py`
- [ ] T002 Update `src/iris_pgwire/sql_translator/logging_config.py` to include `DDL_SKIP_FORMAT` constant as "[DDL-SKIP] <statement> ignored"

## Phase 2: Foundational
- [ ] T003 [P] Implement `SkippedTableSet` in `src/iris_pgwire/sql_translator/skipped_table_set.py`
- [ ] T004 [P] Update `src/iris_pgwire/sql_translator/enum_registry.py` to support registering types from `CREATE TYPE ... AS ENUM` statements

## Phase 3: [US1] DDL Compatibility Enhancement
**Story Goal**: Successfully process PostgreSQL-specific DDL by skipping or transforming unsupported constructs.
**Independent Test Criteria**: A migration script containing all listed constructs completes without error when `strict_ddl=false` and raises error when `strict_ddl=true`.

- [ ] T005 [P] [US1] Unit test for `strict_ddl` flag logic in `tests/unit/test_strict_ddl.py`
- [ ] T006 [P] [US1] Unit test for fillfactor skip in `tests/unit/test_fillfactor.py`
- [ ] T007 [P] [US1] Unit test for generated column skip in `tests/unit/test_generated_columns.py`
- [ ] T008 [P] [US1] Unit test for `USING btree` removal in `tests/unit/test_using_btree.py`
- [ ] T009 [P] [US1] Unit test for cast syntax removal in `tests/unit/test_cast_removal.py`
- [ ] T010 [P] [US1] Unit test for Enum handling in `tests/unit/test_enum_handling.py`
- [ ] T011 [P] [US1] Unit test for CHECK constraint skip in `tests/unit/test_check_constraints.py`
- [ ] T012 [P] [US1] Unit test for Index skip on skipped tables in `tests/unit/test_index_skip.py`
- [ ] T013 [US1] Implement `SET (fillfactor)` skip logic in `src/iris_pgwire/sql_translator/statement_filter.py`
- [ ] T014 [US1] Implement `GENERATED ALWAYS AS` column skip logic in `src/iris_pgwire/sql_translator/statement_filter.py`
- [ ] T015 [US1] Implement `USING btree` stripping logic in `src/iris_pgwire/sql_translator/normalizer.py`
- [ ] T016 [US1] Implement cast syntax (`'value'::type`) removal in `src/iris_pgwire/sql_translator/normalizer.py`
- [ ] T017 [US1] Implement `CREATE TYPE ... AS ENUM` registration in `src/iris_pgwire/sql_translator/statement_filter.py` and `src/iris_pgwire/sql_translator/enum_registry.py`
- [ ] T018 [US1] Implement mapping of enum-typed columns to `VARCHAR(64)` in `src/iris_pgwire/sql_translator/translator.py`
- [ ] T019 [US1] Implement `ADD CONSTRAINT ... CHECK` skip logic in `src/iris_pgwire/sql_translator/validator.py` or `statement_filter.py`
- [ ] T020 [US1] Implement `SkippedTableSet` tracking in `src/iris_pgwire/sql_translator/statement_filter.py` and skip referencing indexes
- [ ] T021 [US1] Integration test for complete migration script using `iris-devtester` in `tests/integration/test_migration_ddl.py`

## Final Phase: Polish & Cross-Cutting Concerns
- [ ] T022 [P] Update `docs/DDL_COMPATIBILITY.md` with supported transformations and `strict_ddl` behavior
- [ ] T023 [P] Run `ruff check .` and `pytest` to ensure no regressions
- [ ] T024 Benchmark migration script performance to verify < 5% overhead compared to baseline

## Dependencies
- US1 (Phase 3) depends on Setup (Phase 1) and Foundational (Phase 2) tasks.
- Implementation tasks (T013-T020) should follow their respective test tasks (T006-T012).
- T021 depends on all implementation tasks (T013-T020).

## Parallel Execution Examples
- T003 and T004 can run in parallel (different files).
- Unit tests T005-T012 can run in parallel (different files).
- Polish tasks T022 and T023 can run in parallel.

## Implementation Strategy
- MVP: Support fillfactor and generated column skips first to enable basic migrations.
- Incremental: Add Enum registration and cast removal which are more complex string transformations.
- Safety: Ensure `strict_ddl=true` always halts execution to prevent silent data loss in strictly managed environments.
