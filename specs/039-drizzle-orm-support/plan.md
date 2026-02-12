# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: 
- `iris-pgwire` v1.3.x+ (PostgreSQL wire protocol adapter to extend)
- `sqlparse` v0.4+ (PostgreSQL DDL parsing)
- `intersystems-irispython` (IRIS database connectivity)
- `psycopg[binary]` (PostgreSQL protocol support)

**Storage**: InterSystems IRIS 2024.2+ via pgwire  
**Testing**: pytest with iris-devtester for live IRIS integration tests  
**Target Platform**: Linux/macOS/Windows servers running iris-pgwire  
**Project Type**: Single Python package (extension to existing iris-pgwire)  
**Performance Goals**: <10ms DDL translation overhead per statement  
**Constraints**: 
- Backward compatible (opt-in via `enable_ddl_translation` flag)
- Must preserve existing iris-pgwire DML/DQL translation
- Transaction support required for rollback on migration failure

**Scale/Scope**: 
- Support 95% of Drizzle-generated migrations (10-50 DDL statements per file typical)
- Handle 20+ PostgreSQL type mappings
- ~1500-2000 LOC for core translation logic

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

[Gates determined based on constitution file]

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

Extends existing `iris-pgwire` package structure:

```text
src/iris_pgwire/
├── sql_translator/
│   ├── translator.py           # EXISTING - extend with DDL routing
│   ├── ddl_translator.py       # NEW - Core DDL translation
│   ├── ddl_parser.py           # NEW - PostgreSQL DDL parsing
│   ├── type_translator.py      # NEW - Type mapping logic
│   ├── constraint_translator.py # NEW - Constraint translation
│   └── reserved_words.py       # NEW - Reserved word checker
├── migrations/
│   ├── executor.py             # NEW - Migration execution + locking
│   └── __main__.py             # NEW - CLI entry point
├── config.py                   # EXTEND - Add DDLTranslationConfig
└── type_mapping.py             # EXTEND - Add DDL type mappings

tests/
├── integration/
│   ├── test_drizzle_migration.py  # NEW - 15+ end-to-end tests
│   └── test_sql_translator_ddl.py # NEW - SQLTranslator DDL routing
├── unit/
│   ├── test_ddl_translator.py     # NEW
│   ├── test_type_translator.py    # NEW
│   ├── test_constraint_translator.py # NEW
│   └── test_reserved_words.py     # NEW
└── fixtures/
    └── drizzle_migrations.py      # NEW - Test migration files
```

**Structure Decision**: Single Python package extension (Option 1). Drizzle DDL translation is a new capability within the existing iris-pgwire architecture, not a standalone project. Core translation logic lives in `sql_translator/`, migration execution in `migrations/`, following the established iris-pgwire patterns.
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
