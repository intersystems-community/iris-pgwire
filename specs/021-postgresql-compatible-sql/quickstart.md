# Quickstart: PostgreSQL-Compatible SQL Normalization

**Feature**: 021-postgresql-compatible-sql
**Date**: 2025-10-08
**Purpose**: End-to-end validation of SQL normalization feature

## Prerequisites

1. **IRIS PGWire Server Running**:
   ```bash
   # Verify server is running
   docker ps | grep iris-pgwire-db
   # Expected: iris-pgwire-db container running on port 5432
   ```

2. **PostgreSQL Client Installed**:
   ```bash
   # Verify psql is available
   psql --version
   # Expected: psql (PostgreSQL) 16.x or later
   ```

3. **Healthcare Dataset Available**:
   ```bash
   # Verify SQL files exist
   ls -l examples/superset-iris-healthcare/data/
   # Expected: init-healthcare-schema.sql, patients-data.sql, labresults-data.sql
   ```

## Quickstart Steps

### Step 1: Clean Slate - Drop Existing Tables

```bash
psql -h localhost -p 5432 -U test_user -d USER -c "
DROP TABLE IF EXISTS LabResults;
DROP TABLE IF EXISTS Patients;
"
```

**Expected Output**:
```
DROP TABLE
DROP TABLE
```

### Step 2: Create Schema with Mixed-Case Identifiers

```bash
psql -h localhost -p 5432 -U test_user -d USER -c "
CREATE TABLE Patients (
    PatientID INT PRIMARY KEY,
    FirstName VARCHAR(50) NOT NULL,
    LastName VARCHAR(50) NOT NULL,
    DateOfBirth DATE NOT NULL,
    Gender VARCHAR(10) NOT NULL,
    Status VARCHAR(20) NOT NULL,
    AdmissionDate DATE NOT NULL,
    DischargeDate DATE
);
"
```

**Expected Output**:
```
CREATE TABLE
```

**Validation**: Identifiers `Patients`, `PatientID`, `FirstName`, etc. normalized to UPPERCASE internally (`PATIENTS`, `PATIENTID`, `FIRSTNAME`).

### Step 3: Load 250-Patient Dataset (THE CRITICAL TEST)

```bash
psql -h localhost -p 5432 -U test_user -d USER \
    -f examples/superset-iris-healthcare/data/patients-data.sql
```

**Expected Output**:
```
INSERT 0 1
INSERT 0 1
INSERT 0 1
...
(250 INSERT statements)
```

**What This Tests**:
- ✅ Mixed-case identifier normalization (`FirstName` → `FIRSTNAME`)
- ✅ DATE literal translation (`'1985-03-15'` → `TO_DATE('1985-03-15', 'YYYY-MM-DD')`)
- ✅ Multi-column INSERT with 8 columns per row
- ✅ 250 rows = 2000 identifier references (performance validation)

### Step 4: Verify Patient Count

```bash
psql -h localhost -p 5432 -U test_user -d USER -c "
SELECT COUNT(*) as patient_count FROM Patients;
"
```

**Expected Output**:
```
 patient_count
---------------
           250
(1 row)
```

**Validation**: All 250 records loaded successfully.

### Step 5: Verify DATE Values Loaded Correctly

```bash
psql -h localhost -p 5432 -U test_user -d USER -c "
SELECT PatientID, FirstName, LastName, DateOfBirth, Status
FROM Patients
WHERE PatientID IN (1, 2, 3)
ORDER BY PatientID;
"
```

**Expected Output**:
```
 patientid | firstname | lastname | dateofbirth | status
-----------+-----------+----------+-------------+--------
         1 | John      | Smith    | 1985-03-15  | Active
         2 | Mary      | Johnson  | 1972-07-22  | Active
         3 | Robert    | Williams | 1990-11-08  | Discharged
(3 rows)
```

**Validation**:
- ✅ DATE values correct (no corruption during translation)
- ✅ Column names returned in lowercase (PostgreSQL standard)
- ✅ Data integrity maintained

### Step 6: Test Quoted Identifier Preservation

```bash
psql -h localhost -p 5432 -U test_user -d USER -c '
CREATE TABLE "MixedCase" (
    "CamelCase" INT PRIMARY KEY,
    "PascalCase" VARCHAR(50)
);
'
```

**Expected Output**:
```
CREATE TABLE
```

**Validation**: Quoted identifiers `"MixedCase"`, `"CamelCase"`, `"PascalCase"` preserved with exact case.

### Step 7: Test Mixed Quoted/Unquoted Identifiers

```bash
psql -h localhost -p 5432 -U test_user -d USER -c '
INSERT INTO "MixedCase" ("CamelCase", "PascalCase")
VALUES (1, '\''Test'\'');

SELECT CamelCase, PascalCase FROM "MixedCase";
'
```

**Expected Output**:
```
INSERT 0 1
 camelcase | pascalcase
-----------+------------
         1 | Test
(1 row)
```

**Validation**:
- ✅ Quoted table name `"MixedCase"` preserved
- ✅ Quoted column names preserved in INSERT
- ✅ Unquoted column names in SELECT normalized to UPPERCASE internally

### Step 8: Test DATE in WHERE Clause

```bash
psql -h localhost -p 5432 -U test_user -d USER -c "
SELECT FirstName, LastName, DateOfBirth
FROM Patients
WHERE DateOfBirth = '1985-03-15';
"
```

**Expected Output**:
```
 firstname | lastname | dateofbirth
-----------+----------+-------------
 John      | Smith    | 1985-03-15
(1 row)
```

**Validation**: DATE literal in WHERE clause translated correctly.

### Step 9: Performance Validation (50 Identifiers)

```bash
psql -h localhost -p 5432 -U test_user -d USER -c "
SELECT
    PatientID, FirstName, LastName, DateOfBirth, Gender, Status, AdmissionDate, DischargeDate,
    PatientID as id1, FirstName as fn1, LastName as ln1,
    PatientID as id2, FirstName as fn2, LastName as ln2,
    PatientID as id3, FirstName as fn3, LastName as ln3,
    PatientID as id4, FirstName as fn4, LastName as ln4,
    PatientID as id5, FirstName as fn5, LastName as ln5,
    PatientID as id6, FirstName as fn6, LastName as ln6,
    PatientID as id7, FirstName as fn7, LastName as ln7,
    PatientID as id8, FirstName as fn8, LastName as ln8,
    PatientID as id9, FirstName as fn9, LastName as ln9,
    PatientID as id10, FirstName as fn10, LastName as ln10
FROM Patients
LIMIT 1;
" > /dev/null

# Check PGWire logs for normalization time
docker exec iris-pgwire-db tail -20 /tmp/pgwire.log | grep normalization
```

**Expected Output**:
```
INFO  normalization_time_ms=3.2  identifier_count=50
```

**Validation**: Normalization time < 5ms (constitutional requirement).

### Step 10: Cleanup

```bash
psql -h localhost -p 5432 -U test_user -d USER -c "
DROP TABLE IF EXISTS \"MixedCase\";
DROP TABLE IF EXISTS Patients;
"
```

**Expected Output**:
```
DROP TABLE
DROP TABLE
```

## Success Criteria

✅ **All 10 steps completed without errors**
✅ **250 patient records loaded successfully**
✅ **DATE values correct (no corruption)**
✅ **Quoted identifiers preserved**
✅ **Mixed quoted/unquoted identifiers work**
✅ **DATE in WHERE clause works**
✅ **Performance: Normalization < 5ms for 50 identifiers**

## Troubleshooting

### Error: "Field 'SQLUSER.PATIENTS.LASTNAME' not found"
**Cause**: Normalization not applied or failed
**Fix**: Check PGWire logs for normalization errors

### Error: "Field 'DateOfBirth' validation failed"
**Cause**: DATE literal translation not applied
**Fix**: Verify regex pattern matching in `date_translator.py`

### Error: Connection refused (port 5432)
**Cause**: PGWire server not running
**Fix**: Start IRIS PGWire server with `docker-compose up`

### Performance Degradation (> 5ms)
**Cause**: Too many identifiers or inefficient regex
**Fix**: Review `performance_monitor` logs, optimize regex patterns

## Next Steps

After quickstart validation passes:
1. Run full integration test suite: `tests/integration/test_sql_file_loading.sh`
2. Run performance benchmarks: `tests/unit/test_sql_translator.py::test_performance`
3. Validate vector query normalization: `tests/integration/test_sql_normalization_e2e.sh`

---

**Quickstart Status**: ✅ **READY FOR EXECUTION**
**Estimated Time**: 5 minutes
**Prerequisites**: IRIS PGWire server running, psql installed
