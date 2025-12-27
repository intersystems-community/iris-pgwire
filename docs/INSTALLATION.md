# Installation Guide: IRIS PGWire

**Last Updated**: 2025-12-27
**Related**: [Deployment](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md), [Architecture](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/ARCHITECTURE.md)

---

## Prerequisites

- **IRIS Database**: InterSystems IRIS 2024.1+ with vector support
- **Python**: 3.11+ (for development) or IRIS embedded Python
- **Docker** (optional): For containerized deployment

---

## Docker Deployment (Recommended)

**Fastest path** - Everything pre-configured:

```bash
# Clone repository
git clone https://github.com/intersystems-community/iris-pgwire.git
cd iris-pgwire

# Start all services
docker-compose up -d

# Verify services
docker-compose ps
```

**Services Started**:
- PGWire server on port `5432`
- IRIS database on port `1972`
- IRIS Management Portal on port `52773`

**Test Connection**:
```bash
psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
```

---

## PyPI Installation

**For existing IRIS installations**:

```bash
# Install via pip
pip install iris-pgwire intersystems-irispython psycopg[binary]

# Or with uv (recommended - faster)
uv pip install iris-pgwire intersystems-irispython psycopg[binary]

# Configure IRIS connection
export IRIS_HOST=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER

# Optional: Schema mapping
export PGWIRE_IRIS_SCHEMA=SQLUser  # Default

# Start server
python -m iris_pgwire.server
```

**Package Note**: Install `intersystems-irispython` but import as `iris`:
```python
import iris  # NOT import intersystems_irispython
```

---

## ZPM Installation (IRIS Native)

**For InterSystems IRIS 2024.1+ with ZPM package manager**:

```objectscript
// Install the package
zpm "install iris-pgwire"

// Start the server manually
do ##class(IrisPGWire.Service).Start()

// Check server status
do ##class(IrisPGWire.Service).ShowStatus()
```

**From terminal**:
```bash
# Install
iris session IRIS -U USER 'zpm "install iris-pgwire"'

# Start server
iris session IRIS -U USER 'do ##class(IrisPGWire.Service).Start()'
```

---

## Embedded Python Deployment (Production)

**Maximum performance** - runs inside IRIS process:

```bash
# From IRIS container/instance
export IRISUSERNAME=_SYSTEM
export IRISPASSWORD=SYS
export IRISNAMESPACE=USER
export BACKEND_TYPE=embedded

# Start embedded server (inside IRIS)
irispython -m iris_pgwire.server
```

**Benefits**:
- Zero network overhead (no TCP to IRIS:1972)
- True VECTOR type handling
- Single-process deployment

**Learn More**: [Dual-Path Architecture](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DUAL_PATH_ARCHITECTURE.md)

---

## Configuration Options

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `IRIS_HOST` | `localhost` | IRIS hostname |
| `IRIS_PORT` | `1972` | IRIS SuperServer port |
| `IRIS_USERNAME` | `_SYSTEM` | IRIS username |
| `IRIS_PASSWORD` | `SYS` | IRIS password |
| `IRIS_NAMESPACE` | `USER` | IRIS namespace |
| `PGWIRE_PORT` | `5432` | PGWire listening port |
| `PGWIRE_IRIS_SCHEMA` | `SQLUser` | IRIS schema for `public` mapping |
| `BACKEND_TYPE` | `dbapi` | Backend: `dbapi` or `embedded` |

### Connection Pooling (DBAPI Backend)

```bash
export DBAPI_POOL_SIZE=50          # Max concurrent connections
export DBAPI_POOL_OVERFLOW=20      # Overflow connections
export DBAPI_POOL_TIMEOUT=30       # Connection timeout (seconds)
```

---

## Verification

### Test PGWire Connection

```bash
# Via psql
psql -h localhost -p 5432 -U _SYSTEM -d USER

# Run query
SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES;
```

### Test from Python

```python
import psycopg

conn = psycopg.connect("host=localhost port=5432 dbname=USER user=_SYSTEM password=SYS")
cur = conn.cursor()
cur.execute("SELECT 'Connection successful!'")
print(cur.fetchone()[0])
```

---

## Troubleshooting

### Port Already in Use

```bash
# Check what's using port 5432
lsof -i :5432

# Kill existing process
kill -9 <PID>

# Or change PGWire port
export PGWIRE_PORT=5433
```

### Docker Container Won't Start

```bash
# Check logs
docker-compose logs pgwire

# Restart services
docker-compose down && docker-compose up -d

# Rebuild if code changed
docker-compose build pgwire
```

### IRIS Connection Refused

```bash
# Verify IRIS is running
docker-compose ps iris

# Check IRIS port
docker port iris-pgwire-iris-1 1972

# Test IRIS connection directly
irissession IRIS -U USER
```

---

## Next Steps

- [Deployment Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/DEPLOYMENT.md) - Production deployment
- [Quick Start Examples](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/QUICKSTART_EXAMPLES.md) - First queries
- [Client Recommendations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md) - Choose your client
