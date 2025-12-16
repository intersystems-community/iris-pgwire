# Open Exchange Submission Metadata

**Feature**: 027-open-exchange
**Date**: 2024-12-13
**Status**: Ready for submission

## Package Information

| Field | Value |
|-------|-------|
| **Title** | IRIS PGWire |
| **Package Name** | iris-pgwire |
| **Version** | 0.1.0 |
| **License** | MIT |

## Short Description (197 characters)

```
PostgreSQL wire protocol server for InterSystems IRIS. Connect any PostgreSQL client to IRIS - psql, DBeaver, Superset, psycopg3, JDBC, and more. Includes pgvector-compatible vector operations.
```

## Long Description

```
IRIS PGWire enables you to connect any PostgreSQL-compatible tool to InterSystems IRIS without custom drivers.

**Key Features:**
- Full PostgreSQL wire protocol v3 support
- pgvector-compatible operators (<=> cosine, <#> dot product)
- Enterprise authentication (OAuth 2.0, SCRAM-SHA-256, IRIS Wallet)
- 171 tests passing across 8 programming languages

**Supported Clients:**
- BI Tools: Apache Superset, Metabase, Grafana
- Python: psycopg3, asyncpg, SQLAlchemy, pandas
- Java: PostgreSQL JDBC, Spring Data JPA, Hibernate
- Node.js, Go, .NET, Ruby, Rust, PHP

**Quick Start:**
```objectscript
zpm "install iris-pgwire"
do ##class(IrisPGWire.Service).Start()
```

Then connect: `psql -h localhost -p 5432 -U _SYSTEM -d USER`
```

## Categories

- Database
- Connectivity
- Developer Tools
- Data Integration

## Keywords

```
postgresql, pgwire, vector, pgvector, connectivity, wire-protocol, postgres, sql, database, iris, intersystems, bi-tools, superset, metabase, grafana
```

## Platforms

- Docker
- Linux
- macOS

## Requirements

| Requirement | Value |
|-------------|-------|
| **IRIS Version** | 2024.1 or later |
| **Python Version** | 3.11+ (embedded in IRIS) |
| **ZPM Version** | Latest recommended |

## Repository

| Field | Value |
|-------|-------|
| **URL** | https://github.com/isc-tdyar/iris-pgwire |
| **Documentation** | README.md, docs/ directory |
| **Issues** | GitHub Issues |

## Author Information

| Field | Value |
|-------|-------|
| **Author** | Thomas Dyar |
| **Organization** | InterSystems |
| **Email** | thomas.dyar@intersystems.com |

## Installation Instructions (for OEX page)

### Via ZPM (Recommended)

```objectscript
zpm "install iris-pgwire"
do ##class(IrisPGWire.Service).Start()
```

### Via Docker

```bash
git clone https://github.com/isc-tdyar/iris-pgwire.git
cd iris-pgwire
docker-compose up -d
```

## Screenshots/Visuals

The README.md includes an ASCII architecture diagram showing:
- PostgreSQL clients connecting on port 5432
- IRIS PGWire Server with wire protocol handler, query parser, and vector translation
- IRIS database backend with SQL engine and vector support

## Test Results

- **Total Tests**: 171+
- **Languages Tested**: Python, Node.js, Java, .NET, Go, Ruby, Rust, PHP
- **ZPM Package Tests**: 21 (all passing)
- **Test Coverage**: Wire protocol, authentication, vector operations, COPY protocol, transactions

## Submission Checklist

- [x] Package name is unique on Open Exchange
- [x] GitHub repository is public
- [x] README.md is comprehensive
- [x] LICENSE file is MIT
- [x] module.xml is valid and tested
- [x] No auto-start on installation (manual start required)
- [x] IRIS 2024.1+ requirement documented
- [x] All tests passing
