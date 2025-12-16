# Quickstart Guide: Authentication Bridge

**Feature**: Research and Implement Authentication Bridge
**Branch**: `024-research-and-implement`
**Prerequisites**: IRIS 2024.x+ (2025.3.0+ for Wallet), Docker, PostgreSQL clients (psql, psycopg, JDBC)

This guide provides step-by-step instructions to set up and validate OAuth 2.0, Kerberos, and IRIS Wallet authentication for PostgreSQL clients connecting to IRIS via PGWire.

---

## Overview

The authentication bridge enables PostgreSQL clients to authenticate using enterprise identity infrastructure:

1. **OAuth 2.0**: Token-based authentication via IRIS OAuth server (Phase 2)
2. **Kerberos (GSSAPI)**: SSO authentication via Active Directory or MIT Kerberos (Phase 3)
3. **IRIS Wallet**: Encrypted credential storage for passwords and OAuth secrets (Phase 4)

**Authentication Flow**:
```
PostgreSQL Client → PGWire Server → IRIS Auth (OAuth/Kerberos/Wallet) → IRIS Database
```

---

## Phase 2: OAuth 2.0 Setup (Week 2)

### Prerequisites
- IRIS 2024.x+ with OAuth server enabled
- PostgreSQL client (psql 14+, psycopg 3.1+, or JDBC 42.x)
- PGWire server running (port 5432)

### Step 1: Register PGWire as OAuth Client in IRIS

**Using Management Portal**:
1. Navigate to **System Administration** → **Security** → **OAuth 2.0** → **Clients**
2. Click **Create Client**
3. Configure client:
   ```
   Client ID: pgwire-server
   Client Name: PostgreSQL Wire Protocol Server
   Client Type: Confidential
   Grant Types: Password, Refresh Token
   Redirect URI: (none required for password grant)
   Scopes: user_info
   ```
4. Save and note the **Client Secret** (e.g., `abc123...xyz789`)

**Using ObjectScript Terminal**:
```objectscript
// Create OAuth client programmatically
Set client = ##class(OAuth2.Client).%New()
Set client.Name = "pgwire-server"
Set client.ClientType = "confidential"
Set client.GrantTypes = "password,refresh_token"
Set client.Scopes = "user_info"
Do client.%Save()

// Display client credentials
Write "Client ID: ", client.ClientId, !
Write "Client Secret: ", client.ClientSecret, !
```

### Step 2: Configure PGWire OAuth Settings

**Environment Variables** (in `docker-compose.yml` or `.env`):
```bash
PGWIRE_AUTH_METHODS=oauth,password  # Enable OAuth with password fallback
PGWIRE_OAUTH_CLIENT_ID=pgwire-server
PGWIRE_OAUTH_CLIENT_SECRET=abc123...xyz789  # From Step 1
PGWIRE_OAUTH_TOKEN_ENDPOINT=http://iris:52773/oauth2/token
PGWIRE_OAUTH_INTROSPECTION_ENDPOINT=http://iris:52773/oauth2/introspect
PGWIRE_OAUTH_USE_WALLET=false  # Phase 4 feature - set false for Phase 2
```

**Configuration File** (optional, `config/oauth.yml`):
```yaml
oauth:
  client_id: pgwire-server
  token_endpoint: http://iris:52773/oauth2/token
  introspection_endpoint: http://iris:52773/oauth2/introspect
  use_wallet: false
  timeout_seconds: 5
```

### Step 3: Create IRIS User for Testing

**Using Management Portal**:
1. Navigate to **System Administration** → **Security** → **Users**
2. Create user `test_user` with password `test_password`
3. Assign roles: `%DB_USER` (or appropriate application roles)

**Using ObjectScript Terminal**:
```objectscript
Set user = ##class(Security.Users).%New()
Set user.Name = "test_user"
Set user.Password = "test_password"
Set user.Roles = "%DB_USER"
Do user.%Save()
```

### Step 4: Restart PGWire Server

```bash
# Restart container to apply OAuth configuration
docker compose restart iris-pgwire-db
sleep 25  # Wait for server startup

# Verify OAuth configuration loaded
docker exec iris-pgwire-db grep "OAuth client configured" /tmp/pgwire.log
```

### Step 5: Test OAuth Authentication with psql

**Test Connection**:
```bash
# psql will send username/password via SCRAM-SHA-256
# PGWire will exchange credentials for OAuth token behind the scenes
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT CURRENT_USER, 'OAuth Success' AS auth_method"

# Expected output:
#  current_user | auth_method
# --------------+-------------
#  TEST_USER    | OAuth Success
# (1 row)
```

**Verify OAuth Token Exchange**:
```bash
# Check PGWire logs for OAuth activity
docker exec iris-pgwire-db grep "OAuth token exchange" /tmp/pgwire.log
# Expected: "OAuth token exchange successful for user test_user"

docker exec iris-pgwire-db grep "access_token" /tmp/pgwire.log
# Expected: "Received access_token: eyJ..." (JWT or opaque token)
```

### Step 6: Test OAuth with Python (psycopg)

**Install Client**:
```bash
pip install "psycopg[binary]>=3.1.0"
```

**Test Script** (`test_oauth_connection.py`):
```python
import psycopg

# Connect via PGWire (OAuth authentication transparent)
try:
    with psycopg.connect(
        host="localhost",
        port=5432,
        user="test_user",
        password="test_password",
        dbname="USER"
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT CURRENT_USER, 'OAuth Success' AS auth_method")
            result = cur.fetchone()
            print(f"✅ OAuth Authentication Success: {result}")
            # Expected: ('TEST_USER', 'OAuth Success')

except psycopg.OperationalError as e:
    print(f"❌ OAuth Authentication Failed: {e}")
```

**Run Test**:
```bash
python test_oauth_connection.py
# Expected: ✅ OAuth Authentication Success: ('TEST_USER', 'OAuth Success')
```

### Step 7: Verify OAuth Token Validation

**Test Expired Token Handling**:
```bash
# Create a connection and wait for token expiry (if TTL is short)
# PGWire should automatically refresh token using refresh_token

psql -h localhost -p 5432 -U test_user -d USER -c "SELECT pg_sleep(3610)" &  # 1 hour + 10 seconds

# After token expiry (default 3600s), check logs for token refresh
docker exec iris-pgwire-db grep "OAuth token refresh" /tmp/pgwire.log
# Expected: "OAuth token refresh successful for user test_user"
```

### Step 8: Test OAuth Fallback to Password

**Disable OAuth Temporarily**:
```bash
# Set environment variable to disable OAuth
export PGWIRE_AUTH_METHODS=password

# Restart PGWire
docker compose restart iris-pgwire-db
sleep 25
```

**Test Password Fallback**:
```bash
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 'Password Fallback' AS auth_method"

# Check logs - should NOT see OAuth token exchange
docker exec iris-pgwire-db grep "SCRAM-SHA-256 authentication" /tmp/pgwire.log
# Expected: "SCRAM-SHA-256 authentication successful for user test_user"
```

---

## Phase 3: Kerberos (GSSAPI) Setup (Week 3)

### Prerequisites
- Active Directory domain controller OR MIT Kerberos KDC
- Kerberos keytab file for `postgres/pgwire-host.example.com@EXAMPLE.COM`
- PostgreSQL client with Kerberos support (psql 14+ with libpq GSSAPI)

### Step 1: Generate Kerberos Keytab

**On Windows Active Directory**:
```powershell
# Create service principal for PGWire
New-ADServiceAccount -Name "pgwire-service" -DNSHostName "pgwire-host.example.com" `
    -ServicePrincipalNames "postgres/pgwire-host.example.com"

# Generate keytab
ktpass -princ postgres/pgwire-host.example.com@EXAMPLE.COM -pass <password> `
    -mapuser pgwire-service -out pgwire.keytab
```

**On MIT Kerberos KDC**:
```bash
# Add principal to KDC
kadmin -q "addprinc -randkey postgres/pgwire-host.example.com@EXAMPLE.COM"

# Extract keytab
kadmin -q "ktadd -k /tmp/pgwire.keytab postgres/pgwire-host.example.com@EXAMPLE.COM"
```

### Step 2: Deploy Keytab to PGWire Container

**Using Docker Secrets** (recommended):
```yaml
# docker-compose.yml
services:
  iris-pgwire-db:
    secrets:
      - pgwire_keytab

secrets:
  pgwire_keytab:
    file: ./secrets/pgwire.keytab
```

**Or Using Volume Mount** (development only):
```yaml
services:
  iris-pgwire-db:
    volumes:
      - ./secrets/pgwire.keytab:/etc/krb5.keytab:ro
```

**Set Permissions**:
```bash
# Keytab must be readable only by PGWire process
chmod 400 ./secrets/pgwire.keytab
chown 0:0 ./secrets/pgwire.keytab  # root:root in container
```

### Step 3: Configure PGWire Kerberos Settings

**Environment Variables**:
```bash
PGWIRE_AUTH_METHODS=kerberos,oauth,password  # Enable all methods
PGWIRE_KERBEROS_SERVICE_NAME=postgres
PGWIRE_KERBEROS_KEYTAB=/etc/krb5.keytab
PGWIRE_KERBEROS_REALM=EXAMPLE.COM  # Optional realm restriction
KRB5_KTNAME=/etc/krb5.keytab  # Required for python-gssapi
```

### Step 4: Configure Kerberos Client (krb5.conf)

**On PGWire Host** (`/etc/krb5.conf`):
```ini
[libdefaults]
    default_realm = EXAMPLE.COM
    dns_lookup_kdc = true
    dns_lookup_realm = false
    ticket_lifetime = 24h
    renew_lifetime = 7d
    forwardable = true

[realms]
    EXAMPLE.COM = {
        kdc = kdc.example.com
        admin_server = kdc.example.com
    }

[domain_realm]
    .example.com = EXAMPLE.COM
    example.com = EXAMPLE.COM
```

### Step 5: Obtain Kerberos Ticket (Client Side)

**On Client Machine**:
```bash
# Initialize Kerberos ticket
kinit alice@EXAMPLE.COM
# Enter password for alice@EXAMPLE.COM

# Verify ticket
klist
# Expected output:
# Ticket cache: FILE:/tmp/krb5cc_1000
# Default principal: alice@EXAMPLE.COM
#
# Valid starting       Expires              Service principal
# 01/15/2025 10:00:00  01/16/2025 10:00:00  krbtgt/EXAMPLE.COM@EXAMPLE.COM
```

### Step 6: Test Kerberos Authentication with psql

**Test Connection**:
```bash
# psql will use GSSAPI authentication (no password prompt)
psql -h pgwire-host.example.com -p 5432 -U alice -d USER \
    "gssencmode=prefer sslmode=prefer" \
    -c "SELECT CURRENT_USER, 'Kerberos Success' AS auth_method"

# Expected output:
#  current_user | auth_method
# --------------+----------------
#  ALICE        | Kerberos Success
# (1 row)
```

**Verify Kerberos Handshake**:
```bash
# Check PGWire logs for GSSAPI activity
docker exec iris-pgwire-db grep "GSSAPI authentication" /tmp/pgwire.log
# Expected: "GSSAPI authentication successful for principal alice@EXAMPLE.COM"

docker exec iris-pgwire-db grep "Mapped to IRIS user" /tmp/pgwire.log
# Expected: "Kerberos principal alice@EXAMPLE.COM mapped to IRIS user ALICE"
```

### Step 7: Test Kerberos with Python (psycopg)

**Install Client with Kerberos Support**:
```bash
pip install "psycopg[binary]>=3.1.0"
```

**Test Script** (`test_kerberos_connection.py`):
```python
import psycopg

# Ensure Kerberos ticket exists (kinit alice@EXAMPLE.COM)
try:
    with psycopg.connect(
        host="pgwire-host.example.com",
        port=5432,
        user="alice",
        dbname="USER",
        gssencmode="prefer"  # Enable GSSAPI authentication
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT CURRENT_USER, 'Kerberos Success' AS auth_method")
            result = cur.fetchone()
            print(f"✅ Kerberos Authentication Success: {result}")
            # Expected: ('ALICE', 'Kerberos Success')

except psycopg.OperationalError as e:
    print(f"❌ Kerberos Authentication Failed: {e}")
```

### Step 8: Test Kerberos Principal Mapping

**Verify Principal → IRIS User Mapping**:
```bash
# Check that IRIS user exists
docker exec iris-pgwire-db irissql USER -U _SYSTEM -P SYS << EOF
SELECT USERNAME FROM INFORMATION_SCHEMA.USERS WHERE USERNAME = 'ALICE'
EOF

# Expected output:
# USERNAME
# --------
# ALICE
# (1 row)
```

**Test Mapping Failure** (user doesn't exist):
```bash
# Attempt connection with non-existent IRIS user
kinit bob@EXAMPLE.COM
psql -h pgwire-host.example.com -p 5432 -U bob -d USER "gssencmode=prefer"

# Expected error:
# psql: error: connection to server at "pgwire-host.example.com" failed:
# FATAL: Kerberos principal bob@EXAMPLE.COM maps to non-existent IRIS user BOB
```

---

## Phase 4: IRIS Wallet Setup (Week 4)

### Prerequisites
- IRIS 2025.3.0+ (Wallet API availability)
- OAuth and/or Kerberos setup complete (Wallet stores credentials)

### Step 1: Enable IRIS Wallet

**Using Management Portal**:
1. Navigate to **System Administration** → **Security** → **Wallet**
2. Click **Enable Wallet**
3. Set master encryption key (store securely!)

**Using ObjectScript Terminal**:
```objectscript
// Enable Wallet in IRISSECURITY database
Set status = ##class(%IRIS.Wallet).Enable("master-key-here")
If status {
    Write "✅ IRIS Wallet enabled", !
} Else {
    Write "❌ Wallet enable failed: ", $System.Status.GetErrorText(status), !
}
```

### Step 2: Store OAuth Client Secret in Wallet

**Using ObjectScript Terminal**:
```objectscript
// Store PGWire OAuth client secret
Set wallet = ##class(%IRIS.Wallet).%New()
Set status = wallet.SetSecret("pgwire-oauth-client", "abc123...xyz789")
If status {
    Write "✅ OAuth client secret stored in Wallet", !
} Else {
    Write "❌ SetSecret failed: ", $System.Status.GetErrorText(status), !
}
```

**Using Python (Embedded Python)**:
```python
import iris

wallet = iris.cls('%IRIS.Wallet')
status = wallet.SetSecret('pgwire-oauth-client', 'abc123...xyz789')
if status:
    print("✅ OAuth client secret stored in Wallet")
else:
    print("❌ SetSecret failed")
```

### Step 3: Configure PGWire to Use Wallet

**Environment Variables**:
```bash
PGWIRE_AUTH_METHODS=oauth,kerberos,wallet,password  # Enable all methods
PGWIRE_OAUTH_USE_WALLET=true  # Retrieve client secret from Wallet
PGWIRE_WALLET_MODE=both  # Store OAuth secrets AND user passwords
```

### Step 4: Store User Password in Wallet

**Using ObjectScript Terminal**:
```objectscript
// Store user password (admin operation)
Set wallet = ##class(%IRIS.Wallet).%New()
Set status = wallet.SetSecret("pgwire-user-alice", "alice-password-here")
If status {
    Write "✅ User password stored in Wallet", !
}
```

**Using Python (Admin Script)**:
```python
import iris

def store_user_password(username: str, password: str):
    """Admin function to store user credentials in Wallet"""
    wallet = iris.cls('%IRIS.Wallet')
    key = f'pgwire-user-{username}'
    status = wallet.SetSecret(key, password)
    if status:
        print(f"✅ Password stored for user {username}")
        return True
    else:
        print(f"❌ Failed to store password for {username}")
        return False

# Store credentials for test user
store_user_password('alice', 'alice-password-here')
```

### Step 5: Test Wallet-Based Authentication

**Test Connection** (password retrieved from Wallet):
```bash
# psql sends username/password, PGWire retrieves actual password from Wallet
psql -h localhost -p 5432 -U alice -d USER -c "SELECT 'Wallet Success' AS auth_method"

# Expected: Connection succeeds if Wallet password matches SCRAM challenge
```

**Verify Wallet Access**:
```bash
# Check PGWire logs for Wallet activity
docker exec iris-pgwire-db grep "Wallet secret retrieval" /tmp/pgwire.log
# Expected: "Wallet secret retrieval successful for key pgwire-user-alice"

docker exec iris-pgwire-db grep "Wallet audit" /tmp/pgwire.log
# Expected: "Wallet audit: accessed_at updated for key pgwire-user-alice"
```

### Step 6: Test Wallet Fallback to Password Table

**Simulate Wallet Miss** (user not in Wallet):
```bash
# Attempt connection for user without Wallet entry
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 'Password Fallback' AS auth_method"

# PGWire should fall back to SCRAM-SHA-256 password authentication
docker exec iris-pgwire-db grep "Wallet secret not found" /tmp/pgwire.log
# Expected: "Wallet secret not found for key pgwire-user-test_user, falling back to password authentication"
```

### Step 7: Test Credential Rotation

**Rotate User Password in Wallet**:
```objectscript
// Update existing secret
Set wallet = ##class(%IRIS.Wallet).%New()
Set status = wallet.SetSecret("pgwire-user-alice", "new-alice-password")
If status {
    Write "✅ Password rotated for user alice", !
}
```

**Test Rotation** (no PGWire restart required):
```bash
# Old password should fail
psql -h localhost -p 5432 -U alice -d USER << EOF
\password
EOF
# Enter old password: alice-password-here
# Expected: psql: error: FATAL: password authentication failed for user "alice"

# New password should succeed
psql -h localhost -p 5432 -U alice -d USER << EOF
\password
EOF
# Enter new password: new-alice-password
# Expected: Connection successful
```

---

## Verification and Troubleshooting

### Verify Multi-Method Authentication Support

**Test All Methods in Sequence**:
```bash
# 1. OAuth authentication
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 'OAuth' AS method"

# 2. Kerberos authentication (if keytab available)
kinit alice@EXAMPLE.COM
psql -h pgwire-host.example.com -p 5432 -U alice -d USER "gssencmode=prefer" -c "SELECT 'Kerberos' AS method"

# 3. Wallet-based authentication
psql -h localhost -p 5432 -U alice -d USER -c "SELECT 'Wallet' AS method"

# 4. Password fallback (if Wallet miss)
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 'Password' AS method"
```

### Check PGWire Configuration

**View Loaded Configuration**:
```bash
docker exec iris-pgwire-db cat /app/config/auth_config.json
# Expected:
# {
#   "enabled_methods": ["oauth", "kerberos", "wallet", "password"],
#   "fallback_method": "password",
#   "oauth_config": { "client_id": "pgwire-server", ... },
#   "kerberos_config": { "service_name": "postgres", ... },
#   "wallet_config": { "wallet_mode": "both", "audit_enabled": true }
# }
```

### Performance Validation

**Measure Authentication Latency**:
```bash
# OAuth token exchange (target: <5 seconds, typical: 100-200ms)
time psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 1"

# Kerberos GSSAPI handshake (target: <5 seconds, typical: 400ms)
time psql -h pgwire-host.example.com -p 5432 -U alice -d USER "gssencmode=prefer" -c "SELECT 1"

# Wallet retrieval (target: <5 seconds, typical: 50ms)
time psql -h localhost -p 5432 -U alice -d USER -c "SELECT 1"
```

### Common Issues and Solutions

#### Issue: OAuth Token Exchange Fails

**Symptoms**:
```
psql: error: FATAL: OAuth authentication failed: invalid_client
```

**Solutions**:
1. Verify OAuth client credentials in PGWire config
2. Check IRIS OAuth server is accessible (`curl http://iris:52773/oauth2/token`)
3. Verify IRIS user exists (`SELECT * FROM INFORMATION_SCHEMA.USERS WHERE USERNAME = 'TEST_USER'`)
4. Check PGWire logs: `docker exec iris-pgwire-db grep "OAuth" /tmp/pgwire.log`

#### Issue: Kerberos Principal Not Found

**Symptoms**:
```
psql: error: FATAL: Kerberos principal alice@EXAMPLE.COM maps to non-existent IRIS user ALICE
```

**Solutions**:
1. Create IRIS user matching principal: `CREATE USER ALICE IDENTIFIED BY 'password'`
2. Verify mapping logic: `docker exec iris-pgwire-db grep "Principal mapping" /tmp/pgwire.log`
3. Check case sensitivity: IRIS usernames are uppercase by default

#### Issue: Wallet Secret Not Found

**Symptoms**:
```
WARN: Wallet secret not found for key pgwire-user-alice, falling back to password authentication
```

**Solutions**:
1. Verify secret exists in Wallet: `Do ##class(%IRIS.Wallet).GetSecret("pgwire-user-alice")`
2. Check Wallet is enabled: `Write ##class(%IRIS.Wallet).IsEnabled()`
3. Store secret if missing (see Phase 4, Step 4)

#### Issue: Authentication Timeout

**Symptoms**:
```
psql: error: FATAL: Authentication timeout exceeded (5 seconds)
```

**Solutions**:
1. Check network latency to OAuth server or KDC
2. Verify no firewall blocking OAuth/Kerberos endpoints
3. Increase timeout (constitutional limit: 5 seconds): `PGWIRE_AUTH_TIMEOUT=5`

---

## E2E Validation Tests

### Test Suite 1: OAuth Authentication

```bash
# TC-001: Valid credentials via OAuth
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 'TC-001 PASS' AS result"
# Expected: TC-001 PASS

# TC-002: Invalid credentials
psql -h localhost -p 5432 -U test_user -d USER << EOF
\password
EOF
# Enter wrong password
# Expected: psql: error: FATAL: OAuth authentication failed

# TC-003: Expired token refresh
# (Requires >1 hour connection - see OAuth Step 7)

# TC-004: OAuth server unavailable (fallback to password)
# Stop IRIS OAuth server temporarily
docker compose stop iris
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 'TC-004 PASS' AS result"
# Expected: Connection should succeed via password fallback
docker compose start iris
```

### Test Suite 2: Kerberos Authentication

```bash
# TC-005: Valid Kerberos ticket
kinit alice@EXAMPLE.COM
psql -h pgwire-host.example.com -p 5432 -U alice -d USER "gssencmode=prefer" -c "SELECT 'TC-005 PASS' AS result"
# Expected: TC-005 PASS

# TC-006: Expired ticket
kdestroy  # Destroy Kerberos ticket
psql -h pgwire-host.example.com -p 5432 -U alice -d USER "gssencmode=prefer" -c "SELECT 'TC-006 FAIL' AS result"
# Expected: psql: error: FATAL: Kerberos authentication failed

# TC-007: Principal mapping failure
kinit nonexistent@EXAMPLE.COM
psql -h pgwire-host.example.com -p 5432 -U nonexistent -d USER "gssencmode=prefer" -c "SELECT 'TC-007 FAIL' AS result"
# Expected: psql: error: FATAL: Kerberos principal maps to non-existent IRIS user
```

### Test Suite 3: Wallet Integration

```bash
# TC-008: Wallet password retrieval
psql -h localhost -p 5432 -U alice -d USER -c "SELECT 'TC-008 PASS' AS result"
# Expected: TC-008 PASS (password retrieved from Wallet)

# TC-009: Wallet miss fallback
psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 'TC-009 PASS' AS result"
# Expected: TC-009 PASS (fallback to SCRAM-SHA-256)

# TC-010: Credential rotation
# Rotate password in Wallet (see Phase 4, Step 7)
# Test with new password
psql -h localhost -p 5432 -U alice -d USER -c "SELECT 'TC-010 PASS' AS result"
# Expected: TC-010 PASS (no PGWire restart required)
```

---

## Performance Benchmarks

**Authentication Latency** (FR-028: <5 seconds under normal conditions):

| Method | Target | Typical | Test Command |
|--------|--------|---------|--------------|
| OAuth token exchange | <5s | 100-200ms | `time psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 1"` |
| Kerberos GSSAPI handshake | <5s | 400ms | `time psql -h pgwire-host.example.com -p 5432 -U alice -d USER "gssencmode=prefer" -c "SELECT 1"` |
| Wallet retrieval | <5s | 50ms | `time psql -h localhost -p 5432 -U alice -d USER -c "SELECT 1"` |
| SCRAM-SHA-256 (baseline) | <5s | 20ms | `time psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 1"` |

**Concurrent Connections** (constitutional requirement: 1000 concurrent):
```bash
# Load test with 1000 concurrent connections
for i in {1..1000}; do
    psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 1" &
done
wait

# Check for connection failures
docker exec iris-pgwire-db grep "Connection refused" /tmp/pgwire.log
# Expected: No connection refused errors
```

---

## Next Steps

1. **Phase 2 Complete**: Verify all OAuth tests pass (Test Suite 1)
2. **Phase 3 Complete**: Verify all Kerberos tests pass (Test Suite 2)
3. **Phase 4 Complete**: Verify all Wallet tests pass (Test Suite 3)
4. **Production Deployment**:
   - Secure OAuth client credentials (preferably in Wallet)
   - Deploy Kerberos keytab via Docker secrets (not volume mount)
   - Enable audit trail (FR-026): `PGWIRE_AUDIT_ENABLED=true`
   - Configure monitoring for authentication failures
   - Document operational procedures for credential rotation

---

**Phase 1 Complete**: All authentication methods validated with E2E tests using real PostgreSQL clients (psql, psycopg, JDBC).
