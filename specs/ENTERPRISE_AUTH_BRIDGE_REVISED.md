# Enterprise Authentication Bridge for IRIS PGWire (REVISED)

**Status**: Specification - **CORRECTED BASED ON IRIS CAPABILITIES**
**Priority**: P5 (MEDIUM) - Enterprise SSO integration
**Key Insight**: Leverage IRIS's existing OAuth 2.0, Kerberos, and Wallet capabilities instead of reimplementing

---

## Executive Summary - Critical Correction

**Original Assumption** (WRONG ❌): IRIS lacks enterprise auth, PGWire needs to implement everything from scratch

**Actual Reality** (CORRECT ✅):
- ✅ **IRIS has native OAuth 2.0** server AND client support (RFC 6749, RFC 7636 PKCE)
- ✅ **IRIS has native Kerberos** authentication for JDBC, ODBC, xDBC
- ✅ **IRIS has TLS/SSL** with client certificate (mTLS) support
- ✅ **IRIS Wallet** (2025.3.0+) provides secure secret storage in IRISSECURITY database
- ✅ **IRIS integrates** with Azure AD, Okta, Auth0, Active Directory

**New Opportunity**: **Bridge** PostgreSQL wire protocol auth to IRIS's existing enterprise authentication infrastructure, not reimplement it!

---

## The Real Value Proposition

### Current State (Authentication Gap)

```
PostgreSQL Client (psql, psycopg, JDBC)
    ↓
    Password-only authentication via PGWire
    ↓
IRIS (with OAuth/Kerberos/Wallet capabilities UNUSED)
```

**Problem**: PostgreSQL clients can't access IRIS's enterprise auth features!

### Proposed State (Authentication Bridge)

```
PostgreSQL Client (psql, psycopg, JDBC)
    ↓
    PostgreSQL GSSAPI/OAuth wire protocol
    ↓
PGWire (authentication bridge)
    ↓
    Map to IRIS native auth methods
    ↓
IRIS OAuth 2.0 / Kerberos / Wallet
    ↓
Enterprise Identity Systems (Azure AD, Okta, Active Directory)
```

**Value**: PostgreSQL clients gain access to IRIS's enterprise auth without IRIS changes!

---

## IRIS Authentication Capabilities (Research Findings)

### 1. OAuth 2.0 (Fully Supported)

**IRIS OAuth 2.0 Server** (`OAuth2.Server`):
- Authorization Server implementation
- Token endpoint, authorization endpoint
- Client credentials, authorization code, implicit flows
- JWT token generation
- Scope-based access control

**IRIS OAuth 2.0 Client** (`OAuth2.Client`):
- Resource Server implementation
- Token validation and introspection (RFC 7662)
- Integration with external OAuth providers (Okta, Azure AD, Auth0)
- Access token validation for incoming requests

**Connection String Support**:
```csharp
// .NET with OAuth
Conn.ConnectionString = "Server=localhost; Port=51773; AccessToken=eyJraWQi...;";
```

```java
// JDBC with OAuth
IRISDataSource ds = new IRISDataSource();
ds.setAccessToken("eyJraWQi...");  // Overwrites username/password
```

**ODBC with OAuth**:
```
ACCESSTOKEN=Fgz-4mGm;  // Replaces UID/PWD parameters
```

### 2. Kerberos (Fully Supported)

**Supported Services**:
- `%Service_Bindings` (JDBC, ODBC, xDBC)
- Instance authentication OR Kerberos

**Connection Security Levels**:
- Level 0: Instance authentication (password)
- Level 1: Kerberos authentication only
- Level 2: Kerberos + packet integrity
- Level 3: Kerberos + encryption

**ODBC Configuration**:
```
Authentication Method: Kerberos
Connection Security Level: Kerberos with Encryption
Service Principal Name: postgres/hostname@REALM
```

**JDBC Configuration**:
```java
// Connection security level for Kerberos
properties.put("connection security level", "3");  // Full encryption
```

**Process** (from Confluence research):
1. Client contacts KDC, receives ticket-granting ticket (TGT)
2. Client uses TGT to obtain service ticket for IRIS
3. Client presents service ticket to IRIS for authentication
4. Optional: Establish encrypted channel

### 3. TLS/SSL with Client Certificates (mTLS)

**Web Gateway mTLS**:
- Client certificate authentication for %Service_WebGateway
- Certificate CN field → IRIS username mapping
- Eliminates password storage (certificate-based identity)

**Configuration**:
- Generate client certificate with CN = IRIS username
- Configure Web Gateway with cert, key, CA files
- Enable mTLS on %Service_WebGateway service

**JDBC/ODBC TLS**:
- Connection Security Level 10 = TLS
- Encrypts credentials in transit
- Can be combined with OAuth or Kerberos

### 4. IRIS Wallet (2025.3.0+)

**Purpose**: Secure storage for secrets, credentials, API keys

**Storage**: IRISSECURITY database (encrypted)

**Use Cases** (from Confluence):
- OAuth client secrets
- External database credentials (xDBC connections)
- API keys for third-party services
- LLM provider credentials (OpenAI, Azure)

**API**: `%IRIS.Wallet` secret storage and retrieval

**Example** (from Confluence):
```objectscript
// Store OAuth client secret in Wallet
Set wallet = ##class(%IRIS.Wallet).%New("ai-gateway")
Do wallet.SetSecret("oauth-client-secret", "Ab12Cd34...")

// Retrieve later
Set secret = wallet.GetSecret("oauth-client-secret")
```

**Benefit**: Credentials never stored in plain text in application code

---

## Proposed Architecture: Authentication Bridge

### Option 1: PostgreSQL GSSAPI → IRIS Kerberos (CLEANEST)

**Approach**: Map PostgreSQL GSSAPI protocol directly to IRIS's existing Kerberos support.

```
┌─────────────────┐
│ PostgreSQL      │
│ Client          │ 1. StartupMessage
│ (psql, psycopg) │────────────────────┐
└─────────────────┘                    │
                                       ▼
                           ┌───────────────────────┐
                           │ PGWire Server         │
                           │ (Authentication       │
                           │  Bridge Layer)        │
                           └───────────────────────┘
                                       │
                    2. AuthenticationGSS (type=7)
                                       │
                                       ▼
                           ┌───────────────────────┐
                           │ GSSAPI Token          │
                           │ Exchange              │ 3. Validate Kerberos
                           │ (python-gssapi)       │    ticket via IRIS
                           └───────────────────────┘
                                       │
                                       ▼
                           ┌───────────────────────┐
                           │ IRIS Native           │
                           │ Kerberos Auth         │ 4. Extract username
                           │ (%Service_Bindings)   │    from Kerberos
                           └───────────────────────┘    principal
                                       │
                                       ▼
                           ┌───────────────────────┐
                           │ IRIS User Session     │
                           │ (authenticated)       │ 5. Ready for queries
                           └───────────────────────┘
```

**Implementation**:
```python
class IRISKerberosAuth:
    """Bridge PostgreSQL GSSAPI to IRIS Kerberos."""

    async def authenticate_via_iris_kerberos(self, gssapi_token: bytes) -> str:
        """
        Validate Kerberos token using IRIS's native Kerberos support.

        Returns:
            IRIS username from Kerberos principal
        """
        # 1. Extract Kerberos principal from GSSAPI token
        principal = await self.validate_gssapi_token(gssapi_token)

        # 2. Use IRIS's Kerberos authentication to validate
        #    Call IRIS via embedded Python to check Kerberos auth
        iris_username = await self.iris_kerberos_validate(principal)

        # 3. Return IRIS username for session
        return iris_username
```

**Key Advantage**: **No duplicate Kerberos implementation** - leverage IRIS's battle-tested Kerberos code!

### Option 2: PostgreSQL Password → IRIS OAuth Token Exchange (HYBRID)

**Approach**: Accept username/password from PostgreSQL clients, exchange for IRIS OAuth token.

```
PostgreSQL Client (username/password)
    ↓
PGWire (SCRAM-SHA-256 or plain password)
    ↓
Exchange username/password for OAuth token
    ↓
IRIS OAuth 2.0 Server (/oauth2/token endpoint)
    ↓
Validate token against IRIS OAuth
    ↓
IRIS User Session (OAuth-authenticated)
```

**Implementation**:
```python
class IriSOAuthBridge:
    """Bridge password auth to IRIS OAuth tokens."""

    async def exchange_password_for_token(self, username: str, password: str) -> str:
        """
        Exchange username/password for IRIS OAuth 2.0 access token.

        Uses IRIS's OAuth 2.0 token endpoint (client credentials flow).
        """
        # Call IRIS OAuth endpoint
        token_response = await self.call_iris_oauth_endpoint(
            grant_type='password',
            username=username,
            password=password,
            client_id=self.pgwire_client_id,
            client_secret=await self.get_wallet_secret('pgwire-oauth-secret')
        )

        # Store token for session
        return token_response['access_token']
```

**Key Advantage**: Existing PostgreSQL clients work **without changes** while gaining OAuth benefits!

### Option 3: IRIS Wallet Integration for Credential Management

**Approach**: Store PostgreSQL connection credentials in IRIS Wallet, retrieve at runtime.

```python
class IRISWalletCredentials:
    """Manage PostgreSQL credentials via IRIS Wallet."""

    async def get_password_from_wallet(self, username: str) -> str:
        """
        Retrieve user password from IRIS Wallet instead of IRIS user table.

        Benefit: Credentials encrypted at rest, audit trail, rotation support.
        """
        wallet_key = f"pgwire-user-{username}"

        # Query IRIS Wallet via embedded Python
        password = await self.iris_wallet_get_secret(wallet_key)

        if not password:
            raise AuthenticationError(f"No wallet entry for user {username}")

        return password
```

**Key Advantage**: Eliminates plain-text password storage, provides audit trail!

---

## Implementation Roadmap

### Phase 1: Research and Validation (1 week)

**Tasks**:
1. Test IRIS OAuth 2.0 token validation from embedded Python
2. Test IRIS Kerberos authentication via %Service_Bindings
3. Validate IRIS Wallet API access from embedded Python
4. Document IRIS auth APIs and integration points

**Deliverable**: Technical feasibility report with code samples

### Phase 2: OAuth Token Bridge (2 weeks)

**Tasks**:
1. Implement password → OAuth token exchange
2. Integrate with IRIS OAuth 2.0 server
3. Store OAuth client credentials in IRIS Wallet
4. E2E testing with psql, psycopg, JDBC

**Deliverable**: Working OAuth authentication for PostgreSQL clients

### Phase 3: Kerberos Bridge (2-3 weeks)

**Tasks**:
1. Implement PostgreSQL GSSAPI message handlers
2. Bridge GSSAPI tokens to IRIS Kerberos validation
3. Map Kerberos principals to IRIS usernames
4. Test with Active Directory and MIT Kerberos

**Deliverable**: Working Kerberos SSO for PostgreSQL clients

### Phase 4: Wallet Integration (1 week)

**Tasks**:
1. Implement credential retrieval from IRIS Wallet
2. Add wallet-based password validation
3. Document credential rotation procedures
4. Test with encrypted credentials

**Deliverable**: IRIS Wallet-backed authentication

---

## Competitive Advantages

### vs. Implementing Kerberos from Scratch

| Approach | Pros | Cons |
|----------|------|------|
| **From Scratch** | Full control | 4+ weeks development<br>Security audit required<br>Duplicate IRIS functionality<br>Maintenance burden |
| **Bridge to IRIS** ✅ | 2 weeks development<br>Leverage tested code<br>Single auth system<br>No duplicate maintenance | Requires IRIS API integration<br>Dependency on IRIS auth |

**Verdict**: **Bridging is 2× faster and more secure** (reuse IRIS's tested code)

### vs. Password-Only Authentication

| Feature | Password-Only | OAuth Bridge | Kerberos Bridge |
|---------|---------------|--------------|-----------------|
| **SSO** | ❌ | ✅ (via Azure AD/Okta) | ✅ (via Active Directory) |
| **Zero-password workflows** | ❌ | ⚠️ (password → token) | ✅ (kinit only) |
| **Credential rotation** | Manual | Automatic (token expiry) | Automatic (ticket expiry) |
| **Audit trail** | IRIS logs only | OAuth server logs | Kerberos KDC logs |
| **Development time** | Complete ✅ | 2 weeks | 3 weeks |

---

## Real-World Use Cases (Updated)

### Use Case 1: BI Tools with Azure AD SSO

**Current**: BI tools (Tableau, PowerBI) → Username/password → IRIS PGWire

**With OAuth Bridge**:
- BI user authenticates to Azure AD (SSO)
- BI tool obtains OAuth token
- PGWire validates token via IRIS OAuth 2.0 server
- IRIS session created with Azure AD identity

**Benefit**: **True SSO** - users never enter IRIS password!

### Use Case 2: Data Science with IRIS Wallet

**Current**: Jupyter notebooks have embedded IRIS passwords (security risk)

**With Wallet Integration**:
- Credentials stored in IRIS Wallet (encrypted in IRISSECURITY)
- PGWire retrieves credentials from Wallet at runtime
- Automatic rotation via Wallet API
- Audit trail of credential access

**Benefit**: **Zero plain-text passwords**, audit compliance!

### Use Case 3: ETL Pipelines with Kerberos

**Current**: ETL jobs store IRIS passwords in Kubernetes secrets

**With Kerberos Bridge**:
- ETL pod authenticates to Active Directory via service principal
- PostgreSQL client uses Kerberos ticket automatically
- PGWire bridges to IRIS Kerberos authentication
- Zero credential storage

**Benefit**: **Zero credential management overhead**!

---

## Security Considerations (Updated)

### Leveraging IRIS Security Infrastructure

**Advantages**:
- ✅ IRIS OAuth 2.0 implementation is **already audited**
- ✅ IRIS Kerberos support is **battle-tested** in production
- ✅ IRIS Wallet provides **encrypted storage** (IRISSECURITY DB)
- ✅ Single audit trail across all IRIS access methods

**Risks Mitigated**:
- ❌ No duplicate crypto implementation (avoid CVEs)
- ❌ No key management (IRIS handles it)
- ❌ No credential storage in PGWire code

### Additional Security Measures

**Token Validation**:
- Validate OAuth tokens against IRIS OAuth server (not local verification)
- Short token expiry (15-60 minutes)
- Refresh token rotation

**Kerberos Ticket Validation**:
- Validate tickets against IRIS Kerberos infrastructure
- Honor ticket expiry and renewable windows
- Log all authentication attempts

**Wallet Access Control**:
- Restrict Wallet access to PGWire service account
- Audit all credential retrievals
- Rotate credentials via Wallet API

---

## Community Feedback Questions (Revised)

1. **OAuth 2.0 Integration**:
   - Do you currently use IRIS OAuth 2.0 for web services? (Yes/No)
   - What OAuth provider do you use? (Azure AD / Okta / Auth0 / Other)

2. **Kerberos Infrastructure**:
   - Do you use Kerberos for JDBC/ODBC today? (Yes/No)
   - What KDC? (Active Directory / MIT Kerberos / Other)

3. **IRIS Wallet**:
   - Are you on IRIS 2025.3.0+ (Wallet available)? (Yes/No)
   - Would Wallet-backed credentials be useful? (Yes/No)

4. **Priority**:
   - Which matters most for your organization?
     - [ ] OAuth 2.0 bridge (Azure AD/Okta SSO)
     - [ ] Kerberos bridge (Active Directory SSO)
     - [ ] IRIS Wallet integration (secure credential storage)

---

## Next Steps (Revised)

1. ✅ **Research Complete** - IRIS auth capabilities documented
2. **Validate IRIS Integration** - Test OAuth/Kerberos/Wallet APIs from embedded Python
3. **Prototype OAuth Bridge** - Simplest option, highest ROI
4. **Community Feedback** - Survey IRIS users on OAuth/Kerberos priorities
5. **Implement Based on Feedback** - Prioritize OAuth or Kerberos based on demand

**Estimated Timeline**: 2-4 weeks (much faster than implementing from scratch!)

---

## References

### IRIS Documentation (from Research)
- OAuth 2.0: `OAuth2.Server`, `OAuth2.Client` classes
- Kerberos: `%Service_Bindings` security levels
- Wallet: `%IRIS.Wallet` API (IRIS 2025.3.0+)
- xDBC Auth: JDBC/ODBC authentication methods

### Confluence Findings
- "Setup OAuth on IRIS" - OAuth server configuration
- "Azure authentication (IRIS e.g. SMP)" - OAuth delegation examples
- "Secure Wallet" - Credential storage in IRISSECURITY database
- "Security Admin Story: OAuth, RBAC, and Audit for MCP Gateway" - OAuth integration patterns

---

## Conclusion (MAJOR REVISION)

**Original Plan** ❌: Implement Kerberos/OAuth from scratch in PGWire (4+ weeks, security risks)

**Revised Plan** ✅: **Bridge PostgreSQL auth to IRIS's existing OAuth/Kerberos/Wallet** (2-4 weeks, leverage tested code)

**Key Insight**: IRIS already has enterprise-grade authentication! We just need to make it accessible to PostgreSQL clients via the wire protocol.

**Next Action**: Validate IRIS API integration from embedded Python, then prototype OAuth bridge (highest ROI).
