# Production Deployment Checklist

**Feature**: 024-research-and-implement (Authentication Bridge)
**Last Updated**: 2025-11-15
**Target**: Production deployment of PGWire with enterprise authentication

This guide provides step-by-step procedures for deploying PGWire with OAuth 2.0, Kerberos GSSAPI, and IRIS Wallet authentication in production environments.

---

## Prerequisites

Before beginning deployment, ensure the following are available:

- ✅ **IRIS Database**: InterSystems IRIS 2025.3.0+ with OAuth server enabled
- ✅ **IRIS Wallet**: Available for credential storage (IRIS 2025.3.0+)
- ✅ **Kerberos KDC**: Active Directory or MIT Kerberos (for GSSAPI auth)
- ✅ **TLS Certificates**: Valid SSL/TLS certificates for production endpoints
- ✅ **Network Access**: Firewall rules for ports 5432 (PGWire), 1972 (IRIS), 52773 (IRIS OAuth)

---

## Phase 1: IRIS OAuth Server Configuration

### Step 1.1: Enable OAuth 2.0 in IRIS

```objectscript
# From IRIS Terminal (_SYSTEM user)

# 1. Enable OAuth server
Do ##class(%SYS.OAuth2.Server).Enable()

# 2. Verify OAuth server is enabled
Write ##class(%SYS.OAuth2.Server).IsEnabled()
# Should return: 1
```

### Step 1.2: Register PGWire OAuth Client

```objectscript
# From IRIS Terminal

# Create OAuth client for PGWire
Set client = ##class(OAuth2.Client).%New()
Set client.ClientId = "pgwire-server"
Set client.Name = "PGWire Server"
Set client.GrantTypes = "password,refresh_token"
Set client.AccessTokenTTL = 3600  # 1 hour token lifetime
Set client.RefreshTokenTTL = 86400  # 24 hour refresh token

# IMPORTANT: Generate strong client secret
Set client.ClientSecret = "GENERATE_SECURE_SECRET_HERE"  # Use password generator (32+ chars)

# Save client
Write client.%Save()
# Should return positive ID
```

**Security Recommendation**: Use a cryptographically secure password generator:
```python
import secrets
import string

def generate_client_secret(length=48):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

client_secret = generate_client_secret()
print(f"Generated client secret: {client_secret}")
```

### Step 1.3: Store OAuth Client Secret in IRIS Wallet

```objectscript
# From IRIS Terminal

# Store client secret in Wallet (recommended over environment variables)
Do ##class(%IRIS.Wallet).SetSecret("pgwire-oauth-client", "YOUR_CLIENT_SECRET_FROM_STEP_1.2")

# Verify stored
Write ##class(%IRIS.Wallet).GetSecret("pgwire-oauth-client")
# Should return: YOUR_CLIENT_SECRET_FROM_STEP_1.2
```

### Step 1.4: Configure OAuth Token Endpoint

**Environment Configuration** (on PGWire server):
```bash
# OAuth server endpoint (default)
export OAUTH_TOKEN_ENDPOINT=http://iris:52773/oauth2/token

# Production: Use HTTPS with valid certificate
export OAUTH_TOKEN_ENDPOINT=https://iris.example.com:52773/oauth2/token

# OAuth client credentials (or use Wallet)
export OAUTH_CLIENT_ID=pgwire-server
# export OAUTH_CLIENT_SECRET=...  # OPTIONAL - use Wallet instead
```

### Step 1.5: Verify OAuth Server Accessibility

```bash
# From PGWire server, test OAuth endpoint
curl -v http://iris:52773/oauth2/token

# Expected: 401 Unauthorized (server is responding)
# Problem: Connection refused → Check IRIS OAuth server enabled
```

**Checklist**:
- [ ] OAuth server enabled in IRIS
- [ ] OAuth client "pgwire-server" registered
- [ ] Client secret generated (48+ characters)
- [ ] Client secret stored in IRIS Wallet
- [ ] OAuth endpoint accessible from PGWire server
- [ ] Token TTL configured (3600s recommended)

---

## Phase 2: IRIS Wallet Setup

### Step 2.1: Verify Wallet Availability

```objectscript
# From IRIS Terminal
Write ##class(%IRIS.Wallet).IsEnabled()
# Should return: 1

# If returns 0:
# - IRIS version may be too old (requires 2025.3.0+)
# - Wallet feature not installed
```

### Step 2.2: Store User Passwords in Wallet

**Bulk User Password Storage**:
```objectscript
# From IRIS Terminal

# Store passwords for users (admin operation)
Do ##class(%IRIS.Wallet).SetSecret("pgwire-user-alice", "secure_password_for_alice_123")
Do ##class(%IRIS.Wallet).SetSecret("pgwire-user-bob", "secure_password_for_bob_456")
Do ##class(%IRIS.Wallet).SetSecret("pgwire-user-admin", "admin_secure_password_789")

# Verify secrets stored
Write ##class(%IRIS.Wallet).GetSecret("pgwire-user-alice")
# Should return: secure_password_for_alice_123
```

**Automated Script for Bulk Loading**:
```python
import iris

def bulk_load_wallet_passwords(users_dict):
    """
    Load multiple user passwords into IRIS Wallet.

    Args:
        users_dict: Dictionary mapping usernames to passwords
                   Example: {'alice': 'password123', 'bob': 'password456'}
    """
    wallet = iris.cls('%IRIS.Wallet')

    for username, password in users_dict.items():
        wallet_key = f"pgwire-user-{username}"
        wallet.SetSecret(wallet_key, password)
        print(f"✅ Stored secret for user: {username}")

    print(f"✅ Bulk load complete: {len(users_dict)} users")

# Example usage
users = {
    'alice': 'secure_password_alice_123',
    'bob': 'secure_password_bob_456',
    'admin': 'admin_password_789'
}
bulk_load_wallet_passwords(users)
```

### Step 2.3: Configure Wallet Backup

**Backup Procedures**:
```objectscript
# From IRIS Terminal (as _SYSTEM or admin)

# Export Wallet secrets to secure backup location
Do ##class(%IRIS.Wallet).Export("/secure/backup/wallet_backup_2025-11-15.dat")

# Verify backup created
Set file = ##class(%File).Open("/secure/backup/wallet_backup_2025-11-15.dat", "R")
Write $IsObject(file)  # Should return 1
Do file.Close()
```

**Restore Procedures** (disaster recovery):
```objectscript
# From IRIS Terminal

# Restore from backup
Do ##class(%IRIS.Wallet).Import("/secure/backup/wallet_backup_2025-11-15.dat")

# Verify restored secrets
Write ##class(%IRIS.Wallet).GetSecret("pgwire-user-alice")
# Should return stored password
```

### Step 2.4: Configure Wallet Permissions

```objectscript
# From IRIS Terminal

# Grant Wallet access to PGWire connection user
Do ##class(Security.Users).AddRoles("_SYSTEM", "%DB_IRISSECURITY")

# Verify IRISSECURITY database mounted
Write ##class(%SYS.Database).Exists("IRISSECURITY")
# Should return: 1
```

**Checklist**:
- [ ] IRIS Wallet enabled (IRIS 2025.3.0+)
- [ ] User passwords stored with `pgwire-user-{username}` format
- [ ] OAuth client secret stored as `pgwire-oauth-client`
- [ ] Wallet backup configured (automated daily recommended)
- [ ] IRISSECURITY database mounted and accessible
- [ ] PGWire user has %DB_IRISSECURITY role

---

## Phase 3: Kerberos GSSAPI Configuration (Optional)

**Status**: Core implementation complete, protocol wiring pending (Phase 3.6)

### Step 3.1: Configure Kerberos Realm

**Create `/etc/krb5.conf`** (on PGWire server):
```ini
[libdefaults]
    default_realm = EXAMPLE.COM
    dns_lookup_realm = false
    dns_lookup_kdc = false
    ticket_lifetime = 24h
    renew_lifetime = 7d
    forwardable = true

[realms]
    EXAMPLE.COM = {
        kdc = kdc.example.com:88
        admin_server = admin.example.com:749
        default_domain = example.com
    }

[domain_realm]
    .example.com = EXAMPLE.COM
    example.com = EXAMPLE.COM
```

### Step 3.2: Generate Service Principal and Keytab

**On KDC server** (as Kerberos admin):
```bash
# Create service principal for PGWire
kadmin.local -q "addprinc -randkey postgres/pgwire-host.example.com@EXAMPLE.COM"

# Export keytab file
kadmin.local -q "ktadd -k /tmp/pgwire.keytab postgres/pgwire-host.example.com@EXAMPLE.COM"

# Verify keytab contents
klist -k /tmp/pgwire.keytab
# Should show: postgres/pgwire-host.example.com@EXAMPLE.COM
```

### Step 3.3: Deploy Keytab to PGWire Server

```bash
# Copy keytab to PGWire server
scp /tmp/pgwire.keytab pgwire-server:/etc/krb5.keytab

# Set proper permissions (readable by root only)
ssh pgwire-server "chmod 400 /etc/krb5.keytab && chown root:root /etc/krb5.keytab"

# Verify keytab works
ssh pgwire-server "kinit -k -t /etc/krb5.keytab postgres/pgwire-host.example.com@EXAMPLE.COM && klist"
# Should show valid Kerberos ticket
```

### Step 3.4: Configure PGWire for Kerberos

**Environment Configuration**:
```bash
# Kerberos service principal
export KRB5_SERVICE_PRINCIPAL=postgres/pgwire-host.example.com@EXAMPLE.COM

# Keytab location
export KRB5_KEYTAB=/etc/krb5.keytab

# Kerberos configuration file
export KRB5_CONFIG=/etc/krb5.conf
```

### Step 3.5: Create IRIS Users for Kerberos Principals

```objectscript
# From IRIS Terminal

# Create user matching Kerberos principal (alice@EXAMPLE.COM → ALICE)
Set user = ##class(Security.Users).%New()
Set user.Name = "ALICE"  # Uppercase
Set user.FullName = "Alice Smith"
Set user.Password = "ChangeMe123!"  # Won't be used with Kerberos
Write user.%Save()

# Repeat for other Kerberos principals
Set user = ##class(Security.Users).%New()
Set user.Name = "BOB"  # bob@EXAMPLE.COM → BOB
Set user.FullName = "Bob Johnson"
Set user.Password = "ChangeMe456!"
Write user.%Save()
```

**Principal Mapping Rules**:
- `alice@EXAMPLE.COM` → `ALICE` (strip realm, uppercase)
- `bob/admin@EXAMPLE.COM` → `BOB` (strip realm and instance, uppercase)
- `service-account@EXAMPLE.COM` → `SERVICE-ACCOUNT` (preserve hyphens)

**Checklist** (for Phase 3.6 completion):
- [ ] `/etc/krb5.conf` configured with realm and KDC
- [ ] Service principal created: `postgres/pgwire-host.example.com@EXAMPLE.COM`
- [ ] Keytab deployed to `/etc/krb5.keytab` with 400 permissions
- [ ] PGWire environment variables set (KRB5_SERVICE_PRINCIPAL, KRB5_KEYTAB)
- [ ] IRIS users created matching Kerberos principals (uppercase)
- [ ] Test ticket acquisition: `kinit -k -t /etc/krb5.keytab postgres/...`

---

## Phase 4: PGWire Server Deployment

### Step 4.1: Install PGWire Dependencies

**Production Environment Setup**:
```bash
# Install Python 3.11+ (if not already installed)
python3 --version  # Should be 3.11 or higher

# Install PGWire package
pip install iris-pgwire intersystems-irispython psycopg[binary]

# Or with uv (recommended)
uv pip install iris-pgwire intersystems-irispython psycopg[binary]

# Verify installation
python3 -c "import iris_pgwire; print(iris_pgwire.__version__)"
```

### Step 4.2: Configure Environment Variables

**Create `/etc/pgwire/environment`** (or use systemd EnvironmentFile):
```bash
# IRIS Connection
IRIS_HOST=iris.example.com
IRIS_PORT=1972
IRIS_USERNAME=_SYSTEM
IRIS_PASSWORD=SYS
IRIS_NAMESPACE=USER

# Backend Type
BACKEND_TYPE=dbapi  # or 'embedded' for IRIS embedded Python

# OAuth Configuration
OAUTH_CLIENT_ID=pgwire-server
OAUTH_TOKEN_ENDPOINT=https://iris.example.com:52773/oauth2/token
# OAUTH_CLIENT_SECRET=...  # OPTIONAL - use Wallet instead

# Kerberos Configuration (Phase 3.6)
KRB5_SERVICE_PRINCIPAL=postgres/pgwire-host.example.com@EXAMPLE.COM
KRB5_KEYTAB=/etc/krb5.keytab
KRB5_CONFIG=/etc/krb5.conf

# Logging
LOG_LEVEL=INFO  # INFO for production, DEBUG for troubleshooting
LOG_FILE=/var/log/pgwire/pgwire.log

# Performance
MAX_CONNECTIONS=50  # Maximum concurrent connections
POOL_SIZE=20  # Connection pool size
```

### Step 4.3: Create systemd Service Unit

**Create `/etc/systemd/system/pgwire.service`**:
```ini
[Unit]
Description=IRIS PostgreSQL Wire Protocol Server
After=network.target iris.service
Requires=network.target

[Service]
Type=simple
User=pgwire
Group=pgwire
WorkingDirectory=/opt/pgwire

# Load environment variables
EnvironmentFile=/etc/pgwire/environment

# Start PGWire server
ExecStart=/usr/bin/python3 -m iris_pgwire.server

# Restart on failure
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pgwire

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/pgwire

[Install]
WantedBy=multi-user.target
```

### Step 4.4: Configure Log Rotation

**Create `/etc/logrotate.d/pgwire`**:
```
/var/log/pgwire/pgwire.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0640 pgwire pgwire
    sharedscripts
    postrotate
        systemctl reload pgwire >/dev/null 2>&1 || true
    endscript
}
```

### Step 4.5: Start PGWire Service

```bash
# Reload systemd configuration
sudo systemctl daemon-reload

# Enable PGWire to start on boot
sudo systemctl enable pgwire

# Start PGWire service
sudo systemctl start pgwire

# Check service status
sudo systemctl status pgwire
# Should show: active (running)

# View logs
sudo journalctl -u pgwire -f
```

**Checklist**:
- [ ] Python 3.11+ installed
- [ ] iris-pgwire package installed
- [ ] Environment variables configured (`/etc/pgwire/environment`)
- [ ] systemd service unit created
- [ ] Log rotation configured
- [ ] PGWire service enabled and started
- [ ] Service logs showing "PGWire server listening on 0.0.0.0:5432"

---

## Phase 5: Security Hardening

### Step 5.1: TLS/SSL Configuration

**Generate TLS Certificates** (or use Let's Encrypt):
```bash
# Self-signed certificate (for testing only)
openssl req -x509 -newkey rsa:4096 -nodes \
    -keyout /etc/pgwire/server-key.pem \
    -out /etc/pgwire/server-cert.pem \
    -days 365 \
    -subj "/CN=pgwire.example.com"

# Set proper permissions
chmod 600 /etc/pgwire/server-key.pem
chmod 644 /etc/pgwire/server-cert.pem
chown pgwire:pgwire /etc/pgwire/server-*.pem
```

**Configure TLS in PGWire** (environment):
```bash
# Enable TLS
export TLS_ENABLED=true
export TLS_CERT_FILE=/etc/pgwire/server-cert.pem
export TLS_KEY_FILE=/etc/pgwire/server-key.pem

# Require TLS for all connections (production recommended)
export TLS_REQUIRED=true
```

### Step 5.2: Firewall Configuration

**Configure iptables** (or use cloud security groups):
```bash
# Allow PostgreSQL wire protocol (port 5432)
sudo iptables -A INPUT -p tcp --dport 5432 -j ACCEPT

# Allow only from specific IP ranges (recommended)
sudo iptables -A INPUT -p tcp --dport 5432 -s 10.0.0.0/8 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 5432 -j DROP

# Save rules
sudo iptables-save > /etc/iptables/rules.v4
```

**Cloud Security Groups** (AWS example):
```
Inbound Rules:
- Type: Custom TCP
- Port Range: 5432
- Source: 10.0.0.0/8 (private VPC only)
- Description: PGWire PostgreSQL protocol
```

### Step 5.3: Audit Logging Configuration

**Enable Structured Logging** (environment):
```bash
# Enable audit logging for authentication events
export AUDIT_LOG_ENABLED=true
export AUDIT_LOG_FILE=/var/log/pgwire/audit.log

# Log all authentication attempts
export LOG_AUTH_ATTEMPTS=true

# Log Wallet credential access
export LOG_WALLET_ACCESS=true
```

**Audit Log Format** (JSON structured):
```json
{
  "timestamp": "2025-11-15T10:30:00Z",
  "event": "authentication_success",
  "method": "oauth",
  "username": "alice",
  "source_ip": "10.0.1.45",
  "connection_id": "conn-12345",
  "wallet_accessed": true,
  "duration_ms": 234
}
```

### Step 5.4: Password Policies

**IRIS Password Requirements** (minimum):
```objectscript
# From IRIS Terminal

# Configure password policy for IRIS users
Set policy = ##class(Security.System).GetPasswordPolicy()
Set policy.MinimumLength = 32  # PGWire requirement (FR-019)
Set policy.RequireUpperCase = 1
Set policy.RequireLowerCase = 1
Set policy.RequireDigits = 1
Set policy.RequireSpecialChars = 1
Set policy.PasswordExpirationDays = 90
Write ##class(Security.System).SetPasswordPolicy(policy)
```

### Step 5.5: Network Segmentation

**Production Network Architecture**:
```
┌─────────────────────────────────────────────┐
│ DMZ (Public Network)                        │
│  ┌──────────────┐                           │
│  │ Load Balancer│ (HAProxy/Nginx)           │
│  └──────┬───────┘                           │
└─────────┼─────────────────────────────────┘
          │ TLS Termination
          ▼
┌─────────────────────────────────────────────┐
│ Application Network (Private)               │
│  ┌──────────────┐                           │
│  │ PGWire Server│ Port 5432                 │
│  └──────┬───────┘                           │
│         │ Internal traffic only             │
└─────────┼─────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│ Database Network (Private, Isolated)        │
│  ┌──────────────┐                           │
│  │ IRIS Database│ Port 1972 (SuperServer)   │
│  │              │ Port 52773 (OAuth server) │
│  └──────────────┘                           │
└─────────────────────────────────────────────┘
```

**Checklist**:
- [ ] TLS certificates deployed and configured
- [ ] TLS required for all client connections
- [ ] Firewall rules restrict access to trusted networks only
- [ ] Audit logging enabled for authentication events
- [ ] IRIS password policy enforced (32+ characters minimum)
- [ ] Network segmentation: PGWire in app tier, IRIS in database tier

---

## Phase 6: Monitoring and Health Checks

### Step 6.1: Health Check Endpoint

**Configure Health Check** (if supported):
```python
# In production deployment, expose health check endpoint
# Example: /health endpoint returning JSON status

{
  "status": "healthy",
  "uptime_seconds": 86400,
  "active_connections": 23,
  "iris_connection": "ok",
  "oauth_server": "ok",
  "wallet_available": true,
  "version": "0.2.0"
}
```

**Monitor with systemd** (basic):
```bash
# Check PGWire service health
sudo systemctl is-active pgwire
# Returns: active (healthy)

# Check recent logs for errors
sudo journalctl -u pgwire --since "5 minutes ago" | grep ERROR
# Should be empty (no errors)
```

### Step 6.2: Prometheus Metrics (Optional)

**Expose Prometheus Metrics**:
```python
# Example metrics to track (if implemented)
pgwire_connections_total{status="success"} 1234
pgwire_connections_total{status="failed"} 5
pgwire_auth_duration_seconds{method="oauth"} 0.234
pgwire_auth_duration_seconds{method="password"} 0.123
pgwire_wallet_access_total 456
pgwire_queries_total 5678
pgwire_errors_total{type="authentication"} 3
```

### Step 6.3: Log Monitoring

**Configure Log Aggregation** (Elasticsearch/Splunk):
```bash
# Ship logs to centralized logging
# Filebeat configuration example
filebeat.inputs:
- type: log
  enabled: true
  paths:
    - /var/log/pgwire/pgwire.log
    - /var/log/pgwire/audit.log
  fields:
    service: pgwire
    environment: production
```

**Alert on Critical Events**:
- Authentication failures >10/minute
- Wallet access failures
- OAuth server unreachable
- IRIS connection pool exhaustion

### Step 6.4: Performance Monitoring

**Key Metrics to Track**:
1. **Authentication Latency**: <5 seconds (constitutional requirement FR-028)
2. **Query Latency**: P95 <100ms for simple queries
3. **Connection Pool Saturation**: <80% utilization
4. **OAuth Token Cache Hit Rate**: >90%
5. **Wallet Retrieval Time**: <1 second

**Query for Metrics** (from logs):
```bash
# Average authentication time
grep "authentication_success" /var/log/pgwire/audit.log | \
  jq '.duration_ms' | \
  awk '{sum+=$1; count++} END {print sum/count}'

# OAuth token cache hit rate
grep "oauth_token" /var/log/pgwire/pgwire.log | \
  grep -c "cache_hit" | \
  awk '{print ($1/NR)*100 "%"}'
```

**Checklist**:
- [ ] Health check endpoint responding
- [ ] systemd health monitoring configured
- [ ] Prometheus metrics exposed (optional)
- [ ] Log aggregation configured (Filebeat/Fluentd)
- [ ] Alerts configured for critical events
- [ ] Performance metrics tracked (auth latency, query latency)

---

## Phase 7: Validation Testing

### Step 7.1: OAuth Authentication Test

```bash
# Test OAuth authentication with psql
psql -h pgwire.example.com -p 5432 -U alice -d USER -c "SELECT 1"
# Enter password when prompted
# Should authenticate successfully via OAuth

# Verify OAuth token in logs
sudo journalctl -u pgwire -n 50 | grep "oauth_token"
# Should show: "OAuth authentication successful, username=alice"
```

### Step 7.2: Wallet Integration Test

```python
import psycopg

# Connect without password (retrieved from Wallet)
conn = psycopg.connect("host=pgwire.example.com port=5432 user=alice dbname=USER")

with conn.cursor() as cur:
    cur.execute("SELECT CURRENT_USER")
    username = cur.fetchone()[0]
    print(f"Authenticated as: {username}")
    # Should print: Authenticated as: ALICE

# Verify Wallet access in audit logs
# sudo grep "Password retrieved from Wallet" /var/log/pgwire/audit.log
```

### Step 7.3: Transaction Test

```bash
# Test transaction integration (Feature 022)
psql -h pgwire.example.com -p 5432 -U alice -d USER << EOF
BEGIN;
SELECT COUNT(*) FROM YourTable;
COMMIT;
EOF

# Should work without errors (BEGIN translated to START TRANSACTION)
```

### Step 7.4: Performance Validation

```bash
# Benchmark authentication latency
time psql -h pgwire.example.com -p 5432 -U alice -d USER -c "SELECT 1"

# Should complete in <5 seconds (constitutional requirement)
# Typical: 1-2 seconds for OAuth authentication
```

### Step 7.5: Kerberos Test (Phase 3.6)

```bash
# Acquire Kerberos ticket
kinit alice@EXAMPLE.COM

# Connect with GSSAPI (no password)
psql -h pgwire.example.com -p 5432 -U alice -d USER
# Should authenticate without password prompt (after Phase 3.6 completion)
```

**Checklist**:
- [ ] OAuth authentication working (psql, psycopg tested)
- [ ] Wallet password retrieval working (audit log confirmed)
- [ ] Transaction commands working (BEGIN/COMMIT/ROLLBACK)
- [ ] Authentication latency <5 seconds (constitutional SLA)
- [ ] Kerberos GSSAPI working (pending Phase 3.6)

---

## Phase 8: Documentation and Runbooks

### Step 8.1: Create Operations Runbook

**Document Common Operations**:
1. **Restart PGWire**: `sudo systemctl restart pgwire`
2. **View Logs**: `sudo journalctl -u pgwire -f`
3. **Rotate OAuth Client Secret**: Update IRIS + Wallet, restart PGWire
4. **Add New User**: Create IRIS user + store password in Wallet
5. **Troubleshoot Authentication**: Check logs, verify OAuth server, test Wallet access

### Step 8.2: Create Troubleshooting Guide

**Reference Existing Guides**:
- `docs/OAUTH_TROUBLESHOOTING.md` - OAuth 2.0 issues
- `docs/KERBEROS_TROUBLESHOOTING.md` - Kerberos GSSAPI issues
- `docs/WALLET_TROUBLESHOOTING.md` - IRIS Wallet issues

**Add Production-Specific Sections**:
- Network connectivity troubleshooting
- TLS certificate issues
- Firewall configuration problems
- Load balancer health check failures

### Step 8.3: Document Disaster Recovery

**Backup Procedures**:
1. **IRIS Wallet Backup**: Daily automated backup to `/secure/backup/`
2. **OAuth Client Configuration**: Documented in version control
3. **Kerberos Keytabs**: Backed up to secure key management system
4. **PGWire Configuration**: `/etc/pgwire/environment` in version control

**Recovery Procedures**:
1. Restore IRIS Wallet from backup
2. Redeploy PGWire with backed-up configuration
3. Restore Kerberos keytabs
4. Verify authentication working

**Checklist**:
- [ ] Operations runbook created and reviewed
- [ ] Troubleshooting guides accessible to operations team
- [ ] Disaster recovery procedures documented and tested
- [ ] Backup procedures automated (daily Wallet backup)
- [ ] Recovery time objective (RTO) documented

---

## Summary Checklist

### Pre-Deployment
- [ ] IRIS 2025.3.0+ installed and configured
- [ ] OAuth server enabled in IRIS
- [ ] IRIS Wallet available
- [ ] Kerberos KDC accessible (optional)
- [ ] TLS certificates generated or obtained
- [ ] Network firewall rules configured

### IRIS Configuration
- [ ] OAuth client "pgwire-server" registered
- [ ] OAuth client secret stored in Wallet
- [ ] User passwords stored in Wallet (`pgwire-user-{username}`)
- [ ] Wallet backup configured
- [ ] IRIS users created for Kerberos principals (optional)

### PGWire Deployment
- [ ] Python 3.11+ installed
- [ ] iris-pgwire package installed
- [ ] Environment variables configured
- [ ] systemd service unit created and enabled
- [ ] Log rotation configured
- [ ] PGWire service started and healthy

### Security
- [ ] TLS enabled and certificates deployed
- [ ] TLS required for client connections
- [ ] Firewall rules restrict access
- [ ] Audit logging enabled
- [ ] Password policies enforced (32+ characters)
- [ ] Network segmentation configured

### Monitoring
- [ ] Health checks configured
- [ ] Log aggregation configured
- [ ] Performance metrics tracked
- [ ] Alerts configured for critical events

### Testing
- [ ] OAuth authentication validated
- [ ] Wallet integration tested
- [ ] Transaction support verified
- [ ] Performance benchmarks passed (<5s auth latency)

### Documentation
- [ ] Operations runbook created
- [ ] Troubleshooting guides reviewed
- [ ] Disaster recovery procedures documented
- [ ] Team trained on operations

---

## Support and References

**Troubleshooting Guides**:
- OAuth 2.0: `docs/OAUTH_TROUBLESHOOTING.md`
- Kerberos GSSAPI: `docs/KERBEROS_TROUBLESHOOTING.md`
- IRIS Wallet: `docs/WALLET_TROUBLESHOOTING.md`

**Implementation Documentation**:
- Architecture: `CLAUDE.md` (section "Enterprise Authentication Bridge - IMPLEMENTATION COMPLETE")
- Feature Specification: `specs/024-research-and-implement/spec.md`
- Completion Reports: `PHASE_3_4_COMPLETION.md`, `PHASE_3_5_COMPLETION.md`

**IRIS Documentation**:
- OAuth 2.0 Server: https://docs.intersystems.com/iris/latest/csp/docbook/DocBook.UI.Page.cls?KEY=GOAUTH
- IRIS Wallet: https://docs.intersystems.com/iris/latest/csp/docbook/DocBook.UI.Page.cls?KEY=GCAS_wallet

**Constitutional Requirements**:
- Authentication Latency: <5 seconds (FR-028)
- Password Length: ≥32 characters (FR-019)
- Backward Compatibility: 100% (password fallback always enabled)

---

**Last Updated**: 2025-11-15
**Feature**: 024-research-and-implement
**Phase**: 3.10 (Documentation & Finalization)
**Status**: Production Deployment Checklist Complete
