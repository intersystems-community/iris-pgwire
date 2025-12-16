# Research: Open Exchange Package Publication

**Feature**: 027-open-exchange
**Date**: 2024-12-13

## Existing Infrastructure Analysis

### ZPM Package Structure (Already Exists)

The project already has substantial ZPM infrastructure in `ipm/`:

```
ipm/
├── module.xml              # ZPM manifest (NEEDS UPDATE)
├── requirements.txt        # Python dependencies
└── IrisPGWire/
    ├── Installer.cls       # Python dependency installer
    └── Service.cls         # Server start/stop management
```

#### module.xml Status
- **Name**: iris-pgwire
- **Version**: 0.1.0
- **Description**: Present but could be more compelling
- **Author**: "InterSystems Community" (should clarify)
- **Keywords**: Good coverage (postgresql, pgwire, vector, iris, dbapi, pgvector)
- **System Requirements**: IRIS>=2024.1 ✅
- **Issue**: Has `Activate` phase that auto-starts server (conflicts with clarification for manual start)

#### Service.cls Capabilities
- Start(), Stop(), Restart(), GetStatus(), ShowStatus()
- PID tracking via globals
- Graceful shutdown (SIGTERM → SIGKILL fallback)
- Log file management
- **Good**: Already supports manual start via `do ##class(IrisPGWire.Service).Start()`

#### Installer.cls Capabilities
- InstallPythonDeps() - irispip install from requirements.txt
- VerifyDependencies() - validation method

### What's Missing for Open Exchange

1. **Screenshots/Visuals**: No PNG/GIF files found in repository
   - Need: Architecture diagram or demo screenshot
   - Location: Should be in README.md or docs/images/

2. **module.xml Updates Needed**:
   - Remove Activate phase (per clarification: manual start only)
   - Keep Deactivate phase for cleanup
   - Update description for Open Exchange compelling copy

3. **Quick Start Guide**:
   - README.md exists but needs ZPM-specific section
   - Post-install manual start instructions needed

4. **Open Exchange Metadata**:
   - Title: "IRIS PGWire" (15 chars) ✅
   - Categories: Database, Connectivity, Tools
   - Platforms: Docker, Linux, macOS

### Docker Configuration (Already Exists)

- `docker-compose.yml` - Full development environment
- `docker-compose.prod.yml` - Production configuration
- `Dockerfile` - Main container build
- `Dockerfile.test` - Test container

### Documentation Status

| Document | Status | Notes |
|----------|--------|-------|
| README.md | ✅ Exists | Needs ZPM install section |
| KNOWN_LIMITATIONS.md | ✅ Exists | Comprehensive |
| LICENSE | ✅ MIT | Ready |
| CHANGELOG.md | ✅ Exists | Ready |
| docs/DEPLOYMENT.md | ✅ Exists | Good detail |

## Technical Decisions

### 1. Manual Start Approach (from Clarification)

**Decision**: Remove auto-start from ZPM Activate phase

**Implementation**:
- Remove `<Invoke Phase="Activate">` from module.xml
- Add clear post-install instructions to README
- Keep Service.cls Start() for manual invocation

**User Flow**:
```
1. zpm "install iris-pgwire"     # Installs package + dependencies
2. do ##class(IrisPGWire.Service).Start()  # Manual start
3. psql -h localhost -p 5432 ...  # Connect
```

### 2. Visual Asset Strategy

**Recommendation**: Create ASCII architecture diagram for README (no external image hosting needed)

```
┌─────────────────────────────────────────────────────────────────┐
│                     PostgreSQL Clients                          │
│  (psql, DBeaver, Superset, psycopg3, JDBC, node-postgres, ...)  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Port 5432
┌─────────────────────────────────────────────────────────────────┐
│                      IRIS PGWire Server                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ Wire Proto   │  │   Query      │  │  Vector Translation  │   │
│  │ Handler      │──│   Parser     │──│  <=> → VECTOR_COSINE │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ IRIS DBAPI
┌─────────────────────────────────────────────────────────────────┐
│                    InterSystems IRIS                            │
│                   (Vector Support, SQL)                         │
└─────────────────────────────────────────────────────────────────┘
```

## Dependencies Analysis

### Python Dependencies (requirements.txt)
- structlog>=23.0.0
- cryptography>=41.0.0
- intersystems-irispython>=5.1.2
- sqlparse>=0.4.0
- psycopg2-binary>=2.9.10
- opentelemetry-* (observability)
- pydantic>=2.0.0
- pyyaml>=6.0.0

### IRIS Requirements
- IRIS 2024.1+ (embedded Python, vector support)
- ZPM package manager installed

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Auto-start conflicts | Port already in use | Removed auto-start per clarification |
| Python dep install fails | Install blocked | VerifyDependencies() for troubleshooting |
| Missing irispython | Server won't start | Check in Service.Start() |

## Open Exchange Submission Checklist

- [x] module.xml exists
- [ ] module.xml updated (remove auto-start)
- [x] README.md exists
- [ ] README.md has ZPM install section
- [x] LICENSE file (MIT)
- [ ] Screenshot or architecture diagram
- [ ] Open Exchange metadata prepared
- [x] Docker support
- [x] Python 3.11+ documented
- [x] IRIS 2024.1+ documented
