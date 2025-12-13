# Kerberos/GSSAPI Authentication - Quick Summary

**TL;DR**: Add enterprise SSO to IRIS PGWire using PostgreSQL-compatible Kerberos authentication, eliminating password management for enterprise IRIS deployments.

## The Problem

Enterprise IRIS users struggle with authentication:
- ❌ Passwords must be embedded in config files/notebooks (security risk)
- ❌ OAuth/SAML integration with IRIS is complex/unsupported
- ❌ No SSO with enterprise Active Directory
- ❌ Manual credential rotation across hundreds of applications

## The Solution

Implement PostgreSQL GSSAPI authentication in PGWire:
- ✅ **Zero-password workflows**: `kinit alice@REALM` → all IRIS connections work
- ✅ **Enterprise SSO**: Leverage existing AD/Kerberos infrastructure
- ✅ **Automatic credential rotation**: Kerberos handles ticket refresh
- ✅ **PostgreSQL-compatible**: All existing clients (psql, JDBC, psycopg) work unchanged

## User Experience

**Before (with passwords)**:
```python
# Security risk - password in code!
conn = psycopg.connect("host=iris port=5432 user=alice password=SECRET123")
```

**After (with Kerberos)**:
```bash
# Authenticate once per session
kinit alice@EXAMPLE.COM
```

```python
# No password needed - authenticated via Kerberos!
conn = psycopg.connect("host=pgwire port=5432 dbname=USER gssencmode=disable")
```

## Implementation Approach (Recommended)

**Option 1: Pure Python GSSAPI** (python-gssapi library)

**Pros**:
- Pure Python, asyncio-compatible
- Battle-tested (used by requests-gssapi, httpx-gssapi)
- Cross-platform (MIT Kerberos, Heimdal, Active Directory)
- PostgreSQL wire protocol compatible

**Architecture**:
```
Client                         PGWire Server                    IRIS
──────                         ─────────────                    ────
1. StartupMessage          →
                           ←   2. AuthenticationGSS (type=7)
3. GSSResponse (token)     →
                           ←   4. AuthenticationGSSContinue
5. GSSResponse (token)     →
                               [Validate Kerberos principal]
                               [Check IRIS user exists]
                           ←   6. AuthenticationOk
```

**Setup Requirements**:
1. **One-time KDC setup** (by Kerberos admin):
   ```bash
   # Create service principal
   kadmin: addprinc -randkey postgres/pgwire.example.com@REALM
   kadmin: ktadd -k postgres.keytab postgres/pgwire.example.com@REALM
   ```

2. **Deploy keytab to PGWire server**:
   ```bash
   docker secret create pgwire_keytab /path/to/postgres.keytab
   ```

3. **Enable GSSAPI in config**:
   ```yaml
   environment:
     IRIS_PGWIRE_ENABLE_GSSAPI: "true"
   ```

4. **Clients work unchanged** - no code modifications needed!

## Real-World Use Cases

### Use Case 1: Data Science Teams
**Current**: Passwords embedded in Jupyter notebooks
**With Kerberos**: `kinit alice@REALM` → all notebooks connect automatically
**Impact**: Eliminates password sprawl, audit trail via Kerberos

### Use Case 2: ETL Pipelines
**Current**: IRIS passwords in Kubernetes secrets (manual rotation)
**With Kerberos**: Service principal with keytab (automatic rotation)
**Impact**: Zero-touch credential management

### Use Case 3: BI Tools (Tableau/PowerBI)
**Current**: Each user enters IRIS password (not SSO)
**With Kerberos**: Windows domain login → BI tool uses Kerberos ticket
**Impact**: True enterprise SSO experience

## Technical Details

**Protocol Messages**:
- `AuthenticationGSS` (type=7): Server requests Kerberos auth
- `GSSResponse` ('p'): Client sends GSSAPI token
- `AuthenticationGSSContinue` (type=8): Server sends continuation token
- `AuthenticationOk` (type=0): Authentication succeeded

**Python Implementation** (simplified):
```python
import gssapi

class GSSAPIAuthenticator:
    async def handle_gssapi_handshake(self):
        # Load service credentials from keytab
        service_name = gssapi.Name('postgres/pgwire.example.com')
        server_creds = gssapi.Credentials(service_name, usage='accept')

        # Create acceptor context
        ctx = gssapi.SecurityContext(creds=server_creds, usage='accept')

        # Multi-step token exchange
        while not ctx.complete:
            client_token = await self.receive_gss_response()
            server_token = await asyncio.to_thread(ctx.step, client_token)

            if not ctx.complete:
                await self.send_authentication_gss_continue(server_token)

        # Extract authenticated username
        username = str(ctx.peer_name)  # e.g., 'alice@EXAMPLE.COM'

        # Validate IRIS user exists
        if await self.validate_iris_user(username):
            await self.send_authentication_ok()
            return username
        else:
            await self.send_error("User not found in IRIS")
```

**Dependencies**:
```txt
python-gssapi>=1.8.0  # Pure Python, cross-platform
```

**System Requirements**:
```bash
# Kerberos libraries (one-time install)
apt-get install libkrb5-dev krb5-user  # Ubuntu/Debian
yum install krb5-devel krb5-workstation  # RHEL/CentOS
brew install krb5  # macOS
```

## Security Considerations

### ✅ Secure by Design
- **Keytab protection**: Mounted as Docker secret (chmod 600)
- **Realm validation**: Only accept trusted Kerberos realms
- **User mapping**: Validate Kerberos principal → IRIS user
- **Audit trail**: All auth attempts logged

### ⚠️ Operational Requirements
- **Keytab rotation**: Periodic refresh via kadmin (like password rotation)
- **KDC availability**: Authentication depends on Kerberos KDC uptime
- **Clock synchronization**: Kerberos requires NTP-synced clocks

## Testing Strategy

### Unit Tests (with k5test)
```python
# Create isolated Kerberos test realm
realm = K5Realm()
realm.addprinc('alice@TEST.REALM', password='pass')
realm.addprinc('postgres/localhost@TEST.REALM')

# Test authentication
auth = GSSAPIAuthenticator()
username = await auth.authenticate_client(client_token)
assert username == 'alice@TEST.REALM'
```

### E2E Tests (with real clients)
```bash
# Test psql
kinit alice@TEST.REALM
psql "host=localhost port=5432 dbname=USER gssencmode=disable"

# Test Python
python -c "import psycopg; psycopg.connect('host=localhost port=5432 dbname=USER gssencmode=disable')"

# Test JDBC
java -jar test-jdbc.jar  # Uses Kerberos ticket automatically
```

## Performance

**Authentication Overhead**:
- First connection: ~400ms (2-3 GSSAPI round trips)
- Cached ticket: ~50ms (ticket validation only)
- Connection pooling: 0ms (authenticate once, reuse)

**Comparison to SCRAM-SHA-256**:
- SCRAM: ~200ms (password hashing + 4 round trips)
- GSSAPI: ~400ms (ticket validation + 2-3 round trips)
- **Difference negligible** for connection-pooled workloads

## Migration Path

### Phase 1: Dual-Mode (Recommended)
Support both SCRAM and GSSAPI:
- Existing clients: Continue using passwords
- New clients: Adopt Kerberos
- **Zero downtime migration**

### Phase 2: Kerberos-Only (Future)
Once all clients migrated:
- Require GSSAPI authentication
- Disable password-based auth
- **Maximum security posture**

## Community Feedback Questions

1. **Priority**: How critical is Kerberos for your organization?
   - [ ] High - blocking enterprise adoption
   - [ ] Medium - nice to have
   - [ ] Low - not needed

2. **Current Setup**: Do you use Kerberos/AD today?
   - [ ] Yes - Active Directory
   - [ ] Yes - MIT Kerberos
   - [ ] No - but considering

3. **Use Cases**: What would Kerberos enable?
   - [ ] SSO for BI tools (Tableau, PowerBI)
   - [ ] Automated ETL (no password management)
   - [ ] Data science workflows (Jupyter)
   - [ ] Other: ___________

4. **Workarounds**: Current password management approach?
   - [ ] Embedded in code (security risk)
   - [ ] Environment variables
   - [ ] Secrets manager (Vault, k8s secrets)
   - [ ] Manual entry (not automated)

**Share feedback**: InterSystems Developer Community forum or GitHub issue

## Estimated Timeline

**Phase 1: Prototype** (1 week)
- Implement GSSAPI authenticator with python-gssapi
- Basic protocol message handlers
- Unit tests with k5test

**Phase 2: Integration** (1 week)
- Integrate with existing auth system (dual-mode)
- E2E tests with real Kerberos KDC
- Documentation for keytab setup

**Phase 3: Production** (1-2 weeks)
- Active Directory testing
- Performance benchmarking
- Enterprise deployment guide

**Total**: 3-4 weeks end-to-end

## Constitutional Alignment

**Principle V: Authentication Security**
> "Authentication mechanisms MUST support enterprise security requirements."

Kerberos authentication aligns with constitutional principles:
- ✅ **Stronger than passwords** (cryptographic tickets vs shared secrets)
- ✅ **Enterprise-grade** (battle-tested in Fortune 500 companies)
- ✅ **Audit-friendly** (centralized KDC logging)
- ✅ **PostgreSQL-compatible** (standard wire protocol)

## Next Steps

1. ✅ **Specification complete** - This document
2. **Community feedback** - Survey IRIS users on requirements
3. **Prototype** - Build proof-of-concept with python-gssapi
4. **Validation** - Test with real AD and MIT Kerberos
5. **Documentation** - Enterprise deployment guide
6. **Roadmap** - Add to P5 backlog if community interest high

---

**Full Specification**: See `specs/KERBEROS_GSSAPI_OPTIONS.md` for detailed implementation guide.

**Questions?** Open GitHub issue or post on InterSystems Developer Community forum.
