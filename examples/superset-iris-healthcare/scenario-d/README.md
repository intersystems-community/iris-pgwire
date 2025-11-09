# Scenario D: Native IRIS for Metadata + Data

## Overview

**Configuration**: Pure IRIS Deployment (Native Driver for Everything)

**What This Demonstrates**:
- Superset metadata stored in **IRIS SUPERSET_META** namespace (native driver)
- Data source in **IRIS USER** namespace (native driver)
- **Zero protocol overhead** (no PGWire translation)
- **Optimal IRIS performance** with full feature access

## Architecture

```
┌─────────────────┐
│  Superset UI    │
└────────┬────────┘
         │
    ┌────▼────────────────────────┐
    │  Superset Application       │
    │  (SQLAlchemy Core + ORM)    │
    └────┬────────────────────┬───┘
         │                    │
         │ Metadata           │ Data Queries
         │ (ORM)              │ (Core)
         │                    │
    ┌────▼────────────────────▼──────────┐
    │    IRIS SQLAlchemy Dialect         │
    │    (intersystems-iris)             │
    └────┬────────────────────┬──────────┘
         │                    │
    ┌────▼────────┐      ┌────▼──────────┐
    │ IRIS        │      │ IRIS          │
    │ SUPERSET_   │      │ USER          │
    │ META        │      │ (Healthcare)  │
    │ (Metadata)  │      │               │
    └─────────────┘      └───────────────┘
```

## Key Features

### ✅ Maximum Performance
- **Zero PGWire overhead**: ~4ms saved per query vs Scenario A/C
- **Direct IRIS connection**: No protocol translation layer
- **Optimal throughput**: Native driver optimizations

### ✅ Full IRIS Feature Access
- **VECTOR operations**: Native IRIS vector support
- **IRIS-specific SQL**: Access all IRIS SQL extensions
- **Advanced features**: Bitmaps, embedded Python, etc.

### ⚠️ Compatibility Risk
- **IRIS SQL vs PostgreSQL**: May have dialect differences
- **Superset metadata schema**: Requires IRIS compatibility
- **SQLAlchemy dialect maturity**: Depends on driver completeness

## Prerequisites

### IRIS Namespace Setup

**MANUAL STEP REQUIRED**: Create SUPERSET_META namespace before starting.

**Via IRIS Management Portal**:
1. Navigate to: http://localhost:52773/csp/sys/UtilHome.csp
2. Login: _SYSTEM / SYS
3. System Administration → Configuration → System Configuration → Namespaces
4. Click "Create New Namespace"
5. Name: `SUPERSET_META`
6. Database: Create new database with same name
7. Click "Save"

## Quick Start

### 1. Create IRIS Namespace (One-Time)

Follow prerequisites above to create SUPERSET_META.

### 2. Start Services

```bash
# From iris-pgwire root directory
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.scenario-d.yml \
               up -d
```

### 3. Monitor Initialization (3-5 minutes)

```bash
docker-compose logs -f superset-scenario-d
```

**Watch For**:
- ✅ "IRIS driver installed successfully"
- ✅ "SUPERSET_META accessible"
- ✅ "Database upgrade completed successfully"
- ✅ "Scenario D Initialization Complete!"

### 4. Access Superset

- **URL**: http://localhost:8091
- **Username**: admin
- **Password**: admin (DEMO CREDENTIALS ONLY)

## Connection Details

| Component | Connection String |
|-----------|-------------------|
| **Superset Metadata** | `iris://_SYSTEM:SYS@iris:1972/SUPERSET_META` |
| **Data Source** | `iris://_SYSTEM:SYS@iris:1972/USER` |
| **Driver** | sqlalchemy-intersystems-iris |
| **Port** | 1972 (IRIS SuperServer) |
| **Backend** | IRIS (dual namespace) |

## Pros & Cons

### ✅ Advantages

- **Optimal Performance**: Zero protocol translation overhead
- **Simplest Architecture**: Fewest containers (no PostgreSQL, no PGWire)
- **Full IRIS Features**: Complete access to IRIS SQL capabilities
- **Single Vendor**: One database system (IRIS for everything)
- **Best for IRIS Shops**: Organizations fully committed to IRIS

### ❌ Disadvantages

- **Highest Risk**: IRIS SQL must be fully compatible with Superset
- **Driver Dependency**: Requires sqlalchemy-intersystems-iris maturity
- **No PostgreSQL Layer**: Can't leverage PGWire compatibility
- **Manual Setup**: Namespace creation requires Management Portal
- **Compatibility Unknown**: May discover IRIS/PostgreSQL SQL differences

## What This Tests

### IRIS SQL Compatibility

Scenario D validates IRIS's native SQL compatibility with:

1. **Superset Metadata DDL**:
   - Complex table structures
   - Foreign key constraints
   - Index creation
   - Enum types (if used)

2. **SQLAlchemy ORM Operations**:
   - Object creation/updates
   - Relationship traversal
   - Query generation
   - Migration framework

3. **IRIS-Specific Behaviors**:
   - Date/time handling
   - String functions
   - Aggregate operations
   - Transaction isolation

## Comparison to All Scenarios

| Feature | Scenario A | Scenario B | Scenario C | Scenario D |
|---------|------------|------------|------------|------------|
| **Metadata** | PostgreSQL | PostgreSQL | IRIS (PGWire) | **IRIS (native)** |
| **Data** | IRIS (PGWire) | IRIS (native) | IRIS (PGWire) | **IRIS (native)** |
| **Performance** | ~4ms overhead | Optimal data | ~4ms overhead | **Optimal** |
| **PGWire Usage** | Data only | None | Both | **None** |
| **Containers** | 3 | 2 | 2 | **2** |
| **Setup** | Easy | Medium | Hard | **Hard** |
| **Risk** | Low | Low | High | **Medium** |
| **Best For** | PGWire demo | IRIS perf | PGWire stress | **Pure IRIS** |

## Troubleshooting

### Database Upgrade Fails

**Symptom**: `superset db upgrade` fails with SQL errors

**Likely Causes**:
1. IRIS SQL dialect incompatibility
2. sqlalchemy-intersystems-iris driver bugs
3. Missing IRIS SQL features

**Diagnosis**:
```bash
# Check full upgrade logs
docker-compose logs superset-scenario-d | grep -A 20 "Database upgrade"

# Look for specific SQL errors
```

**Solutions**:
- Try Scenario A (proven stable with PGWire)
- Report issues to sqlalchemy-intersystems-iris project
- Check IRIS SQL documentation for feature support

### Connection Refused to Port 1972

**Symptom**: "Could not connect to server"

**Check IRIS Accessibility**:
```bash
# Test IRIS port
nc -zv localhost 1972

# Verify IRIS is running
docker-compose ps iris
```

### Namespace Not Found

**Symptom**: "Namespace 'SUPERSET_META' does not exist"

**Verify Namespace Exists**:
```bash
# Via IRIS SQL
docker exec iris-pgwire-db irissql USER \
  "SELECT Name FROM %Library.Namespace WHERE Name='SUPERSET_META'"

# Should return: SUPERSET_META
```

## Performance Benchmarking

### Expected Performance Gains

Compared to Scenario A (PGWire baseline):

| Operation | Scenario A | Scenario D | Improvement |
|-----------|------------|------------|-------------|
| **Simple Query** | ~6ms | ~2ms | **3× faster** |
| **Vector Similarity (128D)** | ~10ms | ~6ms | **1.7× faster** |
| **Metadata Read** | ~8ms | ~4ms | **2× faster** |
| **Bulk Insert (100 rows)** | ~50ms | ~30ms | **1.7× faster** |

**Note**: Actual performance depends on IRIS configuration, network, and hardware.

### Benchmark Queries

```sql
-- Simple query
SELECT COUNT(*) FROM Patients;

-- Complex join
SELECT
    p.FirstName, p.LastName,
    COUNT(lr.ResultID) as test_count
FROM Patients p
LEFT JOIN LabResults lr ON p.PatientID = lr.PatientID
GROUP BY p.PatientID, p.FirstName, p.LastName
ORDER BY test_count DESC
LIMIT 10;
```

## Use Cases

**Best For**:
- Organizations fully committed to IRIS ecosystem
- Performance-critical analytics workloads
- Scenarios requiring IRIS-specific features
- Deployments where PostgreSQL compatibility not needed
- Testing sqlalchemy-intersystems-iris driver

**Not Recommended For**:
- PostgreSQL migration validation
- Multi-database heterogeneous environments
- Proving PostgreSQL ecosystem compatibility
- Production (until proven stable)

## Clean Up

```bash
# Stop Scenario D services
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.scenario-d.yml \
               down

# Optionally delete SUPERSET_META namespace via Management Portal
```

## Next Steps

- Compare performance to all other scenarios
- Document any IRIS SQL compatibility issues
- Test IRIS-specific features (VECTOR, embedded Python)
- Report findings to InterSystems
- Evaluate for production use based on stability

## Expected Outcomes

### If Successful ✅

**Proves**:
- IRIS is fully compatible with Superset metadata requirements
- sqlalchemy-intersystems-iris driver is production-ready
- Pure IRIS deployment is viable for BI tools
- IRIS performance optimal without PGWire layer

**Benefits**:
- Simplest possible architecture
- Maximum performance
- Single vendor solution
- Full IRIS feature access

### If Fails ❌

**Indicates**:
- IRIS SQL has compatibility gaps vs PostgreSQL
- sqlalchemy-intersystems-iris needs improvements
- Scenario A or B recommended for production

**Actionable**:
- Document specific SQL compatibility issues
- Report bugs to driver maintainers
- Use PGWire scenarios as fallback
- Consider hybrid approach (Scenario B)

## Recommendations

**Production Deployment Strategy**:
1. **Start with Scenario A** (proven stable, PGWire for data)
2. **Test Scenario D** in development/staging
3. **Compare performance** (D vs A)
4. **If D stable**: Consider migration for performance
5. **If D unstable**: Use Scenario B (native data, PG metadata)

**Risk Mitigation**:
- Thorough testing of all Superset features
- Load testing with production-scale data
- Monitoring for SQL compatibility issues
- Fallback plan to Scenario A if needed
