# tests/unit — Agent Knowledge Base

**48 files.** Pure-logic tests requiring no IRIS connection. Fast, isolated.

## OVERVIEW

Tests for SQL translation, protocol logic, type mapping, auth, conversions.
No Docker, no IRIS, no network. Run with `pytest tests/unit`.

## STRUCTURE

```
unit/
├── auth/                        # Auth unit tests (SCRAM, OAuth)
├── protocol/                    # Protocol message parsing unit tests
├── test_sql_translator.py       # Core translation logic
├── test_identifier_normalizer.py
├── test_date_translator.py
├── test_boolean_defaults.py     (via contract/)
├── test_transaction_translator.py
├── test_ddl_splitter_fixes.py
├── test_hnsw_translation.py     # Vector index translation
├── test_enum_handling.py
├── test_catalog_integration.py  # Catalog logic (no IRIS)
├── test_conversions.py
├── test_column_validator.py
├── test_confidence_analyzer.py
└── ... (48 total)
```

## CONVENTIONS

- No fixtures requiring `embedded_iris` or `pgwire_client` — those are integration
- Parameterize with `@pytest.mark.parametrize` for translation edge cases
- Mark with `@pytest.mark.unit`
- Use `pytest.approx` for float comparisons (vector scores, timing)

## ANTI-PATTERNS

- No mocks of IRIS — if you need IRIS, it belongs in `tests/integration/`
- No network calls — mock external services if needed
- Don't import `iris` module at module level — it may not be installed in CI unit runs
