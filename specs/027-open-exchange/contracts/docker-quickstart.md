# Contract: Docker Quick Start

**Feature**: 027-open-exchange
**Date**: 2024-12-13

## Overview

Defines the expected behavior when using Docker Compose for quick evaluation.

## Preconditions

1. Docker and Docker Compose installed
2. Git repository cloned
3. Port 5432 available on host

## Quick Start Command

```bash
git clone https://github.com/isc-tdyar/iris-pgwire.git
cd iris-pgwire
docker-compose up -d
```

## Expected Behavior

### Container Startup Sequence

1. **IRIS Container**: Starts InterSystems IRIS database
   - Exposes port 1972 (SuperServer)
   - Exposes port 52773 (Management Portal)
   - Initializes USER namespace

2. **PGWire Container**: Starts PostgreSQL wire protocol server
   - Exposes port 5432 (PostgreSQL protocol)
   - Connects to IRIS container internally
   - Waits for IRIS to be ready before starting

### Timing

| Phase | Expected Duration |
|-------|-------------------|
| Image pull (first time) | 2-5 minutes |
| Container startup | 30-60 seconds |
| Service ready | < 30 seconds after startup |

## Post-Startup User Actions

Connect with any PostgreSQL client:

```bash
psql -h localhost -p 5432 -U _SYSTEM -d USER
```

Default credentials:
- Username: `_SYSTEM`
- Password: `SYS`
- Database: `USER`

## Success Criteria

| Criterion | Verification |
|-----------|--------------|
| Containers running | `docker-compose ps` shows both services "Up" |
| PGWire accepting connections | `psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 1"` succeeds |
| Query execution works | `SELECT * FROM INFORMATION_SCHEMA.TABLES LIMIT 1` returns results |

## Error Scenarios

### E1: Port 5432 Already in Use
- **Trigger**: Local PostgreSQL or other service on 5432
- **Expected**: Docker Compose fails with port binding error
- **User Action**: Stop conflicting service or change port in docker-compose.yml

### E2: Docker Not Running
- **Trigger**: Docker daemon not started
- **Expected**: `docker-compose` command fails
- **User Action**: Start Docker Desktop or docker daemon

### E3: IRIS Container Fails to Start
- **Trigger**: Insufficient resources or license issues
- **Expected**: Container exits with error
- **User Action**: Check `docker logs iris`, ensure sufficient memory (4GB+)

## Sample Test Script

```bash
#!/bin/bash
# Test Docker quick start contract

set -e

echo "Starting containers..."
docker-compose up -d

echo "Waiting for services to be ready..."
sleep 30

echo "Testing connection..."
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Docker Quick Start Works!' AS result"

echo "Testing query execution..."
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES"

echo "✅ Docker quick start contract verified"
```

## Cleanup

```bash
docker-compose down -v
```
