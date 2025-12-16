# Research: Authentication Bridge

**Date**: 2025-11-15
**Feature**: Research and Implement Authentication Bridge
**Phase**: Phase 0 - Technical Research

---

## Research Questions

Based on [NEEDS CLARIFICATION] markers from spec.md and prior research gaps:

1. **Priority Order**: Which authentication method should be implemented first?
2. **IRIS Version Support**: What IRIS versions must be supported?
3. **Authentication Timeout**: What latency is acceptable for Kerberos multi-step handshake?
4. **Wallet Integration Scope**: Should Wallet be standalone or combined with OAuth?

---

## R1: Authentication Method Priority

**Question**: Which auth method should be implemented first - OAuth (simpler, 2 weeks) or Kerberos (enterprise standard, 3 weeks)?

**Decision**: **OAuth 2.0 First** (Phase 2), then Kerberos (Phase 3), then Wallet (Phase 4)

**Rationale**:
1. **Faster Time-to-Value**: OAuth implementation is simpler (2 weeks vs 3 weeks for Kerberos)
   - OAuth uses existing SCRAM-SHA-256 wire protocol (no new message types)
   - Kerberos requires AuthenticationGSS/GSSResponse protocol messages
   - OAuth provides immediate SSO benefits for Azure AD, Okta users

2. **Lower Infrastructure Barrier**: OAuth requires only IRIS configuration, Kerberos requires:
   - KDC (Active Directory or MIT Kerberos) deployment
   - Service principal creation and keytab generation
   - System Kerberos libraries (libkrb5-dev) on server

3. **Incremental Complexity**: OAuth validates IRIS auth bridge approach before tackling GSSAPI
   - Tests embedded Python → IRIS OAuth API integration
   - Validates dual-mode authentication pattern
   - Provides working reference for Kerberos implementation

4. **Market Demand**: Azure AD, Okta, Auth0 integrations more common than pure Kerberos
   - Cloud-first enterprises use OAuth/OIDC
   - On-premise Active Directory also supports OAuth via Azure AD Connect

**Alternatives Considered**:
- **Kerberos First**: Rejected - Higher implementation complexity without validating bridge approach
- **Parallel Development**: Rejected - Resource constraints and integration complexity
- **Wallet First**: Rejected - Wallet is credential storage, not authentication method

**Evidence**:
- ENTERPRISE_AUTH_BRIDGE_REVISED.md lines 320-348 documents OAuth as 2-week implementation
- KERBEROS_GSSAPI_OPTIONS.md lines 816-825 estimates Kerberos at 3-4 weeks
- InterSystems documentation shows OAuth 2.0 available in IRIS 2024.x+

---

## R2: IRIS Version Support Requirements

**Question**: Must support IRIS 2024.x (OAuth available) or only 2025.3.0+ (Wallet available)?

**Decision**: **Target IRIS 2024.x+ for OAuth/Kerberos, IRIS 2025.3.0+ required for Wallet**

**Rationale**:
1. **OAuth 2.0 Availability**: IRIS 2024.x includes `OAuth2.Server` and `OAuth2.Client` classes
   - Confirmed via ENTERPRISE_AUTH_BRIDGE_REVISED.md lines 61-91
   - Provides RFC 6749 compliance and PKCE support (RFC 7636)

2. **Kerberos Availability**: %Service_Bindings Kerberos support available in IRIS 2023.x+
   - Security levels 0-3 (authentication, packet integrity, encryption)
   - ENTERPRISE_AUTH_BRIDGE_REVISED.md lines 92-124

3. **Wallet Availability**: IRIS Wallet (`%IRIS.Wallet` API) introduced in IRIS 2025.3.0
   - IRISSECURITY database for encrypted secrets
   - ENTERPRISE_AUTH_BRIDGE_REVISED.md lines 140-165

4. **Deployment Reality**: Most enterprises run IRIS 2024.x in production
   - 2025.3.0 may not be widely adopted yet (latest preview release)
   - Wallet integration can be optional Phase 4 feature

**Implementation Strategy**:
- Phase 2 (OAuth) + Phase 3 (Kerberos): Minimum IRIS 2024.1 required
- Phase 4 (Wallet): IRIS 2025.3.0 required (version check at runtime)
- Graceful degradation: If Wallet API unavailable, use password table fallback

**Alternatives Considered**:
- **2025.3.0+ Only**: Rejected - Excludes most current production deployments
- **Backport Wallet to 2024.x**: Rejected - API not available, would require custom IRISSECURITY access

**Evidence**:
- ENTERPRISE_AUTH_BRIDGE_REVISED.md lines 140-165 documents Wallet 2025.3.0+ requirement
- InterSystems documentation confirms OAuth 2.0 in 2024.x releases
- Kerberos support predates 2024.x (available in 2023.x)

---

## R3: Kerberos Authentication Timeout

**Question**: Is 5-second timeout acceptable for Kerberos multi-step handshake (typically 2-3 round trips)?

**Decision**: **5 seconds is ACCEPTABLE** - Kerberos handshake completes in 400-500ms under normal conditions

**Rationale**:
1. **Empirical Benchmarks**: GSSAPI handshake measured at ~400ms for typical 2-3 round trips
   - KERBEROS_GSSAPI_OPTIONS.md:759 documents typical handshake timing
   - Includes network latency for KDC communication
   - 5-second timeout provides 10× safety margin

2. **Network Latency Budget**:
   - Round trip 1: Client → PGWire → KDC (AuthenticationGSS) ~100ms
   - Round trip 2: KDC → PGWire → Client (AuthenticationGSSContinue) ~100ms
   - Round trip 3: Client → PGWire (GSSResponse) ~100ms
   - Processing overhead: ~100ms
   - **Total**: ~400ms typical, ~1-2 seconds worst-case (network issues)

3. **PostgreSQL Compatibility**: PostgreSQL clients expect authentication within seconds
   - 5-second timeout matches PostgreSQL default `connect_timeout`
   - Longer timeouts degrade user experience (user assumes connection failed)

4. **Constitutional Compliance**: <5 second latency (FR-028) aligns with constitutional performance standards
   - Translation overhead <5ms (separate from network latency)
   - 1000 concurrent connections (not affected by per-connection handshake time)

**Implementation**:
- Set GSSAPI handshake timeout to 5 seconds (configurable via environment variable)
- Emit warning if handshake exceeds 2 seconds (indicates KDC availability issues)
- Fail fast at 5 seconds with clear error message (e.g., "Kerberos authentication timeout")

**Alternatives Considered**:
- **10-second timeout**: Rejected - Too long, degrades UX for failed authentications
- **2-second timeout**: Rejected - Too aggressive, may fail on slow networks
- **No timeout**: Rejected - Violates constitutional requirement

**Evidence**:
- KERBEROS_GSSAPI_OPTIONS.md:759 benchmarks show 400ms typical GSSAPI handshake
- PostgreSQL documentation: `connect_timeout` defaults to system-dependent (typically 2-10 seconds)
- KERBEROS_GSSAPI_SUMMARY.md:196 documents 2-3 GSSAPI round trips

---

## R4: Wallet Integration Scope

**Question**: Should Wallet be standalone feature or combined with OAuth for client credential storage?

**Decision**: **Dual-Purpose** - Wallet supports BOTH standalone credential retrieval AND OAuth client secret storage

**Rationale**:
1. **FR-009 Synergy**: "System MUST store PGWire OAuth client credentials securely (preferably in IRIS Wallet)"
   - OAuth implementation SHOULD use Wallet for client secret storage
   - Eliminates plain-text secrets in environment variables
   - Enables credential rotation without service restart (FR-023)

2. **FR-020 Independence**: "System MUST retrieve PostgreSQL user credentials from IRIS Wallet when configured"
   - Wallet also provides standalone user credential management
   - Replaces IRIS user table password lookups
   - Useful for enterprises with external identity providers (no IRIS users)

3. **Use Case Coverage**:
   - **OAuth + Wallet**: OAuth client secret stored in Wallet (Phase 2 + Phase 4 integration)
   - **Standalone Wallet**: User passwords stored in Wallet, retrieved at auth time (Phase 4)
   - **Hybrid**: OAuth for most users, Wallet for service accounts without OAuth tokens

4. **Implementation Complexity**: Minimal additional effort
   - Wallet API (`%IRIS.Wallet.GetSecret`) same for both use cases
   - Dual-purpose increases Wallet value without duplicate code

**Implementation Strategy**:
- **Phase 2 (OAuth)**: Initially store OAuth client secret in environment variable
- **Phase 4 (Wallet)**: Refactor OAuth to use Wallet for client secret storage
- **Phase 4 (Wallet)**: Add standalone credential retrieval for password authentication
- **Configuration**: `AUTH_WALLET_MODE=oauth|password|both` to control Wallet usage

**Alternatives Considered**:
- **OAuth-Only Wallet**: Rejected - Misses opportunity for standalone credential management
- **Password-Only Wallet**: Rejected - Doesn't address OAuth client secret security (FR-009)
- **Separate Wallet Implementations**: Rejected - Code duplication, inconsistent API usage

**Evidence**:
- FR-009 explicitly mentions "preferably in IRIS Wallet" for OAuth client credentials
- FR-020-FR-023 define standalone Wallet credential retrieval requirements
- ENTERPRISE_AUTH_BRIDGE_REVISED.md:279-305 shows both use cases

---

## R5: IRIS Authentication API Accessibility (Phase 1 Validation)

**Question**: Can embedded Python access IRIS OAuth, Kerberos, and Wallet APIs?

**Decision**: **YES** - All three APIs accessible via embedded Python `iris` module (to be validated in FR-001-FR-003)

**Rationale**:
1. **OAuth 2.0 APIs**: Available via `iris.cls()` calls
   - `iris.cls('OAuth2.Server')` for authorization server
   - `iris.cls('OAuth2.Client')` for token validation
   - ENTERPRISE_AUTH_BRIDGE_REVISED.md:61-91 documents class access

2. **Kerberos APIs**: Available via `iris.cls('%Service_Bindings')`
   - Security level configuration for Kerberos authentication
   - Principal validation and ticket verification
   - ENTERPRISE_AUTH_BRIDGE_REVISED.md:92-124

3. **Wallet APIs**: Available via `iris.cls('%IRIS.Wallet')` (IRIS 2025.3.0+)
   - `GetSecret(key)` and `SetSecret(key, value)` methods
   - IRISSECURITY database access
   - ENTERPRISE_AUTH_BRIDGE_REVISED.md:140-165

4. **Embedded Python Pattern**: Official InterSystems template proves `iris.cls()` access works
   - intersystems-community/iris-embedded-python-template uses `iris.cls('%SYSTEM.License')`
   - No authentication required when run via `irispython` command
   - CallIn service already enabled (constitutional prerequisite)

**Validation Tasks** (Phase 1 - FR-001-FR-003):
```python
# Test 1: OAuth API access
import iris
oauth_server = iris.cls('OAuth2.Server')
assert oauth_server is not None, "OAuth2.Server class not accessible"

# Test 2: Kerberos API access
service_bindings = iris.cls('%Service_Bindings')
assert service_bindings is not None, "%Service_Bindings class not accessible"

# Test 3: Wallet API access (conditional on IRIS 2025.3.0+)
try:
    wallet = iris.cls('%IRIS.Wallet')
    assert wallet is not None, "Wallet class not accessible"
except Exception as e:
    # Acceptable if IRIS < 2025.3.0
    print(f"Wallet unavailable (expected on IRIS < 2025.3.0): {e}")
```

**Alternatives Considered**:
- **External DBAPI Connections**: Rejected - Requires TCP connections, auth overhead, not embedded pattern
- **REST API Calls**: Rejected - Unnecessary HTTP overhead when embedded Python has direct class access
- **Manual IRISSECURITY Queries**: Rejected - Bypasses Wallet API, loses encryption/audit trail

**Evidence**:
- Constitutional requirement IV: "All IRIS interactions MUST use embedded Python approach"
- intersystems-community/iris-embedded-python-template demonstrates `iris.cls()` pattern
- ENTERPRISE_AUTH_BRIDGE_REVISED.md provides class names and method signatures

---

## R6: PostgreSQL GSSAPI Protocol Implementation

**Question**: How to implement PostgreSQL GSSAPI authentication protocol with python-gssapi?

**Decision**: Use **python-gssapi>=1.8.0** with asyncio.to_thread() for non-blocking GSSAPI calls

**Rationale**:
1. **Battle-Tested Library**: python-gssapi used by requests-gssapi, httpx-gssapi
   - Pure Python with C bindings to MIT Kerberos or Heimdal
   - Cross-platform (Linux, macOS, Windows)
   - KERBEROS_GSSAPI_OPTIONS.md:148-162 recommends python-gssapi

2. **PostgreSQL Wire Protocol Messages**:
   - `AuthenticationGSS` (type=7): Server requests GSSAPI authentication
   - `GSSResponse` ('p'): Client sends GSSAPI token
   - `AuthenticationGSSContinue` (type=8): Server sends continuation token
   - Multi-step exchange until `SecurityContext.complete == True`
   - KERBEROS_GSSAPI_OPTIONS.md:62-142 documents protocol flow

3. **Asyncio Integration**: GSSAPI calls are blocking (C library)
   - Use `asyncio.to_thread()` to execute GSSAPI operations in thread pool
   - Prevents event loop blocking during ticket validation
   - Constitutional requirement IV: "Async threading with `asyncio.to_thread()`"

4. **Keytab Management**: Service principal credentials loaded from keytab file
   - `KRB5_KTNAME` environment variable points to keytab location
   - Docker secret mount for production deployment (chmod 600)
   - KERBEROS_GSSAPI_OPTIONS.md:330-344 documents keytab setup

**Implementation Pattern**:
```python
import gssapi
import asyncio

class GSSAPIAuthenticator:
    def __init__(self, service_name='postgres', hostname=None):
        self.service_principal = f"{service_name}/{hostname}"
        self.server_creds = None

    async def initialize(self):
        """Load keytab credentials in thread pool"""
        def _load_creds():
            name = gssapi.Name(self.service_principal, gssapi.NameType.hostbased_service)
            return gssapi.Credentials(name, usage='accept')

        self.server_creds = await asyncio.to_thread(_load_creds)

    async def handle_gssapi_handshake(self, connection_id: str):
        """Multi-step GSSAPI token exchange"""
        def _create_context():
            return gssapi.SecurityContext(creds=self.server_creds, usage='accept')

        ctx = await asyncio.to_thread(_create_context)

        # Multi-step exchange loop
        while not ctx.complete:
            client_token = await self.receive_gss_response()
            server_token = await asyncio.to_thread(ctx.step, client_token)

            if not ctx.complete:
                await self.send_authentication_gss_continue(server_token)

        # Extract authenticated username
        username = str(ctx.peer_name)  # e.g., 'alice@EXAMPLE.COM'
        return username
```

**Dependencies**:
```txt
python-gssapi>=1.8.0
```

**System Requirements**:
```bash
# Linux (Ubuntu/Debian)
apt-get install libkrb5-dev krb5-user

# macOS (Homebrew)
brew install krb5

# RHEL/CentOS
yum install krb5-devel krb5-workstation
```

**Alternatives Considered**:
- **pykerberos**: Rejected - Less maintained, no asyncio examples
- **Kerberos password validation**: Rejected - Not true SSO, defeats primary benefit (KERBEROS_GSSAPI_OPTIONS.md:377-414)
- **Proxy through Apache mod_auth_kerb**: Rejected - PostgreSQL wire protocol is TCP, not HTTP (KERBEROS_GSSAPI_OPTIONS.md:418-431)

**Evidence**:
- KERBEROS_GSSAPI_OPTIONS.md:148-318 provides complete python-gssapi implementation
- KERBEROS_GSSAPI_SUMMARY.md:110-141 shows simplified usage example
- Constitutional requirement IV: asyncio.to_thread() for blocking calls

---

## R7: Kerberos Principal to IRIS Username Mapping

**Question**: How to map Kerberos principals (e.g., `alice@EXAMPLE.COM`) to IRIS usernames?

**Decision**: **Strip realm by default** (`alice@EXAMPLE.COM` → `ALICE`), validate IRIS user exists

**Rationale**:
1. **IRIS User Table Structure**: IRIS Security.Users table uses simple usernames (no realm)
   - Users created as `ALICE`, `BOB`, etc. (uppercase convention)
   - No built-in realm or domain fields in IRIS user records

2. **Default Mapping**: Strip realm suffix and uppercase username
   - `alice@EXAMPLE.COM` → `ALICE`
   - `bob@CORP.EXAMPLE.COM` → `BOB`
   - Simple, predictable mapping for most deployments

3. **Validation Requirement** (FR-017): Query INFORMATION_SCHEMA.USERS before session creation
   ```sql
   SELECT COUNT(*) FROM INFORMATION_SCHEMA.USERS WHERE USERNAME = :username
   ```
   - Fail authentication if mapped username doesn't exist in IRIS
   - Prevents unauthorized access via Kerberos ticket alone

4. **Future Enhancement**: PostgreSQL-style pg_ident.conf mapping (not Phase 1)
   - Map `alice@EXAMPLE.COM` → `alice_admin` (custom mapping rules)
   - Enable service principals: `service/host@REALM` → `service_account`
   - Deferred to future enhancement (not blocking MVP)

**Implementation**:
```python
async def map_kerberos_principal_to_iris_user(self, principal: str) -> str:
    """
    Map Kerberos principal to IRIS username.

    Args:
        principal: Kerberos principal (e.g., 'alice@EXAMPLE.COM')

    Returns:
        IRIS username (e.g., 'ALICE')

    Raises:
        AuthenticationError: If mapped user doesn't exist in IRIS
    """
    # Strip realm (everything after @)
    username = principal.split('@')[0]

    # Uppercase per IRIS convention
    username = username.upper()

    # Validate user exists in IRIS
    query = """
        SELECT COUNT(*) FROM INFORMATION_SCHEMA.USERS
        WHERE USERNAME = :username
    """
    result = await self.iris_executor.execute_query(query, {'username': username})

    if result[0][0] == 0:
        raise AuthenticationError(f"Kerberos principal {principal} maps to non-existent IRIS user {username}")

    return username
```

**Edge Cases**:
- **Case Sensitivity**: Kerberos principals are case-sensitive, IRIS usernames typically uppercase
- **Service Principals**: `postgres/hostname@REALM` → `POSTGRES` (may not be valid IRIS user)
- **Multi-Realm Deployments**: Same username in different realms → Need realm validation

**Alternatives Considered**:
- **Preserve realm in username**: Rejected - IRIS doesn't support `alice@EXAMPLE.COM` as username
- **Create IRIS users on-the-fly**: Rejected - Security risk, requires special privileges
- **External mapping database**: Rejected - Over-engineered for MVP

**Evidence**:
- FR-016: "System MUST map Kerberos principals to IRIS usernames"
- FR-017: "System MUST validate mapped IRIS user exists before creating session"
- KERBEROS_GSSAPI_OPTIONS.md:263-277 shows mapping example

---

## R8: OAuth Token Exchange Flow

**Question**: How to exchange username/password for IRIS OAuth 2.0 access token?

**Decision**: Use **IRIS OAuth 2.0 token endpoint** with password grant type (Resource Owner Password Credentials flow)

**Rationale**:
1. **OAuth 2.0 Grant Types**: IRIS supports authorization code, client credentials, and implicit flows
   - **Password grant** most suitable for username/password exchange
   - RFC 6749 Section 4.3: Resource Owner Password Credentials Grant
   - Client (PGWire) exchanges user credentials for access token

2. **IRIS OAuth Endpoint**: `/oauth2/token` endpoint on IRIS OAuth server
   - Request: POST with `grant_type=password&username=...&password=...&client_id=...&client_secret=...`
   - Response: `{"access_token": "...", "refresh_token": "...", "expires_in": 3600}`
   - ENTERPRISE_AUTH_BRIDGE_REVISED.md:254-275 shows token exchange pattern

3. **PGWire OAuth Client Registration**: Register PGWire as OAuth client in IRIS
   - Client ID: `pgwire-server` (configured in IRIS OAuth server)
   - Client Secret: Store in IRIS Wallet (Phase 4) or environment variable (Phase 2)
   - Scopes: `user_info` (minimal scope for authentication)

4. **Token Validation** (FR-008): Validate tokens against IRIS OAuth server (NOT local verification)
   - Token introspection endpoint: `/oauth2/introspect`
   - Ensures token hasn't been revoked
   - Validates expiry and scopes

**Implementation**:
```python
class IriSOAuthBridge:
    async def exchange_password_for_token(self, username: str, password: str) -> dict:
        """
        Exchange username/password for IRIS OAuth 2.0 access token.

        Returns:
            dict: {'access_token': '...', 'refresh_token': '...', 'expires_in': 3600}
        """
        # Get OAuth client credentials (from Wallet in Phase 4, env var in Phase 2)
        client_id = self.config.oauth_client_id  # e.g., 'pgwire-server'
        client_secret = await self.get_client_secret()

        # Call IRIS OAuth token endpoint
        def _request_token():
            oauth_client = iris.cls('OAuth2.Client')
            token_response = oauth_client.RequestToken(
                grant_type='password',
                username=username,
                password=password,
                client_id=client_id,
                client_secret=client_secret,
                scope='user_info'
            )
            return token_response

        token_response = await asyncio.to_thread(_request_token)

        if not token_response.get('access_token'):
            raise AuthenticationError("OAuth token exchange failed")

        return token_response

    async def validate_token(self, access_token: str) -> bool:
        """Validate token against IRIS OAuth server (FR-008)"""
        def _introspect_token():
            oauth_client = iris.cls('OAuth2.Client')
            return oauth_client.IntrospectToken(access_token)

        introspection = await asyncio.to_thread(_introspect_token)
        return introspection.get('active', False)
```

**Token Lifecycle**:
1. **Issuance**: Username/password → IRIS OAuth server → Access token (FR-007)
2. **Validation**: Access token → IRIS OAuth server introspection → Active/Inactive (FR-008)
3. **Expiry**: Access token expires after configured TTL (e.g., 60 minutes)
4. **Refresh**: Use refresh token to obtain new access token (FR-010)
5. **Revocation**: IRIS admin can revoke tokens via OAuth server

**Alternatives Considered**:
- **Authorization Code Flow**: Rejected - Requires browser redirect, not suitable for CLI clients
- **Client Credentials Flow**: Rejected - No user context, can't authenticate individual users
- **JWT Self-Validation**: Rejected - Doesn't detect revoked tokens (violates FR-008)

**Evidence**:
- FR-007: "System MUST exchange username/password for IRIS OAuth 2.0 access token"
- FR-008: "System MUST validate OAuth tokens against IRIS OAuth 2.0 server (not local verification)"
- ENTERPRISE_AUTH_BRIDGE_REVISED.md:254-275 shows password grant pattern
- RFC 6749 Section 4.3 defines Resource Owner Password Credentials Grant

---

## R9: Dual-Mode Authentication Routing

**Question**: How to support multiple authentication methods simultaneously (FR-024)?

**Decision**: **Configuration-based auth method selector** with fallback chain

**Rationale**:
1. **Configuration Flags**: Environment variables control which auth methods are enabled
   ```bash
   PGWIRE_AUTH_METHODS=oauth,kerberos,wallet,password  # Comma-separated list
   PGWIRE_AUTH_FALLBACK=password  # Default fallback
   ```

2. **Authentication Flow**:
   - Client connects → PGWire reads startup parameters
   - If `gssencmode` or `gssdelegation` present → Attempt Kerberos (if enabled)
   - Else → Attempt OAuth token exchange (if enabled)
   - If OAuth fails → Attempt Wallet credential retrieval (if enabled)
   - If all fail → Fall back to SCRAM-SHA-256 password authentication (always enabled)

3. **Backward Compatibility** (FR-025): Password authentication ALWAYS enabled
   - Existing clients expect SCRAM-SHA-256 or password authentication
   - OAuth/Kerberos/Wallet are ADD-ONS, not replacements
   - Clients don't break if OAuth/Kerberos unavailable

4. **Client Detection**:
   - Kerberos clients: Include `gssencmode=disable` in connection string (standard PostgreSQL parameter)
   - OAuth clients: Standard username/password connection, but PGWire attempts token exchange
   - Wallet clients: Username-only connection (password retrieved from Wallet)

**Implementation**:
```python
class AuthenticationSelector:
    def __init__(self, config):
        self.enabled_methods = config.auth_methods  # ['oauth', 'kerberos', 'wallet', 'password']
        self.fallback_method = config.auth_fallback  # 'password'

    async def authenticate(self, startup_params: dict, connection_id: str) -> str:
        """
        Authenticate client using enabled auth methods.

        Returns:
            IRIS username for authenticated session

        Raises:
            AuthenticationError: If all enabled methods fail
        """
        # Detect Kerberos client (gssencmode parameter)
        if 'gssencmode' in startup_params and 'kerberos' in self.enabled_methods:
            try:
                return await self.authenticate_kerberos(connection_id)
            except KerberosAuthenticationError as e:
                logger.warning(f"Kerberos authentication failed: {e}")
                # Fall through to next method

        # Attempt OAuth token exchange (if username/password provided)
        if 'oauth' in self.enabled_methods:
            username = startup_params.get('user')
            password = await self.receive_password_from_scram()  # SCRAM handshake

            try:
                token = await self.oauth_bridge.exchange_password_for_token(username, password)
                return username  # OAuth succeeded
            except OAuthAuthenticationError as e:
                logger.warning(f"OAuth authentication failed: {e}")
                # Fall through to next method

        # Attempt Wallet credential retrieval
        if 'wallet' in self.enabled_methods:
            username = startup_params.get('user')
            try:
                wallet_password = await self.wallet_credentials.get_password(username)
                # Validate wallet password against IRIS user table
                if await self.validate_iris_password(username, wallet_password):
                    return username
            except WalletAuthenticationError as e:
                logger.warning(f"Wallet authentication failed: {e}")
                # Fall through to fallback

        # Fallback to SCRAM-SHA-256 password authentication (always enabled)
        return await self.authenticate_scram(startup_params)
```

**Error Handling**:
- Each auth method failure logged for audit trail (FR-026)
- Clear error messages to client (FR-027): "OAuth authentication failed, falling back to password"
- 5-second timeout per method (FR-028)

**Alternatives Considered**:
- **Single Auth Method**: Rejected - Doesn't support gradual migration (Scenario 5)
- **Client-Selected Method**: Rejected - Requires protocol changes, breaks compatibility
- **Hard Failure**: Rejected - No fallback means outages if OAuth/Kerberos server down

**Evidence**:
- FR-024: "System MUST allow multiple authentication methods to be configured simultaneously"
- FR-025: "System MUST not break existing 8 PostgreSQL client drivers"
- Scenario 5: "Dual-mode authentication supports gradual migration"

---

## Summary of Research Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| **Priority Order** | OAuth → Kerberos → Wallet | Fastest time-to-value, incremental complexity |
| **IRIS Version** | 2024.x+ (OAuth/Kerberos), 2025.3.0+ (Wallet) | Maximizes deployment compatibility |
| **Timeout** | 5 seconds acceptable | 10× safety margin over 400ms typical handshake |
| **Wallet Scope** | Dual-purpose (OAuth secrets + user passwords) | Maximizes ROI, addresses FR-009 and FR-020 |
| **API Access** | Yes via `iris.cls()` (to be validated) | Constitutional embedded Python pattern |
| **GSSAPI Library** | python-gssapi>=1.8.0 | Battle-tested, asyncio-compatible |
| **Principal Mapping** | Strip realm + uppercase + validate | Simple, predictable, secure |
| **OAuth Flow** | Password grant with token introspection | RFC 6749 compliant, server-side validation |
| **Dual-Mode** | Config-based selector with fallback chain | Backward compatible, gradual migration |

---

## Next Steps (Phase 1)

With all research questions resolved, proceed to Phase 1:

1. **Validate IRIS API Access** (FR-001-FR-003):
   - Write contract tests for OAuth, Kerberos, Wallet APIs
   - Execute tests against isolated IRIS container (iris-devtester)
   - Document any API access issues or version incompatibilities

2. **Generate Data Model** (data-model.md):
   - Extract entities from spec.md: OAuth Token, Kerberos Principal, Wallet Secret, User Session, Auth Config
   - Define state transitions for authentication flows
   - Document validation rules from functional requirements

3. **Generate API Contracts** (contracts/):
   - OAuth bridge contract: `authenticate_with_oauth(username, password) -> token`
   - GSSAPI auth contract: `authenticate_with_kerberos(gssapi_token) -> username`
   - Wallet credentials contract: `get_password_from_wallet(username) -> password`

4. **Write Quickstart Guide** (quickstart.md):
   - OAuth setup: Register PGWire client in IRIS, configure credentials
   - Kerberos setup: Generate keytab, deploy to Docker container
   - E2E validation: Test psql connection with OAuth/Kerberos

---

**Research Complete**: All [NEEDS CLARIFICATION] markers resolved. Ready for Phase 1 design.
