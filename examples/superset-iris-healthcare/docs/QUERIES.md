# Example SQL Lab Queries for IRIS Healthcare Data

These queries demonstrate Superset SQL Lab executing SQL against IRIS through the PGWire PostgreSQL wire protocol.

**Access SQL Lab**: Top menu → **SQL Lab** → **SQL Editor**

## Basic Queries

### Query 1: Patient Count by Status

```sql
SELECT
    Status,
    COUNT(*) as patient_count
FROM Patients
GROUP BY Status
ORDER BY patient_count DESC;
```

**Expected Results**:
| Status | patient_count |
|--------|---------------|
| Active | ~175 |
| Discharged | ~62 |
| Deceased | ~13 |

**Performance**: < 100ms

---

### Query 2: Recent Lab Results

```sql
SELECT
    lr.ResultID,
    lr.TestName,
    lr.TestDate,
    lr.Result,
    lr.Unit,
    lr.Status,
    p.FirstName || ' ' || p.LastName as patient_name
FROM LabResults lr
JOIN Patients p ON lr.PatientID = p.PatientID
ORDER BY lr.TestDate DESC
LIMIT 10;
```

**Expected Results**: 10 most recent lab results with patient names

**Performance**: < 200ms

---

### Query 3: Abnormal Results by Test Type

```sql
SELECT
    TestName,
    COUNT(*) as abnormal_count,
    ROUND(AVG(Result), 2) as avg_result
FROM LabResults
WHERE Status IN ('Abnormal', 'Critical')
GROUP BY TestName
ORDER BY abnormal_count DESC;
```

**Expected Results**:
| TestName | abnormal_count | avg_result |
|----------|----------------|------------|
| Blood Glucose | ~60 | ~140.50 |
| Blood Pressure | ~50 | ~140.25 |
| Hemoglobin A1C | ~20 | ~7.20 |
| Total Cholesterol | ~20 | ~230.00 |

**Performance**: < 150ms

---

### Query 4: Patient Demographics by Gender

```sql
SELECT
    Gender,
    COUNT(*) as patient_count,
    ROUND(AVG(EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM DateOfBirth)), 1) as avg_age
FROM Patients
GROUP BY Gender
ORDER BY patient_count DESC;
```

**Expected Results**: Patient distribution by gender with average ages

**Performance**: < 100ms

---

### Query 5: Average Lab Results by Test Type

```sql
SELECT
    TestName,
    COUNT(*) as total_tests,
    ROUND(AVG(Result), 2) as avg_result,
    MIN(Result) as min_result,
    MAX(Result) as max_result,
    Unit
FROM LabResults
GROUP BY TestName, Unit
ORDER BY total_tests DESC;
```

**Expected Results**: Statistical summary for each test type

**Performance**: < 150ms

---

## Intermediate Queries

### Query 6: Patients with Critical Results

```sql
SELECT DISTINCT
    p.PatientID,
    p.FirstName,
    p.LastName,
    p.Status,
    COUNT(lr.ResultID) as critical_count
FROM Patients p
JOIN LabResults lr ON p.PatientID = lr.PatientID
WHERE lr.Status = 'Critical'
GROUP BY p.PatientID, p.FirstName, p.LastName, p.Status
ORDER BY critical_count DESC;
```

**Expected Results**: ~20 patients with critical lab results

**Performance**: < 200ms

---

### Query 7: Monthly Lab Test Volume

```sql
SELECT
    TO_CHAR(TestDate, 'YYYY-MM') as month,
    COUNT(*) as test_count,
    COUNT(DISTINCT PatientID) as unique_patients
FROM LabResults
WHERE TestDate >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY TO_CHAR(TestDate, 'YYYY-MM')
ORDER BY month DESC;
```

**Expected Results**: Last 12 months of test volume

**Performance**: < 150ms

---

### Query 8: Patient Admission Patterns

```sql
SELECT
    TO_CHAR(AdmissionDate, 'YYYY-MM') as admission_month,
    Status,
    COUNT(*) as patient_count
FROM Patients
WHERE AdmissionDate >= '2024-01-01'
GROUP BY TO_CHAR(AdmissionDate, 'YYYY-MM'), Status
ORDER BY admission_month DESC, patient_count DESC;
```

**Expected Results**: Monthly admission patterns by patient status

**Performance**: < 150ms

---

## Advanced Queries

### Query 9: Patients with No Lab Results

```sql
SELECT
    p.PatientID,
    p.FirstName,
    p.LastName,
    p.Status,
    p.AdmissionDate
FROM Patients p
LEFT JOIN LabResults lr ON p.PatientID = lr.PatientID
WHERE lr.ResultID IS NULL
ORDER BY p.AdmissionDate DESC;
```

**Expected Results**: Patients without any lab results (should be minimal since avg is 1.6 results/patient)

**Performance**: < 200ms

---

### Query 10: Test Result Trends for Specific Patient

```sql
SELECT
    lr.TestDate,
    lr.TestName,
    lr.Result,
    lr.Unit,
    lr.ReferenceRange,
    lr.Status
FROM LabResults lr
WHERE lr.PatientID = 1  -- Change to any PatientID
ORDER BY lr.TestDate ASC, lr.TestName;
```

**Expected Results**: Time-series lab results for a single patient

**Performance**: < 100ms

---

### Query 11: Critical Results Requiring Attention

```sql
SELECT
    p.FirstName || ' ' || p.LastName as patient_name,
    lr.TestName,
    lr.Result,
    lr.Unit,
    lr.ReferenceRange,
    lr.TestDate,
    p.Status as patient_status
FROM LabResults lr
JOIN Patients p ON lr.PatientID = p.PatientID
WHERE lr.Status = 'Critical'
  AND p.Status = 'Active'  -- Only active patients
ORDER BY lr.TestDate DESC;
```

**Expected Results**: Active patients with critical lab results

**Performance**: < 200ms

---

### Query 12: Age Distribution Analysis

```sql
SELECT
    CASE
        WHEN age < 30 THEN 'Under 30'
        WHEN age BETWEEN 30 AND 50 THEN '30-50'
        WHEN age BETWEEN 51 AND 70 THEN '51-70'
        ELSE 'Over 70'
    END as age_group,
    COUNT(*) as patient_count,
    ROUND(AVG(age), 1) as avg_age_in_group
FROM (
    SELECT
        PatientID,
        EXTRACT(YEAR FROM CURRENT_DATE) - EXTRACT(YEAR FROM DateOfBirth) as age
    FROM Patients
) age_calc
GROUP BY age_group
ORDER BY patient_count DESC;
```

**Expected Results**: Patient distribution across age groups

**Performance**: < 150ms

---

## Performance Testing Queries

### Query 13: Full Table Scan (Patients)

```sql
SELECT
    PatientID,
    FirstName,
    LastName,
    DateOfBirth,
    Gender,
    Status,
    AdmissionDate,
    DischargeDate
FROM Patients;
```

**Expected Results**: All 250 patients

**Performance**: < 100ms (small dataset)

---

### Query 14: Full Table Scan (LabResults)

```sql
SELECT
    ResultID,
    PatientID,
    TestName,
    TestDate,
    Result,
    Unit,
    ReferenceRange,
    Status
FROM LabResults;
```

**Expected Results**: All 400 lab results

**Performance**: < 150ms (small dataset)

---

### Query 15: Complex Join with Aggregation

```sql
SELECT
    p.Status as patient_status,
    lr.Status as result_status,
    COUNT(*) as result_count,
    ROUND(AVG(lr.Result), 2) as avg_result,
    COUNT(DISTINCT p.PatientID) as unique_patients
FROM Patients p
JOIN LabResults lr ON p.PatientID = lr.PatientID
GROUP BY p.Status, lr.Status
ORDER BY result_count DESC;
```

**Expected Results**: Cross-tabulation of patient status vs result status

**Performance**: < 250ms

---

## Validation Queries

### Validate Data Loading: Patient Count

```sql
SELECT COUNT(*) as total_patients FROM Patients;
```

**Expected**: Exactly **250**

---

### Validate Data Loading: Lab Result Count

```sql
SELECT COUNT(*) as total_results FROM LabResults;
```

**Expected**: Exactly **400**

---

### Validate Foreign Key Relationships

```sql
SELECT
    (SELECT COUNT(*) FROM LabResults) as total_lab_results,
    (SELECT COUNT(DISTINCT PatientID) FROM LabResults) as patients_with_results,
    (SELECT COUNT(*) FROM Patients) as total_patients;
```

**Expected**:
- `total_lab_results`: 400
- `patients_with_results`: ≤250 (not all patients may have results)
- `total_patients`: 250

---

## Query Performance Notes

**All queries should execute in < 1 second** given the small dataset size (250 patients, 400 results).

If queries take longer:
1. Check IRIS server health: `docker ps`
2. Review PGWire logs: `docker-compose logs pgwire`
3. Verify network connectivity between containers
4. Check IRIS Management Portal: http://localhost:52773/csp/sys/UtilHome.csp

## Key Demonstrations

These queries prove:

✅ **PostgreSQL Compatibility**: All queries use PostgreSQL syntax (not IRIS-specific)
✅ **JOINs Work**: Foreign key relationships traversed successfully
✅ **Aggregations Work**: COUNT, AVG, MIN, MAX functions execute correctly
✅ **Date Functions Work**: EXTRACT, TO_CHAR, CURRENT_DATE supported
✅ **Subqueries Work**: Nested SELECT statements execute properly
✅ **Performance**: Sub-second query execution through protocol translation

**Core Validation**: Superset SQL Lab → PGWire → IRIS translation layer is working!
