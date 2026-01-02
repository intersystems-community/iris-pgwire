# Feature Specification: IRIS DevTester Agentic Skills Integration

**Feature Branch**: `033-devtester-skills`
**Created**: 2025-01-02
**Status**: Draft
**Input**: User description: "Update iris-devtester and test out new agentic skills exposed in that project to run and test some new-ish functionality in iris-pgwire"

## Execution Flow (main)
```
1. Parse user description from Input
   → Feature clear: Integrate iris-devtester CLI skills for testing iris-pgwire
2. Extract key concepts from description
   → Actors: Developer, CI/CD system
   → Actions: Run tests, manage containers, troubleshoot issues
   → Data: Test results, container state, fixture data
   → Constraints: Must work with existing docker-compose setup
3. For unclear aspects:
   → Reasonable defaults applied (see Assumptions)
4. Fill User Scenarios & Testing section
   → Developer workflow for testing new functionality
5. Generate Functional Requirements
   → Each requirement testable
6. Define Success Criteria
   → Measurable outcomes
7. Return: SUCCESS (spec ready for planning)
```

---

## ⚡ Quick Guidelines
- ✅ Focus on WHAT users need and WHY
- ❌ Avoid HOW to implement (no tech stack, APIs, code structure)
- 👥 Written for business stakeholders, not developers

### Section Requirements
- **Mandatory sections**: Must be completed for every feature
- **Optional sections**: Include only when relevant to the feature
- When a section doesn't apply, remove it entirely (don't leave as "N/A")

---

## Context

**iris-devtester** is a Python package providing testing infrastructure for InterSystems IRIS development. It is a dependency of iris-pgwire used for:
- Container management (start/stop IRIS containers)
- Connection management (DBAPI connections with auto-retry)
- Password reset handling (handles "ChangePassword required" errors)
- CallIn service enablement (required for DBAPI connections)
- Test fixture loading (.DAT files for test data)
- Troubleshooting common IRIS/Docker issues

The package exposes **agentic skills** (Claude Code slash commands) that automate common tasks:
- `/container` - Start, stop, manage IRIS containers
- `/connection` - Establish and troubleshoot database connections
- `/fixture` - Create, load, and validate test fixtures
- `/troubleshooting` - Diagnose and fix common IRIS/Docker issues

---

## User Scenarios & Testing *(mandatory)*

### Primary User Story
As a **developer working on iris-pgwire**, I want to use iris-devtester's agentic skills to quickly set up test environments, run tests, and troubleshoot issues without manually managing Docker containers or debugging connection problems.

As a **CI/CD system**, I want reliable, automated test infrastructure that handles common IRIS container issues automatically so tests pass consistently.

### Acceptance Scenarios

1. **Given** iris-devtester is installed and updated, **When** a developer runs tests for iris-pgwire, **Then** the testing infrastructure automatically handles container startup, password resets, and CallIn service enablement

2. **Given** a fresh development environment, **When** a developer invokes the container skill, **Then** an IRIS container is started and verified healthy within 60 seconds

3. **Given** a "Password change required" error occurs, **When** the connection skill is used, **Then** the password is automatically reset and connection established without manual intervention

4. **Given** new iris-pgwire functionality needs testing, **When** a developer uses the fixture skill, **Then** test data can be loaded/exported to create reproducible test scenarios

5. **Given** a connection or container issue occurs, **When** the troubleshooting skill is invoked, **Then** the issue is diagnosed and remediation steps are provided or automatically applied

### Edge Cases
- What happens when Docker is not running? → Clear error message with remediation steps
- What happens when port 1972 is already in use? → Automatic port selection or clear conflict message
- What happens when the IRIS image is not cached? → Progress indication during download
- What happens when tests run in parallel? → Isolated containers per test session

---

## Requirements *(mandatory)*

### Functional Requirements

**Dependency Management:**
- **FR-001**: iris-pgwire MUST declare iris-devtester as a test dependency
- **FR-002**: The test suite MUST be able to use iris-devtester's container management instead of manual docker-compose

**Container Management:**
- **FR-003**: Tests MUST be able to start an isolated IRIS container automatically
- **FR-004**: Tests MUST be able to verify container health (port 1972 accessible, IRIS ready)
- **FR-005**: Tests MUST be able to stop and clean up containers after test completion

**Connection Management:**
- **FR-006**: Tests MUST be able to obtain DBAPI connections with automatic retry on transient failures
- **FR-007**: Tests MUST handle "Password change required" errors automatically
- **FR-008**: Tests MUST enable CallIn service automatically if disabled

**Test Data Management:**
- **FR-009**: Tests MUST be able to load pre-defined test fixtures for reproducible scenarios
- **FR-010**: Tests MUST be able to export current database state as a fixture for debugging

**Troubleshooting:**
- **FR-011**: Common connection errors MUST produce actionable error messages with remediation steps
- **FR-012**: Container health issues MUST be diagnosable via the troubleshooting skill

**New Functionality Testing:**
- **FR-013**: The integration MUST support testing recently added iris-pgwire features (pg_catalog, ORM introspection, vector operations)
- **FR-014**: Tests MUST verify that PostgreSQL clients can connect through iris-pgwire to the test container

### Key Entities

- **Test Container**: An isolated IRIS instance managed by iris-devtester for testing
- **Test Fixture**: A .DAT file containing pre-defined test data that can be loaded into a container
- **Connection Config**: Configuration object containing host, port, namespace, credentials for IRIS connection
- **Health Check**: Verification that container is running and accepting connections

---

## Assumptions

1. **Docker Desktop**: Docker is installed and running on the development machine
2. **IRIS Image**: The IRIS Community Edition image is available (will be pulled if not cached)
3. **Existing Tests**: iris-pgwire has existing test suites that can be enhanced with iris-devtester
4. **Port Availability**: Port 1972 (IRIS) and 5432 (PGWire) are available or can be dynamically allocated
5. **Single Container**: Most tests use a single shared container for efficiency; isolation tests get their own container

---

## Dependencies

1. **iris-devtester package**: Must be updated to latest version with agentic skills
2. **Docker**: Required for container management
3. **intersystems-irispython**: Required for DBAPI connections
4. **Existing test infrastructure**: docker-compose.yml and conftest.py in iris-pgwire

---

## Success Criteria

1. **Automated Setup**: Developer can run `pytest` without manual container setup - infrastructure handles everything automatically
2. **Error Recovery**: 90%+ of common errors (password change, CallIn disabled, container not started) are handled automatically
3. **Test Reliability**: Test suite passes consistently (no flaky tests due to infrastructure issues)
4. **Development Speed**: Time from "git clone" to "first test passing" is under 5 minutes
5. **New Feature Coverage**: At least 3 new iris-pgwire features are tested using the devtester infrastructure

---

## Review & Acceptance Checklist

### Content Quality
- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

### Requirement Completeness
- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

---

## Execution Status

- [x] User description parsed
- [x] Key concepts extracted (container management, connection handling, fixtures, troubleshooting)
- [x] Ambiguities resolved (reasonable defaults applied)
- [x] User scenarios defined
- [x] Requirements generated (14 functional requirements)
- [x] Entities identified (Test Container, Test Fixture, Connection Config, Health Check)
- [x] Review checklist passed
