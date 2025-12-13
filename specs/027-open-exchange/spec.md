# Feature Specification: Open Exchange Package Publication

**Feature Branch**: `027-open-exchange`
**Created**: 2024-12-13
**Status**: Draft
**Input**: User description: "Make this an open exchange package for publication on openexchange.intersystems.com"

## Overview

Package IRIS PGWire for publication on InterSystems Open Exchange, enabling developers worldwide to discover, download, and deploy the PostgreSQL wire protocol server for IRIS databases. This involves creating the required metadata, documentation, and deployment artifacts that meet Open Exchange publication standards.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Developer Discovers and Evaluates Package (Priority: P1)

A developer searching for PostgreSQL compatibility with IRIS discovers the iris-pgwire package on Open Exchange. They can read a clear description of what the package does, see screenshots/demos of it in action, and understand the value proposition within 60 seconds of landing on the package page.

**Why this priority**: Discovery is the first step - if developers can't find and understand the package, nothing else matters.

**Independent Test**: Can be fully tested by visiting the Open Exchange page and timing how quickly a new user understands the package purpose.

**Acceptance Scenarios**:

1. **Given** a developer visits the Open Exchange package page, **When** they read the description, **Then** they understand "connect PostgreSQL tools to IRIS" within 60 seconds
2. **Given** a developer is evaluating the package, **When** they view the package page, **Then** they see at least one visual (screenshot or architecture diagram) demonstrating the capability
3. **Given** a developer wants to know compatibility, **When** they review the package metadata, **Then** they see supported IRIS versions, Python versions, and client compatibility

---

### User Story 2 - Developer Installs Package via ZPM (Priority: P1)

A developer installs the iris-pgwire package using ZPM (IRIS package manager) with a single command and has a working PostgreSQL wire protocol server running within 5 minutes.

**Why this priority**: Installation experience is critical for adoption - complex installation drives developers away.

**Independent Test**: Can be fully tested by running `zpm "install iris-pgwire"` on a fresh IRIS instance and connecting with psql.

**Acceptance Scenarios**:

1. **Given** a developer has IRIS with ZPM installed, **When** they run `zpm "install iris-pgwire"`, **Then** the package downloads and installs without errors
2. **Given** the package is installed, **When** the developer follows the quick start guide, **Then** they can connect using `psql` within 5 minutes
3. **Given** a fresh IRIS 2024.1+ instance, **When** installing via ZPM, **Then** all dependencies are automatically resolved

---

### User Story 3 - Developer Uses Docker Quick Start (Priority: P2)

A developer who prefers containers can use Docker Compose to spin up a complete IRIS + PGWire environment for evaluation without installing anything on their host system.

**Why this priority**: Docker is the fastest path to evaluation for developers unfamiliar with IRIS, removing all friction.

**Independent Test**: Can be fully tested by running `docker-compose up` and connecting with any PostgreSQL client.

**Acceptance Scenarios**:

1. **Given** a developer has Docker installed, **When** they run `docker-compose up -d`, **Then** both IRIS and PGWire services start successfully
2. **Given** the Docker environment is running, **When** the developer runs `psql -h localhost -p 5432 -U _SYSTEM -d USER`, **Then** they connect successfully
3. **Given** the Docker environment is running, **When** the developer executes a sample query, **Then** they receive results from IRIS

---

### User Story 4 - Developer Reads Comprehensive Documentation (Priority: P2)

A developer can access complete documentation for configuration options, authentication methods, vector operations, and troubleshooting directly from the Open Exchange page or linked README.

**Why this priority**: Good documentation reduces support burden and increases successful adoption.

**Independent Test**: Can be fully tested by navigating from the Open Exchange page to find answers to common questions.

**Acceptance Scenarios**:

1. **Given** a developer wants to configure authentication, **When** they search the documentation, **Then** they find OAuth 2.0, IRIS Wallet, and SCRAM-SHA-256 setup guides
2. **Given** a developer encounters an error, **When** they check the troubleshooting section, **Then** they find the KNOWN_LIMITATIONS.md document
3. **Given** a developer wants to use vector operations, **When** they read the documentation, **Then** they find pgvector operator examples and HNSW index guidance

---

### Edge Cases

- What happens when a user tries to install on unsupported IRIS version (pre-2024.1)?
- How does the package handle missing Python dependencies?
- What happens if port 5432 is already in use during installation?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Package MUST include a valid `module.xml` manifest file with correct metadata (name, version, description, dependencies)
- **FR-002**: Package MUST be installable via ZPM with `zpm "install iris-pgwire"` command
- **FR-003**: Package MUST include a README.md that renders correctly on Open Exchange
- **FR-004**: Package MUST specify minimum IRIS version (2024.1+) in manifest
- **FR-005**: Package MUST specify Python version requirements (3.11+) in manifest
- **FR-006**: Package MUST include a LICENSE file (MIT)
- **FR-007**: Package MUST include working Docker Compose configuration for quick evaluation
- **FR-008**: Package MUST include at least one screenshot or visual demonstrating functionality
- **FR-009**: Package MUST link to or include KNOWN_LIMITATIONS.md for transparency
- **FR-010**: Package MUST include example code demonstrating basic usage (Python, psql)

### Open Exchange Metadata Requirements

- **FR-011**: Package MUST have a clear, concise title (max 50 characters)
- **FR-012**: Package MUST have a compelling description (150-300 characters)
- **FR-013**: Package MUST be tagged with relevant categories (Database, Connectivity, Tools)
- **FR-014**: Package MUST specify supported platforms (Docker, Linux, macOS)
- **FR-015**: Package MUST include GitHub repository link

### Key Entities

- **module.xml**: ZPM package manifest containing name, version, dependencies, and installation instructions
- **Open Exchange Listing**: The public-facing package page with description, screenshots, and metadata
- **Quick Start Guide**: Step-by-step instructions for first-time users to get running in minutes

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Package installs successfully via ZPM on fresh IRIS 2024.1+ instance in under 2 minutes
- **SC-002**: Docker quick start brings up working environment in under 60 seconds (after image pull)
- **SC-003**: New user can connect to IRIS via PostgreSQL client within 5 minutes of starting installation
- **SC-004**: Package page clearly communicates value proposition within 60 seconds of viewing
- **SC-005**: README renders correctly on Open Exchange without formatting issues
- **SC-006**: Package passes Open Exchange submission review on first attempt

## Assumptions

- IRIS 2024.1+ is available and supports embedded Python
- ZPM (ObjectScript Package Manager) is the standard installation method for Open Exchange packages
- The target audience is developers already familiar with either IRIS or PostgreSQL
- Docker and Docker Compose are available for container-based evaluation
- GitHub is the source repository for the package

## Out of Scope

- Native Windows installation (use Docker on Windows)
- Support for IRIS versions prior to 2024.1
- Commercial licensing or paid features
- 24/7 support commitments (community-supported package)
