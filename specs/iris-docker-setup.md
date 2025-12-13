# IRIS Docker Setup Specification

## Overview
This document specifies the proper setup for IRIS containers in the iris-pgwire project based on proven patterns from rag-templates.

## Container Configuration

### Image
Use the licensed IRIS 2025.3.0EHAT.127.0 build for full compatibility:
```yaml
image: docker.iscinternal.com/intersystems/iris:2025.3.0EHAT.127.0-linux-arm64v8
```

### Environment Variables
```yaml
environment:
  - IRISNAMESPACE=USER
  - ISC_DEFAULT_PASSWORD=SYS
```

Key differences from other setups:
- Use `ISC_DEFAULT_PASSWORD` instead of `ISC_PASSWORD`
- Use `IRISNAMESPACE` instead of `IRIS_NAMESPACE`

### Password Expiry Handling
**CRITICAL**: Every new IRIS container requires password expiry to be disabled.

```yaml
command: --check-caps false -a "iris session iris -U%SYS '##class(Security.Users).UnExpireUserPasswords(\"*\")'"
```

This command:
1. Starts IRIS with `--check-caps false`
2. Executes the password unexpiry command during startup
3. Prevents "Password change required" errors

### Health Check
Use the proven health check from rag-templates:
```yaml
healthcheck:
  test: ["CMD", "/usr/irissys/bin/iris", "session", "iris", "-U%SYS", "##class(%SYSTEM.Process).CurrentDirectory()"]
  interval: 15s
  timeout: 10s
  retries: 5
  start_period: 60s
```

### Port Mapping
Standard IRIS ports for direct integration:
```yaml
ports:
  - "1972:1972"   # SuperServer port
  - "52773:52773" # Management Portal
```

## Connection Configuration

### IRIS Executor Configuration
```python
iris_config = {
    'host': 'localhost',
    'port': 1972,
    'username': '_SYSTEM',
    'password': 'SYS',
    'namespace': 'USER'
}
```

### Verification Steps
1. Container starts successfully
2. Health check passes
3. Log shows: `[INFO] ...executed command iris session iris -U%SYS '##class(Security.Users).UnExpireUserPasswords("*")'`
4. IRIS connection test succeeds without password errors

## Complete docker-compose.yml Template

```yaml
services:
  iris:
    image: docker.iscinternal.com/intersystems/iris:2025.3.0EHAT.127.0-linux-arm64v8
    container_name: iris-pgwire-db
    environment:
      - IRISNAMESPACE=USER
      - ISC_DEFAULT_PASSWORD=SYS
    ports:
      - "1972:1972"  # IRIS SQL port
      - "52773:52773"  # Management Portal
    healthcheck:
      test: ["CMD", "/usr/irissys/bin/iris", "session", "iris", "-U%SYS", "##class(%SYSTEM.Process).CurrentDirectory()"]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 60s
    # Disable password expiration for all accounts using Security.Users.UnExpireUserPasswords()
    command: --check-caps false -a "iris session iris -U%SYS '##class(Security.Users).UnExpireUserPasswords(\"*\")'"
```

## Known Issues Resolved

### Issue: "Password change required"
**Cause**: New IRIS containers require password changes by default
**Solution**: Use the UnExpireUserPasswords command in startup

### Issue: Container exits with license key error
**Cause**: Missing license key file
**Solution**: Remove `--key` command argument for unlicensed development

### Issue: Health check failures
**Cause**: Incorrect health check command
**Solution**: Use the ObjectScript-based health check from rag-templates

## References
- Proven patterns from `/Users/tdyar/ws/rag-templates/docker-compose.yml`
- Licensed IRIS patterns from `/Users/tdyar/ws/rag-templates/docker-compose.licensed.yml`