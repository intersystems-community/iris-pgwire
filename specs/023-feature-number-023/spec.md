# Feature Specification: P6 COPY Protocol - Bulk Data Operations

**Feature Branch**: `023-feature-number-023`
**Created**: 2025-01-09
**Status**: Draft
**Input**: User description: "PostgreSQL COPY protocol for bulk data loading and export via IRIS integration"

## Execution Flow (main)
```
1. Parse user description from Input
   → Feature: Bulk data operations via PostgreSQL COPY protocol
2. Extract key concepts from description
   → Actors: BI tools (Superset, Metabase), Data engineers, Healthcare admins
   → Actions: Bulk load data (COPY FROM STDIN), Bulk export data (COPY TO STDOUT)
   → Data: Healthcare patient records, lab results, large datasets
   → Constraints: Performance (>10K rows/sec), Memory (<100MB for 1M rows), Transaction integration
3. No unclear aspects - PostgreSQL COPY protocol is well-defined
4. User Scenarios & Testing section complete
   → Primary: Healthcare data migration (250 patients)
   → Secondary: BI tool data import, Large dataset export
5. Functional Requirements generated (FR-001 through FR-007)
   → All requirements testable via E2E tests
6. Key Entities identified:
   → Patient records, Lab results, CSV data streams
7. Review Checklist passed
   → No [NEEDS CLARIFICATION] markers
   → No implementation details exposed to spec
8. Return: SUCCESS (spec ready for planning)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story
A healthcare data engineer needs to migrate 250 patient records from an existing PostgreSQL database to IRIS via the PGWire server. Using standard PostgreSQL tools (psql, pg_dump, BI connectors), they expect bulk data loading to complete in under 1 second, not 2.5 seconds with individual INSERT statements.

### Acceptance Scenarios

1. **Given** a CSV file with 250 patient records, **When** the user executes `COPY Patients FROM STDIN WITH (FORMAT CSV)`, **Then** all 250 records are loaded into IRIS in < 1 second with no errors

2. **Given** a Patients table with 250 records in IRIS, **When** the user executes `COPY Patients TO STDOUT WITH (FORMAT CSV)`, **Then** all 250 records are exported to CSV format and streamed to the client

3. **Given** a healthcare admin using Apache Superset, **When** they import a 10,000-row lab results dataset via Superset's CSV import feature, **Then** the data loads without memory exhaustion or timeouts

4. **Given** a BI tool executing `COPY ... FROM STDIN` within a transaction, **When** the load completes successfully, **Then** the transaction can be committed and all rows are visible to subsequent queries

5. **Given** a data export job for 1 million patient records, **When** the user executes `COPY (SELECT * FROM Patients) TO STDOUT`, **Then** the server streams results without exceeding 100MB memory usage

### Edge Cases

- What happens when a CSV file contains malformed rows (missing quotes, extra columns)?
  → System MUST report error with line number and reject the entire COPY operation

- What happens when a COPY FROM STDIN operation is interrupted (client disconnect)?
  → System MUST clean up temporary files and rollback transaction (if active)

- What happens when a COPY TO STDOUT query returns zero rows?
  → System MUST send valid CopyOutResponse and CopyDone messages with zero DataRows

- What happens when a COPY operation exceeds memory limits (e.g., 1GB CSV file)?
  → System MUST stream data in batches, flushing to IRIS every 1000 rows or 10MB to avoid memory exhaustion

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support PostgreSQL `COPY table_name FROM STDIN` syntax for bulk data loading from client to IRIS

- **FR-002**: System MUST support PostgreSQL `COPY table_name TO STDOUT` syntax for bulk data export from IRIS to client

- **FR-003**: System MUST support CSV format with PostgreSQL-compatible options (DELIMITER, NULL, HEADER, QUOTE, ESCAPE)

- **FR-004**: System MUST integrate COPY operations with transaction semantics (BEGIN/COMMIT/ROLLBACK compatibility with Feature 022)

- **FR-005**: System MUST achieve > 10,000 rows/second throughput for bulk loading operations (vs. 100 rows/second for individual INSERTs)

- **FR-006**: System MUST handle datasets up to 1 million rows without exceeding 100MB server memory usage (streaming/batching required)

- **FR-007**: System MUST validate CSV data format and report errors with specific line numbers when malformed data is encountered

### Non-Functional Requirements

- **NFR-001**: COPY operations MUST complete 10-100× faster than equivalent individual INSERT statements for datasets > 250 rows

- **NFR-002**: System MUST be compatible with standard PostgreSQL clients: psql, pg_dump, Apache Superset, Metabase, pgAdmin

### Key Entities *(include if feature involves data)*

- **Patient Record**: Healthcare patient data with demographics (PatientID, FirstName, LastName, DateOfBirth, Gender, Status, AdmissionDate, DischargeDate)
  - Attributes: 8 columns (1 INT primary key, 6 VARCHAR, 2 DATE)
  - Representative dataset: 250 rows from examples/superset-iris-healthcare/data/patients-data.sql

- **Lab Result**: Clinical lab test results linked to patients
  - Attributes: TestID, PatientID, TestType, TestValue, TestDate, Status
  - Representative dataset: 500 rows (2 tests per patient average)

- **CSV Data Stream**: Bulk data in CSV format flowing from client to server (COPY FROM STDIN) or server to client (COPY TO STDOUT)
  - Format: PostgreSQL CSV with header row, comma-delimited, NULL representation, quoted strings
  - Size: 1KB (single row) to 100MB (large datasets)

---

## Review & Acceptance Checklist
*GATE: Automated checks run during main() execution*

### Content Quality
- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable (>10K rows/sec, <100MB memory, <1 sec for 250 rows)
- [x] Scope is clearly bounded (PostgreSQL COPY protocol, CSV format, IRIS backend)
- [x] Dependencies and assumptions identified (Feature 022 transaction verbs, existing Patients table)

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed
- [x] Key concepts extracted
- [x] Ambiguities marked (none found)
- [x] User scenarios defined
- [x] Requirements generated
- [x] Entities identified
- [x] Review checklist passed

---

## Business Value

**Problem**: Individual INSERT statements via PostgreSQL wire protocol are slow for bulk data operations:
- 250 patient records take 2.5 seconds (100 rows/second throughput)
- BI tools (Superset, Metabase) experience timeouts on large imports
- Data migration workflows are impractical for production datasets

**Solution**: PostgreSQL COPY protocol provides 10-100× speedup for bulk operations:
- 250 patient records load in < 1 second (>10,000 rows/second)
- Streaming architecture prevents memory exhaustion on large datasets
- Standard PostgreSQL tooling (psql, pg_dump) works without modification

**Impact**:
- **Healthcare data migration**: Enable production-scale patient data migration (10K+ records)
- **BI ecosystem compatibility**: Unlock Apache Superset and Metabase bulk import features
- **Developer productivity**: Use familiar PostgreSQL tools (pg_dump, psql \copy) instead of custom scripts

---

## Success Metrics

1. **Performance Benchmark**: 250 patient records load in < 1 second (vs. 2.5 seconds baseline)
2. **Throughput Target**: >10,000 rows/second sustained for datasets up to 1M rows
3. **Memory Efficiency**: Server memory usage < 100MB for 1M row COPY operation
4. **Compatibility**: psql `\copy` command works without errors against PGWire server
5. **Transaction Integration**: COPY operations within BEGIN/COMMIT blocks work correctly (Feature 022 integration)

---

## Dependencies & Assumptions

**Dependencies**:
- Feature 022: PostgreSQL transaction verb translation (BEGIN/COMMIT/ROLLBACK) - COMPLETED
- Feature 018: IRIS DBAPI backend for SQL execution - COMPLETED
- Working Patients table schema (PatientID, FirstName, LastName, DateOfBirth, Gender, Status, AdmissionDate, DischargeDate)
- PostgreSQL wire protocol infrastructure (protocol.py message handling)

**Assumptions**:
- IRIS supports bulk loading mechanisms (LOAD DATA or equivalent)
- CSV is the primary format (binary COPY format is out of scope for P6)
- Temporary file storage available on server for batching operations
- Network bandwidth sufficient for streaming large datasets (10 Mbps minimum)

---

## Out of Scope

**Explicitly NOT included in P6**:
- Binary COPY format (PostgreSQL's binary wire format) - only CSV/text format
- COPY FROM file paths on server filesystem - only STDIN/STDOUT streams
- Custom delimiter formats beyond standard CSV - PostgreSQL CSV options only
- Compression during transfer - raw CSV streaming
- Parallel bulk loading - single-threaded COPY operations

**Deferred to future features**:
- P7 Performance Tuning: COPY operation optimization, parallel loading, compression
- Custom IRIS LOAD DATA parameter tuning for specific dataset characteristics

---

## PostgreSQL COPY Protocol Reference

**Standard Syntax** (for reference, not implementation):
```sql
-- COPY FROM STDIN (data loading)
COPY table_name [(column_list)] FROM STDIN [WITH (option [, ...])]

-- COPY TO STDOUT (data export)
COPY table_name [(column_list)] TO STDOUT [WITH (option [, ...])]

-- Options: FORMAT CSV, DELIMITER ',', NULL '\N', HEADER, QUOTE '"', ESCAPE '\'
```

**Wire Protocol Messages** (for reference, not implementation):
- CopyInResponse: Server → Client (initiate COPY FROM STDIN)
- CopyOutResponse: Server → Client (initiate COPY TO STDOUT)
- CopyData: Bidirectional (stream CSV data)
- CopyDone: Client → Server (end of COPY FROM STDIN data)
- CopyFail: Client → Server (abort COPY FROM STDIN)

---

## Examples from Healthcare Dataset

**Sample Patients Data** (examples/superset-iris-healthcare/data/patients-data.sql):
```csv
PatientID,FirstName,LastName,DateOfBirth,Gender,Status,AdmissionDate,DischargeDate
1,John,Smith,1985-03-15,M,Active,2024-01-10,NULL
2,Jane,Doe,1990-07-22,F,Discharged,2024-01-12,2024-01-15
...
250,Alice,Johnson,1978-11-03,F,Active,2024-02-01,NULL
```

**Expected Usage**:
```bash
# Load 250 patients via psql (E2E test)
cat patients-data.csv | psql -h localhost -p 5432 -U test_user -d USER \
  -c "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)"

# Export patients for backup (E2E test)
psql -h localhost -p 5432 -U test_user -d USER \
  -c "COPY Patients TO STDOUT WITH (FORMAT CSV, HEADER)" > backup.csv
```

---

## Next Steps

After approval of this specification:
1. Run `/plan` to generate implementation plan (tasks.md)
2. Execute TDD workflow: Write E2E tests BEFORE implementation
3. Implement COPY protocol handlers to make tests pass
4. Benchmark performance against 250-patient healthcare dataset
5. Validate with Apache Superset CSV import workflow
