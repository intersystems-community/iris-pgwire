# Superset 4 + IRIS Healthcare Example - Detailed Setup Guide

This guide walks through every step of setting up Apache Superset 4 to query InterSystems IRIS healthcare data through the PGWire PostgreSQL wire protocol.

## Prerequisites Check

Before starting, ensure you have:

- [ ] Docker Engine 20.10+ installed
- [ ] Docker Compose 1.29+ installed
- [ ] At least 4GB free RAM
- [ ] Ports available: 5432 (PGWire), 8088 (Superset), 52773 (IRIS Portal)

```bash
# Verify Docker installation
docker --version
docker-compose --version

# Check available RAM
docker system info | grep "Total Memory"
```

## Section 1: Starting Services (5 minutes)

### 1.1 Start Docker Compose Stack

From the `iris-pgwire` repository root:

```bash
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               up -d
```

Expected output:
```
Creating network "iris-pgwire-network" done
Creating volume "superset-postgres-data" done
Creating iris-pgwire-db ... done
Creating iris-pgwire-superset-db ... done
Creating iris-pgwire-superset-redis ... done
Creating iris-pgwire-superset ... done
```

### 1.2 Monitor Initialization

Watch Superset initialization logs:
```bash
docker-compose logs -f superset
```

Wait for this message (2-3 minutes):
```
✅ Superset initialization complete!

Access Superset at: http://localhost:8088
Username: admin
Password: admin
```

Press `Ctrl+C` to stop following logs.

### 1.3 Verify All Services Running

```bash
docker-compose ps
```

Expected status for all services: **Up** (healthy)

| Service | Status | Port |
|---------|--------|------|
| iris-pgwire-db | Up (healthy) | 1972, 5432, 52773 |
| iris-pgwire-superset | Up (healthy) | 8088 |
| iris-pgwire-superset-db | Up (healthy) | 5432 (internal) |
| iris-pgwire-superset-redis | Up (healthy) | 6379 (internal) |

## Section 2: Load Healthcare Data into IRIS (5 minutes)

### 2.1 Connect to IRIS via psql (through PGWire)

```bash
docker exec -it postgres-client psql \
  -h iris \
  -p 5432 \
  -U test_user \
  -d USER
```

You should see:
```
psql (15.x, server 16.0 (InterSystems IRIS))
Type "help" for help.

USER=>
```

**KEY DEMONSTRATION**: This psql client is talking to IRIS via PGWire, treating it as PostgreSQL!

### 2.2 Load Schema

```sql
-- From psql prompt
\i /path/to/examples/superset-iris-healthcare/data/init-healthcare-schema.sql
```

Or copy-paste the schema SQL from `examples/superset-iris-healthcare/data/init-healthcare-schema.sql`.

Expected output:
```
DROP TABLE
DROP TABLE
CREATE TABLE
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE INDEX
```

### 2.3 Load Patient Data

```sql
-- This will take ~30 seconds for 250 INSERT statements
\i /path/to/examples/superset-iris-healthcare/data/patients-data.sql
```

Expected output:
```
INSERT 0 1
INSERT 0 1
... (250 times)
```

### 2.4 Load Lab Results Data

```sql
-- This will take ~1 minute for 400 INSERT statements
\i /path/to/examples/superset-iris-healthcare/data/labresults-data.sql
```

Expected output:
```
INSERT 0 1
INSERT 0 1
... (400 times)
```

### 2.5 Verify Data Loaded

```sql
-- Check patient count
SELECT COUNT(*) as patient_count FROM Patients;
```

Expected result: `250`

```sql
-- Check lab results count
SELECT COUNT(*) as result_count FROM LabResults;
```

Expected result: `400`

```sql
-- Exit psql
\q
```

## Section 3: Access Superset UI (2 minutes)

### 3.1 Open Superset in Browser

Navigate to: **http://localhost:8088**

You should see the Superset login page.

### 3.2 Login

- **Username**: `admin`
- **Password**: `admin`

Click **Sign In**.

**⚠️ SECURITY REMINDER**: Change this password in production!

### 3.3 Explore Superset Interface

After login, you'll see the Superset home page with:
- **Dashboards** tab (currently empty)
- **Charts** tab (currently empty)
- **SQL Lab** tab (for writing queries)
- **Settings** menu (for database connections)

## Section 4: Configure IRIS Database Connection (3 minutes)

### 4.1 Navigate to Database Connections

1. Click **Settings** (gear icon) in top-right
2. Select **Database Connections** from dropdown

### 4.2 Add New Database

1. Click **+ DATABASE** button (top-right)
2. Select **PostgreSQL** from the database type list

**CRITICAL**: Superset uses standard PostgreSQL driver - no IRIS-specific configuration!

### 4.3 Configure Connection

**SUPPORTED CONNECTION STRING**:
```
postgresql://test_user@iris:5432/USER
```

Or use the form fields:

| Field | Value | Notes |
|-------|-------|-------|
| **Database name** | `IRIS Healthcare` | Display name in Superset |
| **SQLAlchemy URI** | `postgresql://test_user@iris:5432/USER` | Connection string |
| **Expose database in SQL Lab** | ✅ Checked | Enables SQL Lab queries |
| **Allow CREATE TABLE AS** | ✅ Checked | (Optional) |
| **Allow CREATE VIEW AS** | ✅ Checked | (Optional) |
| **Allow DML** | ❌ Unchecked | (Safe for demo) |

**Advanced Settings** (expand):
- **SSL Mode**: `disable` (demo only - use `require` in production)

### 4.4 Test Connection

Click **TEST CONNECTION** button.

Expected result:
```
✅ Connection looks good!
```

If you see this, **PGWire is successfully translating PostgreSQL protocol to IRIS!**

### 4.5 Save Database

Click **CONNECT** button to save the database connection.

## Section 5: Create Datasets (4 minutes)

### 5.1 Navigate to Datasets

1. Click **Data** menu (top nav)
2. Select **Datasets** from dropdown

### 5.2 Create Patients Dataset

1. Click **+ DATASET** button
2. Select:
   - **Database**: `IRIS Healthcare`
   - **Schema**: `SQLUSER` (or default schema)
   - **Table**: `Patients`
3. Click **CREATE DATASET AND CREATE CHART**

Expected result: Dataset created, chart editor opens

### 5.3 Create LabResults Dataset

Repeat the same process for `LabResults`:

1. Navigate back to Datasets page
2. Click **+ DATASET**
3. Select:
   - **Database**: `IRIS Healthcare`
   - **Schema**: `SQLUSER`
   - **Table**: `LabResults`
4. Click **CREATE DATASET AND CREATE CHART**

## Section 6: Create Your First Chart (5 minutes)

### 6.1 Bar Chart: Patient Count by Status

In the chart editor (from Patients dataset):

1. **Chart Type**: Select **Bar Chart**
2. **Query** section:
   - **Dimensions**: Select `Status`
   - **Metrics**: Click **Simple** tab → Select `COUNT(*)`
3. **Customize** section:
   - **Chart Title**: `Patient Count by Status`
   - **X Axis Label**: `Status`
   - **Y Axis Label**: `Patient Count`
   - **Show Value**: ✅ Checked
4. Click **RUN** button (top-right)

Expected result: Bar chart showing Active, Discharged, Deceased counts

### 6.2 Save Chart

1. Click **SAVE** button (top-right)
2. Enter chart name: `Patient Status Distribution`
3. Select **Add to new dashboard**
4. Dashboard name: `Healthcare Overview`
5. Click **SAVE & GO TO DASHBOARD**

Congratulations! You've created your first Superset chart querying IRIS data!

## Section 7: Use SQL Lab (3 minutes)

### 7.1 Navigate to SQL Lab

1. Click **SQL Lab** menu (top nav)
2. Select **SQL Editor** from dropdown

### 7.2 Execute Test Query

1. **Database**: Select `IRIS Healthcare`
2. **Schema**: Select `SQLUSER`
3. In the SQL editor, type:

```sql
SELECT
    Status,
    COUNT(*) as patient_count,
    AVG(EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM DateOfBirth)) as avg_age
FROM Patients
GROUP BY Status
ORDER BY patient_count DESC;
```

4. Click **RUN** button

Expected result: Query executes successfully, results show patient statistics

**KEY DEMONSTRATION**: This SQL query is being translated by PGWire from PostgreSQL to IRIS SQL!

### 7.3 Try More Complex Query

```sql
SELECT
    p.FirstName,
    p.LastName,
    p.Status,
    COUNT(lr.ResultID) as test_count,
    AVG(CASE WHEN lr.Status = 'Critical' THEN 1 ELSE 0 END) * 100 as critical_percentage
FROM Patients p
LEFT JOIN LabResults lr ON p.PatientID = lr.PatientID
GROUP BY p.PatientID, p.FirstName, p.LastName, p.Status
HAVING COUNT(lr.ResultID) > 0
ORDER BY critical_percentage DESC
LIMIT 10;
```

Expected result: Top 10 patients by critical test percentage

## Section 8: Create Additional Charts (Optional, 15 minutes)

### 8.1 Line Chart: Lab Results Over Time

1. **Chart Type**: Line Chart
2. **Dataset**: LabResults
3. **Dimensions**: `TestDate` (as Time Column)
4. **Metrics**: `COUNT(*)`
5. **Group By**: `TestName`
6. **Time Grain**: Month
7. **Time Range**: Last year

### 8.2 Pie Chart: Lab Result Status Distribution

1. **Chart Type**: Pie Chart
2. **Dataset**: LabResults
3. **Dimensions**: `Status`
4. **Metrics**: `COUNT(*)`
5. **Show Labels**: ✅ Checked
6. **Show Percentage**: ✅ Checked

### 8.3 Table: Recent Patients

1. **Chart Type**: Table
2. **Dataset**: Patients
3. **Columns**: `PatientID`, `FirstName`, `LastName`, `Status`, `AdmissionDate`
4. **Sort By**: `AdmissionDate` DESC
5. **Row Limit**: 10

## Section 9: Build Dashboard (5 minutes)

### 9.1 Navigate to Dashboard

If not already there, click **Dashboards** → `Healthcare Overview`

### 9.2 Add Charts to Dashboard

1. Click **EDIT DASHBOARD** button
2. Drag charts from left sidebar to canvas
3. Arrange in 2x2 grid:
   - Top-left: Bar chart (Patient Count by Status)
   - Top-right: Line chart (Lab Results Over Time)
   - Bottom-left: Pie chart (Lab Result Status)
   - Bottom-right: Table (Recent Patients)

### 9.3 Add Filters (Optional)

1. Click **+ FILTERS** button
2. Add date range filter on `AdmissionDate`
3. Add categorical filter on `Status`
4. Link filters to applicable charts

### 9.4 Save Dashboard

Click **SAVE** button (top-right)

## Troubleshooting

See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) for common issues.

## Next Steps

- Explore [Example Queries](./QUERIES.md)
- Create your own custom charts
- Experiment with SQL Lab queries
- Export dashboard for backup

## Validation Checklist

- [ ] All Docker containers running and healthy
- [ ] 250 patients loaded into IRIS
- [ ] 400 lab results loaded into IRIS
- [ ] Superset accessible at localhost:8088
- [ ] Database connection successful (green checkmark)
- [ ] Datasets created for both tables
- [ ] At least one chart renders data from IRIS
- [ ] SQL Lab queries execute successfully
- [ ] Dashboard displays with multiple charts

If all checkboxes are checked: **✅ Setup Complete!**

## Cleanup

When done with the example:

```bash
# Stop services (keep data)
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               down

# Stop services and delete data
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               down -v
```
