# Data Model: Open Exchange Package Publication

**Feature**: 027-open-exchange
**Date**: 2024-12-13

## Overview

This feature primarily involves configuration and documentation artifacts rather than runtime data models. The "data" consists of package metadata and installation state.

## Key Entities

### 1. ZPM Package Manifest (module.xml)

```xml
<Module>
  <Name>iris-pgwire</Name>
  <Version>0.1.0</Version>
  <Description>string(150-300 chars)</Description>
  <Author>string</Author>
  <Keywords>comma-separated-list</Keywords>
  <SystemRequirements>
    <Version>IRIS>=2024.1</Version>
  </SystemRequirements>
</Module>
```

**Attributes**:
| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| Name | string | Required, unique in OEX | Package identifier |
| Version | semver | Required | e.g., 0.1.0, 1.0.0 |
| Description | string | 150-300 chars | Open Exchange listing text |
| Author | string | Required | Attribution |
| Keywords | string | Comma-separated | Search/discovery |
| SystemRequirements | XML | Required | IRIS version minimum |

### 2. Server Runtime State (Globals)

Managed by IrisPGWire.Service class:

```
^IrisPGWire.PID = <integer>    # Process ID when running
^IrisPGWire.Status = <string>  # "running" | "stopped"
```

**State Transitions**:
```
stopped → (Start()) → running
running → (Stop()) → stopped
```

### 3. Open Exchange Listing Metadata

Not stored in repository - configured during OEX submission:

| Field | Value | Notes |
|-------|-------|-------|
| Title | IRIS PGWire | Max 50 chars |
| Short Description | PostgreSQL wire protocol for IRIS | 150-300 chars |
| Categories | Database, Connectivity, Tools | OEX taxonomy |
| Platforms | Docker, Linux, macOS | Supported platforms |
| Repository | github.com/isc-tdyar/iris-pgwire | Source link |
| License | MIT | From LICENSE file |

## File Structure

### Package Files (in repository)

```
/
├── ipm/
│   ├── module.xml           # ZPM manifest
│   ├── requirements.txt     # Python dependencies
│   └── IrisPGWire/
│       ├── Installer.cls    # Setup logic
│       └── Service.cls      # Runtime management
├── src/iris_pgwire/         # Python source (copied to IRIS)
├── README.md                # Main documentation
├── LICENSE                  # MIT license
├── KNOWN_LIMITATIONS.md     # Transparency doc
└── docker-compose.yml       # Docker quick start
```

### Installed Files (in IRIS)

After `zpm "install iris-pgwire"`:

```
$SYSTEM.Util.InstallDirectory()
├── mgr/
│   └── python/
│       └── iris-pgwire/
│           ├── iris_pgwire/     # Python package
│           └── requirements.txt  # Dependencies list
└── csp/
    └── [namespace]/
        └── IrisPGWire.*.cls     # ObjectScript classes
```

## Relationships

```
┌─────────────────┐
│   module.xml    │
│   (manifest)    │
└────────┬────────┘
         │ defines
         ▼
┌─────────────────┐      ┌─────────────────┐
│ Installer.cls   │      │  Service.cls    │
│ (setup phase)   │      │ (runtime mgmt)  │
└────────┬────────┘      └────────┬────────┘
         │                        │
         │ installs               │ manages
         ▼                        ▼
┌─────────────────┐      ┌─────────────────┐
│ Python deps     │      │ PGWire server   │
│ (requirements)  │      │ (running proc)  │
└─────────────────┘      └─────────────────┘
```

## Validation Rules

1. **Version Format**: Must be valid semver (X.Y.Z)
2. **IRIS Requirement**: Must be 2024.1 or higher
3. **Description Length**: 150-300 characters for OEX
4. **Title Length**: Max 50 characters
5. **License**: Must have LICENSE file in root
