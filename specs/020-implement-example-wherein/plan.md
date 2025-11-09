# Implementation Plan: Apache Superset 4 with IRIS Backend Example

**Branch**: `020-implement-example-wherein` | **Date**: 2025-01-05 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/020-implement-example-wherein/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → ✅ Loaded: Apache Superset 4 with IRIS Backend Example
2. Fill Technical Context
   → Project Type: Example/Demo (lives in examples/ directory)
   → Structure Decision: Single example directory with docker-compose orchestration
3. Fill Constitution Check section
   → No constitutional violations (example project, not protocol modification)
4. Evaluate Constitution Check
   → ✅ PASS: Example uses existing PGWire functionality, no protocol changes
   → Update Progress Tracking: Initial Constitution Check ✅
5. Execute Phase 0 → research.md
   → Research Superset 4 configuration, IRIS healthcare schema patterns, dashboard export/import
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, CLAUDE.md update
   → Data model: Healthcare tables (Patients, LabResults)
   → Contracts: SQL schema files, Superset configuration JSON
   → Quickstart: Step-by-step setup guide
7. Re-evaluate Constitution Check
   → No design violations introduced
   → Update Progress Tracking: Post-Design Constitution Check ✅
8. Plan Phase 2 → Task generation approach described
9. STOP - Ready for /tasks command
```

## Summary

Create a working demonstration of Apache Superset 4 connected to InterSystems IRIS via the PGWire PostgreSQL wire protocol. The example includes healthcare sample data (Patients and LabResults tables with 100-500 rows each), pre-configured Superset datasets, and a sample dashboard with basic visualizations (bar, line, pie, table charts). Users should be able to launch the complete stack via Docker Compose and have a working Superset instance querying IRIS healthcare data in under 10 minutes.

**Key Technical Approach**: Leverage existing docker-compose.yml with new `superset-example` profile, create healthcare data SQL initialization scripts, export pre-configured Superset dashboard as JSON, provide comprehensive setup documentation.

## Technical Context

**Language/Version**: Python 3.11 (Superset requirement), SQL (IRIS schema)
**Primary Dependencies**:
- Apache Superset 4.0+ (BI platform)
- PostgreSQL driver (psycopg2 for Superset's PostgreSQL connection)
- Existing PGWire server (no modifications needed)
- Existing IRIS instance with healthcare schema

**Storage**: IRIS database (healthcare tables: Patients, LabResults)
**Testing**: Manual validation via Superset UI, SQL Lab query execution, dashboard rendering
**Target Platform**: Docker Compose on Linux/macOS (containerized deployment)
**Project Type**: Example/Demo (single directory structure in `examples/superset-iris-healthcare/`)

**Performance Goals**:
- 10-minute setup time (from `docker-compose up -d` command to viewing dashboard at http://localhost:8088)
- Dashboard renders in <2 seconds with 500-row datasets
- SQL Lab queries execute in <1 second

**Constraints**:
- Must use Superset 4.x (not 3.x or 5.x alpha)
- Standard PostgreSQL connection only (no custom Superset plugins)
- Healthcare data must be realistic but synthetic (HIPAA compliance not required for demo)
- Basic visualizations only: bar, line, pie, table charts (no custom viz plugins, no computed expressions, no advanced chart types)

**Scale/Scope**:
- 2 IRIS tables (Patients, LabResults)
- 250 patient records, 400 lab result records (synthetic generated data)
- 1 pre-configured dashboard with 4-6 visualizations
- 3-5 example SQL Lab queries
- Single docker-compose.yml addition (~50 lines)

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle I: Protocol Fidelity
**Status**: ✅ PASS
- Example uses existing PGWire protocol implementation
- No protocol modifications required
- Standard PostgreSQL wire protocol for Superset connection

### Principle II: Test-First Development
**Status**: ✅ PASS (Adapted for Example)
- Manual validation via Superset UI (end-to-end user testing)
- SQL Lab query execution validation
- Dashboard rendering verification
- No unit tests required (configuration-driven example)

### Principle III: Phased Implementation
**Status**: ✅ N/A
- Example project, not protocol implementation
- Phases P0-P6 do not apply

### Principle IV: IRIS Integration
**Status**: ✅ PASS
- Uses existing IRIS instance via PGWire
- No embedded Python modifications
- Healthcare schema follows IRIS SQL patterns
- Standard INFORMATION_SCHEMA queries for table metadata

**Package Naming**: ✅ Compliant
- Superset uses standard PostgreSQL driver (no intersystems-irispython awareness needed)
- Connection through PGWire appears as standard PostgreSQL database

### Principle V: Production Readiness
**Status**: ✅ PASS (Demo Scope)
- Example includes troubleshooting documentation
- Connection parameters clearly documented
- Health check guidance provided
- **Note**: SSL/TLS not required for local demo environment

### Principle VI: Vector Performance Requirements
**Status**: ✅ N/A
- Example excludes vector demonstrations per clarifications
- Focus on standard relational healthcare data only

**Conclusion**: No constitutional violations. Example leverages existing PGWire functionality without protocol modifications.

## Project Structure

### Documentation (this feature)
```
specs/020-implement-example-wherein/
├── plan.md              # This file (/plan command output)
├── spec.md              # Feature specification (completed)
├── research.md          # Phase 0 output (/plan command)
├── data-model.md        # Phase 1 output (/plan command)
├── quickstart.md        # Phase 1 output (/plan command)
├── contracts/           # Phase 1 output (/plan command)
│   ├── patients-schema.sql
│   ├── labresults-schema.sql
│   └── superset-dashboard-config.json
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
examples/
└── superset-iris-healthcare/
    ├── README.md                    # Setup instructions, troubleshooting
    ├── docker-compose.superset.yml  # Superset service definition
    ├── data/                        # Sample healthcare data
    │   ├── init-healthcare-schema.sql
    │   ├── patients-data.sql        # 100-500 patient records
    │   └── labresults-data.sql      # 100-500 lab results
    ├── superset/                    # Superset configuration
    │   ├── superset_config.py       # Custom Superset settings
    │   ├── dashboards/
    │   │   └── healthcare-overview.json  # Pre-configured dashboard export
    │   └── datasets/
    │       ├── patients-dataset.json
    │       └── labresults-dataset.json
    └── docs/
        ├── SETUP.md                 # Detailed setup walkthrough
        ├── QUERIES.md               # Example SQL Lab queries
        └── TROUBLESHOOTING.md       # Common issues and solutions
```

**Structure Decision**: Single example directory structure (`examples/superset-iris-healthcare/`) containing all necessary configuration, data, and documentation. This follows the existing pattern in `examples/` directory (BI_TOOLS_SETUP.md, translation_api_demo.py, etc.).

## Phase 0: Outline & Research

**Research Tasks**:

1. **Superset 4 Configuration**:
   - Research: Docker deployment of Superset 4.x
   - Research: PostgreSQL connection configuration (host, port, credentials)
   - Research: Dashboard export/import formats (JSON structure)
   - Research: Dataset creation via API or manual export

2. **IRIS Healthcare Schema**:
   - Research: Realistic healthcare table structures (Patients, LabResults)
   - Research: IRIS SQL data types for healthcare fields (VARCHAR, DATE, NUMERIC, etc.)
   - Research: Synthetic data generation patterns for 250 patient records and 400 lab results

3. **Docker Compose Integration**:
   - Research: Superset 4 official Docker image (apache/superset:latest or 4.x tag)
   - Research: Superset initialization sequence (db upgrade, create admin, import configs)
   - Research: Volume mounts for persistent configuration

4. **Dashboard Design**:
   - Research: Basic chart types in Superset (bar, line, pie, table)
   - Research: Simple filter configurations (date range, categorical)
   - Research: SQL Lab usage patterns for simple queries

**Output**: research.md with consolidated findings including:
- Superset 4.x Docker image tag decision
- Healthcare schema field definitions
- Dashboard JSON export format
- Docker Compose service configuration

## Phase 1: Design & Contracts

*Prerequisites: research.md complete*

### 1. Data Model (`data-model.md`)

**Entities**:

**Patients** (250 synthetic records):
- PatientID (INT, PRIMARY KEY)
- FirstName (VARCHAR(50))
- LastName (VARCHAR(50))
- DateOfBirth (DATE)
- Gender (VARCHAR(10)) - M/F/Other
- Status (VARCHAR(20)) - Active/Discharged/Deceased
- AdmissionDate (DATE)
- DischargeDate (DATE, nullable)

**LabResults** (400 synthetic records, averaging 1.6 results per patient):
- ResultID (INT, PRIMARY KEY)
- PatientID (INT, FOREIGN KEY → Patients.PatientID)
- TestName (VARCHAR(100)) - e.g., "Blood Glucose", "Hemoglobin A1C"
- TestDate (DATE)
- Result (NUMERIC(10,2))
- Unit (VARCHAR(20)) - e.g., "mg/dL", "%"
- ReferenceRange (VARCHAR(50)) - e.g., "70-100 mg/dL"
- Status (VARCHAR(20)) - Normal/Abnormal/Critical

### 2. Contracts (`/contracts/`)

**patients-schema.sql**:
```sql
CREATE TABLE Patients (
    PatientID INT PRIMARY KEY,
    FirstName VARCHAR(50),
    LastName VARCHAR(50),
    DateOfBirth DATE,
    Gender VARCHAR(10),
    Status VARCHAR(20),
    AdmissionDate DATE,
    DischargeDate DATE
);
```

**labresults-schema.sql**:
```sql
CREATE TABLE LabResults (
    ResultID INT PRIMARY KEY,
    PatientID INT,
    TestName VARCHAR(100),
    TestDate DATE,
    Result NUMERIC(10,2),
    Unit VARCHAR(20),
    ReferenceRange VARCHAR(50),
    Status VARCHAR(20),
    FOREIGN KEY (PatientID) REFERENCES Patients(PatientID)
);
```

**superset-dashboard-config.json**:
- Dashboard title: "Healthcare Overview"
- Charts:
  1. Bar chart: Patient count by Status
  2. Line chart: Lab results trend over time (by TestDate)
  3. Pie chart: Lab result distribution by Status (Normal/Abnormal/Critical)
  4. Table: Recent patients (sorted by AdmissionDate DESC, LIMIT 10)

### 3. Contract Tests

**Manual Validation Checklist** (No automated tests for example project):
- [ ] Patients table accessible via Superset SQL Lab
- [ ] LabResults table accessible via Superset SQL Lab
- [ ] Patients dataset created without errors
- [ ] LabResults dataset created without errors
- [ ] Bar chart renders with patient status data
- [ ] Line chart renders with time-series lab results
- [ ] Pie chart renders with lab result status distribution
- [ ] Table displays patient records with proper sorting

### 4. Quickstart Test Scenarios

**Scenario 1**: Docker Compose Launch
```bash
# From repository root
cd examples/superset-iris-healthcare
docker-compose -f ../../docker-compose.yml -f docker-compose.superset.yml --profile superset-example up -d

# Expected: All services start (iris, pgwire, superset)
# Expected: Superset accessible at http://localhost:8088
# Expected: Login with admin/admin
```

**Scenario 2**: Database Connection Test
```
1. Navigate to Superset UI (http://localhost:8088)
2. Go to Settings → Database Connections
3. Test existing "IRIS Healthcare" connection
4. Expected: "Connection looks good!" message
```

**Scenario 3**: Query Execution
```sql
-- In Superset SQL Lab
SELECT COUNT(*) as patient_count, Status
FROM Patients
GROUP BY Status
ORDER BY patient_count DESC;

-- Expected: Results showing patient counts by status
-- Expected: Query executes in <1 second
```

**Scenario 4**: Dashboard Access
```
1. Navigate to Dashboards → "Healthcare Overview"
2. Expected: 4 visualizations render without errors
3. Expected: Charts populate with IRIS data
4. Expected: Filters are functional (date range, status)
```

### 5. Agent Context Update

Execute: `.specify/scripts/bash/update-agent-context.sh claude`

**New Technology Context to Add**:
- Apache Superset 4 configuration (docker-compose, database connections, dashboard JSON export)
- IRIS healthcare schema patterns (Patients, LabResults tables)
- Superset dataset creation and dashboard configuration

**Output**: Updated `/Users/tdyar/ws/iris-pgwire/CLAUDE.md` with example-specific guidance

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:

1. **Data Preparation Tasks**:
   - T001: Create IRIS healthcare schema SQL (Patients, LabResults tables)
   - T002: Generate synthetic patient data (100-500 records)
   - T003: Generate synthetic lab results data (100-500 records)

2. **Docker Configuration Tasks**:
   - T004: Create docker-compose.superset.yml with Superset 4 service
   - T005: Configure Superset initialization (db upgrade, admin creation)
   - T006: Add superset-example profile to main docker-compose.yml

3. **Superset Configuration Tasks**:
   - T007: Create IRIS database connection in Superset (PostgreSQL driver to PGWire)
   - T008: Create Patients dataset in Superset
   - T009: Create LabResults dataset in Superset
   - T010: Create bar chart (Patient count by Status)
   - T011: Create line chart (Lab results trend over time)
   - T012: Create pie chart (Lab result status distribution)
   - T013: Create table visualization (Recent patients)
   - T014: Assemble dashboard with all 4 visualizations
   - T015: Export dashboard configuration to JSON

4. **Documentation Tasks**:
   - T016: Write examples/superset-iris-healthcare/README.md (setup instructions)
   - T017: Write SETUP.md (detailed walkthrough with screenshots)
   - T018: Write QUERIES.md (example SQL Lab queries)
   - T019: Write TROUBLESHOOTING.md (common issues and solutions)
   - T020: Update main repository README.md to mention Superset example

5. **Validation Tasks**:
   - T021: Manual test: Docker Compose launch (all services start)
   - T022: Manual test: Superset database connection (PGWire connectivity)
   - T023: Manual test: SQL Lab query execution (simple SELECTs work)
   - T024: Manual test: Dashboard rendering (all 4 charts display)
   - T025: Manual test: 10-minute setup time (follow README from scratch)

**Ordering Strategy**:
- **Sequential Dependencies**:
  1. Data tasks first (T001-T003) → Required for Superset datasets
  2. Docker tasks (T004-T006) → Required for Superset service
  3. Superset config tasks (T007-T015) → Builds on data and docker
  4. Documentation tasks (T016-T020) → Can be done in parallel after T001-T015
  5. Validation tasks (T021-T025) → Final verification

- **Parallel Opportunities** [P]:
  - T002, T003 [P] - Data generation can be done independently
  - T004, T005, T006 [P] - Docker configuration files independent
  - T010, T011, T012, T013 [P] - Chart creation can be done independently
  - T016, T017, T018, T019 [P] - Documentation writing independent

**Estimated Output**: 25 numbered, dependency-ordered tasks in tasks.md

**Task Categories**:
- Data Preparation: 3 tasks
- Docker Configuration: 3 tasks
- Superset Configuration: 9 tasks
- Documentation: 5 tasks
- Validation: 5 tasks

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)
**Phase 4**: Implementation (execute tasks.md following TDD and constitutional principles)
**Phase 5**: Validation (manual testing via Superset UI, SQL Lab, dashboard rendering)

## Complexity Tracking
*No complexity deviations - example project uses existing functionality*

## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [ ] Phase 3: Tasks generated (/tasks command)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS (no protocol modifications)
- [x] Post-Design Constitution Check: PASS (example uses existing PGWire)
- [x] All NEEDS CLARIFICATION resolved (5 clarifications in spec.md Session 2025-01-05)
- [x] Complexity deviations documented (none - straightforward example project)

---
*Based on Constitution v1.2.4 - See `.specify/memory/constitution.md`*
