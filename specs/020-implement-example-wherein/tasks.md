# Tasks: Apache Superset 4 with IRIS Backend Example

**Input**: Design documents from `/specs/020-implement-example-wherein/`
**Prerequisites**: plan.md (complete), spec.md (complete)
**Branch**: `020-implement-example-wherein`

## Execution Flow (main)
```
1. Load plan.md from feature directory
   → ✅ Loaded: Apache Superset 4 with IRIS Backend Example
   → Extract: Superset 4, Python 3.11, Docker Compose, healthcare data
2. Load optional design documents:
   → spec.md: 17 functional requirements, healthcare domain
   → data-model.md: Not yet created (will be in contracts)
   → contracts/: SQL schemas and JSON configs (defined in plan)
3. Generate tasks by category:
   → Data Preparation: 3 tasks (schema, patient data, lab results)
   → Docker Configuration: 3 tasks (compose file, init, profile)
   → Superset Configuration: 9 tasks (connection, datasets, charts, dashboard)
   → Documentation: 5 tasks (README, SETUP, QUERIES, TROUBLESHOOTING, main README)
   → Validation: 5 tasks (manual testing)
4. Apply task rules:
   → Data generation tasks can run [P]
   → Docker config tasks can run [P]
   → Chart creation tasks can run [P]
   → Documentation tasks can run [P]
   → Superset config depends on data + docker
5. Number tasks sequentially (T001-T025)
6. Manual testing approach (no automated tests for demo)
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions
- This is an example/demo project - manual validation instead of automated tests

## Path Conventions
- **Example directory**: `examples/superset-iris-healthcare/`
- **Data files**: `examples/superset-iris-healthcare/data/`
- **Superset configs**: `examples/superset-iris-healthcare/superset/`
- **Documentation**: `examples/superset-iris-healthcare/docs/`

## Phase 3.1: Data Preparation
**Purpose**: Create IRIS healthcare schema and synthetic sample data

- [x] **T001** Create IRIS healthcare schema SQL in `examples/superset-iris-healthcare/data/init-healthcare-schema.sql`
  - Define Patients table (PatientID, FirstName, LastName, DateOfBirth, Gender, Status, AdmissionDate, DischargeDate)
  - Define LabResults table (ResultID, PatientID, TestName, TestDate, Result, Unit, ReferenceRange, Status)
  - Add foreign key constraint: LabResults.PatientID → Patients.PatientID
  - Use IRIS SQL data types (INT, VARCHAR, DATE, NUMERIC)
  - Include DROP TABLE IF EXISTS statements for clean re-initialization

- [x] **T002 [P]** Generate synthetic patient data in `examples/superset-iris-healthcare/data/patients-data.sql`
  - Generate exactly 250 INSERT statements for Patients table
  - Realistic but synthetic names (use common first/last names)
  - Randomized dates of birth (range: 1940-2010)
  - Gender distribution: M/F/Other (balanced)
  - Status distribution: Active (70%), Discharged (25%), Deceased (5%)
  - AdmissionDate range: 2020-2025
  - DischargeDate: NULL for Active, populated for Discharged/Deceased

- [x] **T003 [P]** Generate synthetic lab results data in `examples/superset-iris-healthcare/data/labresults-data.sql`
  - Generate exactly 400 INSERT statements for LabResults table (averaging 1.6 results per patient)
  - Link to existing PatientIDs from T002
  - Test types: Blood Glucose, Hemoglobin A1C, Cholesterol, Blood Pressure, etc.
  - TestDate range: 2020-2025 (after patient admission)
  - Result values: Numeric with appropriate ranges per test type
  - Units: mg/dL, %, mmHg, etc.
  - ReferenceRange: Normal ranges per test type
  - Status distribution: Normal (70%), Abnormal (25%), Critical (5%)

## Phase 3.2: Docker Configuration
**Purpose**: Configure Docker Compose for Superset 4 service

- [x] **T004 [P]** Create Superset service definition in `examples/superset-iris-healthcare/docker-compose.superset.yml`
  - Use official Superset 4 Docker image (apache/superset:4.0 or latest-4.x tag)
  - Expose port 8088:8088
  - Configure environment variables (SUPERSET_SECRET_KEY, database backend)
  - Add healthcheck (HTTP GET to /health endpoint)
  - Define depends_on: iris, pgwire (from main docker-compose.yml)
  - Volume mounts for persistent configs and dashboards
  - Network: Connect to existing iris-pgwire network

- [x] **T005 [P]** Create Superset initialization script in `examples/superset-iris-healthcare/superset/init-superset.sh`
  - Database upgrade: `superset db upgrade`
  - Create admin user: `superset fab create-admin` (username: admin, password: admin)
    **SECURITY NOTE**: These credentials are for DEMO PURPOSES ONLY. Do NOT use admin/admin in production environments.
  - Initialize Superset: `superset init`
  - Import database connection (IRIS via PGWire)
  - Import datasets (Patients, LabResults)
  - Import dashboard (healthcare-overview.json)
  - Make script executable and idempotent

- [x] **T006 [P]** Add superset-example profile to main `docker-compose.yml`
  - Add include directive for docker-compose.superset.yml
  - Document profile in comments
  - Add to existing profiles (alongside bi-tools, etc.)
  - Usage: `docker-compose --profile superset-example up -d`

## Phase 3.3: Superset Configuration (Sequential - Depends on T001-T006)
**Purpose**: Configure Superset connection, datasets, charts, and dashboard

**CRITICAL**: These tasks must be done AFTER T001-T006 (data and docker ready)

- [x] **T007** Document IRIS database connection configuration for Superset
  - Connection type: PostgreSQL
  - Host: iris (or localhost if outside Docker)
  - Port: 5432
  - Database: USER
  - Username: test_user (or configured PGWire user)
  - Password: (blank or configured password)
  - Test connection and document expected success message
  - Save as JSON export in `examples/superset-iris-healthcare/superset/database-connection.json`

- [x] **T008** Create Patients dataset configuration in `examples/superset-iris-healthcare/superset/datasets/patients-dataset.json`
  - Dataset name: "IRIS Patients"
  - Table: Patients
  - Database: IRIS Healthcare (from T007)
  - Columns: Map all 8 columns with appropriate data types
  - Metrics: Patient Count (COUNT(*))
  - Default time column: AdmissionDate
  - Enable caching (1 hour)
  - **Validation**: Execute test query `SELECT COUNT(*) FROM Patients` - expect 250 rows
  - Export as JSON for import during initialization

- [x] **T009** Create LabResults dataset configuration in `examples/superset-iris-healthcare/superset/datasets/labresults-dataset.json`
  - Dataset name: "IRIS Lab Results"
  - Table: LabResults
  - Database: IRIS Healthcare (from T007)
  - Columns: Map all 8 columns with appropriate data types
  - Metrics: Result Count (COUNT(*)), Average Result (AVG(Result))
  - Default time column: TestDate
  - Enable caching (1 hour)
  - **Validation**: Execute test query `SELECT COUNT(*) FROM LabResults` - expect 400 rows
  - Export as JSON for import during initialization

## Phase 3.4: Chart Creation (Parallel - Depends on T007-T009)
**Purpose**: Create 4 basic visualizations for healthcare dashboard

**CRITICAL**: These tasks can run in PARALLEL (different chart files)

- [ ] **T010 [P]** Create bar chart "Patient Count by Status" in `examples/superset-iris-healthcare/superset/charts/patient-status-bar.json`
  - Chart type: Bar Chart
  - Dataset: IRIS Patients (from T008)
  - Dimension: Status
  - Metric: Patient Count (COUNT(*))
  - Sort: Descending by count
  - Color scheme: Categorical (green for Active, blue for Discharged, gray for Deceased)
  - Export as JSON

- [ ] **T011 [P]** Create line chart "Lab Results Trend" in `examples/superset-iris-healthcare/superset/charts/labresults-trend-line.json`
  - Chart type: Line Chart
  - Dataset: IRIS Lab Results (from T009)
  - X-axis: TestDate (time series, grouped by month)
  - Y-axis: Result Count (COUNT(*))
  - Series: TestName (multiple lines for different test types)
  - Time range: Last 12 months
  - Export as JSON

- [ ] **T012 [P]** Create pie chart "Lab Result Status Distribution" in `examples/superset-iris-healthcare/superset/charts/labresults-status-pie.json`
  - Chart type: Pie Chart
  - Dataset: IRIS Lab Results (from T009)
  - Dimension: Status
  - Metric: Result Count (COUNT(*))
  - Show percentages
  - Color scheme: Green (Normal), Yellow (Abnormal), Red (Critical)
  - Export as JSON

- [ ] **T013 [P]** Create table "Recent Patients" in `examples/superset-iris-healthcare/superset/charts/recent-patients-table.json`
  - Chart type: Table
  - Dataset: IRIS Patients (from T008)
  - Columns: PatientID, FirstName, LastName, Status, AdmissionDate
  - Sort: AdmissionDate DESC
  - Limit: 10 rows
  - Enable pagination
  - Export as JSON

## Phase 3.5: Dashboard Assembly (Sequential - Depends on T010-T013)
**Purpose**: Assemble final dashboard and export configuration

- [ ] **T014** Assemble "Healthcare Overview" dashboard in Superset UI
  - Create new dashboard: "Healthcare Overview"
  - Add all 4 charts from T010-T013
  - Layout: 2x2 grid (bar chart top-left, line chart top-right, pie chart bottom-left, table bottom-right)
  - Add title and description
  - Configure filters:
    - Date range filter (linked to AdmissionDate and TestDate)
    - Status filter (categorical, linked to both datasets)
  - Test filter functionality

- [ ] **T015** Export dashboard configuration to `examples/superset-iris-healthcare/superset/dashboards/healthcare-overview.json`
  - Use Superset export dashboard feature
  - Include all 4 charts, datasets, and database connection
  - Verify JSON structure (dashboards, charts, datasets, databases arrays)
  - Document import process in comments
  - This JSON will be imported during T005 initialization

## Phase 3.6: Documentation (Parallel - Depends on T001-T015)
**Purpose**: Create comprehensive setup and usage documentation

**CRITICAL**: These tasks can run in PARALLEL (different documentation files)

- [x] **T016 [P]** Write main example README in `examples/superset-iris-healthcare/README.md`
  - Overview: What this example demonstrates
  - Prerequisites: Docker, Docker Compose
  - Quick start (3 steps):
    1. Start services: `docker-compose --profile superset-example up -d`
    2. Wait for initialization (2-3 minutes)
    3. Access Superset: http://localhost:8088 (admin/admin)
  - What's included: 2 tables, 4 charts, 1 dashboard
  - Connection details: PGWire on port 5432
  - Links to detailed docs (SETUP.md, QUERIES.md, TROUBLESHOOTING.md)
  - Expected setup time: <10 minutes

- [x] **T017 [P]** Write detailed setup guide in `examples/superset-iris-healthcare/docs/SETUP.md`
  - Step-by-step walkthrough with screenshots
  - Section 1: Starting services (docker-compose command, health checks)
  - Section 2: Accessing Superset UI (login, initial screen)
  - Section 3: Verifying database connection (Settings → Database Connections → Test)
  - Section 4: Exploring datasets (Data → Datasets → IRIS Patients, IRIS Lab Results)
  - Section 5: Viewing dashboard (Dashboards → Healthcare Overview)
  - Section 6: Using SQL Lab (SQL Lab → query editor, sample queries)
  - Screenshots/descriptions for each section

- [x] **T018 [P]** Write example queries guide in `examples/superset-iris-healthcare/docs/QUERIES.md`
  - 3-5 example SQL Lab queries:
    1. Patient count by status: `SELECT Status, COUNT(*) FROM Patients GROUP BY Status`
    2. Recent lab results: `SELECT * FROM LabResults ORDER BY TestDate DESC LIMIT 10`
    3. Abnormal results by test: `SELECT TestName, COUNT(*) FROM LabResults WHERE Status = 'Abnormal' GROUP BY TestName`
    4. Patient demographics: `SELECT Gender, COUNT(*) FROM Patients GROUP BY Gender`
    5. Average results by test: `SELECT TestName, AVG(Result) FROM LabResults GROUP BY TestName`
  - Expected results for each query
  - Performance expectations (<1 second execution)

- [x] **T019 [P]** Write troubleshooting guide in `examples/superset-iris-healthcare/docs/TROUBLESHOOTING.md`
  - Common Issue 1: "Connection refused" → Check PGWire is running on port 5432
  - Common Issue 2: "Authentication failed" → Verify credentials (test_user, blank password)
  - Common Issue 3: "Table not found" → Check IRIS schema initialized (run init-healthcare-schema.sql)
  - Common Issue 4: "Dashboard empty" → Verify data loaded (patients-data.sql, labresults-data.sql)
  - Common Issue 5: "Charts not rendering" → Check browser console, clear Superset cache
  - Health check commands:
    - `docker-compose ps` (verify all services running)
    - `psql -h localhost -p 5432 -U test_user -d USER -c "SELECT COUNT(*) FROM Patients"`
  - Logs: `docker-compose logs superset`, `docker-compose logs pgwire`

- [x] **T020 [P]** Update main repository README to mention Superset example in `README.md`
  - **Dependency Note**: Can proceed in parallel with T016-T019, but verify example README path after T016 completion
  - Add row to "What Works" table:
    | **Apache Superset 4** | ✅ BI dashboards, SQL Lab, data exploration | examples/superset-iris-healthcare/ |
  - Add to "Use Cases" section:
    - "Connect Superset 4 to IRIS for healthcare data visualization (see examples/superset-iris-healthcare/)"
  - Add link to documentation section:
    - examples/superset-iris-healthcare/README.md - Apache Superset 4 integration example

## Phase 3.7: Validation (Sequential - Final Phase, Depends on All)
**Purpose**: Manual validation of complete example

**CRITICAL**: These tasks MUST be done SEQUENTIALLY (each builds on previous)

- [ ] **T021** Manual test: Docker Compose launch
  - Clean environment: `docker-compose down -v`
  - Start services: `docker-compose --profile superset-example up -d`
  - Verify all services start without errors (iris, pgwire, superset)
  - Check health: `docker-compose ps` (all should show "healthy" or "running")
  - Wait for Superset initialization (2-3 minutes)
  - Expected: All services running, no error logs

- [ ] **T022** Manual test: Superset database connection
  - Navigate to http://localhost:8088
  - Login: admin/admin
  - Go to Settings → Database Connections
  - Find "IRIS Healthcare" connection
  - Click "Test Connection" button
  - Expected: "Connection looks good!" success message
  - If fails: Check TROUBLESHOOTING.md

- [ ] **T023** Manual test: SQL Lab query execution
  - Navigate to SQL Lab → SQL Editor
  - Select database: "IRIS Healthcare"
  - Select schema: USER
  - Execute query: `SELECT COUNT(*) as patient_count, Status FROM Patients GROUP BY Status ORDER BY patient_count DESC`
  - Expected: Results showing patient counts by status (Active, Discharged, Deceased)
  - Expected: Query executes in <1 second
  - Try 2-3 more queries from QUERIES.md

- [ ] **T024** Manual test: Dashboard rendering
  - Navigate to Dashboards
  - Find "Healthcare Overview" dashboard
  - Click to open
  - Expected: 4 visualizations render without errors:
    1. Bar chart (Patient Count by Status) - top-left
    2. Line chart (Lab Results Trend) - top-right
    3. Pie chart (Lab Result Status Distribution) - bottom-left
    4. Table (Recent Patients) - bottom-right
  - Expected: All charts populated with IRIS data
  - Test filters: Date range filter, Status filter
  - Expected: Dashboard renders in <2 seconds

- [ ] **T025** Manual test: 10-minute setup time
  - Fresh clone: `git clone <repo>` (or fresh checkout)
  - Follow README.md from scratch (no prior knowledge)
  - Start timer: Execute `docker-compose --profile superset-example up -d`
  - Stop timer: Dashboard visible at http://localhost:8088 with all 4 charts rendering
  - Expected: Complete setup in <10 minutes from docker-compose command
  - Document actual time and any pain points
  - Update README if any steps unclear

## Dependencies

### Sequential Dependencies
- **T001** (schema) blocks → T002, T003 (data needs schema structure)
- **T001-T003** (data ready) + **T004-T006** (docker ready) block → **T007** (Superset connection)
- **T007** (connection) blocks → **T008, T009** (datasets need connection)
- **T008, T009** (datasets) block → **T010-T013** (charts need datasets)
- **T010-T013** (charts) block → **T014** (dashboard assembly)
- **T014** (dashboard) blocks → **T015** (export configuration)
- **T001-T015** (implementation complete) block → **T016-T020** (documentation)
- **T001-T020** (everything) blocks → **T021-T025** (validation)

### Parallel Opportunities [P]
- **T002, T003** [P] - Different data files (patients vs lab results)
- **T004, T005, T006** [P] - Different docker config files
- **T010, T011, T012, T013** [P] - Different chart configurations
- **T016, T017, T018, T019, T020** [P] - Different documentation files

## Parallel Execution Examples

### Data Generation (after T001)
```bash
# Launch T002 and T003 together:
# In separate terminals or background processes
python scripts/generate_patients.py > examples/superset-iris-healthcare/data/patients-data.sql &
python scripts/generate_labresults.py > examples/superset-iris-healthcare/data/labresults-data.sql &
```

### Docker Configuration (independent)
```bash
# Can work on these files simultaneously
# T004: docker-compose.superset.yml
# T005: superset/init-superset.sh
# T006: docker-compose.yml (add profile)
```

### Chart Creation (after T008-T009)
```bash
# Create all 4 charts in parallel in Superset UI
# Different chart types, different names, no file conflicts
# T010: Bar chart
# T011: Line chart
# T012: Pie chart
# T013: Table
```

### Documentation Writing (after implementation)
```bash
# Launch T016-T020 together:
# All different markdown files, no conflicts
# T016: README.md
# T017: docs/SETUP.md
# T018: docs/QUERIES.md
# T019: docs/TROUBLESHOOTING.md
# T020: ../../README.md (different file)
```

## Notes

### Manual Testing Approach
- **No automated tests**: This is an example/demo project
- **Manual validation**: Via Superset UI and SQL Lab
- **Success criteria**: Dashboard renders, queries execute, <10 min setup
- **Documentation**: Detailed troubleshooting for common issues

### Performance Expectations
- **Setup time**: <10 minutes (T025 validates)
- **Query execution**: <1 second (T023 validates)
- **Dashboard rendering**: <2 seconds (T024 validates)

### Docker Integration
- **Profile-based**: `--profile superset-example`
- **Network**: Reuses existing iris-pgwire network
- **Dependencies**: iris and pgwire services from main compose file

### Data Scale
- **Small dataset**: 100-500 rows per table
- **Purpose**: Fast setup, quick rendering, clear visualizations
- **Realistic**: Synthetic healthcare data with proper distributions

## Task Generation Rules
*Applied during main() execution*

1. **From Plan.md**:
   - Data Preparation: 3 tasks (schema, patients, lab results)
   - Docker Configuration: 3 tasks (compose file, init, profile)
   - Superset Configuration: 9 tasks (connection, datasets, charts, dashboard, export)
   - Documentation: 5 tasks (README, SETUP, QUERIES, TROUBLESHOOTING, main README)
   - Validation: 5 tasks (manual testing checklist)

2. **Ordering**:
   - Data → Docker → Superset Config → Documentation → Validation
   - Charts can be parallel (different files)
   - Documentation can be parallel (different files)

3. **No TDD**:
   - Example project, not production code
   - Manual validation replaces automated tests
   - UI-driven workflow (Superset configuration)

## Validation Checklist
*GATE: Checked before marking tasks complete*

- [x] All data preparation tasks defined (T001-T003)
- [x] All docker configuration tasks defined (T004-T006)
- [x] All Superset configuration tasks defined (T007-T015)
- [x] All documentation tasks defined (T016-T020)
- [x] All validation tasks defined (T021-T025)
- [x] Parallel tasks truly independent (different files)
- [x] Each task specifies exact file path
- [x] No task modifies same file as another [P] task
- [x] Sequential dependencies clearly documented
- [x] 25 tasks total (matches plan.md estimate)

---

**Ready for Implementation**: Execute tasks T001-T025 in dependency order
**Next Command**: Begin implementation with T001 (create schema SQL)
