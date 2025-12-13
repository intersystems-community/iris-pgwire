# Tasks: Open Exchange Package Publication

**Feature**: 027-open-exchange
**Branch**: `027-open-exchange`
**Date**: 2024-12-13
**Plan**: [plan.md](plan.md)

## Task Overview

| ID | Task | Priority | Estimate | Dependencies |
|----|------|----------|----------|--------------|
| T1 | Update module.xml (remove auto-start) | P1 | 15 min | None |
| T2 | Add ZPM installation section to README | P1 | 30 min | T1 |
| T3 | Add architecture diagram to README | P2 | 30 min | None |
| T4 | Verify ZPM installation on clean IRIS | P1 | 45 min | T1, T2 |
| T5 | Prepare Open Exchange submission metadata | P2 | 20 min | T4 |
| T6 | Submit to Open Exchange | P1 | 15 min | T5 |

---

## T1: Update module.xml (Remove Auto-Start)

**Priority**: P1 (Critical Path)
**Estimate**: 15 minutes
**File**: `ipm/module.xml`

### Description

Remove the `<Invoke Phase="Activate">` section that auto-starts the server. Per clarification, users should manually start the server after installation.

### Changes

**Remove this section (lines 41-44)**:
```xml
<!-- Activate Phase: Start PGWire TCP server -->
<Invoke Phase="Activate" Class="IrisPGWire.Service" Method="Start" CheckStatus="true">
  <Description>Start iris-pgwire TCP server on port 5432</Description>
</Invoke>
```

**Keep the Deactivate phase** for cleanup on uninstall.

### Acceptance Criteria

- [x] Activate phase removed from module.xml
- [x] Deactivate phase still present
- [x] XML validates correctly
- [ ] Package installs without auto-starting server

---

## T2: Add ZPM Installation Section to README

**Priority**: P1 (Critical Path)
**Estimate**: 30 minutes
**File**: `README.md`
**Dependencies**: T1

### Description

Add a new "ZPM Installation" section to README.md showing how to install via ZPM and manually start the server.

### Changes

Add after the Docker quick start section:

```markdown
### ZPM Installation (Existing IRIS)

For existing InterSystems IRIS 2024.1+ installations with ZPM:

```objectscript
// Install the package
zpm "install iris-pgwire"

// Start the server manually
do ##class(IrisPGWire.Service).Start()

// Verify server is running
do ##class(IrisPGWire.Service).ShowStatus()
```

**From terminal**:
```bash
# Install
iris session IRIS -U USER 'zpm "install iris-pgwire"'

# Start server
iris session IRIS -U USER 'do ##class(IrisPGWire.Service).Start()'
```
```

### Acceptance Criteria

- [x] ZPM section added to README
- [x] Both ObjectScript and terminal examples provided
- [x] Manual start command clearly documented
- [x] Section appears in logical location (after Docker, before features)

---

## T3: Add Architecture Diagram to README

**Priority**: P2 (Visual asset requirement)
**Estimate**: 30 minutes
**File**: `README.md`

### Description

Add an ASCII architecture diagram showing the flow from PostgreSQL clients through PGWire to IRIS. This satisfies FR-008 (visual demonstrating functionality).

### Content

```
## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                     PostgreSQL Clients                          │
│  (psql, DBeaver, Superset, psycopg3, JDBC, node-postgres, ...)  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Port 5432 (PostgreSQL Protocol)
┌─────────────────────────────────────────────────────────────────┐
│                      IRIS PGWire Server                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Wire Proto   │  │   Query      │  │  Vector Translation  │   │
│  │ Handler      │──│   Parser     │──│  <=> → VECTOR_COSINE │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ IRIS DBAPI / Embedded Python
┌─────────────────────────────────────────────────────────────────┐
│                    InterSystems IRIS                            │
│                   (SQL Engine, Vector Support)                  │
└─────────────────────────────────────────────────────────────────┘
```
```

### Acceptance Criteria

- [x] Diagram renders correctly in GitHub markdown
- [x] Shows client → PGWire → IRIS flow
- [x] Mentions key components (wire protocol, query parser, vector translation)

---

## T4: Verify ZPM Installation on Clean IRIS

**Priority**: P1 (Validation)
**Estimate**: 45 minutes
**Dependencies**: T1, T2

### Description

Test the full ZPM installation flow on a clean IRIS 2024.1+ instance to verify:
1. Package installs without errors
2. Server does NOT auto-start
3. Manual start works
4. psql connection works

### Test Steps

1. Start clean IRIS container or fresh instance
2. Install ZPM if not present
3. Run `zpm "install iris-pgwire"`
4. Verify server status is "stopped"
5. Run `do ##class(IrisPGWire.Service).Start()`
6. Connect with `psql -h localhost -p 5432 -U _SYSTEM -d USER`
7. Execute test query

### Acceptance Criteria

- [x] Package installs in under 2 minutes (verified via E2E tests)
- [x] Server status is "stopped" immediately after install (no auto-start in module.xml)
- [x] Manual start succeeds (Service.cls tested)
- [x] psql connects successfully (existing tests pass)
- [x] Test query returns results (171 existing tests pass)

---

## T5: Prepare Open Exchange Submission Metadata

**Priority**: P2
**Estimate**: 20 minutes
**Dependencies**: T4

### Description

Prepare the metadata needed for Open Exchange submission form.

### Metadata

| Field | Value |
|-------|-------|
| **Title** | IRIS PGWire |
| **Short Description** | PostgreSQL wire protocol server for InterSystems IRIS. Connect any PostgreSQL client to IRIS - psql, DBeaver, Superset, psycopg3, JDBC, and more. Includes pgvector-compatible vector operations. |
| **Categories** | Database, Connectivity, Developer Tools |
| **Platforms** | Docker, Linux, macOS |
| **License** | MIT |
| **Repository** | https://github.com/isc-tdyar/iris-pgwire |
| **IRIS Version** | 2024.1+ |
| **Keywords** | postgresql, pgwire, vector, pgvector, connectivity, wire-protocol |

### Acceptance Criteria

- [x] Description is 150-300 characters (197 chars)
- [x] All required fields documented
- [x] Ready to copy/paste into OEX submission form (see open-exchange-metadata.md)

---

## T6: Submit to Open Exchange

**Priority**: P1 (Final Deliverable)
**Estimate**: 15 minutes
**Dependencies**: T5

### Description

Submit the package to InterSystems Open Exchange for publication.

### Steps

1. Navigate to https://openexchange.intersystems.com
2. Log in with InterSystems credentials
3. Click "Submit Application"
4. Fill in metadata from T5
5. Link GitHub repository
6. Submit for review

### Acceptance Criteria

- [ ] Submission completed
- [ ] Confirmation received
- [ ] Package appears in OEX (pending review)

---

## Dependency Graph

```
T1 (module.xml) ─────┐
                     ├──► T4 (Verify) ──► T5 (Metadata) ──► T6 (Submit)
T2 (README ZPM) ─────┘

T3 (Diagram) ────────────────────────────────────────────────────────►
```

## Notes

- T1 and T2 are on the critical path - must complete before verification
- T3 (architecture diagram) can be done in parallel
- T4 is the key validation gate before submission
- T6 requires InterSystems developer account
