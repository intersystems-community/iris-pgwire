# Apache Superset 4 with IRIS Backend - Complete Scenarios

This example demonstrates **4 different architectures** for connecting Apache Superset 4 to InterSystems IRIS, each testing different combinations of metadata and data source connectivity.

## 🎯 Four Complete Scenarios Implemented

| Scenario | Metadata | Data | Port | Status | Best For |
|----------|----------|------|------|--------|----------|
| **[A](README.md#scenario-a-default)** | PostgreSQL | IRIS (PGWire) | 8088 | ✅ **Production Ready** | **PGWire Demo** |
| **[B](scenario-b/README.md)** | PostgreSQL | IRIS (Native) | 8089 | ✅ Implemented | **IRIS Performance** |
| **[C](scenario-c/README.md)** | IRIS (PGWire) | IRIS (PGWire) | 8090 | ⚠️ Experimental | **PGWire Stress Test** |
| **[D](scenario-d/README.md)** | IRIS (Native) | IRIS (Native) | 8091 | ⚠️ Experimental | **Pure IRIS** |

**See [SCENARIOS_COMPARISON.md](SCENARIOS_COMPARISON.md) for detailed comparison and decision guide.**

---

## Scenario A (Default): PostgreSQL Metadata + PGWire Data

**This is the primary demo** - Superset connects to IRIS using standard PostgreSQL drivers via PGWire. From Superset's perspective, IRIS appears as a PostgreSQL 16-compatible database.

## What's Included

- **2 Healthcare Tables**: `Patients` (250 records) and `LabResults` (400 records)
- **Synthetic Healthcare Data**: Realistic patient demographics and lab test results
- **SQL Initialization Scripts**: Schema creation and data population
- **Docker Compose Setup**: Complete stack (IRIS + PGWire + Superset + PostgreSQL + Redis)
- **Documentation**: Setup guides, example queries, troubleshooting tips

## Prerequisites

- Docker and Docker Compose installed
- At least 4GB free RAM
- IRIS license key (for VECTOR operations, optional for this demo)

## Quick Start (3 Steps)

### 1. Start Services

```bash
# From repository root
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               up -d

# Alternatively, use the provided script (if available):
# ./examples/superset-iris-healthcare/start-example.sh
```

### 2. Wait for Initialization (2-3 minutes)

The init script will:
- Upgrade Superset metadata database
- Create admin user (admin/admin)
- Initialize Superset
- Wait for IRIS and PGWire to be ready

Monitor progress:
```bash
docker-compose logs -f superset
```

Look for: `✅ Superset initialization complete!`

### 3. Access Superset

Open browser: **http://localhost:8088**

Login:
- **Username**: `admin`
- **Password**: `admin`

**⚠️ SECURITY WARNING**: These credentials are for DEMO PURPOSES ONLY. Change them immediately if using in any non-demo environment.

## What You'll Do

1. **Load Healthcare Data into IRIS** (via SQL)
2. **Configure Database Connection** (Superset → PGWire → IRIS)
3. **Create Datasets** (Patients and LabResults tables)
4. **Build Charts** (Bar, Line, Pie, Table visualizations)
5. **Assemble Dashboard** (Healthcare Overview)
6. **Query with SQL Lab** (Execute SQL directly against IRIS)

All of this works because **PGWire translates PostgreSQL wire protocol to IRIS SQL**.

## Connection Details

When configuring Superset's PostgreSQL connection:

| Setting | Value | Notes |
|---------|-------|-------|
| **Connection Type** | PostgreSQL | Standard PostgreSQL driver |
| **Host** | `iris` | Inside Docker network |
| **Host** | `localhost` | Outside Docker (if port forwarded) |
| **Port** | `5432` | PGWire PostgreSQL wire protocol port |
| **Database** | `USER` | IRIS namespace |
| **Username** | `test_user` | PGWire configured user |
| **Password** | *(blank)* | Or configured password |

**Key Point**: Superset uses its standard PostgreSQL connector - no IRIS-specific configuration needed!

## Step-by-Step Setup Guide

See [docs/SETUP.md](./docs/SETUP.md) for detailed walkthrough with screenshots and troubleshooting.

## Example SQL Queries

See [docs/QUERIES.md](./docs/QUERIES.md) for example queries you can run in Superset SQL Lab to validate IRIS connectivity.

## Troubleshooting

See [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md) for common issues and solutions.

## Expected Setup Time

**< 10 minutes** from `docker-compose up` to viewing your first chart in Superset

Breakdown:
- 2-3 minutes: Container startup and Superset initialization
- 2 minutes: Load healthcare data into IRIS
- 2 minutes: Configure database connection in Superset
- 3 minutes: Create first dataset and chart

## Architecture

```
┌─────────────────┐
│  Superset 4     │  (Uses standard PostgreSQL driver)
│  (BI Platform)  │
└────────┬────────┘
         │ PostgreSQL Wire Protocol (port 5432)
         │
┌────────▼────────┐
│    PGWire       │  (Protocol translator)
│  (Embedded in   │
│   IRIS Process) │
└────────┬────────┘
         │ IRIS Embedded Python
         │
┌────────▼────────┐
│  IRIS Database  │  (Healthcare data storage)
└─────────────────┘
```

## Data Model

### Patients Table
- 250 synthetic patient records
- Status: Active (70%), Discharged (25%), Deceased (5%)
- Demographics: Name, DOB, Gender, Admission/Discharge dates

### LabResults Table
- 400 synthetic lab test results
- Test Types: Blood Glucose, Hemoglobin A1C, Total Cholesterol, Blood Pressure
- Result Status: Normal (70%), Abnormal (25%), Critical (5%)
- Foreign key relationship to Patients table

## All Scenario Documentation

### Quick Links
- **[Scenarios Comparison](SCENARIOS_COMPARISON.md)** - Complete comparison matrix and decision guide
- **[Scenario A](README.md)** - PostgreSQL metadata + PGWire data (this document)
- **[Scenario B](scenario-b/README.md)** - PostgreSQL metadata + Native IRIS data
- **[Scenario C](scenario-c/README.md)** - IRIS via PGWire for both metadata and data
- **[Scenario D](scenario-d/README.md)** - Native IRIS for both metadata and data

### Testing
- **[Test Suite](test-all-scenarios.sh)** - Automated testing for all scenarios

### Additional Documentation
- **[Connection Options Analysis](docs/CONNECTION_OPTIONS.md)** - Detailed architectural analysis
- **[Setup Guide](docs/SETUP.md)** - Step-by-step setup walkthrough
- **[Example Queries](docs/QUERIES.md)** - SQL Lab queries to validate connectivity
- **[Troubleshooting](docs/TROUBLESHOOTING.md)** - Common issues and solutions

## Further Reading

- [PGWire PostgreSQL Wire Protocol](https://www.postgresql.org/docs/current/protocol.html)
- [Apache Superset Documentation](https://superset.apache.org/docs/intro)
- [InterSystems IRIS Documentation](https://docs.intersystems.com/)

## Cleanup

```bash
# Stop all services
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               down

# Stop and remove volumes (deletes all data)
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               down -v
```

## License

See main repository [LICENSE](../../LICENSE) file.
