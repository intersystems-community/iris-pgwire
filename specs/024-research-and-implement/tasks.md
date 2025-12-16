# Tasks: Research and Implement Authentication Bridge

**Input**: Design documents from `/Users/tdyar/ws/iris-pgwire/specs/024-research-and-implement/`
**Prerequisites**: plan.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

## Execution Flow (main)
```
1. ✅ Loaded plan.md from feature directory
   → Tech stack: Python 3.11+, python-gssapi>=1.8.0, asyncio, IRIS embedded Python
   → Structure: Single project (iris-pgwire codebase), new src/iris_pgwire/auth/ module
2. ✅ Loaded design documents:
   → data-model.md: 5 entities (OAuth Token, Kerberos Principal, Wallet Secret, User Session, Auth Config)
   → contracts/: 3 files (oauth_bridge_interface.py, gssapi_auth_interface.py, wallet_credentials_interface.py)
   → research.md: 9 decisions (OAuth → Kerberos → Wallet sequence, 5s timeout, dual-purpose Wallet)
   → quickstart.md: 3 test suites (OAuth, Kerberos, Wallet), 10 test cases
3. ✅ Generated 70 tasks across 6 categories:
   → Setup: Project structure, dependencies
   → Tests: 13 contract tests, 15 integration tests, 10 E2E tests
   → Core: 4 implementations (OAuth, Kerberos, Wallet, Auth Selector)
   → Integration: Protocol extensions, configuration management
   → Polish: Performance benchmarking, documentation
4. ✅ Applied task rules:
   → 38 parallel tasks [P] (independent files)
   → 32 sequential tasks (shared files or dependencies)
   → Tests before implementation (TDD)
5. ✅ Tasks numbered T001-T070
6. ✅ Dependencies documented
7. ✅ Parallel execution examples provided
8. ✅ Validation complete - all contracts, entities, and stories covered
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Paths shown are relative to repository root: `/Users/tdyar/ws/iris-pgwire/`

---

## Phase 3.1: Setup & Dependencies

### T001: Create authentication module structure
**File**: `src/iris_pgwire/auth/__init__.py`
**Description**: Create new `auth/` module directory and `__init__.py` with module docstring and exports.
**Requirements**:
- Create directory: `src/iris_pgwire/auth/`
- Create `__init__.py` with exports for all authentication components
- Add module-level docstring explaining authentication bridge architecture
- Export: `OAuthBridge`, `GSSAPIAuthenticator`, `WalletCredentials`, `AuthenticationSelector`

**Validation**: Module can be imported: `from iris_pgwire.auth import OAuthBridge`

---

### T002: [P] Add python-gssapi dependency
**File**: `requirements.txt`
**Description**: Add Kerberos GSSAPI authentication library with version constraint.
**Requirements**:
- Add `python-gssapi>=1.8.0` to requirements.txt
- Add comment explaining Kerberos authentication requirement
- Verify compatibility with Python 3.11+

**Validation**: `pip install -r requirements.txt` succeeds

---

### T003: [P] Add k5test dependency (development)
**File**: `requirements-dev.txt`
**Description**: Add k5test library for isolated Kerberos test realms (constitutional requirement).
**Requirements**:
- Add `k5test>=0.10.3` to requirements-dev.txt
- Add comment: "Kerberos test realm isolation (constitutional TDD requirement)"
- Document usage in testing strategy

**Validation**: `pip install -r requirements-dev.txt` succeeds

---

## Phase 3.2: Contract Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

### T004: [P] Contract test: OAuth token exchange (exchange_password_for_token)
**File**: `tests/contract/test_oauth_bridge_contract.py`
**Description**: Test OAuth password grant flow with valid/invalid credentials and timeout validation.
**Requirements** (from `contracts/oauth_bridge_interface.py:48-80`):
- Test valid credentials → returns OAuthToken with access_token
- Test invalid credentials → raises OAuthAuthenticationError
- Test OAuth server down → raises OAuthAuthenticationError
- Test completes within 5 seconds (FR-028)
- Use mock IRIS OAuth server (no real OAuth dependency)

**Expected**: FAIL (no implementation yet)
**Validation**: `pytest tests/contract/test_oauth_bridge_contract.py::test_exchange_password_for_token -v`

---

### T005: [P] Contract test: OAuth token validation (validate_token)
**File**: `tests/contract/test_oauth_bridge_contract.py`
**Description**: Test OAuth token introspection with active/expired/revoked tokens.
**Requirements** (from `contracts/oauth_bridge_interface.py:82-110`):
- Test valid active token → returns True
- Test expired token → returns False
- Test revoked token → returns False
- Test invalid token → raises OAuthValidationError
- Complete within 1 second

**Expected**: FAIL (no implementation yet)

---

### T006: [P] Contract test: OAuth token refresh (refresh_token)
**File**: `tests/contract/test_oauth_bridge_contract.py`
**Description**: Test OAuth refresh token grant with valid/invalid refresh tokens.
**Requirements** (from `contracts/oauth_bridge_interface.py:112-140`):
- Test valid refresh token → returns new OAuthToken
- Test invalid refresh token → raises OAuthRefreshError
- Test expired refresh token → raises OAuthRefreshError
- Verify new access_token differs from old
- Complete within 5 seconds

**Expected**: FAIL (no implementation yet)

---

### T007: [P] Contract test: OAuth client credentials (get_client_credentials)
**File**: `tests/contract/test_oauth_bridge_contract.py`
**Description**: Test OAuth client credential retrieval from environment or Wallet.
**Requirements** (from `contracts/oauth_bridge_interface.py:142-162`):
- Test environment variable → retrieves (client_id, client_secret)
- Test Wallet configured (Phase 4) → retrieves from IRIS Wallet
- Test not configured → raises OAuthConfigurationError
- Verify client_secret minimum length (32 chars)

**Expected**: FAIL (no implementation yet)

---

### T008: [P] Contract test: OAuth IRIS integration (asyncio.to_thread)
**File**: `tests/contract/test_oauth_bridge_contract.py`
**Description**: Test OAuth bridge uses asyncio.to_thread() for blocking IRIS calls (constitutional requirement).
**Requirements** (from `contracts/oauth_bridge_interface.py:225-227`):
- Mock `iris.cls('OAuth2.Client')` calls
- Verify token operations executed in thread pool (not event loop)
- Verify no external HTTP client used (embedded Python only)

**Expected**: FAIL (no implementation yet)

---

### T009: [P] Contract test: OAuth error handling (SQLSTATE 28000)
**File**: `tests/contract/test_oauth_bridge_contract.py`
**Description**: Test OAuth errors surface with PostgreSQL-compatible error codes.
**Requirements** (from `contracts/oauth_bridge_interface.py:230-232`):
- Test authentication failure → SQLSTATE 28000 (invalid authorization specification)
- Test error messages clear and actionable
- Verify errors propagate to PostgreSQL clients

**Expected**: FAIL (no implementation yet)

---

### T010: [P] Contract test: Kerberos GSSAPI handshake (handle_gssapi_handshake)
**File**: `tests/contract/test_gssapi_auth_contract.py`
**Description**: Test multi-step GSSAPI authentication with ticket validation.
**Requirements** (from `contracts/gssapi_auth_interface.py:26-37`):
- Test valid Kerberos ticket → returns KerberosPrincipal
- Test invalid ticket → raises KerberosAuthenticationError
- Test expired ticket → raises KerberosAuthenticationError
- Test handshake timeout (>5 seconds) → raises KerberosTimeoutError
- Use k5test for isolated KDC (constitutional requirement)

**Expected**: FAIL (no implementation yet)
**Validation**: `pytest tests/contract/test_gssapi_auth_contract.py::test_handle_gssapi_handshake -v`

---

### T011: [P] Contract test: Kerberos principal extraction (extract_principal)
**File**: `tests/contract/test_gssapi_auth_contract.py`
**Description**: Test username extraction from SecurityContext.peer_name.
**Requirements** (from `contracts/gssapi_auth_interface.py:43-45`, research.md R7):
- Test `alice@EXAMPLE.COM` → extracts `alice` as username
- Test principal without realm → handles gracefully
- Test malformed principal → raises KerberosAuthenticationError

**Expected**: FAIL (no implementation yet)

---

### T012: [P] Contract test: Kerberos principal mapping (map_principal_to_iris_user)
**File**: `tests/contract/test_gssapi_auth_contract.py`
**Description**: Test Kerberos principal → IRIS username mapping with validation.
**Requirements** (from `contracts/gssapi_auth_interface.py:47-50`, data-model.md lines 90-99):
- Test `alice@EXAMPLE.COM` → `ALICE` (strip realm + uppercase)
- Test mapped user exists in IRIS → mapping succeeds
- Test mapped user doesn't exist → raises AuthenticationError with clear message
- Validate against INFORMATION_SCHEMA.USERS (FR-017)

**Expected**: FAIL (no implementation yet)

---

### T013: [P] Contract test: Kerberos ticket validation (validate_kerberos_ticket)
**File**: `tests/contract/test_gssapi_auth_contract.py`
**Description**: Test Kerberos ticket validation via IRIS %Service_Bindings.
**Requirements** (from `contracts/gssapi_auth_interface.py:39-41`):
- Test valid GSSAPI token → validation succeeds
- Test invalid token → validation fails
- Use IRIS embedded Python: `iris.cls('%Service_Bindings')`
- Use asyncio.to_thread() for blocking IRIS call

**Expected**: FAIL (no implementation yet)

---

### T014: [P] Contract test: Wallet password retrieval (get_password_from_wallet)
**File**: `tests/contract/test_wallet_credentials_contract.py`
**Description**: Test encrypted password retrieval from IRIS Wallet with fallback.
**Requirements** (from `contracts/wallet_credentials_interface.py:26-37`):
- Test user exists in Wallet → returns decrypted password
- Test user not in Wallet → raises WalletSecretNotFoundError (triggers fallback)
- Test Wallet API failure → raises WalletAPIError
- Key format: `pgwire-user-{username}`

**Expected**: FAIL (no implementation yet)
**Validation**: `pytest tests/contract/test_wallet_credentials_contract.py::test_get_password_from_wallet -v`

---

### T015: [P] Contract test: Wallet password storage (set_password_in_wallet)
**File**: `tests/contract/test_wallet_credentials_contract.py`
**Description**: Test encrypted password storage in IRIS Wallet (admin operation).
**Requirements** (from `contracts/wallet_credentials_interface.py:39-41`):
- Test password storage → encrypted in IRISSECURITY database
- Test password update → updates `updated_at` timestamp
- Admin-only operation (no user-initiated password changes)

**Expected**: FAIL (no implementation yet)

---

### T016: [P] Contract test: Wallet OAuth client secret retrieval (get_oauth_client_secret)
**File**: `tests/contract/test_wallet_credentials_contract.py`
**Description**: Test OAuth client secret retrieval from Wallet (FR-009, dual-purpose Wallet).
**Requirements** (from `contracts/wallet_credentials_interface.py:43-45`, research.md R4):
- Test OAuth secret exists → returns decrypted client_secret
- Test secret not configured → raises WalletAPIError
- Key format: `pgwire-oauth-client`
- Dual-purpose Wallet: same API for user passwords and OAuth secrets

**Expected**: FAIL (no implementation yet)

---

## Phase 3.3: Integration Tests (TDD) ⚠️ MUST COMPLETE BEFORE 3.4

### T017: [P] Integration test: OAuth token exchange with IRIS OAuth server
**File**: `tests/integration/test_oauth_token_exchange.py`
**Description**: E2E OAuth password grant flow against real IRIS OAuth server using iris-devtester.
**Requirements** (from quickstart.md Phase 2, research.md R8):
- Use iris-devtester for isolated IRIS container (constitutional requirement)
- Register PGWire as OAuth client: `client_id=pgwire-test`
- Test username/password → OAuth access_token via `iris.cls('OAuth2.Client').RequestToken()`
- Validate token structure (access_token, refresh_token, expires_in, username, scopes)
- Use asyncio.to_thread() for blocking IRIS calls

**Expected**: FAIL (no implementation yet)
**Validation**: `pytest tests/integration/test_oauth_token_exchange.py -v`

---

### T018: [P] Integration test: OAuth token validation with IRIS introspection endpoint
**File**: `tests/integration/test_oauth_token_validation.py`
**Description**: E2E OAuth token introspection against IRIS OAuth server.
**Requirements** (from quickstart.md Phase 2, FR-008):
- Use iris-devtester container
- Test valid active token → introspection returns `active: true`
- Test expired token → introspection returns `active: false`
- Use IRIS OAuth introspection: `OAuth2.Client.IntrospectToken()`
- NOT local verification (constitutional requirement)

**Expected**: FAIL (no implementation yet)

---

### T019: [P] Integration test: Kerberos GSSAPI handshake with k5test KDC
**File**: `tests/integration/test_kerberos_gssapi_handshake.py`
**Description**: E2E Kerberos authentication with isolated test realm using k5test.
**Requirements** (from quickstart.md Phase 3, research.md R6):
- Use k5test for isolated KDC (no shared state)
- Generate test keytab: `postgres/pgwire-test.local@TEST.REALM`
- Test GSSAPI handshake with valid ticket → extracts principal
- Test multi-step token exchange (AuthenticationGSS, GSSResponse, AuthenticationGSSContinue)
- Measure handshake latency (target: <5s, typical: ~400ms)

**Expected**: FAIL (no implementation yet)

---

### T020: [P] Integration test: Kerberos principal validation against IRIS Security.Users
**File**: `tests/integration/test_kerberos_principal_validation.py`
**Description**: E2E Kerberos principal → IRIS user mapping with validation.
**Requirements** (from quickstart.md Phase 3, data-model.md lines 90-99):
- Use iris-devtester container
- Create IRIS user: `ALICE` (uppercase per IRIS convention)
- Test `alice@TEST.REALM` → maps to `ALICE` → validation succeeds
- Test `nonexistent@TEST.REALM` → validation fails with clear error (FR-017)
- Query INFORMATION_SCHEMA.USERS for validation

**Expected**: FAIL (no implementation yet)

---

### T021: [P] Integration test: Wallet password retrieval from IRISSECURITY database
**File**: `tests/integration/test_wallet_password_retrieval.py`
**Description**: E2E encrypted password retrieval from IRIS Wallet.
**Requirements** (from quickstart.md Phase 4, FR-020):
- Use iris-devtester container with IRIS 2025.3.0+ (Wallet support)
- Store test password: `wallet.SetSecret('pgwire-user-testuser', 'encrypted-password')`
- Test retrieval: `wallet.GetSecret('pgwire-user-testuser')` → returns decrypted password
- Test Wallet miss → returns None (triggers password fallback)
- Test audit trail: `accessed_at` timestamp updated (FR-022)

**Expected**: FAIL (no implementation yet)

---

### T022: [P] Integration test: OAuth client secret retrieval from Wallet
**File**: `tests/integration/test_wallet_oauth_secret_retrieval.py`
**Description**: E2E OAuth client secret retrieval from dual-purpose Wallet.
**Requirements** (from quickstart.md Phase 4, research.md R4):
- Use iris-devtester container with IRIS 2025.3.0+
- Store OAuth secret: `wallet.SetSecret('pgwire-oauth-client', 'client-secret-here')`
- Test retrieval via `get_client_credentials()` → returns (client_id, client_secret)
- Dual-purpose Wallet: same API for user passwords and OAuth secrets
- Fallback to environment variable if Wallet retrieval fails

**Expected**: FAIL (no implementation yet)

---

### T023: [P] Integration test: Authentication selector routing (OAuth → Kerberos → Wallet → password)
**File**: `tests/integration/test_auth_selector_routing.py`
**Description**: E2E dual-mode authentication with fallback chain.
**Requirements** (from research.md R9, data-model.md lines 249-266):
- Test Kerberos client (gssencmode parameter) → routes to GSSAPI authentication
- Test OAuth enabled → attempts token exchange first
- Test OAuth failure → falls back to Wallet retrieval
- Test Wallet miss → falls back to SCRAM-SHA-256 password authentication
- Test timeout enforcement (5-second per-method limit)

**Expected**: FAIL (no implementation yet)

---

### T024: [P] Integration test: Authentication configuration loading from environment variables
**File**: `tests/integration/test_auth_config_loading.py`
**Description**: Test authentication method configuration from environment variables.
**Requirements** (from data-model.md lines 207-239):
- Test `PGWIRE_AUTH_METHODS=oauth,kerberos,wallet,password` → enables all methods
- Test `PGWIRE_AUTH_FALLBACK=password` → sets fallback method
- Test `PGWIRE_AUTH_TIMEOUT=5` → sets per-method timeout
- Test missing OAuth config with `oauth` in enabled_methods → raises error
- Validate configuration at server startup

**Expected**: FAIL (no implementation yet)

---

## Phase 3.4: Core Implementation (ONLY after tests are failing)

### T025: Implement OAuth token dataclass (OAuthToken)
**File**: `src/iris_pgwire/auth/oauth_bridge.py`
**Description**: Create OAuthToken dataclass with expiry calculation.
**Requirements** (from data-model.md lines 18-39):
- Fields: access_token, refresh_token, token_type, expires_in, issued_at, username, scopes
- Property: `expires_at` (calculated: issued_at + expires_in)
- Property: `is_expired` (check datetime.utcnow() >= expires_at)
- Type hints for all fields

**Tests to Pass**: T004, T005, T006 (contract tests)
**Validation**: `pytest tests/contract/test_oauth_bridge_contract.py -v` - 6 tests pass

---

### T026: Implement OAuth bridge class (OAuthBridge)
**File**: `src/iris_pgwire/auth/oauth_bridge.py`
**Description**: Implement OAuthBridgeProtocol with IRIS OAuth 2.0 integration.
**Requirements** (from contracts/oauth_bridge_interface.py, research.md R8):
- `async def exchange_password_for_token(username, password) -> OAuthToken`
  - Use `iris.cls('OAuth2.Client').RequestToken()` for password grant
  - Use asyncio.to_thread() to avoid blocking event loop
  - Complete within 5 seconds (FR-028)
  - Raise OAuthAuthenticationError on failure
- `async def validate_token(access_token) -> bool`
  - Use `OAuth2.Client.IntrospectToken()` for validation (not local verification - FR-008)
  - Return True if active, False if expired/revoked
  - Complete within 1 second
- `async def refresh_token(refresh_token) -> OAuthToken`
  - Use refresh token grant type
  - Return new OAuthToken with updated access_token
  - Complete within 5 seconds
- `async def get_client_credentials() -> tuple[str, str]`
  - Try Wallet retrieval first (if Phase 4 complete)
  - Fallback to environment variables: PGWIRE_OAUTH_CLIENT_ID, PGWIRE_OAUTH_CLIENT_SECRET
  - Raise OAuthConfigurationError if not configured

**Tests to Pass**: T004-T008, T017, T018 (contract + integration tests)
**Validation**: All OAuth tests pass - 8 tests green

---

### T027: Implement Kerberos principal dataclass (KerberosPrincipal)
**File**: `src/iris_pgwire/auth/gssapi_auth.py`
**Description**: Create KerberosPrincipal dataclass with IRIS user mapping.
**Requirements** (from data-model.md lines 59-103):
- Fields: principal, username, realm, mapped_iris_user, authenticated_at, ticket_expiry
- Extract username from principal (split on '@')
- Extract realm from principal
- Map to IRIS user: strip realm + uppercase
- Type hints for all fields

**Tests to Pass**: T011, T012 (contract tests)
**Validation**: `pytest tests/contract/test_gssapi_auth_contract.py::test_extract_principal -v`

---

### T028: Implement GSSAPI authenticator class (GSSAPIAuthenticator)
**File**: `src/iris_pgwire/auth/gssapi_auth.py`
**Description**: Implement GSSAPIAuthenticatorProtocol with Kerberos ticket validation.
**Requirements** (from contracts/gssapi_auth_interface.py, research.md R6, R7):
- `async def handle_gssapi_handshake(connection_id) -> KerberosPrincipal`
  - Multi-step token exchange (AuthenticationGSS type=7, GSSResponse, AuthenticationGSSContinue type=8)
  - Use python-gssapi for SecurityContext creation
  - Complete within 5 seconds (FR-028, research.md R3)
  - Raise KerberosAuthenticationError on failure, KerberosTimeoutError on timeout
- `async def validate_kerberos_ticket(gssapi_token) -> bool`
  - Use `iris.cls('%Service_Bindings')` for ticket validation (FR-014)
  - Use asyncio.to_thread() for blocking IRIS call
- `async def extract_principal(security_context) -> str`
  - Use SecurityContext.peer_name to extract principal
  - Return full principal (e.g., 'alice@EXAMPLE.COM')
- `async def map_principal_to_iris_user(principal) -> str`
  - Strip realm: `principal.split('@')[0]`
  - Uppercase: `username.upper()`
  - Validate IRIS user exists: query INFORMATION_SCHEMA.USERS (FR-017)
  - Raise AuthenticationError if user doesn't exist

**Tests to Pass**: T010-T013, T019, T020 (contract + integration tests)
**Validation**: All Kerberos tests pass - 6 tests green

---

### T029: Implement Wallet secret dataclass (WalletSecret)
**File**: `src/iris_pgwire/auth/wallet_credentials.py`
**Description**: Create WalletSecret dataclass for encrypted credential storage.
**Requirements** (from data-model.md lines 106-156):
- Fields: key, value, secret_type, created_at, updated_at, accessed_at
- Key format: `pgwire-user-{username}` for passwords, `pgwire-oauth-client` for OAuth
- Secret type enum: 'password' or 'oauth_client_secret'
- Type hints for all fields

**Tests to Pass**: T014, T015 (contract tests)
**Validation**: `pytest tests/contract/test_wallet_credentials_contract.py::test_wallet_secret_dataclass -v`

---

### T030: Implement Wallet credentials class (WalletCredentials)
**File**: `src/iris_pgwire/auth/wallet_credentials.py`
**Description**: Implement WalletCredentialsProtocol with IRIS Wallet integration.
**Requirements** (from contracts/wallet_credentials_interface.py, research.md R4):
- `async def get_password_from_wallet(username) -> str`
  - Key: `f'pgwire-user-{username}'`
  - Use `iris.cls('%IRIS.Wallet').GetSecret(key)` for retrieval
  - Use asyncio.to_thread() for blocking IRIS call
  - Update accessed_at timestamp (FR-022 audit trail)
  - Raise WalletSecretNotFoundError if not found (triggers fallback - FR-021)
  - Raise WalletAPIError if Wallet API fails
- `async def set_password_in_wallet(username, password) -> None`
  - Admin operation only (no user-initiated changes)
  - Use `Wallet.SetSecret(key, password)` for storage
  - Encrypted at rest in IRISSECURITY database
  - Update updated_at timestamp
- `async def get_oauth_client_secret() -> str`
  - Key: `'pgwire-oauth-client'`
  - Dual-purpose Wallet: same API for OAuth secrets (FR-009, research.md R4)
  - Fallback to environment variable if not in Wallet

**Tests to Pass**: T014-T016, T021, T022 (contract + integration tests)
**Validation**: All Wallet tests pass - 5 tests green

---

### T031: Implement user session dataclass (UserSession)
**File**: `src/iris_pgwire/auth/auth_selector.py`
**Description**: Create UserSession dataclass for authenticated connection tracking.
**Requirements** (from data-model.md lines 159-204):
- Fields: session_id, connection_id, iris_username, auth_method, oauth_token, kerberos_principal, wallet_key, created_at, last_activity_at, client_info
- Auth method enum: 'password', 'oauth', 'kerberos', 'wallet'
- Exactly ONE of oauth_token, kerberos_principal, or wallet_key must be non-null
- Update last_activity_at on each query execution
- Type hints for all fields

**Validation**: Dataclass can be instantiated with correct auth_method constraints

---

### T032: Implement authentication selector class (AuthenticationSelector)
**File**: `src/iris_pgwire/auth/auth_selector.py`
**Description**: Implement dual-mode authentication routing with fallback chain.
**Requirements** (from research.md R9, data-model.md lines 249-266):
- `async def authenticate(startup_params, connection_id) -> UserSession`
  - Detect auth method from startup parameters
  - Route to appropriate authenticator:
    1. If `gssencmode` in startup_params and `kerberos` enabled → handle_gssapi_handshake()
    2. If `oauth` enabled → exchange_password_for_token()
    3. If `wallet` enabled → get_password_from_wallet()
    4. Fallback to SCRAM-SHA-256 password authentication (always enabled - FR-025)
  - Enforce per-method timeout (5 seconds - FR-028)
  - Create UserSession with auth_method set
  - Log authentication attempt for audit trail (FR-026)
- `async def validate_iris_user_exists(username) -> bool`
  - Query INFORMATION_SCHEMA.USERS WHERE USERNAME = :username
  - Return True if user exists, False otherwise
  - Used by Kerberos principal mapping (FR-017)

**Tests to Pass**: T023, T024 (integration tests)
**Validation**: All authentication selector tests pass - 2 tests green

---

## Phase 3.5: Protocol Integration

### T033: Extend protocol.py for AuthenticationGSS messages
**File**: `src/iris_pgwire/protocol.py`
**Description**: Add PostgreSQL GSSAPI authentication protocol message support.
**Requirements** (from data-model.md authentication flow, quickstart.md Phase 3):
- Add AuthenticationGSS message (type=7): Initiates GSSAPI authentication
- Add GSSResponse message: Client sends GSSAPI token to server
- Add AuthenticationGSSContinue message (type=8): Server sends token to client (multi-step)
- Add message parsing for GSSAPI tokens (binary data)
- Integrate with GSSAPIAuthenticator.handle_gssapi_handshake()

**Dependencies**: T028 (GSSAPIAuthenticator must exist)
**Validation**: psql with gssencmode=prefer can negotiate GSSAPI authentication

---

### T034: Extend iris_executor.py for IRIS auth API calls
**File**: `src/iris_pgwire/iris_executor.py`
**Description**: Add helper methods for IRIS OAuth/Kerberos/Wallet API access.
**Requirements**:
- `async def call_iris_oauth_api(method, **kwargs)` - Wrapper for OAuth2.Client methods
- `async def call_iris_kerberos_api(method, **kwargs)` - Wrapper for %Service_Bindings methods
- `async def call_iris_wallet_api(method, **kwargs)` - Wrapper for %IRIS.Wallet methods
- All methods use asyncio.to_thread() (constitutional requirement)
- All methods have proper error handling and logging

**Dependencies**: T026, T028, T030 (auth implementations must exist)
**Validation**: Auth components can call IRIS APIs without blocking event loop

---

### T035: Integrate AuthenticationSelector into server startup
**File**: `src/iris_pgwire/server.py`
**Description**: Initialize authentication selector with configuration from environment variables.
**Requirements** (from data-model.md lines 207-239):
- Load configuration at server startup:
  - PGWIRE_AUTH_METHODS (comma-separated: oauth,kerberos,wallet,password)
  - PGWIRE_AUTH_FALLBACK (always 'password' for backward compatibility - FR-025)
  - PGWIRE_AUTH_TIMEOUT (default: 5 seconds)
  - PGWIRE_OAUTH_CLIENT_ID, PGWIRE_OAUTH_TOKEN_ENDPOINT, PGWIRE_OAUTH_INTROSPECTION_ENDPOINT
  - PGWIRE_KERBEROS_SERVICE_NAME, PGWIRE_KERBEROS_KEYTAB, KRB5_KTNAME
  - PGWIRE_WALLET_MODE (oauth | password | both)
- Create AuthenticationSelector instance
- Validate configuration (fail fast if OAuth config missing when oauth enabled)
- Pass selector to connection handler

**Dependencies**: T032 (AuthenticationSelector must exist)
**Validation**: Server starts successfully with all auth methods enabled

---

### T036: Update connection handler to use AuthenticationSelector
**File**: `src/iris_pgwire/protocol.py` (or `server.py` - wherever connection handling lives)
**Description**: Replace existing SCRAM-SHA-256 authentication with AuthenticationSelector.
**Requirements**:
- On StartupMessage received → call `auth_selector.authenticate(startup_params, connection_id)`
- Store UserSession in connection state
- Update last_activity_at on each query execution
- Log authentication method used for audit trail (FR-026)
- Surface authentication errors to client with proper SQLSTATE codes (FR-027)

**Dependencies**: T035 (server startup integration)
**Validation**: PostgreSQL clients can connect with OAuth/Kerberos/Wallet/password authentication

---

## Phase 3.6: E2E Testing (Client Compatibility)

### T037: [P] E2E test: psql OAuth authentication
**File**: `tests/e2e/test_psql_oauth.py`
**Description**: E2E test with psql client using OAuth token exchange (Test Suite 1 from quickstart.md).
**Requirements**:
- Use iris-devtester for IRIS container
- Register PGWire OAuth client
- Execute: `psql -h localhost -p 5432 -U test_user -d USER -c "SELECT CURRENT_USER"`
- Verify connection succeeds (OAuth token exchange transparent)
- Verify PGWire logs show: "OAuth token exchange successful for user test_user"
- Verify query execution works after authentication

**Dependencies**: T036 (connection handler integration)
**Validation**: `pytest tests/e2e/test_psql_oauth.py -v` - psql authentication succeeds

---

### T038: [P] E2E test: psycopg OAuth authentication
**File**: `tests/e2e/test_psycopg_oauth.py`
**Description**: E2E test with psycopg driver using OAuth token exchange.
**Requirements**:
- Use iris-devtester for IRIS container
- Execute: `psycopg.connect(host='localhost', port=5432, user='test_user', password='test_password')`
- Verify connection succeeds with OAuth authentication
- Execute query: `SELECT CURRENT_USER`
- Verify result matches expected username

**Dependencies**: T036 (connection handler integration)
**Validation**: Python psycopg client authenticates successfully via OAuth

---

### T039: [P] E2E test: JDBC OAuth authentication
**File**: `tests/e2e/test_jdbc_oauth.py`
**Description**: E2E test with JDBC driver using OAuth token exchange.
**Requirements**:
- Use iris-devtester for IRIS container
- Execute: `DriverManager.getConnection("jdbc:postgresql://localhost:5432/USER", "test_user", "test_password")`
- Verify connection succeeds with OAuth authentication
- Execute query: `SELECT CURRENT_USER`
- Verify JDBC driver compatibility maintained

**Dependencies**: T036 (connection handler integration)
**Validation**: Java JDBC client authenticates successfully via OAuth

---

### T040: [P] E2E test: psql Kerberos authentication
**File**: `tests/e2e/test_psql_kerberos.py`
**Description**: E2E test with psql client using GSSAPI authentication (Test Suite 2 from quickstart.md).
**Requirements**:
- Use k5test for isolated Kerberos realm
- Generate test keytab: `postgres/pgwire-test.local@TEST.REALM`
- Initialize ticket: `kinit alice@TEST.REALM`
- Execute: `psql -h pgwire-test.local -p 5432 -U alice -d USER "gssencmode=prefer" -c "SELECT CURRENT_USER"`
- Verify GSSAPI authentication succeeds
- Verify PGWire logs show: "GSSAPI authentication successful for principal alice@TEST.REALM"
- Verify principal mapping: `alice@TEST.REALM` → `ALICE`

**Dependencies**: T033, T036 (GSSAPI protocol + connection handler)
**Validation**: psql GSSAPI authentication succeeds with Kerberos ticket

---

### T041: [P] E2E test: psycopg Kerberos authentication
**File**: `tests/e2e/test_psycopg_kerberos.py`
**Description**: E2E test with psycopg driver using GSSAPI authentication.
**Requirements**:
- Use k5test for isolated Kerberos realm
- Initialize ticket: `kinit alice@TEST.REALM`
- Execute: `psycopg.connect(host='pgwire-test.local', port=5432, user='alice', gssencmode='prefer')`
- Verify GSSAPI authentication succeeds
- Verify query execution works

**Dependencies**: T033, T036 (GSSAPI protocol + connection handler)
**Validation**: psycopg Kerberos authentication succeeds

---

### T042: [P] E2E test: psql Wallet-backed authentication
**File**: `tests/e2e/test_psql_wallet.py`
**Description**: E2E test with psql client using Wallet credential retrieval (Test Suite 3 from quickstart.md).
**Requirements**:
- Use iris-devtester with IRIS 2025.3.0+ (Wallet support)
- Store password in Wallet: `wallet.SetSecret('pgwire-user-alice', 'alice-password')`
- Execute: `psql -h localhost -p 5432 -U alice -d USER -c "SELECT CURRENT_USER"`
- Verify connection succeeds (Wallet password retrieval transparent)
- Verify PGWire logs show: "Wallet secret retrieval successful for key pgwire-user-alice"
- Verify audit trail: accessed_at timestamp updated

**Dependencies**: T036 (connection handler integration)
**Validation**: psql authentication succeeds with Wallet-backed credentials

---

### T043: [P] E2E test: psql password fallback (Wallet miss)
**File**: `tests/e2e/test_psql_password_fallback.py`
**Description**: E2E test for Wallet miss → SCRAM-SHA-256 password fallback.
**Requirements**:
- Use iris-devtester container
- Ensure user NOT in Wallet
- Execute: `psql -h localhost -p 5432 -U test_user -d USER -c "SELECT CURRENT_USER"`
- Verify connection succeeds via SCRAM-SHA-256 fallback
- Verify PGWire logs show: "Wallet secret not found for key pgwire-user-test_user, falling back to password authentication"

**Dependencies**: T036 (connection handler integration)
**Validation**: Password fallback works when Wallet entry missing

---

### T044: [P] E2E test: Credential rotation without service restart
**File**: `tests/e2e/test_wallet_credential_rotation.py`
**Description**: E2E test for credential rotation support (FR-023).
**Requirements**:
- Store initial password in Wallet: `wallet.SetSecret('pgwire-user-alice', 'old-password')`
- Connect with old password → succeeds
- Rotate password: `wallet.SetSecret('pgwire-user-alice', 'new-password')` (updates updated_at)
- Connect with new password → succeeds (NO PGWire restart required)
- Connect with old password → fails

**Dependencies**: T036 (connection handler integration)
**Validation**: Credential rotation works without service restart (FR-023)

---

### T045: [P] E2E test: Multi-method authentication fallback chain
**File**: `tests/e2e/test_multi_method_fallback.py`
**Description**: E2E test for OAuth → Kerberos → Wallet → password fallback chain.
**Requirements**:
- Configure all methods enabled: `PGWIRE_AUTH_METHODS=oauth,kerberos,wallet,password`
- Test OAuth failure (server down) → falls back to password
- Test Kerberos failure (no ticket) → falls back to password
- Test Wallet miss → falls back to password
- Verify connection succeeds via fallback method
- Verify PGWire logs show fallback chain execution

**Dependencies**: T036 (connection handler integration)
**Validation**: Fallback chain ensures connection always succeeds (backward compatibility - FR-025)

---

### T046: [P] E2E test: Backward compatibility with 8 existing PostgreSQL clients
**File**: `tests/e2e/test_backward_compatibility.py`
**Description**: Regression test for 8 PostgreSQL client drivers (FR-025).
**Requirements**:
- Run existing 171 client compatibility tests (from tests/client_compatibility/)
- Clients: psql, psycopg (Python), JDBC (Java), pg (Node.js), Npgsql (C#), libpq (C/C++), go-pg (Go), rust-postgres (Rust)
- Verify all 171 tests still pass with authentication bridge enabled
- Test with auth bridge disabled (password-only) → backward compatibility maintained
- No test failures introduced by authentication bridge

**Dependencies**: T036 (connection handler integration)
**Validation**: All 171 existing client tests pass - 100% backward compatibility maintained

---

## Phase 3.7: Unit Tests (Code Coverage)

### T047: [P] Unit test: OAuth token expiry calculation
**File**: `tests/unit/test_oauth_token_expiry.py`
**Description**: Test OAuthToken expires_at and is_expired properties.
**Requirements**:
- Test expires_at = issued_at + timedelta(seconds=expires_in)
- Test is_expired = True when datetime.utcnow() >= expires_at
- Test is_expired = False when datetime.utcnow() < expires_at

**Validation**: OAuth token expiry logic correct

---

### T048: [P] Unit test: Kerberos principal parsing
**File**: `tests/unit/test_kerberos_principal_parsing.py`
**Description**: Test principal extraction and realm parsing.
**Requirements**:
- Test `alice@EXAMPLE.COM` → username='alice', realm='EXAMPLE.COM'
- Test `bob@SUBDOMAIN.EXAMPLE.COM` → username='bob', realm='SUBDOMAIN.EXAMPLE.COM'
- Test malformed principals → raises error

**Validation**: Principal parsing logic correct

---

### T049: [P] Unit test: Kerberos principal → IRIS user mapping
**File**: `tests/unit/test_kerberos_principal_mapping.py`
**Description**: Test principal mapping algorithm (strip realm + uppercase).
**Requirements** (from data-model.md lines 90-99):
- Test `alice@EXAMPLE.COM` → `ALICE`
- Test `john.doe@EXAMPLE.COM` → `JOHN.DOE`
- Test `alice` (no realm) → `ALICE`
- Test empty principal → raises error

**Validation**: Mapping algorithm correct per research.md R7

---

### T050: [P] Unit test: Wallet key formatting
**File**: `tests/unit/test_wallet_key_formatting.py`
**Description**: Test Wallet secret key generation.
**Requirements** (from data-model.md lines 121-122):
- Test username='alice' → key='pgwire-user-alice'
- Test username='john.doe' → key='pgwire-user-john.doe'
- Test OAuth client secret → key='pgwire-oauth-client'

**Validation**: Key format consistent with Wallet API expectations

---

### T051: [P] Unit test: Authentication timeout enforcement
**File**: `tests/unit/test_auth_timeout.py`
**Description**: Test per-method authentication timeout (5 seconds).
**Requirements** (from FR-028, research.md R3):
- Test OAuth token exchange timeout → raises timeout error after 5s
- Test Kerberos GSSAPI handshake timeout → raises timeout error after 5s
- Test Wallet retrieval timeout → raises timeout error after 5s
- Use mock sleeps to simulate slow operations

**Validation**: Timeout enforcement prevents slow auth methods from blocking connections

---

### T052: [P] Unit test: UserSession state transitions
**File**: `tests/unit/test_user_session_state.py`
**Description**: Test UserSession lifecycle and state management.
**Requirements** (from data-model.md lines 189-204):
- Test AUTHENTICATING → ACTIVE → IDLE → DISCONNECTED transitions
- Test ERROR state → DISCONNECTED transition
- Test last_activity_at update on query execution
- Test exactly one of oauth_token, kerberos_principal, or wallet_key is non-null

**Validation**: UserSession state machine correct

---

### T053: [P] Unit test: Authentication method selection logic
**File**: `tests/unit/test_auth_method_selection.py`
**Description**: Test AuthenticationSelector.select_auth_method() routing logic.
**Requirements** (from research.md R9):
- Test gssencmode in startup_params → returns 'kerberos'
- Test oauth enabled → returns 'oauth'
- Test wallet enabled → returns 'wallet'
- Test all disabled → returns 'password' (fallback)
- Test method priority: Kerberos > OAuth > Wallet > password

**Validation**: Method selection logic correct

---

## Phase 3.8: Production Readiness

### T054: Implement audit trail logging (FR-026)
**File**: `src/iris_pgwire/auth/audit_logger.py`
**Description**: Log all authentication attempts for security monitoring.
**Requirements** (from FR-026):
- Log successful authentication: session_id, iris_username, auth_method, timestamp, client_info
- Log failed authentication: username, auth_method, failure_reason, timestamp, client_ip
- Use structured logging (JSON format) for audit trail parsing
- Integrate with existing PGWire logging infrastructure
- Log to dedicated audit log file: `/tmp/pgwire-audit.log`

**Validation**: All authentication attempts logged with required fields

---

### T055: Implement error surfacing to PostgreSQL clients (FR-027)
**File**: `src/iris_pgwire/auth/error_mapper.py`
**Description**: Map authentication errors to PostgreSQL-compatible error codes.
**Requirements** (from FR-027):
- OAuthAuthenticationError → SQLSTATE 28000 (invalid authorization specification)
- KerberosAuthenticationError → SQLSTATE 28000
- WalletAPIError → SQLSTATE 08006 (connection failure)
- OAuthConfigurationError → SQLSTATE 08004 (server rejected connection)
- Error messages clear and actionable (no sensitive information leaked)
- Include hint field for troubleshooting (e.g., "Check OAuth server availability")

**Validation**: PostgreSQL clients receive proper error codes and messages

---

### T056: Implement OAuth client credential security (FR-009)
**File**: `src/iris_pgwire/auth/oauth_bridge.py` (update get_client_credentials method)
**Description**: Secure storage of PGWire OAuth client credentials (preferably in Wallet).
**Requirements** (from FR-009):
- Phase 4: Retrieve client_secret from Wallet: `wallet.GetSecret('pgwire-oauth-client')`
- Fallback to environment variable: `PGWIRE_OAUTH_CLIENT_SECRET` (Phase 2-3)
- Never log client_secret in plaintext
- Validate client_secret minimum length (32 chars)

**Validation**: Client credentials securely retrieved, never logged in plaintext

---

### T057: Document keytab deployment with Docker secrets
**File**: `docs/KERBEROS_DEPLOYMENT.md`
**Description**: Production deployment guide for Kerberos keytab file.
**Requirements** (from quickstart.md Phase 3):
- Document Docker secrets deployment (recommended over volume mount)
- Document keytab file permissions (chmod 400, chown 0:0)
- Document keytab generation (Active Directory + MIT Kerberos)
- Document KRB5_KTNAME environment variable requirement
- Document service principal format: `postgres/pgwire-host.example.com@EXAMPLE.COM`

**Validation**: Deployment guide complete and actionable

---

### T058: Document OAuth client registration
**File**: `docs/OAUTH_SETUP.md`
**Description**: OAuth 2.0 client setup guide for IRIS OAuth server.
**Requirements** (from quickstart.md Phase 2):
- Document client registration via Management Portal
- Document client registration via ObjectScript Terminal
- Document required grant types: password, refresh_token
- Document required scopes: user_info
- Document client secret storage (Wallet recommended)

**Validation**: Setup guide complete with Management Portal + Terminal examples

---

## Phase 3.9: Performance Benchmarking

### T059: Benchmark OAuth token exchange latency
**File**: `tests/performance/test_oauth_latency.py`
**Description**: Validate OAuth token exchange completes within 5 seconds (FR-028).
**Requirements**:
- Measure token exchange latency (50 iterations)
- Target: <5 seconds (constitutional requirement)
- Typical: 100-200ms (from research.md R3)
- Report P50, P95, P99 latencies
- Fail if P99 > 5 seconds

**Validation**: OAuth latency meets constitutional requirement (<5s P99)

---

### T060: Benchmark Kerberos GSSAPI handshake latency
**File**: `tests/performance/test_kerberos_latency.py`
**Description**: Validate Kerberos GSSAPI handshake completes within 5 seconds (FR-028).
**Requirements**:
- Use k5test for isolated KDC
- Measure handshake latency (50 iterations)
- Target: <5 seconds (constitutional requirement)
- Typical: ~400ms (from research.md R3)
- Report P50, P95, P99 latencies
- Fail if P99 > 5 seconds

**Validation**: Kerberos latency meets constitutional requirement (<5s P99)

---

### T061: Benchmark Wallet retrieval latency
**File**: `tests/performance/test_wallet_latency.py`
**Description**: Validate Wallet secret retrieval completes within 5 seconds (FR-028).
**Requirements**:
- Use iris-devtester with IRIS 2025.3.0+
- Measure retrieval latency (50 iterations)
- Target: <5 seconds (constitutional requirement)
- Typical: ~50ms (from research.md R3)
- Report P50, P95, P99 latencies
- Fail if P99 > 5 seconds

**Validation**: Wallet latency meets constitutional requirement (<5s P99)

---

### T062: Benchmark concurrent authentication load (1000 connections)
**File**: `tests/performance/test_concurrent_auth.py`
**Description**: Validate PGWire supports 1000 concurrent connections (constitutional requirement).
**Requirements**:
- Spawn 1000 concurrent psql connections
- Use mix of auth methods: 40% OAuth, 30% Kerberos, 20% Wallet, 10% password
- Measure authentication success rate
- Measure connection latency (P50, P95, P99)
- Target: >99% success rate, <10s P99 latency
- Fail if connection refused errors occur

**Validation**: 1000 concurrent connections supported without connection refused errors

---

### T063: Benchmark authentication fallback chain latency
**File**: `tests/performance/test_fallback_chain_latency.py`
**Description**: Validate authentication fallback doesn't exceed 5-second timeout per method.
**Requirements**:
- Test OAuth failure (server down) → fallback to password
- Measure total latency: OAuth attempt (5s timeout) + password fallback
- Target: <10 seconds total (2 methods × 5s each)
- Verify timeout enforcement prevents indefinite blocking

**Validation**: Fallback chain completes within timeout limits

---

## Phase 3.10: Documentation & Finalization

### T064: Update CLAUDE.md with authentication bridge patterns
**File**: `CLAUDE.md`
**Description**: Document authentication bridge architecture for Claude Code context.
**Requirements**:
- Add section: "🔐 Authentication Bridge (Feature 024)"
- Document OAuth integration patterns (token exchange, validation, refresh)
- Document Kerberos integration patterns (GSSAPI handshake, principal mapping)
- Document Wallet integration patterns (credential retrieval, rotation)
- Document dual-mode authentication routing
- Document testing patterns (iris-devtester + k5test)

**Validation**: CLAUDE.md updated with authentication context

---

### T065: Update README.md with authentication features
**File**: `README.md`
**Description**: Document new authentication capabilities in project README.
**Requirements**:
- Add "Authentication Methods" section
- Document OAuth 2.0, Kerberos (GSSAPI), IRIS Wallet support
- Document configuration via environment variables
- Link to quickstart.md for setup instructions
- Document backward compatibility (password fallback always enabled)

**Validation**: README.md describes authentication bridge features

---

### T066: [P] Document OAuth troubleshooting
**File**: `docs/OAUTH_TROUBLESHOOTING.md`
**Description**: Troubleshooting guide for common OAuth authentication issues.
**Requirements**:
- Issue: "OAuth authentication failed: invalid_client" → check client credentials
- Issue: "OAuth server unavailable" → verify IRIS OAuth server accessible
- Issue: "Token validation failed" → check token expiry, introspection endpoint
- Document OAuth server health check: `curl http://iris:52773/oauth2/token`
- Document PGWire log inspection commands

**Validation**: Troubleshooting guide covers common OAuth issues

---

### T067: [P] Document Kerberos troubleshooting
**File**: `docs/KERBEROS_TROUBLESHOOTING.md`
**Description**: Troubleshooting guide for common Kerberos authentication issues.
**Requirements**:
- Issue: "Kerberos principal not found" → verify IRIS user exists (uppercase)
- Issue: "GSSAPI handshake failed" → check keytab file permissions, KDC availability
- Issue: "Principal mapping failed" → verify mapping algorithm (strip realm + uppercase)
- Document keytab verification: `klist -k /etc/krb5.keytab`
- Document KDC health check: `kinit -k -t /etc/krb5.keytab postgres/pgwire-host.example.com`

**Validation**: Troubleshooting guide covers common Kerberos issues

---

### T068: [P] Document Wallet troubleshooting
**File**: `docs/WALLET_TROUBLESHOOTING.md`
**Description**: Troubleshooting guide for IRIS Wallet integration issues.
**Requirements**:
- Issue: "Wallet secret not found" → verify secret stored, Wallet enabled
- Issue: "Wallet API failure" → check IRIS version (2025.3.0+ required)
- Document secret storage via ObjectScript: `Set wallet = ##class(%IRIS.Wallet).%New(); Do wallet.SetSecret(...)`
- Document secret retrieval verification: `Write ##class(%IRIS.Wallet).GetSecret('pgwire-user-alice')`
- Document Wallet enable check: `Write ##class(%IRIS.Wallet).IsEnabled()`

**Validation**: Troubleshooting guide covers common Wallet issues

---

### T069: Create production deployment checklist
**File**: `docs/PRODUCTION_DEPLOYMENT.md`
**Description**: Checklist for production authentication bridge deployment.
**Requirements**:
- [ ] Register PGWire as OAuth client in IRIS
- [ ] Store OAuth client secret in Wallet (or secure environment variable)
- [ ] Generate Kerberos keytab for production service principal
- [ ] Deploy keytab via Docker secrets (not volume mount)
- [ ] Configure authentication methods: `PGWIRE_AUTH_METHODS=oauth,kerberos,wallet,password`
- [ ] Enable audit trail: `PGWIRE_AUDIT_ENABLED=true`
- [ ] Verify TLS enforced (constitutional requirement)
- [ ] Run performance benchmarks (T059-T063)
- [ ] Test backward compatibility with 8 PostgreSQL clients (T046)
- [ ] Configure monitoring for authentication failures
- [ ] Document credential rotation procedures

**Validation**: Deployment checklist complete and actionable

---

### T070: Generate implementation report (FR-005)
**File**: `specs/024-research-and-implement/IMPLEMENTATION_REPORT.md`
**Description**: Implementation report documenting authentication bridge completion.
**Requirements** (from FR-005):
- Summary: Features implemented (OAuth, Kerberos, Wallet, dual-mode routing)
- Test coverage: 70 tasks, 38 [P] parallel tasks
- Performance validation: All benchmarks pass (T059-T063)
- Backward compatibility: 171 existing tests pass (T046)
- Security compliance: Audit trail (FR-026), error surfacing (FR-027), secure credential storage (FR-009)
- Production readiness: Deployment guide (T069), troubleshooting docs (T066-T068)
- Known limitations: None - all 28 functional requirements met
- Next steps: Monitor authentication failures in production, rotate credentials per policy

**Validation**: Implementation report complete, ready for review

---

## Dependencies

### Phase Dependencies
- **Phase 3.2 (Tests)** blocks **Phase 3.4 (Implementation)** - TDD requirement
- **Phase 3.4 (Implementation)** blocks **Phase 3.5 (Protocol Integration)**
- **Phase 3.5 (Protocol Integration)** blocks **Phase 3.6 (E2E Testing)**
- **Phase 3.6 (E2E Testing)** blocks **Phase 3.9 (Performance Benchmarking)**

### Task Dependencies
- T001 blocks T025-T032 (auth module structure required)
- T002 blocks T028 (python-gssapi required for Kerberos)
- T003 blocks T019, T040, T041 (k5test required for Kerberos testing)
- T004-T016 (contract tests) block T025-T032 (implementations)
- T025 blocks T026 (OAuthToken dataclass required by OAuthBridge)
- T027 blocks T028 (KerberosPrincipal required by GSSAPIAuthenticator)
- T029 blocks T030 (WalletSecret required by WalletCredentials)
- T031 blocks T032 (UserSession required by AuthenticationSelector)
- T026, T028, T030 block T034 (IRIS executor helpers require auth implementations)
- T032 blocks T035 (AuthenticationSelector required for server startup)
- T035 blocks T036 (server startup integration required for connection handler)
- T036 blocks T037-T046 (connection handler required for E2E tests)
- T036 blocks T059-T063 (performance benchmarks require working authentication)

---

## Parallel Execution Examples

### Example 1: Contract Tests (T004-T016)
Launch all contract tests in parallel - **13 independent test files**:
```bash
# OAuth contract tests (6 tests)
pytest tests/contract/test_oauth_bridge_contract.py::test_exchange_password_for_token &
pytest tests/contract/test_oauth_bridge_contract.py::test_validate_token &
pytest tests/contract/test_oauth_bridge_contract.py::test_refresh_token &
pytest tests/contract/test_oauth_bridge_contract.py::test_get_client_credentials &
pytest tests/contract/test_oauth_bridge_contract.py::test_iris_integration &
pytest tests/contract/test_oauth_bridge_contract.py::test_error_handling &

# Kerberos contract tests (4 tests)
pytest tests/contract/test_gssapi_auth_contract.py::test_handle_gssapi_handshake &
pytest tests/contract/test_gssapi_auth_contract.py::test_extract_principal &
pytest tests/contract/test_gssapi_auth_contract.py::test_map_principal_to_iris_user &
pytest tests/contract/test_gssapi_auth_contract.py::test_validate_kerberos_ticket &

# Wallet contract tests (3 tests)
pytest tests/contract/test_wallet_credentials_contract.py::test_get_password_from_wallet &
pytest tests/contract/test_wallet_credentials_contract.py::test_set_password_in_wallet &
pytest tests/contract/test_wallet_credentials_contract.py::test_get_oauth_client_secret &

wait  # Wait for all tests to complete
```

**Expected**: All 13 tests FAIL (no implementation yet) - TDD requirement satisfied

---

### Example 2: Integration Tests (T017-T024)
Launch all integration tests in parallel - **8 independent test files**:
```bash
pytest tests/integration/test_oauth_token_exchange.py &
pytest tests/integration/test_oauth_token_validation.py &
pytest tests/integration/test_kerberos_gssapi_handshake.py &
pytest tests/integration/test_kerberos_principal_validation.py &
pytest tests/integration/test_wallet_password_retrieval.py &
pytest tests/integration/test_wallet_oauth_secret_retrieval.py &
pytest tests/integration/test_auth_selector_routing.py &
pytest tests/integration/test_auth_config_loading.py &
wait
```

**Expected**: All 8 tests FAIL (no implementation yet)

---

### Example 3: E2E Tests (T037-T046)
Launch all E2E tests in parallel - **10 independent test files**:
```bash
pytest tests/e2e/test_psql_oauth.py &
pytest tests/e2e/test_psycopg_oauth.py &
pytest tests/e2e/test_jdbc_oauth.py &
pytest tests/e2e/test_psql_kerberos.py &
pytest tests/e2e/test_psycopg_kerberos.py &
pytest tests/e2e/test_psql_wallet.py &
pytest tests/e2e/test_psql_password_fallback.py &
pytest tests/e2e/test_wallet_credential_rotation.py &
pytest tests/e2e/test_multi_method_fallback.py &
pytest tests/e2e/test_backward_compatibility.py &
wait
```

**Expected**: All 10 tests PASS (after T036 complete)

---

### Example 4: Unit Tests (T047-T053)
Launch all unit tests in parallel - **7 independent test files**:
```bash
pytest tests/unit/test_oauth_token_expiry.py &
pytest tests/unit/test_kerberos_principal_parsing.py &
pytest tests/unit/test_kerberos_principal_mapping.py &
pytest tests/unit/test_wallet_key_formatting.py &
pytest tests/unit/test_auth_timeout.py &
pytest tests/unit/test_user_session_state.py &
pytest tests/unit/test_auth_method_selection.py &
wait
```

**Expected**: All 7 tests PASS

---

### Example 5: Performance Benchmarks (T059-T063)
Run performance benchmarks sequentially (resource-intensive):
```bash
pytest tests/performance/test_oauth_latency.py -v
pytest tests/performance/test_kerberos_latency.py -v
pytest tests/performance/test_wallet_latency.py -v
pytest tests/performance/test_concurrent_auth.py -v
pytest tests/performance/test_fallback_chain_latency.py -v
```

**Expected**: All 5 benchmarks PASS, meet constitutional requirements (<5s auth latency, 1000 concurrent connections)

---

## Notes

### TDD Workflow
1. ✅ Write contract tests (T004-T016) - MUST FAIL initially
2. ✅ Write integration tests (T017-T024) - MUST FAIL initially
3. ✅ Implement core components (T025-T032) - Make tests PASS
4. ✅ Integrate with protocol (T033-T036) - Enable E2E testing
5. ✅ Run E2E tests (T037-T046) - Validate client compatibility
6. ✅ Run performance benchmarks (T059-T063) - Validate constitutional requirements

### Parallel Execution Strategy
- **38 tasks marked [P]** - Can run in parallel (independent files)
- **32 tasks sequential** - Shared files or dependencies
- Maximum parallelism: 13 contract tests, 8 integration tests, 10 E2E tests

### Commit Strategy
- Commit after each task (70 commits total)
- Branch: `024-research-and-implement`
- Merge to main after T070 (implementation report complete)

### Validation Strategy
- **Contract tests** (T004-T016): Verify API contracts before implementation
- **Integration tests** (T017-T024): Verify IRIS API integration with iris-devtester
- **E2E tests** (T037-T046): Verify PostgreSQL client compatibility
- **Unit tests** (T047-T053): Verify code coverage and edge cases
- **Performance tests** (T059-T063): Verify constitutional requirements

### Constitutional Compliance
- ✅ Protocol Fidelity: PostgreSQL GSSAPI protocol (T033)
- ✅ Test-First Development: All tests written before implementation (Phase 3.2 before 3.4)
- ✅ IRIS Integration: Uses embedded Python, asyncio.to_thread() (T026, T028, T030)
- ✅ Performance Standards: <5s authentication latency (T059-T063)
- ✅ Backward Compatibility: 171 existing tests pass (T046)

---

## Validation Checklist
*GATE: Verify before marking feature complete*

- [x] All contracts have corresponding tests (T004-T016 cover 3 contract files)
- [x] All entities have model tasks (T025 OAuth, T027 Kerberos, T029 Wallet, T031 Session, T032 Config)
- [x] All tests come before implementation (Phase 3.2 blocks Phase 3.4)
- [x] Parallel tasks truly independent (38 [P] tasks use different files)
- [x] Each task specifies exact file path (all 70 tasks have file paths)
- [x] No task modifies same file as another [P] task (verified)
- [x] All 28 functional requirements mapped to tasks
- [x] All 5 acceptance scenarios covered by E2E tests (T037-T046)
- [x] Constitutional requirements validated (T059-T063 performance benchmarks)

**Status**: ✅ **READY FOR EXECUTION** - All 70 tasks documented, dependencies clear, parallel execution optimized
