# Kerberos/GSSAPI Authentication for IRIS PGWire

**Feature Priority**: P5 (MEDIUM) - Enterprise SSO integration
**Status**: Planning / Specification
**Target**: Enterprise IRIS deployments with existing Kerberos infrastructure

## Executive Summary

Kerberos/GSSAPI authentication is critical for enterprise IRIS deployments where:
- **Single Sign-On (SSO)** is required across multiple systems
- **Active Directory** integration is standard (Windows environments)
- **Zero-password workflows** improve developer experience
- **OAuth/SAML complexity** makes traditional enterprise auth difficult with IRIS

This document outlines implementation options for adding PostgreSQL-compatible Kerberos authentication to IRIS PGWire, enabling seamless integration with enterprise identity infrastructure.

---

## Business Value

### Current Pain Points in IRIS Enterprise Auth

1. **Manual Credential Management**: Developers must store IRIS passwords in config files or environment variables
2. **OAuth/SAML Complexity**: IRIS lacks native support for modern OAuth/SAML flows, making automation difficult
3. **Credential Rotation**: Password changes require updating credentials across all applications
4. **Audit Trail Gaps**: Username/password auth doesn't integrate with enterprise audit systems
5. **Multi-System Complexity**: Managing separate credentials for IRIS vs other enterprise databases

### Benefits of Kerberos/GSSAPI

✅ **Zero-Password Workflows**: Developers authenticate once via `kinit`, all IRIS connections "just work"
✅ **Enterprise SSO**: Leverage existing Active Directory or MIT Kerberos infrastructure
✅ **Automatic Credential Rotation**: Kerberos tickets expire and renew automatically
✅ **Audit Integration**: All authentication events logged in Kerberos KDC
✅ **PostgreSQL Compatibility**: Existing PostgreSQL tools (psql, psycopg, JDBC) work with IRIS via PGWire

### Real-World Use Cases

**Use Case 1: Data Science Teams**
- Data scientists use Jupyter notebooks with Python (psycopg/asyncpg)
- Current: Must embed IRIS password in notebooks (security risk)
- With Kerberos: `kinit username@REALM` once, all notebooks connect automatically
- **Impact**: Eliminates password sprawl, improves security posture

**Use Case 2: Automated ETL Pipelines**
- ETL jobs run on Kubernetes with service accounts
- Current: IRIS passwords stored in Kubernetes secrets (rotation overhead)
- With Kerberos: Use keytab files or k8s service principal integration
- **Impact**: Automated credential rotation via Kerberos, zero manual updates

**Use Case 3: BI Tool Integration**
- Tableau/PowerBI connecting to IRIS via PostgreSQL connector
- Current: Each user must enter IRIS password (not SSO-compatible)
- With Kerberos: Users authenticate to Windows domain, BI tools use Kerberos tickets
- **Impact**: True SSO experience for end users

---

## PostgreSQL GSSAPI Protocol Overview

### Authentication Flow (RFC 4559)

```
┌──────────┐                                    ┌──────────┐
│  Client  │                                    │  Server  │
│ (psql)   │                                    │ (PGWire) │
└────┬─────┘                                    └────┬─────┘
     │                                                │
     │  1. StartupMessage                             │
     │ ──────────────────────────────────────────────>│
     │                                                │
     │  2. AuthenticationGSS (type=7)                 │
     │ <──────────────────────────────────────────────│
     │                                                │
     │  3. GSSResponse (initial token)                │
     │ ──────────────────────────────────────────────>│
     │                                                │
     │  4. AuthenticationGSSContinue (server token)   │
     │ <──────────────────────────────────────────────│
     │                                                │
     │  5. GSSResponse (client token)                 │
     │ ──────────────────────────────────────────────>│
     │                                                │
     │  [Repeat 4-5 until context established]        │
     │                                                │
     │  6. AuthenticationOk                           │
     │ <──────────────────────────────────────────────│
     │                                                │
     │  7. ParameterStatus, BackendKeyData            │
     │ <──────────────────────────────────────────────│
     │                                                │
     │  8. ReadyForQuery                              │
     │ <──────────────────────────────────────────────│
```

### Protocol Message Types

| Message | Type Code | Direction | Description |
|---------|-----------|-----------|-------------|
| `AuthenticationGSS` | 7 | Server→Client | Server requests GSSAPI authentication |
| `AuthenticationGSSContinue` | 8 | Server→Client | Server sends GSSAPI token for continuation |
| `GSSResponse` | 'p' | Client→Server | Client sends GSSAPI token |
| `AuthenticationOk` | 0 | Server→Client | Authentication succeeded |

### GSSAPI Token Exchange

**Initiate Context (Client)**:
```python
import gssapi

# Client creates service name: postgres/hostname@REALM
service_name = gssapi.Name('postgres/pgwire-host.example.com',
                           gssapi.NameType.hostbased_service)

# Create initiator context
client_ctx = gssapi.SecurityContext(name=service_name, usage='initiate')

# Generate first token
initial_token = client_ctx.step()
# Send to server via GSSResponse message
```

**Accept Context (Server)**:
```python
import gssapi

# Server loads credentials from keytab (postgres/hostname@REALM)
service_name = gssapi.Name('postgres/pgwire-host.example.com',
                           gssapi.NameType.hostbased_service)
server_creds = gssapi.Credentials(service_name, usage='accept')

# Create acceptor context
server_ctx = gssapi.SecurityContext(creds=server_creds, usage='accept')

# Process client token
server_token = server_ctx.step(client_token)
# Send back via AuthenticationGSSContinue

# Continue until server_ctx.complete == True
# Extract authenticated username: server_ctx.peer_name
```

---

## Implementation Options

### Option 1: Pure Python GSSAPI Integration (RECOMMENDED)

**Approach**: Use `python-gssapi` library to implement GSSAPI authentication natively in PGWire server.

**Pros**:
- ✅ **Pure Python**: No C extensions, works with asyncio
- ✅ **Cross-Platform**: Supports both MIT Kerberos and Heimdal
- ✅ **Well-Maintained**: Active development by pythongssapi organization
- ✅ **Battle-Tested**: Used by requests-gssapi, httpx-gssapi
- ✅ **IRIS Integration**: Can validate against IRIS user database after Kerberos auth

**Cons**:
- ⚠️ **Requires libgssapi**: System must have Kerberos libraries installed
- ⚠️ **Keytab Management**: Requires setting up keytab for service principal
- ⚠️ **Async Support**: Need `asyncio.to_thread()` for blocking GSSAPI calls

**Implementation Sketch**:

```python
# src/iris_pgwire/auth/gssapi_auth.py
import asyncio
import gssapi
from typing import Optional

class GSSAPIAuthenticator:
    def __init__(self, service_name: str = 'postgres', hostname: str = None):
        """
        Initialize GSSAPI authenticator.

        Args:
            service_name: Service principal name (default: 'postgres')
            hostname: Fully qualified hostname for service principal
                     (defaults to system FQDN)
        """
        if hostname is None:
            import socket
            hostname = socket.getfqdn()

        # Service principal: postgres/hostname@REALM
        self.service_principal = f"{service_name}/{hostname}"
        self.server_creds = None
        self.contexts = {}  # Map connection_id → SecurityContext

    async def initialize(self):
        """Load server credentials from keytab (KRB5_KTNAME env var)."""
        def _load_creds():
            service_name = gssapi.Name(
                self.service_principal,
                gssapi.NameType.hostbased_service
            )
            return gssapi.Credentials(service_name, usage='accept')

        self.server_creds = await asyncio.to_thread(_load_creds)

    async def handle_gssapi_handshake(self, connection_id: str) -> str:
        """
        Handle multi-step GSSAPI authentication.

        Returns:
            Authenticated username (e.g., 'alice@EXAMPLE.COM')

        Raises:
            GSSAPIAuthenticationError: If authentication fails
        """
        # Create new acceptor context
        def _create_context():
            return gssapi.SecurityContext(
                creds=self.server_creds,
                usage='accept'
            )

        ctx = await asyncio.to_thread(_create_context)
        self.contexts[connection_id] = ctx

        # Return context for multi-step exchange
        return ctx

    async def process_client_token(self, connection_id: str,
                                   client_token: bytes) -> Optional[bytes]:
        """
        Process GSSAPI token from client.

        Args:
            connection_id: Unique connection identifier
            client_token: GSSAPI token from GSSResponse message

        Returns:
            Server token to send back (None if context complete)
        """
        ctx = self.contexts[connection_id]

        def _step():
            return ctx.step(client_token)

        server_token = await asyncio.to_thread(_step)

        if ctx.complete:
            # Authentication successful - extract username
            username = str(ctx.peer_name)
            del self.contexts[connection_id]  # Clean up context
            return None, username
        else:
            # Need more tokens - return server token
            return server_token, None

    async def validate_iris_user(self, kerberos_principal: str) -> bool:
        """
        Validate that Kerberos principal maps to valid IRIS user.

        Args:
            kerberos_principal: Authenticated Kerberos principal
                               (e.g., 'alice@EXAMPLE.COM')

        Returns:
            True if user exists in IRIS and is allowed to connect
        """
        # Option 1: Strip realm and query IRIS user table
        username = kerberos_principal.split('@')[0]

        # Option 2: Use pg_ident.conf style mapping (future enhancement)
        # mapped_user = self.apply_ident_mapping(kerberos_principal)

        # Check IRIS Security.Users table
        query = """
        SELECT COUNT(*) FROM INFORMATION_SCHEMA.USERS
        WHERE USERNAME = :username
        """
        result = await self.iris_executor.execute_query(query,
                                                        {'username': username})
        return result[0][0] > 0


# Integration with protocol.py
async def handle_authentication(self, startup_params: dict):
    """Handle authentication request from client."""

    # Check if GSSAPI is configured and client supports it
    if self.config.enable_gssapi:
        # Send AuthenticationGSS (type=7)
        await self.send_authentication_gss()

        # Receive GSSResponse from client
        client_token = await self.receive_gss_response()

        # Multi-step token exchange
        while True:
            server_token, username = await self.gssapi_auth.process_client_token(
                self.connection_id, client_token
            )

            if username:
                # Context complete - validate IRIS user
                if await self.gssapi_auth.validate_iris_user(username):
                    self.authenticated_user = username
                    await self.send_authentication_ok()
                    break
                else:
                    await self.send_error_response(
                        "FATAL", "28000",
                        f"Kerberos user {username} not found in IRIS"
                    )
                    return False
            else:
                # Send server token, get next client token
                await self.send_authentication_gss_continue(server_token)
                client_token = await self.receive_gss_response()

        return True
    else:
        # Fall back to SCRAM-SHA-256
        return await self.handle_scram_auth(startup_params)
```

**Configuration**:
```yaml
# docker-compose.yml or config
environment:
  IRIS_PGWIRE_ENABLE_GSSAPI: "true"
  IRIS_PGWIRE_GSSAPI_SERVICE: "postgres"  # Service name
  IRIS_PGWIRE_GSSAPI_HOSTNAME: "pgwire.example.com"  # FQDN
  KRB5_KTNAME: "/etc/krb5.keytab"  # Keytab file location
```

**Keytab Setup** (one-time admin task):
```bash
# On Kerberos KDC server (or via kadmin)
kadmin -p admin/admin

# Create service principal
addprinc -randkey postgres/pgwire.example.com@EXAMPLE.COM

# Generate keytab
ktadd -k /tmp/postgres.keytab postgres/pgwire.example.com@EXAMPLE.COM

# Transfer keytab to PGWire server
scp /tmp/postgres.keytab pgwire-host:/etc/krb5.keytab
chmod 600 /etc/krb5.keytab
```

**Client Usage** (zero code changes - standard PostgreSQL clients work):
```bash
# User authenticates to Kerberos once
kinit alice@EXAMPLE.COM
Password for alice@EXAMPLE.COM: ****

# All PostgreSQL connections now use Kerberos automatically
psql "host=pgwire.example.com port=5432 dbname=USER gssencmode=disable"
# No password prompt - authenticated via Kerberos!

# Python
import psycopg
conn = psycopg.connect(
    "host=pgwire.example.com port=5432 dbname=USER gssencmode=disable"
)
# Just works - no password needed

# JDBC
String url = "jdbc:postgresql://pgwire.example.com:5432/USER?gssencmode=disable";
Connection conn = DriverManager.getConnection(url);
// Authenticated via Kerberos ticket
```

**Dependency**:
```txt
# requirements.txt
python-gssapi>=1.8.0  # Pure Python, cross-platform
```

---

### Option 2: Kerberos Password Validation (Simpler Alternative)

**Approach**: Accept username/password via SCRAM, but validate against Kerberos KDC instead of IRIS password table.

**Pros**:
- ✅ **Simpler Implementation**: No multi-step token exchange
- ✅ **No Keytab Required**: Server doesn't need service principal
- ✅ **Works with Existing Clients**: No GSSAPI support needed in clients

**Cons**:
- ❌ **Not True SSO**: Users still enter password (defeats main benefit)
- ❌ **Credential Exposure**: Password sent over network (though encrypted via TLS)
- ❌ **No Token Delegation**: Can't pass Kerberos ticket to IRIS for downstream auth
- ❌ **Not PostgreSQL-Standard**: PostgreSQL's Kerberos support uses GSSAPI, not password validation

**Implementation Sketch**:
```python
import kerberos  # PyKerberos library

async def validate_kerberos_password(username: str, password: str,
                                     realm: str = "EXAMPLE.COM") -> bool:
    """
    Validate username/password against Kerberos KDC.

    NOTE: This does NOT provide SSO - user still enters password.
    """
    try:
        # Attempt to get TGT from KDC
        result = kerberos.checkPassword(username, password,
                                       f"krbtgt/{realm}@{realm}", realm)
        return result == 1
    except kerberos.KrbError as e:
        logger.warning(f"Kerberos password validation failed: {e}")
        return False
```

**Verdict**: ⚠️ **NOT RECOMMENDED** - Defeats primary value of Kerberos (SSO). Only useful as interim step if full GSSAPI is too complex initially.

---

### Option 3: Proxy Through Apache mod_auth_kerb

**Approach**: Run Apache/nginx in front of PGWire with `mod_auth_kerb`, set `REMOTE_USER` header.

**Pros**:
- ✅ **Leverage Existing Tools**: mod_auth_kerb is battle-tested
- ✅ **Separation of Concerns**: Auth handled outside PGWire server

**Cons**:
- ❌ **HTTP-Only**: PostgreSQL wire protocol doesn't use HTTP
- ❌ **Protocol Incompatibility**: Can't proxy binary PostgreSQL protocol through HTTP
- ❌ **Not Feasible**: This approach fundamentally doesn't work for database connections

**Verdict**: ❌ **NOT APPLICABLE** - PostgreSQL wire protocol is TCP-based, not HTTP.

---

### Option 4: Kerberos via IRIS Native Auth (Future Enhancement)

**Approach**: If IRIS gains native Kerberos support, PGWire could delegate auth to IRIS.

**Pros**:
- ✅ **Unified Auth**: One Kerberos setup for all IRIS access methods
- ✅ **IRIS-Managed**: Leverage IRIS security infrastructure

**Cons**:
- ❌ **Not Currently Available**: IRIS doesn't have native Kerberos auth
- ❌ **Requires IRIS Changes**: Outside scope of PGWire project

**Verdict**: 📋 **FUTURE CONSIDERATION** - Track IRIS Kerberos roadmap, revisit if IRIS adds support.

---

## Recommended Implementation: Option 1 (Pure Python GSSAPI)

### Phase 1: Basic GSSAPI Authentication (P5)

**Deliverables**:
1. GSSAPI authenticator class using `python-gssapi`
2. Protocol message handlers for AuthenticationGSS, GSSResponse
3. Multi-step token exchange state machine
4. Username extraction from authenticated Kerberos principal
5. IRIS user validation (query Security.Users table)
6. E2E tests with MIT Kerberos test realm (k5test)

**Success Criteria**:
- ✅ `psql` connects using Kerberos ticket (no password)
- ✅ Python psycopg connects using Kerberos
- ✅ JDBC connects using Kerberos
- ✅ All 8 existing client drivers still work (no regression)

### Phase 2: Advanced Features (Future)

**pg_ident.conf Mapping** (PostgreSQL-compatible):
- Map Kerberos principals to IRIS usernames flexibly
- Example: `alice@EXAMPLE.COM` → `ALICE` (strip realm)
- Example: `service/host@REALM` → `service_account`

**Credential Delegation**:
- Pass Kerberos ticket to IRIS for downstream authentication
- Enables "double-hop" scenarios (PGWire → IRIS → another Kerberized service)

**GSSAPI Encryption** (gss_encrypt_mode):
- Encrypt data channel using GSSAPI (alternative to TLS)
- PostgreSQL supports this via `gssencmode=prefer`

---

## Security Considerations

### Keytab Protection

**Critical**: Keytab file contains service principal keys - must be protected like passwords!

```bash
# Keytab should be:
# - Readable only by PGWire server user
# - Not in Docker image (mount as secret)
# - Rotated periodically via kadmin

chmod 600 /etc/krb5.keytab
chown pgwire:pgwire /etc/krb5.keytab

# Docker Compose secret
docker secret create pgwire_keytab /path/to/postgres.keytab
```

### Realm Trust

**Important**: Kerberos authentication inherently trusts the KDC.

- Validate realm of authenticated principals (don't accept arbitrary realms)
- Configure trusted realms explicitly
- Log all authentication attempts (audit trail)

### Username Mapping

**Risk**: Kerberos principal may not match IRIS username exactly.

**Mitigation**:
- Require explicit pg_ident.conf mapping (don't auto-create users)
- Strip realm by default (`alice@EXAMPLE.COM` → `ALICE`)
- Log mapping decisions for audit

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/test_gssapi_auth.py
import pytest
from iris_pgwire.auth.gssapi_auth import GSSAPIAuthenticator

@pytest.mark.asyncio
async def test_gssapi_handshake_success(k5test_realm):
    """Test successful GSSAPI authentication with test KDC."""
    auth = GSSAPIAuthenticator(service_name='postgres',
                               hostname='test.example.com')
    await auth.initialize()

    # Simulate client token
    client_token = k5test_realm.get_client_token('alice@TEST.REALM')

    # Process token
    server_token, username = await auth.process_client_token(
        'conn-1', client_token
    )

    assert username == 'alice@TEST.REALM'

@pytest.mark.asyncio
async def test_iris_user_validation(iris_container, k5test_realm):
    """Test that Kerberos principal maps to IRIS user."""
    auth = GSSAPIAuthenticator()

    # Create IRIS user 'alice'
    await iris_container.create_user('alice', 'password')

    # Validate Kerberos principal maps to IRIS user
    valid = await auth.validate_iris_user('alice@TEST.REALM')
    assert valid is True

    # Unknown principal should fail
    valid = await auth.validate_iris_user('bob@TEST.REALM')
    assert valid is False
```

### E2E Tests (with Real Kerberos)

```python
# tests/e2e/test_gssapi_e2e.py
import subprocess
import psycopg

def test_psql_kerberos_auth(k5test_realm, pgwire_server):
    """Test psql connecting with Kerberos ticket."""
    # Get Kerberos ticket
    k5test_realm.kinit('alice@TEST.REALM', 'password')

    # Connect via psql (should use Kerberos automatically)
    result = subprocess.run([
        'psql',
        '-h', 'localhost',
        '-p', '5432',
        '-U', 'alice',  # Username from Kerberos ticket
        '-d', 'USER',
        '-c', 'SELECT 1'
    ], capture_output=True, text=True)

    assert result.returncode == 0
    assert '1' in result.stdout

def test_psycopg_kerberos_auth(k5test_realm, pgwire_server):
    """Test Python psycopg with Kerberos."""
    k5test_realm.kinit('alice@TEST.REALM', 'password')

    # Connect with gssencmode=disable (no GSSAPI encryption, just auth)
    conn = psycopg.connect(
        "host=localhost port=5432 dbname=USER gssencmode=disable"
    )

    cur = conn.cursor()
    cur.execute("SELECT CURRENT_USER")
    username = cur.fetchone()[0]

    assert username.upper() == 'ALICE'
```

### Integration with k5test

Use `k5test` library to create isolated Kerberos test realms:

```python
# conftest.py
import pytest
from k5test import K5Realm

@pytest.fixture(scope='session')
def k5test_realm():
    """Create isolated Kerberos test realm."""
    realm = K5Realm()

    # Create test principals
    realm.addprinc('alice@TEST.REALM', password='alice_pass')
    realm.addprinc('bob@TEST.REALM', password='bob_pass')

    # Create service principal for PGWire
    realm.addprinc('postgres/localhost@TEST.REALM')
    realm.extract_keytab('postgres/localhost@TEST.REALM',
                        realm.keytab)

    yield realm

    realm.stop()
```

---

## Deployment Guide

### Prerequisites

**System Requirements**:
```bash
# Install Kerberos libraries
# Ubuntu/Debian
apt-get install libkrb5-dev krb5-user

# RHEL/CentOS
yum install krb5-devel krb5-workstation

# macOS
brew install krb5
```

**Python Dependencies**:
```bash
pip install python-gssapi>=1.8.0
```

### Configuration

**Environment Variables**:
```bash
# Enable GSSAPI authentication
export IRIS_PGWIRE_ENABLE_GSSAPI=true

# Service principal configuration
export IRIS_PGWIRE_GSSAPI_SERVICE=postgres
export IRIS_PGWIRE_GSSAPI_HOSTNAME=pgwire.example.com

# Keytab location (required)
export KRB5_KTNAME=/etc/krb5.keytab

# Optional: Restrict to specific realm
export IRIS_PGWIRE_GSSAPI_REALM=EXAMPLE.COM
```

**Docker Deployment**:
```yaml
# docker-compose.yml
services:
  iris-pgwire:
    image: iris-pgwire:latest
    environment:
      IRIS_PGWIRE_ENABLE_GSSAPI: "true"
      IRIS_PGWIRE_GSSAPI_HOSTNAME: "pgwire.example.com"
    secrets:
      - source: pgwire_keytab
        target: /etc/krb5.keytab
        mode: 0600
    volumes:
      - /etc/krb5.conf:/etc/krb5.conf:ro  # Kerberos config

secrets:
  pgwire_keytab:
    external: true  # Managed via Docker secrets
```

### Client Configuration

**No changes required** - standard PostgreSQL clients work automatically!

```bash
# 1. Get Kerberos ticket (once per session)
kinit alice@EXAMPLE.COM

# 2. Connect to IRIS via PGWire (no password)
psql "host=pgwire.example.com port=5432 dbname=USER gssencmode=disable"

# 3. Python (psycopg)
python -c "
import psycopg
conn = psycopg.connect('host=pgwire.example.com port=5432 dbname=USER gssencmode=disable')
print('Connected via Kerberos!')
"

# 4. JDBC
java -Djava.security.auth.login.config=jaas.conf MyApp
# JDBC URL: jdbc:postgresql://pgwire.example.com:5432/USER?gssencmode=disable
```

---

## Migration Path for Existing Deployments

### Phase 1: Dual-Mode Auth (Recommended)

Support both SCRAM-SHA-256 and GSSAPI simultaneously:

```python
# Allow clients to choose authentication method
if self.config.enable_gssapi and client_supports_gssapi():
    # Offer GSSAPI
    await self.send_authentication_gss()
else:
    # Fall back to SCRAM
    await self.send_authentication_sasl()
```

**Benefit**: Gradual rollout - existing clients continue working while new clients adopt Kerberos.

### Phase 2: Kerberos-Only (Future)

Once all clients migrated to Kerberos:
```python
# Require GSSAPI
if not client_supports_gssapi():
    await self.send_error_response(
        "FATAL", "28000",
        "Kerberos authentication required"
    )
```

---

## Performance Considerations

### GSSAPI Overhead

**Typical Handshake**: 2-3 round trips (300-500ms including network latency)

**Mitigation**:
- Connection pooling (authenticate once, reuse connection)
- Ticket caching (GSSAPI libraries cache credentials)
- Fast path for ticket renewal (< 10ms)

**Comparison to SCRAM-SHA-256**:
- SCRAM: ~200ms (password hashing + 4 round trips)
- GSSAPI: ~400ms (ticket validation + 2-3 round trips)
- **Negligible difference** for long-lived connections

### Production Benchmarks (Expected)

```
Authentication Method     | First Connection | Subsequent (cached) | Connection Pool
--------------------------|------------------|---------------------|------------------
SCRAM-SHA-256 (current)  | 200ms           | 200ms               | 0ms (reuse)
GSSAPI (proposed)        | 400ms           | 50ms (ticket cache) | 0ms (reuse)
```

**Conclusion**: GSSAPI overhead is acceptable for enterprise workloads (connections are pooled).

---

## Community Feedback Request

**Questions for IRIS Community**:

1. **Priority**: How critical is Kerberos/GSSAPI support for your organization? (High/Medium/Low)

2. **Infrastructure**: Do you currently use Kerberos/Active Directory for authentication? (Yes/No/Considering)

3. **Use Case**: What would Kerberos enable for you?
   - [ ] SSO for BI tools (Tableau, PowerBI)
   - [ ] Automated ETL pipelines (no password management)
   - [ ] Data science workflows (Jupyter notebooks)
   - [ ] Other: ___________

4. **Migration**: Would dual-mode auth (SCRAM + GSSAPI) be useful during migration? (Yes/No)

5. **Alternatives**: Are you currently using workarounds (embedded passwords, OAuth proxies, etc.)?

**Feedback**: Please comment on InterSystems Developer Community or GitHub issue #XXX

---

## References

- **PostgreSQL GSSAPI Auth**: https://www.postgresql.org/docs/current/gssapi-auth.html
- **python-gssapi Documentation**: https://pythonhosted.org/python-gssapi/
- **RFC 4559 (SPNEGO)**: https://www.ietf.org/rfc/rfc4559.txt
- **RFC 2743 (GSSAPI)**: https://www.ietf.org/rfc/rfc2743.txt
- **MIT Kerberos Documentation**: https://web.mit.edu/kerberos/krb5-latest/doc/

---

## Next Steps

1. **Gather Community Feedback** - Survey IRIS users on Kerberos requirements
2. **Prototype Implementation** - Build proof-of-concept with python-gssapi
3. **Test with Real KDC** - Validate against Active Directory and MIT Kerberos
4. **Document Enterprise Deployment** - Create setup guide for IRIS admins
5. **Integrate with Feature Roadmap** - Add to PGWire P5 backlog if community interest high

**Estimated Effort**: 3-4 weeks (1 week prototype, 1 week testing, 1-2 weeks documentation)

**Constitutional Compliance**: Principle V (Authentication Security) - Kerberos provides stronger authentication than passwords, meets enterprise requirements.
