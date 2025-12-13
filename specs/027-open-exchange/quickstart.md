# Quick Start Guide: IRIS PGWire

**Feature**: 027-open-exchange
**Date**: 2024-12-13

## Overview

Get IRIS PGWire running in under 5 minutes. Choose your preferred method:

1. **Docker** (Recommended for evaluation) - No IRIS installation required
2. **ZPM** (For existing IRIS installations) - Native package manager

---

## Option 1: Docker Quick Start (60 seconds)

### Prerequisites
- Docker and Docker Compose installed

### Steps

```bash
# Clone repository
git clone https://github.com/isc-tdyar/iris-pgwire.git
cd iris-pgwire

# Start services
docker-compose up -d

# Wait for startup (about 30 seconds)
sleep 30

# Test connection
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
```

### Default Credentials
- **Host**: localhost
- **Port**: 5432
- **Username**: _SYSTEM
- **Password**: SYS
- **Database**: USER

---

## Option 2: ZPM Installation (5 minutes)

### Prerequisites
- InterSystems IRIS 2024.1 or later
- ZPM package manager installed

### Steps

```objectscript
// Step 1: Install the package
zpm "install iris-pgwire"

// Step 2: Start the server manually
do ##class(IrisPGWire.Service).Start()

// Step 3: Check status
do ##class(IrisPGWire.Service).ShowStatus()
```

### From Terminal (alternative)

```bash
# Install
iris session IRIS -U USER 'zpm "install iris-pgwire"'

# Start server
iris session IRIS -U USER 'do ##class(IrisPGWire.Service).Start()'

# Test connection
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 1"
```

---

## Verify Installation

### Test Query

```sql
-- Connect with psql
psql -h localhost -p 5432 -U _SYSTEM -d USER

-- Run test query
SELECT 'IRIS PGWire is working!' AS message;

-- Check IRIS metadata
SELECT * FROM INFORMATION_SCHEMA.TABLES LIMIT 5;
```

### Test Vector Operations

```sql
-- Create table with vector column
CREATE TABLE test_vectors (
    id INT PRIMARY KEY,
    embedding VECTOR(DOUBLE, 3)
);

-- Insert data
INSERT INTO test_vectors VALUES (1, TO_VECTOR('[0.1, 0.2, 0.3]'));
INSERT INTO test_vectors VALUES (2, TO_VECTOR('[0.4, 0.5, 0.6]'));

-- Similarity search
SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('[0.1, 0.2, 0.3]', DOUBLE)) AS similarity
FROM test_vectors
ORDER BY similarity DESC;
```

---

## Management Commands

### Server Control (ZPM installation)

```objectscript
// Start server
do ##class(IrisPGWire.Service).Start()

// Stop server
do ##class(IrisPGWire.Service).Stop()

// Restart server
do ##class(IrisPGWire.Service).Restart()

// Check status
do ##class(IrisPGWire.Service).ShowStatus()
```

### Docker Control

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# View logs
docker-compose logs -f pgwire

# Restart PGWire only
docker-compose restart pgwire
```

---

## Troubleshooting

### Port 5432 Already in Use

```bash
# Check what's using the port
lsof -i :5432

# Option 1: Stop the conflicting service
# Option 2: Change port in docker-compose.yml or iris_pgwire.json
```

### Connection Refused

```objectscript
// Check if server is running
do ##class(IrisPGWire.Service).GetStatus()

// Check logs
// Log file: $SYSTEM.Util.InstallDirectory() _ "mgr/iris-pgwire.log"
```

### Python Dependencies Failed

```objectscript
// Verify dependencies are installed
do ##class(IrisPGWire.Installer).VerifyDependencies()

// Reinstall if needed
do ##class(IrisPGWire.Installer).InstallPythonDeps()
```

---

## Next Steps

- **BI Tools**: See [BI_TOOLS_SETUP.md](examples/BI_TOOLS_SETUP.md) for Superset, Metabase, Grafana
- **Vector Operations**: See [VECTOR_PARAMETER_BINDING.md](docs/VECTOR_PARAMETER_BINDING.md)
- **Known Limitations**: See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)
- **Full Documentation**: See [README.md](README.md)
