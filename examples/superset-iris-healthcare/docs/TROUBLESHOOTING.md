# Troubleshooting Guide - Superset 4 + IRIS Healthcare Example

Common issues and solutions when running the Superset healthcare demo with IRIS via PGWire.

## Issue 1: "Connection refused" when testing database connection

### Symptoms
- Superset database connection test fails
- Error message: `Connection refused` or `could not connect to server`
- Database shows as offline

### Diagnosis

Check if PGWire server is running and accessible:

```bash
# Check PGWire service status
docker-compose ps iris

# Check PGWire port is listening
docker exec iris-pgwire-db netstat -tuln | grep 5432
```

Expected output: Port 5432 should show LISTEN state

### Solutions

**Solution 1**: Verify PGWire is running inside IRIS container

```bash
# Check PGWire server logs
docker-compose logs iris | grep -i pgwire

# Look for: "PGWire server started on port 5432"
```

**Solution 2**: Restart IRIS container

```bash
docker-compose restart iris

# Wait 30 seconds for PGWire to start
sleep 30

# Test connection from another container
docker exec postgres-client psql -h iris -p 5432 -U test_user -d USER -c "SELECT 1"
```

**Solution 3**: Check network connectivity

```bash
# Verify containers are on same network
docker network inspect iris-pgwire-network

# Should show both 'iris' and 'superset' containers
```

---

## Issue 2: "Authentication failed" when connecting

### Symptoms
- Connection test fails with authentication error
- Error: `password authentication failed for user "test_user"`
- Login prompt appears in SQL Lab

### Diagnosis

PGWire authentication is configured for blank password by default.

### Solutions

**Solution 1**: Verify connection string has no password

Correct connection string:
```
postgresql://test_user@iris:5432/USER
```

**NOT**:
```
postgresql://test_user:SYS@iris:5432/USER  # ❌ Wrong password
```

**Solution 2**: Check PGWire configuration

```bash
# Verify PGWire user configuration
docker exec iris-pgwire-db /bin/bash -c "cat /app/src/iris_pgwire/config.py | grep -A 5 'test_user'"
```

**Solution 3**: Use IRIS Management Portal credentials (if configured)

If PGWire is configured to use IRIS authentication:
- Username: `_SYSTEM`
- Password: `SYS`

---

## Issue 3: "Table not found" errors

### Symptoms
- Dataset creation fails
- Error: `relation "Patients" does not exist`
- SQL Lab queries fail with table not found

### Diagnosis

Healthcare schema not loaded into IRIS.

### Solutions

**Solution 1**: Load healthcare schema and data

```bash
# Connect to IRIS via PGWire
docker exec -it postgres-client psql -h iris -p 5432 -U test_user -d USER

# Execute schema creation
\i /path/to/examples/superset-iris-healthcare/data/init-healthcare-schema.sql

# Execute data loading
\i /path/to/examples/superset-iris-healthcare/data/patients-data.sql
\i /path/to/examples/superset-iris-healthcare/data/labresults-data.sql

# Verify tables exist
\dt

# Expected output should list: Patients, LabResults
```

**Solution 2**: Check correct namespace/schema

IRIS default namespace for PGWire is **USER**, not **%SYS** or other namespaces.

In Superset:
- Database: `USER`
- Schema: `SQLUSER` (may vary based on IRIS configuration)

---

## Issue 4: "Dashboard empty" - charts not rendering

### Symptoms
- Dashboard page loads but no charts display
- Charts show loading spinner indefinitely
- No error messages in browser console

### Diagnosis

Charts may not be linked to correct datasets or database connection.

### Solutions

**Solution 1**: Verify datasets exist and are accessible

1. Navigate to **Data** → **Datasets**
2. Verify `Patients` and `LabResults` datasets exist
3. Click dataset name → Verify "Database" column shows `IRIS Healthcare`

**Solution 2**: Refresh dataset schema

1. Navigate to **Data** → **Datasets**
2. Click dataset name
3. Click **Settings** tab
4. Click **Sync columns from source**
5. Click **Advanced** tab → **Clear cache**

**Solution 3**: Check chart configuration

1. Edit the chart
2. Verify **Dataset** is selected
3. Verify **Database** shows `IRIS Healthcare`
4. Click **RUN** to manually execute query
5. If data appears, save chart again

---

## Issue 5: "Charts not rendering" - browser errors

### Symptoms
- Browser console shows JavaScript errors
- Charts display error messages
- Error: `Cannot read property 'length' of undefined`

### Diagnosis

Superset frontend caching or configuration issue.

### Solutions

**Solution 1**: Clear Superset cache

```bash
# Clear all Superset caches
docker exec iris-pgwire-superset superset cache-clear

# Restart Superset
docker-compose restart superset
```

**Solution 2**: Hard refresh browser

Press `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac) to bypass browser cache.

**Solution 3**: Clear browser cache manually

1. Open browser DevTools (F12)
2. Right-click refresh button
3. Select "Empty Cache and Hard Reload"

---

## Issue 6: Slow query performance (> 5 seconds)

### Symptoms
- SQL Lab queries take > 5 seconds
- Charts timeout during rendering
- Database appears unresponsive

### Diagnosis

IRIS or PGWire server may be under load or misconfigured.

### Solutions

**Solution 1**: Check IRIS server health

```bash
# Check IRIS container resource usage
docker stats iris-pgwire-db

# Should show reasonable CPU/memory usage (< 80%)

# Check IRIS Management Portal
# Navigate to: http://localhost:52773/csp/sys/UtilHome.csp
# Login: _SYSTEM / SYS
# Check: System Monitor → SQL Statistics
```

**Solution 2**: Check PGWire translation overhead

```bash
# Compare direct IRIS query vs PGWire query
# Direct IRIS (via Management Portal SQL interface):
SELECT COUNT(*) FROM Patients;

# PGWire (via psql):
docker exec postgres-client psql -h iris -p 5432 -U test_user -d USER \
  -c "SELECT COUNT(*) FROM Patients;"

# Times should be similar (< 100ms difference)
```

**Solution 3**: Review query complexity

Simple queries (< 1 second):
- `SELECT COUNT(*) FROM Patients`
- `SELECT * FROM Patients WHERE PatientID = 1`

Medium queries (< 2 seconds):
- `SELECT * FROM Patients JOIN LabResults ...`
- Aggregations with GROUP BY

If simple queries are slow, check IRIS server health.

---

## Issue 7: "Superset initialization failed"

### Symptoms
- Superset container exits immediately
- Logs show database migration errors
- Error: `superset db upgrade` fails

### Diagnosis

Superset metadata database (PostgreSQL) not ready or corrupted.

### Solutions

**Solution 1**: Verify Superset PostgreSQL is healthy

```bash
# Check superset-db container status
docker-compose ps iris-pgwire-superset-db

# Should show "Up (healthy)"

# Check superset-db logs
docker-compose logs iris-pgwire-superset-db

# Should NOT show connection errors
```

**Solution 2**: Reset Superset metadata database

**⚠️ WARNING**: This deletes all Superset dashboards, charts, and datasets!

```bash
# Stop Superset services
docker-compose stop superset

# Remove Superset volumes
docker volume rm superset-postgres-data

# Restart all services
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               up -d
```

**Solution 3**: Manual database migration

```bash
# Execute database upgrade manually
docker exec iris-pgwire-superset superset db upgrade

# Check for errors in output
```

---

## Issue 8: "Not a zip file" when importing dashboard

### Symptoms
- Dashboard import fails
- Error: `Not a zip file`
- Import button accepts file but shows error

### Diagnosis

Dashboard export format mismatch (Superset 4 uses ZIP/YAML, not JSON).

### Solutions

**Solution 1**: Export dashboard correctly

1. Navigate to **Dashboards**
2. Click dashboard menu (three dots)
3. Select **Export**
4. Verify file is `.zip` format (not `.json`)

**Solution 2**: Enable VERSIONED_EXPORT (if disabled)

In `superset_config.py`:
```python
FEATURE_FLAGS = {
    "VERSIONED_EXPORT": True  # Ensures ZIP/YAML format
}
```

---

## Health Check Commands

### Verify All Services Running

```bash
docker-compose ps
```

Expected output: All services **Up (healthy)**

### Verify IRIS PGWire Connectivity

```bash
# From host machine
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 1"

# Expected output: Returns 1
```

### Verify Data Loaded

```bash
docker exec postgres-client psql -h iris -p 5432 -U test_user -d USER \
  -c "SELECT
        (SELECT COUNT(*) FROM Patients) as patients,
        (SELECT COUNT(*) FROM LabResults) as lab_results;"
```

Expected output:
```
 patients | lab_results
----------+-------------
      250 |         400
```

### Verify Superset Accessibility

```bash
curl -I http://localhost:8088
```

Expected output: `HTTP/1.1 200 OK`

---

## Log Inspection Commands

### View Superset Logs

```bash
# Real-time logs
docker-compose logs -f superset

# Last 100 lines
docker-compose logs --tail=100 superset
```

### View IRIS Logs

```bash
# Real-time logs
docker-compose logs -f iris

# Last 100 lines
docker-compose logs --tail=100 iris
```

### View PGWire Logs (embedded in IRIS)

```bash
# PGWire runs inside IRIS container
docker-compose logs iris | grep -i pgwire

# Or check dedicated PGWire log file
docker exec iris-pgwire-db cat /tmp/pgwire.log
```

---

## Network Debugging

### Verify Container Network Connectivity

```bash
# Check if Superset can reach IRIS
docker exec iris-pgwire-superset ping -c 3 iris

# Check if Superset can reach IRIS PGWire port
docker exec iris-pgwire-superset nc -zv iris 5432
```

Expected output: `iris:5432 open`

### Verify DNS Resolution

```bash
# Verify 'iris' hostname resolves
docker exec iris-pgwire-superset nslookup iris

# Should return IP address in iris-pgwire-network range
```

---

## Complete Reset Procedure

If all else fails, complete environment reset:

```bash
# Stop all services
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               down

# Remove all volumes (⚠️ DELETES ALL DATA!)
docker volume rm superset-postgres-data
docker volume ls | grep iris-pgwire | awk '{print $2}' | xargs docker volume rm

# Remove all containers
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               rm -f

# Start fresh
docker-compose -f docker-compose.yml \
               -f examples/superset-iris-healthcare/docker-compose.superset.yml \
               up -d

# Wait for initialization
docker-compose logs -f superset

# Look for: "✅ Superset initialization complete!"
```

---

## Still Having Issues?

1. **Check System Resources**:
   ```bash
   docker system df
   ```
   Ensure sufficient disk space (> 5GB free).

2. **Check Docker Version**:
   ```bash
   docker --version
   docker-compose --version
   ```
   Minimum: Docker 20.10+, Compose 1.29+

3. **Review Full Logs**:
   Save all logs for analysis:
   ```bash
   docker-compose logs > superset-debug.log
   ```

4. **Check GitHub Issues**:
   - [iris-pgwire issues](https://github.com/intersystems-community/iris-pgwire/issues)
   - [Apache Superset issues](https://github.com/apache/superset/issues)

5. **Consult Documentation**:
   - [SETUP.md](./SETUP.md) - Detailed setup walkthrough
   - [QUERIES.md](./QUERIES.md) - Example queries to validate connectivity
   - [Main README](../README.md) - Architecture and overview
