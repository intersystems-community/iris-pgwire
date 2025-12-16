# Implementation Plan: Open Exchange Package Publication

**Branch**: `027-open-exchange` | **Date**: 2024-12-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/027-open-exchange/spec.md`

## Summary

Package IRIS PGWire for publication on InterSystems Open Exchange. The project already has substantial ZPM infrastructure (module.xml, ObjectScript classes, requirements.txt). Key changes needed:

1. Update module.xml to remove auto-start (per clarification: manual start only)
2. Add ZPM installation section to README.md
3. Create architecture diagram for visual asset
4. Prepare Open Exchange submission metadata

## Technical Context

**Language/Version**: Python 3.11+, ObjectScript (IRIS 2024.1+)
**Primary Dependencies**: ZPM package manager, irispython, structlog, cryptography
**Storage**: IRIS globals for server state (^IrisPGWire.PID, ^IrisPGWire.Status)
**Testing**: Manual verification via ZPM install + psql connection
**Target Platform**: InterSystems IRIS 2024.1+, Docker (Linux/macOS)
**Project Type**: Single project with ZPM packaging layer
**Performance Goals**: Install in <2 minutes, connect in <5 minutes
**Constraints**: No auto-start, manual server startup required
**Scale/Scope**: Single Open Exchange package submission

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Authorship | ✅ Pass | Thomas Dyar authorship maintained |
| II. Test-First | ✅ Pass | Existing 171 tests, package tests not required |
| III. PostgreSQL Compatibility | ✅ Pass | Wire protocol preserved |
| IV. Documentation Accuracy | ✅ Pass | Will test all examples |
| V. Professional Presentation | ✅ Pass | Clean root directory maintained |

## Project Structure

### Documentation (this feature)

```text
specs/027-open-exchange/
├── plan.md              # This file
├── research.md          # Phase 0 output (complete)
├── data-model.md        # Phase 1 output (complete)
├── quickstart.md        # Phase 1 output (complete)
├── contracts/           # Phase 1 output (complete)
│   ├── zpm-install.md
│   └── docker-quickstart.md
└── tasks.md             # Phase 2 output (pending)
```

### Source Code (existing structure)

```text
/
├── ipm/                     # ZPM package directory
│   ├── module.xml           # Package manifest (NEEDS UPDATE)
│   ├── requirements.txt     # Python dependencies
│   └── IrisPGWire/
│       ├── Installer.cls    # Setup phase handler
│       └── Service.cls      # Server management
├── src/iris_pgwire/         # Python source package
├── README.md                # Main documentation (NEEDS UPDATE)
├── KNOWN_LIMITATIONS.md     # Limitations doc (ready)
├── LICENSE                  # MIT license (ready)
├── docker-compose.yml       # Docker quick start (ready)
└── docs/                    # Additional documentation
```

**Structure Decision**: Existing single-project structure with `ipm/` packaging layer. No structural changes needed - only content updates to existing files.

## Implementation Phases

### Phase 1: Module.xml Update (Remove Auto-Start)

**Rationale**: Per clarification, server should NOT auto-start after installation.

**Change**: Remove `<Invoke Phase="Activate">` section from module.xml

**Before**:
```xml
<Invoke Phase="Activate" Class="IrisPGWire.Service" Method="Start" CheckStatus="true">
```

**After**: Section removed entirely

### Phase 2: README.md ZPM Section

Add new section between Docker quick start and features:

```markdown
### ZPM Installation (Existing IRIS)

For existing IRIS 2024.1+ installations:

```objectscript
zpm "install iris-pgwire"
do ##class(IrisPGWire.Service).Start()
```
```

### Phase 3: Architecture Diagram

Add ASCII architecture diagram to README.md for visual asset requirement.

### Phase 4: Open Exchange Submission

Prepare metadata for OEX submission form:
- Title: IRIS PGWire
- Description: 150-300 char compelling copy
- Categories: Database, Connectivity, Tools
- Platforms: Docker, Linux, macOS
- Repository URL: https://github.com/isc-tdyar/iris-pgwire

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| ZPM install fails | Low | High | Test on clean IRIS instance |
| Port conflict | Medium | Medium | Document troubleshooting steps |
| Python deps fail | Low | High | VerifyDependencies() method exists |

## Complexity Tracking

No constitution violations - no complexity tracking required.

## Progress Tracking

- [x] Phase 0: Research existing structure
- [x] Phase 1: Design artifacts (data-model, contracts, quickstart)
- [x] Phase 2: Task generation (tasks.md)
