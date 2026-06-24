# tests/contract — Agent Knowledge Base

**44 files.** API contract/compliance tests. Verify interfaces are stable and
implementations honor their declared contracts.

## OVERVIEW

Contract tests sit between unit and integration: they test that modules satisfy
their interface contracts (shapes, error types, return values) without necessarily
requiring live IRIS. Some do require IRIS — check `@pytest.mark.requires_iris`.

## WHERE TO LOOK

| Contract | File |
|----------|------|
| SQL translator interface | `test_sql_translator_contract.py`, `test_translation_contracts.py` |
| Backend selector interface | `test_backend_selector_contract.py` |
| Catalog emulator shapes | `test_catalog_router.py`, `test_catalog_pg_*.py` |
| Auth interface | `test_gssapi_auth_contract.py`, `test_oauth_bridge_contract.py`, `test_wallet_credentials_contract.py` |
| COPY handler | `test_copy_handler_contract.py` |
| Bulk executor | `test_bulk_executor_contract.py` |
| Vector optimizer | `test_vector_optimizer_syntax.py`, `test_vector_optimizer_validation.py` |
| Schema mapping | `test_schema_mapping_config.py`, `test_schema_mapping_input.py`, `test_schema_mapping_output.py` |
| Security | `test_security_contract.py` |
| Package metadata | `test_package_metadata_contract.py` |
| Documentation coverage | `test_documentation_contract.py` |
| Benchmark timeouts | `test_benchmark_timeouts.py` |

## CONVENTIONS

- Mark with `@pytest.mark.contract`
- Prefer pure-Python assertions over IRIS calls — test the *shape* of the contract
- If IRIS is needed, mark `@pytest.mark.requires_iris` and skip gracefully
- No mocks of the module under test — test real implementations against interface
