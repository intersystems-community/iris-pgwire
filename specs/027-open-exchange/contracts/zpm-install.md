# Contract: ZPM Installation

**Feature**: 027-open-exchange
**Date**: 2024-12-13

## Overview

Defines the expected behavior when installing iris-pgwire via ZPM.

## Preconditions

1. IRIS 2024.1+ instance running
2. ZPM package manager installed (`zpm` command available)
3. Network access to Open Exchange registry (or local package)

## Installation Command

```objectscript
zpm "install iris-pgwire"
```

## Expected Behavior

### Phase: Load
- Download package from Open Exchange registry
- Verify package integrity

### Phase: Compile
- Load ObjectScript classes (IrisPGWire.Installer, IrisPGWire.Service)
- Compile classes in target namespace

### Phase: Setup (Custom)
- Execute `IrisPGWire.Installer.InstallPythonDeps()`
- Install Python dependencies via irispip
- Copy iris_pgwire Python package to libdir

### Phase: Activate
- **NO automatic server start** (per manual start clarification)
- Server remains stopped until user explicitly starts

### Phase: Deactivate (on uninstall)
- Execute `IrisPGWire.Service.Stop()`
- Gracefully stop server if running

## Post-Install User Actions

After successful installation, user must manually start server:

```objectscript
do ##class(IrisPGWire.Service).Start()
```

Or from terminal:
```bash
iris session IRIS -U USER "do ##class(IrisPGWire.Service).Start()"
```

## Success Criteria

| Criterion | Verification |
|-----------|--------------|
| Package installs without errors | ZPM returns success status |
| Python dependencies installed | `do ##class(IrisPGWire.Installer).VerifyDependencies()` returns $$$OK |
| Classes compiled | `$CLASSMETHOD("IrisPGWire.Service", "%Extends", "%RegisteredObject")` = 1 |
| Server NOT auto-started | `do ##class(IrisPGWire.Service).GetStatus()` returns "stopped" |

## Error Scenarios

### E1: IRIS Version Too Old
- **Trigger**: IRIS < 2024.1
- **Expected**: ZPM rejects installation with version mismatch error
- **User Action**: Upgrade IRIS to 2024.1+

### E2: Python Dependencies Fail
- **Trigger**: Network issue or incompatible Python
- **Expected**: Setup phase fails with irispip error
- **User Action**: Check network, verify Python 3.11+ available

### E3: Class Compilation Fails
- **Trigger**: Namespace permissions or conflicts
- **Expected**: Compile phase fails with error
- **User Action**: Check namespace permissions, resolve conflicts

## Sample Test

```objectscript
// Test installation contract
ClassMethod TestInstallContract() As %Status
{
    Set sc = $$$OK

    // Verify classes exist
    If '$$$classExists("IrisPGWire.Service") {
        Set sc = $$$ERROR($$$GeneralError, "IrisPGWire.Service class not found")
        Quit sc
    }

    // Verify dependencies
    Set sc = ##class(IrisPGWire.Installer).VerifyDependencies()
    If $$$ISERR(sc) Quit sc

    // Verify server not auto-started
    Set status = ##class(IrisPGWire.Service).GetStatus()
    If status '= "stopped" {
        Set sc = $$$ERROR($$$GeneralError, "Server should not auto-start")
        Quit sc
    }

    Quit $$$OK
}
```
