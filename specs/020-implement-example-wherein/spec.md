# Feature Specification: Apache Superset 4 with IRIS Backend Example

**Feature Branch**: `020-implement-example-wherein`
**Created**: 2025-01-05
**Status**: Draft
**Input**: User description: "implement example wherein we provide a IRIS back end to superset version 4"

## Clarifications

### Session 2025-01-05

- Q: Sample Data Domain - What type of data should the example demonstrate? → A: Healthcare/Medical - Synthetic patient records and lab results (realistic but generated data, not real patient information)
- Q: Vector Capabilities Demonstration - Should the example include IRIS VECTOR column demonstrations with similarity queries? → A: No - Focus on standard relational data only, skip vector features entirely
- Q: Dashboard Complexity - What level of Superset features should the example demonstrate? → A: Basic charts only - Bar, line, pie, table visualizations with simple filters (see Definitions section for criteria)
- Q: SQL Query Complexity - What SQL features should example queries demonstrate? → A: Simple SELECTs - Basic queries with WHERE, ORDER BY, LIMIT only
- Q: Dataset Scale - What data volume should the example include? → A: Small - 250 patient records and 400 lab results (fast setup, quick visualization rendering, realistic data distribution)

---

## Execution Flow (main)
```
1. Parse user description from Input
   → Feature: Create working example of Apache Superset 4 connected to IRIS via PGWire
2. Extract key concepts from description
   → Actors: Data analysts, BI users, developers
   → Actions: Connect Superset to IRIS, query IRIS data, create dashboards
   → Data: Healthcare/medical IRIS database tables (patient records, lab results)
   → Constraints: Superset version 4 specifically, basic visualizations only
3. Clarifications resolved:
   → Healthcare/medical domain data (100-500 rows per table)
   → No vector demonstrations (standard relational data only)
   → Basic charts (bar, line, pie, table) with simple filters
   → Simple SQL queries (SELECT, WHERE, ORDER BY, LIMIT)
4. Fill User Scenarios & Testing section
   → User flow: Install → Configure → Connect → Query → Visualize
5. Generate Functional Requirements
   → All requirements testable via actual Superset usage
6. Identify Key Entities
   → Superset database connection, IRIS healthcare data source, example datasets
7. Run Review Checklist
   → SUCCESS: All clarifications resolved, scope clearly defined
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
**As a** data analyst or BI developer working with healthcare data
**I want to** connect Apache Superset 4 to an InterSystems IRIS database via the PGWire protocol
**So that** I can create interactive dashboards and visualizations using IRIS healthcare data without needing IRIS-specific drivers

### Acceptance Scenarios

1. **Given** I have IRIS running with PGWire server and Superset 4 installed
   **When** I configure a PostgreSQL database connection in Superset pointing to PGWire (localhost:5432)
   **Then** Superset successfully connects and can list available IRIS healthcare tables

2. **Given** I have connected Superset to IRIS via PGWire
   **When** I create a new dataset from an IRIS healthcare table (e.g., Patients, LabResults)
   **Then** Superset can query the table and display sample healthcare data without errors

3. **Given** I have created a dataset from IRIS healthcare data
   **When** I build a basic chart (bar, line, pie, or table) using that dataset
   **Then** The visualization renders correctly with patient or lab result data from IRIS

4. **Given** I am viewing a working example
   **When** I examine the example configuration and sample queries
   **Then** I can understand how to replicate the setup for my own IRIS healthcare data

5. **Given** The example includes sample healthcare data (100-500 rows)
   **When** I access the pre-configured example dashboard
   **Then** I can see basic visualizations demonstrating IRIS healthcare data capabilities through Superset

### Edge Cases
- What happens when the PGWire server is unavailable? (Superset should show clear connection error)
- What happens if IRIS SQL syntax differs from PostgreSQL? (PGWire translation layer should handle this transparently)
- How are result sets handled for tables at the upper limit (500 rows)? (Superset should render without performance issues)

## Definitions

**Basic Charts**: Bar charts, line charts, pie charts, and table visualizations only. No custom visualization plugins, no computed chart expressions, no advanced chart types (bubble, scatter, heatmap, etc.).

**Simple Filters**: Single-column filters only. Includes categorical filters (e.g., filter by Status = 'Active') and date range filters (e.g., filter AdmissionDate between 2024-01-01 and 2024-12-31). Excludes multi-column filters, computed filter expressions, and cross-dataset filters.

**Simple SQL Queries**: SELECT statements with basic clauses: WHERE (equality comparisons), ORDER BY (single column), LIMIT (row count). Excludes JOINs, subqueries, CTEs, window functions, and aggregations beyond COUNT(*).

---

## Requirements *(mandatory)*

### Functional Requirements

**Example Setup & Configuration**
- **FR-001**: Example MUST provide a working Apache Superset 4 instance configured to connect to IRIS via PGWire
- **FR-002**: Example MUST include clear instructions for starting all required services (IRIS, PGWire, Superset)
- **FR-003**: Example MUST use standard PostgreSQL connection configuration in Superset (no custom drivers required)
- **FR-004**: Example MUST demonstrate successful database connection test in Superset UI

**Sample Data & Datasets**
- **FR-005**: Example MUST include IRIS tables with synthetic healthcare/medical data (e.g., Patients table with 250 generated demographic records, LabResults table with 400 generated test results and dates)
- **FR-006**: Example MUST provide at least one pre-configured Superset dataset connected to IRIS healthcare data
- **FR-007**: Synthetic data MUST contain 250 patient records and 400 lab result records to enable meaningful visualizations while ensuring fast setup and rendering

**Visualization Demonstrations**
- **FR-008**: Example MUST include at least one working dashboard with multiple basic visualizations (bar chart, line chart, pie chart, table)
- **FR-009**: Example MUST demonstrate basic chart types using IRIS healthcare data with simple filters (e.g., filter by date range, patient status)
- **FR-010**: Example MUST show successful execution of simple SQL queries (SELECT with WHERE, ORDER BY, LIMIT) from Superset SQL Lab against IRIS

**Documentation & Usability**
- **FR-011**: Example MUST include README with step-by-step setup instructions
- **FR-012**: Example MUST document the connection parameters (host, port, database, credentials)
- **FR-013**: Example MUST provide troubleshooting guidance for common connection issues
- **FR-014**: Example MUST be reproducible using Docker Compose or similar containerized approach

**Compatibility & Standards**
- **FR-015**: Example MUST work with Apache Superset version 4.x specifically
- **FR-016**: Example MUST use existing PGWire server configuration (no Superset-specific PGWire changes)
- **FR-017**: Example MUST demonstrate that Superset treats IRIS as a standard PostgreSQL database

### Key Entities

- **Superset Database Connection**: Represents the PostgreSQL connection configuration in Superset pointing to PGWire (host: localhost, port: 5432, database: USER)

- **IRIS Healthcare Data Source**: The backend InterSystems IRIS database containing healthcare tables (Patients, LabResults) accessible via PGWire protocol

- **Example Healthcare Datasets**: Pre-configured Superset datasets connected to IRIS healthcare tables (Patients table with 100-500 patient records, LabResults table with 100-500 lab test results), ready for visualization

- **Sample Healthcare Dashboard**: Pre-built Superset dashboard demonstrating basic chart types (bar, line, pie, table) using IRIS patient and lab result data with simple date/status filters

- **Example SQL Queries**: Sample simple SQL queries (SELECT with WHERE, ORDER BY, LIMIT) demonstrating basic healthcare data retrieval executed through Superset SQL Lab

---

## Review & Acceptance Checklist
*GATE: Automated checks run during main() execution*

### Content Quality
- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain (all 5 clarifications resolved)
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable (working Superset connection and dashboards)
- [x] Scope is clearly bounded (example demonstration with healthcare data, basic visualizations, 100-500 rows)
- [x] Dependencies and assumptions identified (requires IRIS, PGWire, Superset 4)

---

## Execution Status
*Updated by main() during processing*

- [x] User description parsed
- [x] Key concepts extracted (Superset 4, IRIS backend, PGWire connection, healthcare data)
- [x] Ambiguities marked and resolved (5 clarification questions answered)
- [x] User scenarios defined (setup, connect, query, visualize healthcare data)
- [x] Requirements generated (17 functional requirements, focused on healthcare demo)
- [x] Entities identified (connection, healthcare data source, datasets, dashboard, queries)
- [x] Review checklist passed (all clarifications resolved, scope clearly defined)

---

## Success Metrics

The example will be considered successful when:
- A user can follow the README and have Superset 4 connected to IRIS healthcare data in under 10 minutes (measured from executing `docker-compose up` to viewing the dashboard in browser)
- Pre-configured dashboard with basic charts (bar, line, pie, table) renders without errors using 100-500 row healthcare datasets
- The example serves as a template for connecting production Superset instances to IRIS healthcare databases
- Documentation clearly demonstrates that no IRIS-specific Superset drivers are needed (standard PostgreSQL connection)
- Simple SQL queries (SELECT, WHERE, ORDER BY, LIMIT) execute successfully in Superset SQL Lab against IRIS healthcare tables
