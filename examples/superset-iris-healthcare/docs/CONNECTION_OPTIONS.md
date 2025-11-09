# Superset + IRIS: Connection Architecture Options

This document compares different ways to connect Apache Superset to InterSystems IRIS, including using IRIS as both a data source and as Superset's metadata backend.

## Background: Two Types of Database Connections in Superset

Superset requires **two distinct database connections**:

1. **Metadata Database** (Superset's internal storage)
   - Stores Superset configuration, dashboards, charts, users, permissions
   - Uses SQLAlchemy ORM for CRUD operations
   - REQUIRED for Superset to function

2. **Data Source Databases** (what users analyze/visualize)
   - The actual data warehouses being queried and visualized
   - Uses SQLAlchemy Core for query execution
   - Optional, added as needed

## Available IRIS SQLAlchemy Drivers

### 1. PGWire (PostgreSQL Wire Protocol)
- **Connection String**: `postgresql://user@host:5432/USER`
- **Driver**: psycopg2 (standard PostgreSQL driver)
- **Port**: 5432 (PGWire server)
- **Mechanism**: PostgreSQL wire protocol → PGWire translator → IRIS
- **Pros**:
  - Uses standard PostgreSQL tooling
  - No IRIS-specific drivers needed
  - Works with entire PostgreSQL ecosystem
  - Demonstrates wire protocol compatibility
- **Cons**:
  - Requires PGWire server running
  - Slight protocol translation overhead (~4ms)
  - Not all PostgreSQL features supported

### 2. Official InterSystems Driver (sqlalchemy-intersystems-iris)
- **Connection String**: `iris://user:password@host:1972/USER`
- **Driver**: intersystems-irispython (official IRIS DB-API driver)
- **Port**: 1972 (IRIS SQL port)
- **Mechanism**: Direct connection to IRIS
- **Pros**:
  - Native IRIS connection (no translation layer)
  - Full IRIS SQL feature support
  - Official InterSystems support
  - Optimal performance
- **Cons**:
  - Requires IRIS-specific driver installation
  - Not demonstrating PostgreSQL compatibility
  - Superset needs to know about `iris://` URI scheme

### 3. Community Driver (caretdev/sqlalchemy-iris)
- **Connection String**: `iris+psycopg://host:5432/USER`
- **Driver**: Hybrid approach (IRIS dialect + psycopg for transport)
- **Port**: Can use 1972 or 5432
- **Mechanism**: IRIS SQLAlchemy dialect with flexible backend
- **Pros**:
  - Combines IRIS features with PostgreSQL compatibility
  - Supports VECTOR operations
  - Active community development
- **Cons**:
  - Third-party driver (not official)
  - Requires understanding of dual-path architecture

## Connection Architecture Matrix

| Scenario | Metadata Backend | Data Source | Use Case | Complexity |
|----------|------------------|-------------|----------|------------|
| **A** | PostgreSQL (separate) | IRIS via PGWire | **Current demo** - Proves PGWire works for BI | Low |
| **B** | PostgreSQL (separate) | IRIS direct (iris://) | Native IRIS performance testing | Medium |
| **C** | IRIS via PGWire | IRIS via PGWire | **All-IRIS** via PostgreSQL compatibility | Medium |
| **D** | IRIS direct (iris://) | IRIS direct (iris://) | **Full native IRIS** deployment | High |

## Scenario A: PGWire for Data Source (Current Demo)

**What it demonstrates**: Superset treating IRIS as PostgreSQL

### Configuration

**Metadata Database** (in docker-compose.superset.yml):
```yaml
postgres:
  image: postgres:16-alpine
  environment:
    - POSTGRES_DB=superset
    - POSTGRES_USER=superset
    - POSTGRES_PASSWORD=superset
```

**Superset Configuration**:
```python
# In superset_config.py or environment
SQLALCHEMY_DATABASE_URI = 'postgresql://superset:superset@postgres:5432/superset'
```

**Data Source Connection** (in Superset UI):
```
Database Type: PostgreSQL
SQLAlchemy URI: postgresql://test_user@iris:5432/USER
```

### Architecture Flow
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
    ┌────▼───────┐       ┌────▼──────────┐
    │ PostgreSQL │       │ psycopg2      │
    │ (metadata) │       │ PostgreSQL    │
    └────────────┘       │ Driver        │
                         └────┬──────────┘
                              │
                         ┌────▼──────────┐
                         │ PGWire Server │
                         │ (Protocol     │
                         │  Translator)  │
                         └────┬──────────┘
                              │
                         ┌────▼──────────┐
                         │ IRIS Database │
                         │ (Healthcare   │
                         │  Data)        │
                         └───────────────┘
```

### Pros
- ✅ Demonstrates PGWire PostgreSQL compatibility
- ✅ Standard PostgreSQL tooling works
- ✅ No IRIS-specific driver installation needed
- ✅ Simple configuration

### Cons
- ❌ Requires PGWire server running
- ❌ Small protocol translation overhead
- ❌ Separate PostgreSQL for metadata (more containers)

## Scenario B: Official IRIS Driver for Data Source

**What it demonstrates**: Native IRIS performance with standard metadata backend

### Configuration

**Metadata Database**: Same as Scenario A (PostgreSQL)

**Data Source Connection** (in Superset UI):
```
Database Type: Other
SQLAlchemy URI: iris://_SYSTEM:SYS@iris:1972/USER
```

**Additional Setup**:
```bash
# Install IRIS driver in Superset container
pip install sqlalchemy-intersystems-iris
```

### Architecture Flow
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

### Pros
- ✅ Native IRIS performance (no PGWire overhead)
- ✅ Full IRIS SQL feature support
- ✅ Official InterSystems driver
- ✅ Direct connection (simpler architecture)

### Cons
- ❌ Requires IRIS-specific driver installation
- ❌ Doesn't demonstrate PostgreSQL compatibility
- ❌ Still uses separate PostgreSQL for metadata

## Scenario C: IRIS via PGWire for Both Metadata and Data

**What it demonstrates**: Complete IRIS deployment using PostgreSQL compatibility

### Configuration

**Superset Configuration**:
```python
# In superset_config.py
SQLALCHEMY_DATABASE_URI = 'postgresql://superset_user@iris:5432/SUPERSET_META'
```

**Data Source Connection** (in Superset UI):
```
Database Type: PostgreSQL
SQLAlchemy URI: postgresql://test_user@iris:5432/USER
```

**IRIS Setup** (requires):
```sql
-- Create metadata namespace
CREATE DATABASE SUPERSET_META;

-- Create healthcare data namespace
CREATE DATABASE USER;
```

### Architecture Flow
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

### Pros
- ✅ Single database system (IRIS for everything)
- ✅ No separate PostgreSQL container needed
- ✅ Demonstrates PGWire handles both ORM and analytics
- ✅ Simpler deployment (fewer containers)

### Cons
- ❌ PGWire must support ALL PostgreSQL features Superset needs
- ❌ Superset metadata operations must work through PGWire
- ❌ Higher risk if PGWire has compatibility issues
- ❌ Performance overhead for metadata operations too

**⚠️ Risk Assessment**: This scenario tests PGWire's compatibility more rigorously, as Superset's metadata operations use complex ORM patterns that may stress PGWire's PostgreSQL compatibility.

## Scenario D: IRIS Direct for Both Metadata and Data

**What it demonstrates**: Pure native IRIS deployment

### Configuration

**Superset Configuration**:
```python
# In superset_config.py
SQLALCHEMY_DATABASE_URI = 'iris://superset_user:password@iris:1972/SUPERSET_META'
```

**Data Source Connection** (in Superset UI):
```
Database Type: Other
SQLAlchemy URI: iris://_SYSTEM:SYS@iris:1972/USER
```

**Additional Setup**:
```bash
# Install IRIS driver in Superset container
pip install sqlalchemy-intersystems-iris
```

### Architecture Flow
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

### Pros
- ✅ Optimal performance (no protocol translation)
- ✅ Single database system (IRIS for everything)
- ✅ Full IRIS SQL feature support
- ✅ Simplest container architecture

### Cons
- ❌ Requires IRIS-specific driver installation
- ❌ Doesn't demonstrate PostgreSQL compatibility
- ❌ Superset metadata schema must be compatible with IRIS
- ❌ Higher risk if IRIS SQL differs from PostgreSQL for metadata ops

**⚠️ Risk Assessment**: This scenario requires that IRIS SQL is fully compatible with Superset's metadata schema requirements, including all DDL, constraints, and features SQLAlchemy uses for the metadata ORM.

## Recommendation: Which Scenario to Implement?

### For **PGWire Demonstration** → Use Scenario A (Current)
- Primary goal: Prove PGWire enables PostgreSQL ecosystem access
- Lower risk: Metadata in proven PostgreSQL, data via PGWire
- Clear separation of concerns
- **Status**: ✅ Already implemented

### For **IRIS Performance Showcase** → Add Scenario B
- Goal: Show native IRIS performance
- Comparison: vs PGWire overhead
- Effort: Medium (requires driver installation doc)
- **Status**: ⏭️ Could add as alternative configuration

### For **Complete PGWire Validation** → Test Scenario C
- Goal: Prove PGWire handles complex ORM operations
- Stress test: Superset metadata operations
- Risk: Medium-High (may expose PGWire limitations)
- **Status**: ⏭️ Advanced demo

### For **Pure IRIS Deployment** → Document Scenario D
- Goal: Reference architecture for IRIS-only shops
- Benefit: Optimal performance + simplicity
- Risk: Requires driver setup + compatibility validation
- **Status**: ⏭️ Documentation only

## Implementation Guide: Adding Scenario B (Native IRIS Driver)

To add the native IRIS driver option to our current demo:

### 1. Update docker-compose.superset.yml

```yaml
superset:
  # ... existing config ...
  environment:
    # Add IRIS driver installation flag
    - INSTALL_IRIS_DRIVER=true
  volumes:
    # Mount installation script
    - ./superset/install-iris-driver.sh:/app/docker/install-iris-driver.sh:ro
```

### 2. Create install-iris-driver.sh

```bash
#!/bin/bash
# Install official IRIS SQLAlchemy driver

if [ "$INSTALL_IRIS_DRIVER" = "true" ]; then
  echo "Installing IRIS SQLAlchemy driver..."
  pip install sqlalchemy-intersystems-iris
  echo "✅ IRIS driver installed"
fi
```

### 3. Document Alternative Connection in SETUP.md

Add section:

```markdown
## Alternative: Native IRIS Connection (Without PGWire)

For direct IRIS connectivity:

**Connection Details**:
- Database Type: Other
- SQLAlchemy URI: `iris://_SYSTEM:SYS@iris:1972/USER`

**Performance**: ~4ms faster (no PGWire translation)
**Trade-off**: Requires IRIS-specific driver
```

## Conclusion

The current demo (Scenario A) is **optimal for demonstrating PGWire's value proposition**: enabling PostgreSQL ecosystem tools to access IRIS.

**For comprehensive coverage**, consider documenting all scenarios with guidance on when each is appropriate:
- **Scenario A**: Production BI tools needing PostgreSQL compatibility
- **Scenario B**: Performance-critical analytics with native IRIS
- **Scenario C**: IRIS-first organizations wanting PostgreSQL ecosystem access
- **Scenario D**: Pure IRIS shops with full InterSystems stack

Each scenario has valid use cases depending on organizational priorities: ecosystem compatibility, performance, simplicity, or IRIS feature access.
