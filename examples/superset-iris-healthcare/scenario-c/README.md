# Scenario C: IRIS via PGWire for Metadata + Data

## Overview

**Configuration**: IRIS via PGWire for Both Metadata and Data Source

**What This Demonstrates**:
- Superset metadata stored in **IRIS SUPERSET_META** namespace (via PGWire)
- Data source in **IRIS USER** namespace (via PGWire)
- **Single database system** (IRIS for everything, no PostgreSQL)
- **STRESS TEST** for PGWire PostgreSQL compatibility

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
    ┌────▼───────┐       ┌────▼──────────┐
    │ psycopg2   │       │ psycopg2      │
    └────┬───────┘       └────┬──────────┘
         │                    │
    ┌────▼────────────────────▼──────────┐
    │       PGWire Server                │
    │       (Protocol Translator)        │
    └────┬────────────────────┬──────────┘
         │                    │
    ┌────▼────────┐      ┌────▼──────────┐
    │ IRIS        │      │ IRIS          │
    │ SUPERSET_   │      │ USER          │
    │ META        │      │ (Healthcare)  │
    │ (Metadata)  │      │               │
    └─────────────┘      └───────────────┘
```

## ⚠️ Critical Requirements

### IRIS Namespace Setup

**MANUAL STEP REQUIRED**: Create SUPERSET_META namespace in IRIS before starting.

**Via IRIS Management Portal**:
1. Navigate to: http://localhost:52773/csp/sys/UtilHome.csp
2. Login: _SYSTEM / SYS
3. System Administration → Configuration → System Configuration → Namespaces
4. Click "Create New Namespace"
5. Name: `SUPERSET_META`
6. Click "Save"

**Why Required**: PGWire may not support `CREATE DATABASE` DDL for IRIS namespace creation.

## Quick Start

### 1. Create IRIS Namespace (One-Time Setup)

Follow the manual steps above to create SUPERSET_META namespace.

### 2. Start Services

```bash
# From iris-pgwire root directory
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.scenario-c.yml \
               up -d
```

### 3. Monitor Initialization (3-5 minutes)

```bash
docker-compose logs -f superset-scenario-c
```

**Watch For**:
- ✅ "SUPERSET_META accessible"
- ✅ "Database upgrade completed successfully"
- ✅ "Scenario C Initialization Complete!"

**If Errors**:
- Check SUPERSET_META namespace exists
- Review logs for PGWire compatibility issues
- See Troubleshooting section below

### 4. Access Superset

- **URL**: http://localhost:8090
- **Username**: admin
- **Password**: admin (DEMO CREDENTIALS ONLY)

## Connection Details

| Component | Connection String |
|-----------|-------------------|
| **Superset Metadata** | `postgresql://superset_user@iris:5432/SUPERSET_META` |
| **Data Source** | `postgresql://test_user@iris:5432/USER` |
| **Driver** | psycopg2 (PostgreSQL) |
| **Port** | 5432 (PGWire) |
| **Backend** | IRIS (dual namespace) |

## Pros & Cons

### ✅ Advantages

- **Single Database System**: IRIS hosts everything (simpler deployment)
- **No PostgreSQL Container**: Reduced infrastructure complexity
- **Demonstrates PGWire Capability**: Proves PGWire can handle ORM operations
- **Cost Savings**: One database license vs two

### ❌ Disadvantages

- **High Risk**: PGWire must support ALL Superset metadata operations
- **Complex ORM Requirements**: SQLAlchemy migrations, constraints, indexes
- **INFORMATION_SCHEMA Dependency**: Must work correctly for introspection
- **Manual Namespace Setup**: Cannot auto-create IRIS namespaces via DDL
- **Performance Overhead**: Metadata operations also go through PGWire (~4ms)

## What This Tests

### PGWire Compatibility Requirements

Scenario C validates PGWire's ability to handle:

1. **DDL Operations** (via SQLAlchemy ORM):
   - CREATE TABLE with complex constraints
   - ALTER TABLE operations
   - CREATE INDEX statements
   - Foreign key relationships

2. **INFORMATION_SCHEMA Queries**:
   - Table metadata introspection
   - Column metadata retrieval
   - Index information queries
   - Constraint information

3. **Transaction Management**:
   - BEGIN/COMMIT for metadata changes
   - ROLLBACK on errors
   - Isolation level handling

4. **Data Type Mapping**:
   - PostgreSQL → IRIS type conversion
   - OID compatibility
   - Enum type handling

### Likely Failure Points

Based on CONNECTION_OPTIONS.md analysis, expect challenges with:

- **IRIS DDL Differences**: IRIS may not support all PostgreSQL DDL syntax
- **INFORMATION_SCHEMA Gaps**: IRIS schema may differ from PostgreSQL
- **Constraint Enforcement**: Foreign key behavior may differ
- **Sequence/Serial Types**: Auto-increment handling

## Troubleshooting

### Database Upgrade Fails

**Symptom**: `superset db upgrade` fails with errors

**Possible Causes**:
1. SUPERSET_META namespace doesn't exist
2. PGWire doesn't support required DDL operations
3. IRIS/PostgreSQL schema incompatibility

**Solutions**:
```bash
# Check namespace exists
docker exec iris-pgwire-db irissql USER \
  "SELECT Namespace FROM %Library.Namespace WHERE Namespace='SUPERSET_META'"

# Check PGWire logs for errors
docker-compose logs iris | grep -i error

# Try Scenario A or B instead (proven stable)
```

### Connection Refused to SUPERSET_META

**Symptom**: "Could not connect to server"

**Check PGWire Namespace Support**:
```bash
# Test connection to SUPERSET_META
psql -h localhost -p 5432 -U superset_user -d SUPERSET_META -c 'SELECT 1'

# If fails, namespace may not be configured for PGWire access
```

### Tables Not Created

**Symptom**: Superset UI loads but shows errors

**Check Metadata Tables**:
```bash
# List tables in SUPERSET_META
psql -h localhost -p 5432 -U superset_user -d SUPERSET_META -c '\dt'

# Should see: dashboards, slices, tables, databases, etc.
```

## Comparison to Other Scenarios

| Feature | Scenario A | Scenario B | Scenario C | Scenario D |
|---------|------------|------------|------------|------------|
| **Metadata Backend** | PostgreSQL | PostgreSQL | IRIS (PGWire) | IRIS (native) |
| **Data Backend** | IRIS (PGWire) | IRIS (native) | IRIS (PGWire) | IRIS (native) |
| **Containers** | 3 (PG + Redis + Superset) | 2 (Redis + Superset) | 2 (Redis + Superset) | 2 (Redis + Superset) |
| **PGWire Stress** | Low (data only) | None | **HIGH** (metadata + data) | None |
| **Setup Complexity** | Low | Medium | **High** | **High** |
| **Risk Level** | Low | Low | **High** | **Medium** |

## Use Cases

**Best For**:
- Testing PGWire's comprehensive PostgreSQL compatibility
- Organizations wanting all-IRIS deployment
- Validating PGWire for production metadata operations
- Research/development scenarios

**Not Recommended For**:
- Production deployments (too risky)
- Time-critical implementations (use Scenario A)
- Environments where proven stability is required

## Expected Outcomes

### If Successful

**Proves**:
- PGWire fully supports PostgreSQL ORM operations
- IRIS can replace PostgreSQL for Superset metadata
- All-IRIS deployment is viable

**Benefits**:
- Simplified architecture (one database system)
- Reduced infrastructure costs
- Validates PGWire production readiness

### If Fails

**Indicates**:
- PGWire has PostgreSQL compatibility gaps
- IRIS metadata operations need work
- Scenario A or B recommended for production

**Actionable Insights**:
- Specific DDL operations not supported
- INFORMATION_SCHEMA differences
- Areas for PGWire improvement

## Clean Up

```bash
# Stop Scenario C services
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.scenario-c.yml \
               down

# Optionally delete SUPERSET_META namespace via IRIS Management Portal
```

## Next Steps

- Monitor initialization logs carefully
- Document any PGWire compatibility issues
- Compare performance to Scenario A (baseline)
- Test Scenario D (native IRIS for comparison)
- Report findings to PGWire development team
