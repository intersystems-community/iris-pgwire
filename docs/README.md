# IRIS PGWire Documentation

**Navigation hub** for all project documentation.

---

## 🚀 Getting Started

**New to IRIS PGWire?** Start here:

1. **[Installation Guide](INSTALLATION.md)** - Docker, PyPI, ZPM, Embedded Python deployment
2. **[Quick Start Examples](QUICKSTART_EXAMPLES.md)** - First queries with psql, Python, FastAPI
3. **[Features Overview](FEATURES_OVERVIEW.md)** - pgvector, ORM compatibility, authentication

---

## 📚 User Guides

### Core Features
- **[Features Overview](FEATURES_OVERVIEW.md)** - pgvector syntax, ORM compatibility, enterprise authentication
- **[Vector Operations](VECTOR_PARAMETER_BINDING.md)** - High-dimensional vectors, parameter binding, HNSW indexes
- **[pg_catalog Support](PG_CATALOG.md)** - 6 catalog tables + 5 functions for ORM introspection
- **[Client Compatibility](CLIENT_RECOMMENDATIONS.md)** - 171 tests across 8 languages, recommended clients

### Integration & Deployment
- **[BI Tools Setup](BI_TOOLS.md)** - Apache Superset, Metabase, Grafana integration
- **[Deployment Guide](DEPLOYMENT.md)** - Production setup, authentication, SSL/TLS
- **[DBAPI Backend](DBAPI_BACKEND.md)** - Connection pooling, external IRIS access
- **[Embedded Python Servers](EMBEDDED_PYTHON_SERVERS_HOWTO.md)** - Running inside IRIS

### Async & ORM Support
- **[Async SQLAlchemy Quickstart](ASYNC_SQLALCHEMY_QUICKSTART.md)** - FastAPI integration, async sessions
- **[SQLAlchemy Async Support](SQLALCHEMY_ASYNC_SUPPORT.md)** - Detailed async ORM guide

### Enterprise Setup
- **[IRIS Enterprise Setup](IRIS_ENTERPRISE_SETUP_GUIDE.md)** - Production IRIS configuration
- **[IntegratedML Support](INTEGRATEDML_SUPPORT.md)** - ML model integration
- **[IntegratedML Configuration](INTEGRATEDML_CONFIGURATION.md)** - ML setup guide

---

## 🏗️ Architecture & Design

- **[Architecture Overview](ARCHITECTURE.md)** - System design, dual backend, components
- **[Performance Benchmarks](PERFORMANCE.md)** - ~4ms overhead, HNSW indexes, test results
- **[Roadmap & Limitations](ROADMAP.md)** - Current status, future enhancements, known issues

**Detailed Architecture**:
- [Dual-Path Architecture](architecture/DUAL_PATH_ARCHITECTURE.md) - DBAPI vs Embedded execution
- [IRIS Constructs](architecture/IRIS_CONSTRUCTS_IMPLEMENTATION.md) - IRIS-specific SQL handling
- [REST API Strategy](architecture/REST_API_STRATEGY.md) - API design patterns
- [Translation API](architecture/TRANSLATION_API.md) - SQL translation layer

---

## 👨‍💻 Development

### Contributing
- **[Developer Guide](developer_guide.md)** - Development setup, contribution guidelines
- **[Testing Guide](testing.md)** - Test framework, validation, contract tests
- **[Development Setup](DEVELOPMENT.md)** - Local development environment

### Release & Quality
- **[PyPI Release Process](PYPI_RELEASE.md)** - Package publishing workflow
- **[Pre-Commit Setup](PRE_COMMIT_SETUP.md)** - Code quality hooks

---

## 🔧 Troubleshooting

Common issues and solutions:

- [Kerberos Issues](troubleshooting/KERBEROS_TROUBLESHOOTING.md) - Authentication problems
- [OAuth Configuration](troubleshooting/OAUTH_TROUBLESHOOTING.md) - OAuth 2.0 setup
- [IRIS Wallet](troubleshooting/WALLET_TROUBLESHOOTING.md) - Credential storage issues
- [Package Naming](troubleshooting/INTERSYSTEMS_PACKAGE_NAMING_ISSUE.md) - Import errors

---

## 🔬 Investigations & Research

Historical context and deep-dives (for maintainers):

### Client Compatibility
- [AsyncPG Fix Summary](investigations/ASYNCPG_FIX_SUMMARY.md) - Savepoint handling
- [AsyncPG Final Status](investigations/ASYNCPG_FINAL_STATUS.md) - 100% compatibility achieved
- [Column Alias Investigation](investigations/COLUMN_ALIAS_INVESTIGATION.md) - JDBC compatibility
- [PostgreSQL Compatibility](investigations/POSTGRESQL_COMPATIBILITY.md) - Protocol audit

### Performance
- [COPY Performance](investigations/COPY_PERFORMANCE_INVESTIGATION.md) - Bulk operations
- [HNSW Investigation](investigations/HNSW_INVESTIGATION.md) - Vector index performance
- [HNSW Findings](investigations/HNSW_FINDINGS_2025_10_02.md) - Production results

### Architecture Decisions
- [Protocol Completeness Audit](investigations/PROTOCOL_COMPLETENESS_AUDIT.md) - Feature coverage
- [Competitive Analysis](investigations/COMPETITIVE_ANALYSIS.md) - Market comparison
- [IRIS SQL Analysis](investigations/IRIS_SQL_ANALYSIS.md) - SQL dialect differences

### Integration Research
- [LangChain Integration](investigations/LANGCHAIN_INTEGRATION.md) - RAG framework support
- [IntegratedML Analysis](investigations/INTEGRATEDML_ANALYSIS.md) - ML capabilities
- [IRIS Document Database](investigations/IRIS_DOCUMENT_DATABASE_RESEARCH.md) - NoSQL features

### Development History
- [Recent Developments](investigations/RECENT_DEVELOPMENTS.md) - Changelog
- [Research Backlog](investigations/RESEARCH_BACKLOG.md) - Future topics
- [Debugging Investigation](investigations/DEBUGGING_INVESTIGATION_2025_10_03.md) - Bug fixes

---

## 📖 Quick Reference

### Most Important Docs (Start Here)
1. [Installation](INSTALLATION.md) - Get started in 60 seconds
2. [Quick Start Examples](QUICKSTART_EXAMPLES.md) - First queries
3. [Features Overview](FEATURES_OVERVIEW.md) - What can it do?
4. [Client Compatibility](CLIENT_RECOMMENDATIONS.md) - Which client should I use?

### Common Tasks
- **Run first query**: [Quick Start Examples](QUICKSTART_EXAMPLES.md)
- **Connect BI tool**: [BI Tools Setup](BI_TOOLS.md)
- **Vector similarity search**: [Vector Operations](VECTOR_PARAMETER_BINDING.md)
- **Use with Prisma/SQLAlchemy**: [pg_catalog Support](PG_CATALOG.md)
- **Production deployment**: [Deployment Guide](DEPLOYMENT.md)
- **Performance tuning**: [Performance Benchmarks](PERFORMANCE.md)

### For Contributors
- [Developer Guide](developer_guide.md) - Setup and workflow
- [Testing Guide](testing.md) - Run and write tests
- [Architecture Overview](ARCHITECTURE.md) - Understand the system

---

## 🔗 External Resources

- **Main Repository**: https://github.com/intersystems-community/iris-pgwire
- **IRIS Documentation**: https://docs.intersystems.com/iris/
- **PostgreSQL Protocol**: https://www.postgresql.org/docs/current/protocol.html
- **pgvector**: https://github.com/pgvector/pgvector

---

**Questions?** Open an issue on [GitHub](https://github.com/intersystems-community/iris-pgwire/issues)
