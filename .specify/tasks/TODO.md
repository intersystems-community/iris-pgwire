# TODO: Unverified Features from README Cleanup

These features were claimed in README but have no test verification. Each needs a /specify task to implement and test.

## High Priority

- [ ] **BI Tool Integration** - Test actual Tableau/Power BI connection
  - Verify connection string works
  - Test basic query execution
  - Test IRIS-specific features (JSON, PREDICT)

- [x] **Async SQLAlchemy** - ✅ IMPLEMENTED (2025-10-06)
  - ✅ Created `IRISDialect_psycopg` with async support
  - ✅ Uses IRIS dialect (INFORMATION_SCHEMA) + psycopg transport (async)
  - ✅ Connection string: `iris+psycopg://localhost:5432/USER`
  - ✅ Full test suite created in `tests/test_sqlalchemy_async.py`
  - ⏸️ E2E testing pending (requires PGWire server running)
  - 📝 Documentation: `docs/SQLALCHEMY_ASYNC_SUPPORT.md`
  - 📦 Fork: `/Users/tdyar/ws/sqlalchemy-iris` (ready to push)

- [ ] **LangChain Integration** - Actual LangChain PGVector test
  - Verify PGVector vectorstore initialization
  - Test similarity_search()
  - Test document ingestion

## Medium Priority

- [ ] **IPM Package Installation** - Test ZPM installation flow
  - Verify package loads
  - Test ObjectScript lifecycle hooks
  - Verify server starts via `##class(IrisPGWire.Service).Start()`

- [ ] **IntegratedML PREDICT()** - Test ML model predictions through PGWire
  - Create test model in IRIS
  - Execute PREDICT() via psycopg
  - Verify results match direct IRIS execution

- [ ] **Monitoring Stack** - Implement Grafana/Prometheus
  - Create docker-compose with monitoring services
  - Implement metrics endpoints
  - Create Grafana dashboards
  - Test metric collection

## Low Priority

- [ ] **Production Deployment Script** - Create `start-production.sh`
  - SSL/TLS configuration
  - Connection limits
  - Health checks
  - Logging configuration

- [ ] **SSL/TLS Support** - Implement encryption (P3 dependency)
  - SSL negotiation handshake
  - Certificate management
  - Client verification

- [ ] **SCRAM-SHA-256 Authentication** - Full auth implementation
  - SCRAM handshake
  - Password verification
  - IRIS user integration

- [ ] **IRIS Construct Translation Coverage** - Test all 87 constructs
  - Comprehensive test suite for each construct
  - Validation against IRIS behavior
  - Document translation patterns

- [ ] **JSON_TABLE Translation** - Complex JSON operations
  - Test JSON_TABLE → jsonb_to_recordset
  - Test nested JSON paths
  - Test with real-world JSON documents

## Notes

All removed claims are preserved in git history (commit before README cleanup).
Use `/specify` to create formal specifications for each feature before implementation.
