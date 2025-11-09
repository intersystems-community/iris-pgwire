# Scenario B: Native IRIS Driver for Data Source

## Overview

**Configuration**: PostgreSQL Metadata + IRIS Native Driver for Data Source

**What This Demonstrates**:
- Superset metadata stored in PostgreSQL (proven stability)
- Data source uses **native IRIS SQLAlchemy driver** (iris:// URI)
- Direct connection to IRIS on port **1972** (no PGWire translation)
- Optimal IRIS performance without protocol overhead

## Architecture

```
┌─────────────────┐
│  Superset UI    │
└────────┬────────┘
         │
    ┌────▼────────────────────────┐
    │  Superset Application       │
    │  (SQLAlchemy Core)          │
    └────┬────────────────────┬───┘
         │                    │
         │ Metadata           │ Data Queries
         │ (ORM)              │ (Core)
         │                    │
    ┌────▼───────┐       ┌────▼─────────────────┐
    │ PostgreSQL │       │ IRIS SQLAlchemy      │
    │ (metadata) │       │ Dialect              │
    └────────────┘       │ (intersystems-iris)  │
                         └────┬─────────────────┘
                              │
                         ┌────▼──────────┐
                         │ IRIS Database │
                         │ (Direct       │
                         │  Connection)  │
                         └───────────────┘
```

## Quick Start

### 1. Start Services

```bash
# From iris-pgwire root directory
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.scenario-b.yml \
               up -d
```

### 2. Wait for Initialization (2-3 minutes)

```bash
docker-compose logs -f superset-scenario-b
```

Look for: `✅ Scenario B Initialization Complete!`

### 3. Access Superset

- **URL**: http://localhost:8089
- **Username**: admin
- **Password**: admin (DEMO CREDENTIALS ONLY)

### 4. Verify IRIS Connection

Navigate to: **Settings** → **Database Connections** → **IRIS Healthcare (Native Driver - Scenario B)**

Click **Test Connection** - Expected: "Connection looks good!"

## Connection Details

| Parameter | Value |
|-----------|-------|
| **Database Type** | Other |
| **SQLAlchemy URI** | `iris://_SYSTEM:SYS@iris:1972/USER` |
| **Driver** | sqlalchemy-intersystems-iris |
| **Port** | 1972 (IRIS SuperServer) |
| **Mechanism** | Direct IRIS connection |

## Pros & Cons

### ✅ Advantages

- **Native Performance**: No PGWire translation overhead (~4ms saved)
- **Full IRIS Features**: All IRIS SQL features supported
- **Official Support**: Backed by InterSystems
- **Direct Connection**: Simpler architecture (fewer layers)

### ❌ Disadvantages

- **IRIS-Specific Driver**: Requires sqlalchemy-intersystems-iris installation
- **Not PostgreSQL**: Doesn't demonstrate PostgreSQL ecosystem compatibility
- **Port 1972 Required**: Must expose IRIS SuperServer port
- **Superset Dependency**: Superset must support `iris://` URI scheme

## Comparison to Scenario A

| Feature | Scenario A (PGWire) | Scenario B (Native IRIS) |
|---------|---------------------|--------------------------|
| **Data Source Port** | 5432 (PGWire) | 1972 (IRIS SuperServer) |
| **Driver** | psycopg2 (PostgreSQL) | sqlalchemy-intersystems-iris |
| **Connection String** | `postgresql://...` | `iris://...` |
| **Protocol Overhead** | ~4ms translation | 0ms (direct) |
| **PostgreSQL Compatibility** | ✅ Demonstrates | ❌ Bypasses |
| **IRIS Feature Support** | Limited by PGWire | ✅ Full access |
| **Setup Complexity** | Low (standard driver) | Medium (custom driver) |

## Testing Queries

All queries from Scenario A work identically:

```sql
-- Patient count by status
SELECT Status, COUNT(*) as patient_count
FROM Patients
GROUP BY Status
ORDER BY patient_count DESC;

-- Recent lab results with patient names
SELECT
    lr.ResultID,
    lr.TestName,
    lr.TestDate,
    p.FirstName || ' ' || p.LastName as patient_name
FROM LabResults lr
JOIN Patients p ON lr.PatientID = p.PatientID
ORDER BY lr.TestDate DESC
LIMIT 10;
```

**Expected Performance**: Queries should be ~4ms faster than Scenario A (no PGWire overhead).

## Troubleshooting

### Connection Test Fails

**Symptom**: "Could not connect to server"

**Check IRIS Accessibility**:
```bash
# Verify IRIS port 1972 is accessible
docker exec iris-pgwire-superset-scenario-b nc -zv iris 1972

# Expected: "iris:1972 open"
```

**Check Driver Installation**:
```bash
docker exec iris-pgwire-superset-scenario-b pip show sqlalchemy-intersystems-iris

# Should show package version
```

### Tables Not Found

**Symptom**: "Table 'Patients' does not exist"

**Load Schema** (via IRIS Management Portal):
1. Navigate to http://localhost:52773/csp/sys/UtilHome.csp
2. Login: _SYSTEM / SYS
3. SQL → Execute Query
4. Execute: `/app/data/init-healthcare-schema.sql`
5. Execute: `/app/data/patients-data.sql`
6. Execute: `/app/data/labresults-data.sql`

Or use PGWire from Scenario A to load data.

## Use Cases

**Best For**:
- Performance-critical analytics workloads
- Organizations already using IRIS-specific features
- Testing native IRIS performance vs PGWire overhead
- Scenarios where PostgreSQL compatibility is not required

**Not Recommended For**:
- Demonstrating PostgreSQL ecosystem access
- Environments where IRIS-specific drivers can't be installed
- Multi-database setups requiring standard drivers
- PostgreSQL migration validation

## Clean Up

```bash
# Stop Scenario B services
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.scenario-b.yml \
               down

# Remove volumes (deletes all Superset config)
docker volume rm iris-pgwire-superset-postgres-scenario-b
```

## Next Steps

- Compare performance to Scenario A (PGWire)
- Test IRIS-specific SQL features not available in PostgreSQL
- Explore Scenario C (IRIS for both metadata and data via PGWire)
- Explore Scenario D (IRIS native for both metadata and data)
