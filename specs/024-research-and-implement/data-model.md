# Data Model: Authentication Bridge

**Feature**: Research and Implement Authentication Bridge
**Phase**: Phase 1 - Design & Contracts
**Date**: 2025-11-15

---

## Entity Overview

This authentication bridge introduces 5 key entities to manage enterprise authentication:

1. **IRIS OAuth Token**: Represents OAuth 2.0 authenticated session
2. **Kerberos Principal**: Represents Kerberos authenticated identity
3. **IRIS Wallet Secret**: Represents encrypted credentials
4. **User Session**: Represents authenticated PostgreSQL client connection
5. **Authentication Method Configuration**: Determines auth flow selection

---

## Entity 1: IRIS OAuth Token

**Purpose**: Represents OAuth 2.0 access token issued by IRIS OAuth server for authenticated sessions.

**Fields**:
| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `access_token` | str | NOT NULL, 256 chars | OAuth 2.0 access token (JWT or opaque) |
| `refresh_token` | str | NULLABLE, 256 chars | OAuth refresh token for token renewal |
| `token_type` | str | NOT NULL, enum('Bearer') | Token type per RFC 6749 |
| `expires_in` | int | NOT NULL, > 0 | Token TTL in seconds (e.g., 3600) |
| `issued_at` | datetime | NOT NULL | Token issuance timestamp (UTC) |
| `expires_at` | datetime | NOT NULL | Calculated: issued_at + expires_in |
| `username` | str | NOT NULL, 64 chars | IRIS username associated with token |
| `scopes` | list[str] | DEFAULT ['user_info'] | OAuth scopes granted to token |

**Validation Rules** (from FR-007, FR-008, FR-010):
- `access_token` MUST be validated against IRIS OAuth server (not local verification)
- `expires_at` MUST be checked before each query execution
- If expired, MUST attempt refresh using `refresh_token` before failing
- If refresh fails, MUST re-authenticate (new token exchange)

**Relationships**:
- **1:1** with **User Session**: One OAuth token per authenticated session
- **N:1** with IRIS OAuth Server: Tokens issued by centralized OAuth server

**State Transitions**:
```
ISSUED → ACTIVE → EXPIRED → REFRESHED → ACTIVE
                     ↓
                 REVOKED (terminal state)
```

**Source**: spec.md lines 160-161
**Reference**: research.md R8 (OAuth Token Exchange Flow)

---

## Entity 2: Kerberos Principal

**Purpose**: Represents authenticated user identity extracted from Kerberos GSSAPI token.

**Fields**:
| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `principal` | str | NOT NULL, 255 chars | Full Kerberos principal (e.g., alice@EXAMPLE.COM) |
| `username` | str | NOT NULL, 64 chars | Username component (e.g., alice) |
| `realm` | str | NOT NULL, 255 chars | Kerberos realm (e.g., EXAMPLE.COM) |
| `mapped_iris_user` | str | NOT NULL, 64 chars | IRIS username (e.g., ALICE) |
| `authenticated_at` | datetime | NOT NULL | GSSAPI authentication timestamp (UTC) |
| `ticket_expiry` | datetime | NULLABLE | Kerberos ticket expiry (if available) |

**Validation Rules** (from FR-015, FR-016, FR-017):
- `principal` extracted from `SecurityContext.peer_name` after GSSAPI handshake
- `mapped_iris_user` derived via principal mapping (strip realm + uppercase)
- `mapped_iris_user` MUST exist in IRIS Security.Users table (query INFORMATION_SCHEMA.USERS)
- If mapping validation fails, authentication MUST fail with error (no user creation)

**Relationships**:
- **1:1** with **User Session**: One Kerberos principal per authenticated session
- **N:1** with Kerberos KDC: Principals authenticated by external KDC (Active Directory or MIT Kerberos)

**State Transitions**:
```
RECEIVED (GSSAPI token) → VALIDATED (principal extracted) → MAPPED (IRIS user) → ACTIVE
                                  ↓
                              INVALID (KDC rejection, expired ticket)
```

**Mapping Algorithm** (from research.md R7):
```python
def map_principal_to_iris_user(principal: str) -> str:
    username = principal.split('@')[0]  # Strip realm
    username = username.upper()         # Uppercase per IRIS convention
    # Validate existence in IRIS (FR-017)
    if not iris_user_exists(username):
        raise AuthenticationError(f"Mapped user {username} doesn't exist")
    return username
```

**Source**: spec.md lines 162-163
**Reference**: research.md R7 (Kerberos Principal to IRIS Username Mapping)

---

## Entity 3: IRIS Wallet Secret

**Purpose**: Represents encrypted credential stored in IRIS Wallet (IRISSECURITY database).

**Fields**:
| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `key` | str | NOT NULL, 255 chars | Wallet secret key (e.g., pgwire-user-alice) |
| `value` | str | NOT NULL, ENCRYPTED | Encrypted secret value (password or OAuth client secret) |
| `secret_type` | str | NOT NULL, enum('password', 'oauth_client_secret') | Type of secret stored |
| `created_at` | datetime | NOT NULL | Secret creation timestamp (UTC) |
| `updated_at` | datetime | NOT NULL | Last rotation timestamp (UTC) |
| `accessed_at` | datetime | NULLABLE | Last access timestamp (for audit) |

**Validation Rules** (from FR-020, FR-021, FR-022, FR-023):
- `key` format: `pgwire-user-{username}` for user passwords, `pgwire-oauth-client` for OAuth secrets
- `value` encrypted at rest in IRISSECURITY database (IRIS Wallet handles encryption)
- Access audited via `accessed_at` update + IRIS Wallet logs (FR-022)
- Rotation supported without service restart (FR-023) - new secret retrieved on next auth attempt

**Relationships**:
- **N:1** with IRIS Wallet API: Multiple secrets managed by centralized Wallet
- **1:1** with User (for password secrets): One Wallet entry per PostgreSQL user
- **1:1** with OAuth Client (for OAuth secrets): PGWire client ID → client secret mapping

**State Transitions**:
```
CREATED → ACTIVE → ROTATED (updated_at changes) → ACTIVE
             ↓
         DELETED (terminal state)
```

**API Usage** (from research.md R4):
```python
# Store secret (admin operation)
wallet = iris.cls('%IRIS.Wallet')
wallet.SetSecret('pgwire-user-alice', 'encrypted_password_here')

# Retrieve secret (auth-time operation)
password = wallet.GetSecret('pgwire-user-alice')
if not password:
    raise WalletSecretNotFound(f"No Wallet entry for user alice")
```

**Dual Purpose** (from research.md R4):
- **User Passwords**: Store PostgreSQL user credentials (standalone Wallet feature)
- **OAuth Client Secrets**: Store PGWire OAuth client credentials (FR-009 requirement)

**Source**: spec.md lines 164-165
**Reference**: research.md R4 (Wallet Integration Scope)

---

## Entity 4: User Session

**Purpose**: Represents authenticated PostgreSQL client connection with auth method tracking.

**Fields**:
| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `session_id` | str | NOT NULL, PRIMARY KEY | Unique session identifier (UUID) |
| `connection_id` | str | NOT NULL | PostgreSQL wire protocol connection ID |
| `iris_username` | str | NOT NULL, 64 chars | Authenticated IRIS username |
| `auth_method` | str | NOT NULL, enum('password', 'oauth', 'kerberos', 'wallet') | Authentication method used |
| `oauth_token` | OAuth Token | NULLABLE | OAuth token if auth_method=oauth |
| `kerberos_principal` | Kerberos Principal | NULLABLE | Kerberos principal if auth_method=kerberos |
| `wallet_key` | str | NULLABLE | Wallet key if auth_method=wallet |
| `created_at` | datetime | NOT NULL | Session start timestamp (UTC) |
| `last_activity_at` | datetime | NOT NULL | Last query execution timestamp |
| `client_info` | dict | NULLABLE | PostgreSQL client metadata (application_name, etc.) |

**Validation Rules** (from FR-024, FR-025, FR-026):
- `auth_method` determined by authentication flow (OAuth → Kerberos → Wallet → password fallback)
- Exactly ONE of `oauth_token`, `kerberos_principal`, or `wallet_key` must be non-null (matches `auth_method`)
- `last_activity_at` updated on each query execution
- Session logged for audit trail (FR-026): session_id, iris_username, auth_method, created_at

**Relationships**:
- **1:1** with PostgreSQL Connection: One session per active client connection
- **N:1** with IRIS User: Multiple sessions per IRIS user (concurrent connections)
- **1:1** with OAuth Token (if auth_method=oauth): Session holds active OAuth token
- **1:1** with Kerberos Principal (if auth_method=kerberos): Session holds authenticated principal

**State Transitions**:
```
AUTHENTICATING → ACTIVE → IDLE (no queries) → DISCONNECTED
                     ↓
                 ERROR (auth failure, query error) → DISCONNECTED
```

**Lifecycle**:
1. **Connection Establishment**: Client connects, PGWire creates session with `auth_method=None`
2. **Authentication**: Auth selector runs, sets `auth_method` and associated token/principal
3. **Query Execution**: Session remains ACTIVE, `last_activity_at` updated per query
4. **Disconnection**: Client closes connection, session transitions to DISCONNECTED

**Source**: spec.md lines 166-167
**Reference**: research.md R9 (Dual-Mode Authentication Routing)

---

## Entity 5: Authentication Method Configuration

**Purpose**: Determines which authentication methods are enabled and fallback behavior.

**Fields**:
| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| `enabled_methods` | list[str] | NOT NULL, DEFAULT ['password'] | Enabled auth methods (e.g., ['oauth', 'kerberos', 'password']) |
| `fallback_method` | str | NOT NULL, DEFAULT 'password' | Fallback auth method (always 'password' for compatibility) |
| `oauth_config` | dict | NULLABLE | OAuth configuration (client_id, token_endpoint) |
| `kerberos_config` | dict | NULLABLE | Kerberos configuration (service_name, keytab_path) |
| `wallet_config` | dict | NULLABLE | Wallet configuration (wallet_mode: 'oauth', 'password', 'both') |
| `auth_timeout_seconds` | int | NOT NULL, DEFAULT 5 | Per-method authentication timeout (FR-028) |

**Validation Rules** (from FR-024, FR-025, FR-028):
- `fallback_method` MUST be 'password' (backward compatibility - FR-025)
- If 'oauth' in `enabled_methods`, `oauth_config` MUST be present
- If 'kerberos' in `enabled_methods`, `kerberos_config` MUST be present
- `auth_timeout_seconds` MUST be <= 5 seconds (constitutional requirement)

**Configuration Source**:
Environment variables:
```bash
PGWIRE_AUTH_METHODS=oauth,kerberos,wallet,password  # Comma-separated list
PGWIRE_AUTH_FALLBACK=password                        # Always password
PGWIRE_AUTH_TIMEOUT=5                                # Seconds per method
PGWIRE_OAUTH_CLIENT_ID=pgwire-server
PGWIRE_OAUTH_TOKEN_ENDPOINT=http://iris-host:52773/oauth2/token
PGWIRE_KERBEROS_SERVICE_NAME=postgres
PGWIRE_KERBEROS_KEYTAB=/etc/krb5.keytab
PGWIRE_WALLET_MODE=both                              # oauth | password | both
```

**Relationships**:
- **1:N** with User Sessions: Configuration applies to all sessions
- **Singleton**: One configuration instance per PGWire server

**State Transitions**:
```
LOADING (startup) → ACTIVE (serving connections) → RELOADING (config change) → ACTIVE
```

**Auth Method Selection Logic** (from research.md R9):
```python
async def select_auth_method(config: AuthConfig, startup_params: dict) -> str:
    # Detect Kerberos client (gssencmode parameter)
    if 'gssencmode' in startup_params and 'kerberos' in config.enabled_methods:
        return 'kerberos'

    # Attempt OAuth token exchange (if enabled)
    if 'oauth' in config.enabled_methods:
        return 'oauth'

    # Attempt Wallet credential retrieval (if enabled)
    if 'wallet' in config.enabled_methods:
        return 'wallet'

    # Fallback to password authentication (always enabled)
    return config.fallback_method  # 'password'
```

**Source**: spec.md lines 168-169
**Reference**: research.md R9 (Dual-Mode Authentication Routing)

---

## Entity Relationships Diagram

```
┌──────────────────────────┐
│ Authentication Method    │
│ Configuration            │
│ (Singleton)              │
└────────────┬─────────────┘
             │ 1:N
             ▼
┌──────────────────────────┐       1:1        ┌──────────────────────────┐
│ User Session             │◄─────────────────│ IRIS OAuth Token         │
│                          │                  │ (if auth_method=oauth)   │
│ - session_id             │       1:1        └──────────────────────────┘
│ - auth_method            │◄─────────────────┐
│ - iris_username          │                  │ ┌──────────────────────────┐
│ - created_at             │                  └─│ Kerberos Principal       │
└────────────┬─────────────┘                    │ (if auth_method=kerberos)│
             │ N:1                               └──────────────────────────┘
             ▼
┌──────────────────────────┐
│ IRIS User                │
│ (Security.Users table)   │
│                          │
│ - USERNAME               │
│ - Roles                  │
└──────────────────────────┘

┌──────────────────────────┐       N:1        ┌──────────────────────────┐
│ IRIS Wallet Secret       │──────────────────│ IRIS Wallet API          │
│                          │                  │ (%IRIS.Wallet)           │
│ - key (pgwire-user-*)    │                  │                          │
│ - value (encrypted)      │                  │ - GetSecret(key)         │
│ - secret_type            │                  │ - SetSecret(key, value)  │
└──────────────────────────┘                  └──────────────────────────┘
```

---

## State Transition: Authentication Flow

```
PostgreSQL Client Connection
            ↓
[1] StartupMessage Received
            ↓
[2] AuthenticationSelector.authenticate()
            ↓
    ┌───────────────────────────────┐
    │ Detect Auth Method            │
    │ (from startup_params)         │
    └──┬─────────────┬──────────────┬┘
       │             │              │
   [Kerberos]   [OAuth/Wallet]  [Fallback]
       │             │              │
       ▼             ▼              ▼
[3a] GSSAPI    [3b] OAuth      [3c] SCRAM-SHA-256
  Handshake      Token           Password
  (multi-step)   Exchange        Authentication
       │             │              │
       ▼             ▼              ▼
[4a] Extract  [4b] Validate   [4c] Validate
  Principal     OAuth Token     Password
  from Context  vs IRIS OAuth   vs IRIS User Table
       │             │              │
       ▼             ▼              ▼
[5a] Map       [5b] Extract   [5c] Username
  Principal      Username       from SCRAM
  to IRIS User   from Token
       │             │              │
       └─────────────┴──────────────┘
                     ▼
            [6] Validate IRIS User Exists
                (INFORMATION_SCHEMA.USERS)
                     │
                     ▼
            [7] Create User Session
                (session_id, auth_method, iris_username)
                     │
                     ▼
            [8] Send AuthenticationOk
                     │
                     ▼
            [9] Send ParameterStatus, BackendKeyData
                     │
                     ▼
            [10] Send ReadyForQuery ('I' = idle, ready for queries)
                     │
                     ▼
            ACTIVE SESSION (query execution loop)
```

**Error Paths**:
- Step 3: Auth method times out (>5 seconds) → Fall back to next method
- Step 4: Token/principal validation fails → Fall back to next method
- Step 6: IRIS user doesn't exist → Send ErrorResponse, close connection (no fallback)
- Step 10: Session creation fails → Send ErrorResponse, close connection

---

## Validation Rules Summary

**From Functional Requirements**:

| Requirement | Entity | Validation Rule |
|-------------|--------|-----------------|
| FR-007 | OAuth Token | Exchange username/password for token via IRIS OAuth server |
| FR-008 | OAuth Token | Validate token against IRIS OAuth server (not local verification) |
| FR-010 | OAuth Token | Handle expiry transparently (refresh token flow) |
| FR-014 | Kerberos Principal | Validate ticket via IRIS %Service_Bindings |
| FR-015 | Kerberos Principal | Extract username from principal (SecurityContext.peer_name) |
| FR-016 | Kerberos Principal | Map principal to IRIS username (strip realm + uppercase) |
| FR-017 | Kerberos Principal | Validate mapped IRIS user exists (INFORMATION_SCHEMA.USERS) |
| FR-020 | Wallet Secret | Retrieve credentials from IRIS Wallet when configured |
| FR-021 | Wallet Secret | Handle Wallet API errors gracefully (fallback to password table) |
| FR-022 | Wallet Secret | Audit all credential retrievals (accessed_at + IRIS logs) |
| FR-023 | Wallet Secret | Support credential rotation without service restart |
| FR-024 | Auth Config | Allow multiple auth methods configured simultaneously |
| FR-025 | User Session | Must not break existing 8 client drivers (password fallback) |
| FR-026 | User Session | Log all auth attempts (success and failure) for audit trail |
| FR-027 | User Session | Surface auth errors to clients with appropriate error codes |
| FR-028 | Auth Config | Complete authentication within 5 seconds under normal conditions |

---

## Data Persistence

**In-Memory (PGWire Server)**:
- User Session (ephemeral, exists only during connection lifetime)
- OAuth Token (cached during session, discarded on disconnect)
- Kerberos Principal (ephemeral, used only for initial authentication)
- Authentication Method Configuration (loaded at startup, reloaded on config change)

**IRIS Database**:
- IRIS Wallet Secret (persistent in IRISSECURITY database, encrypted at rest)
- IRIS User (persistent in Security.Users table, queried for validation)
- OAuth Token Metadata (persistent in IRIS OAuth server storage, managed by IRIS)

**External Systems**:
- Kerberos KDC (Active Directory or MIT Kerberos) - ticket validation
- IRIS OAuth Server (/oauth2/token, /oauth2/introspect endpoints) - token lifecycle

---

## Performance Considerations

**From research.md**:
- OAuth token exchange: ~100-200ms (HTTP call to IRIS OAuth server)
- Kerberos GSSAPI handshake: ~400ms (2-3 round trips to KDC)
- Wallet secret retrieval: ~50ms (IRIS embedded Python call to %IRIS.Wallet)
- IRIS user validation: ~20ms (INFORMATION_SCHEMA.USERS query)

**Optimization Strategies**:
1. **Token Caching**: Cache OAuth tokens in User Session (avoid re-validation per query)
2. **Connection Pooling**: Reuse authenticated sessions (avoid re-authentication per connection)
3. **Async Threading**: Use `asyncio.to_thread()` for blocking IRIS API calls
4. **Timeout Enforcement**: 5-second per-method timeout prevents slow auth methods from blocking others

**Constitutional Compliance**:
- Query translation overhead <5ms maintained (no changes to query execution path)
- Authentication latency <5 seconds (FR-028, constitutional requirement)
- 1000 concurrent connections supported (existing PGWire server capacity)

---

**Phase 1 Complete**: Data model documented with entities, relationships, state transitions, and validation rules extracted from functional requirements and research decisions.
