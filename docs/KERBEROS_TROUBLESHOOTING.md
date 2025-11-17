# Kerberos (GSSAPI) Authentication Troubleshooting Guide

**Feature**: 024-research-and-implement (Authentication Bridge)
**Component**: GSSAPIAuthenticator
**Status**: Core implementation complete, protocol wiring pending (Phase 3.6)
**Last Updated**: 2025-11-15

This guide helps diagnose and resolve common Kerberos GSSAPI authentication issues with PGWire.

---

## Quick Diagnostics

### Check Kerberos Configuration

```bash
# Verify Kerberos configuration file exists
cat /etc/krb5.conf

# Should contain:
# [libdefaults]
#     default_realm = EXAMPLE.COM
# [realms]
#     EXAMPLE.COM = {
#         kdc = kdc.example.com
#         admin_server = admin.example.com
#     }
```

### Check Service Principal and Keytab

```bash
# List principals in keytab
klist -k /etc/krb5.keytab

# Should show:
# postgres/pgwire-host.example.com@EXAMPLE.COM
```

### Test Kerberos Ticket Acquisition

```bash
# Acquire ticket using keytab
kinit -k -t /etc/krb5.keytab postgres/pgwire-host.example.com@EXAMPLE.COM

# Verify ticket obtained
klist

# Expected output:
# Ticket cache: FILE:/tmp/krb5cc_1000
# Default principal: postgres/pgwire-host.example.com@EXAMPLE.COM
# Valid starting     Expires            Service principal
# 11/15/25 10:00:00  11/15/25 20:00:00  krbtgt/EXAMPLE.COM@EXAMPLE.COM
```

### Check PGWire Logs for GSSAPI

```bash
# View Kerberos authentication logs
docker exec iris-pgwire-db tail -50 /tmp/pgwire.log | grep -i kerberos

# Look for:
# ✅ "Kerberos authentication successful" → Working correctly
# ❌ "GSSAPI handshake failed" → See error-specific sections below
```

---

## Common Issues

### Issue 1: "Kerberos principal not found in IRIS"

**Symptom**: Authentication fails with "No IRIS user for principal alice@EXAMPLE.COM"

**Root Cause**: Kerberos principal not mapped to existing IRIS user

**Solution**:

1. **Verify principal mapping algorithm**:
   ```python
   # PGWire mapping: alice@EXAMPLE.COM → ALICE (uppercase, strip realm)
   # Verify user exists in IRIS with correct case
   ```

2. **Check IRIS user exists**:
   ```objectscript
   # From IRIS Terminal
   Write ##class(%SQL.Statement).%ExecDirect(,
     "SELECT Name FROM INFORMATION_SCHEMA.USERS WHERE UPPER(Name) = 'ALICE'").%Next()
   # Should return 1 (user exists)
   ```

3. **Create IRIS user if missing**:
   ```objectscript
   # Create user matching principal
   Set user = ##class(Security.Users).%New()
   Set user.Name = "ALICE"
   Set user.FullName = "Alice Smith"
   Set user.Password = "ChangeMe123!"  ; Won't be used with Kerberos
   Write user.%Save()
   ```

4. **Verify principal → username mapping**:
   ```bash
   # Expected mappings:
   # alice@EXAMPLE.COM → ALICE
   # bob/admin@EXAMPLE.COM → BOB (strips /admin instance)
   # service-account@EXAMPLE.COM → SERVICE-ACCOUNT (preserves hyphens)
   ```

**Verification**:
```bash
# Connect with Kerberos principal (after Phase 3.6)
psql -h pgwire-host.example.com -p 5432 -U alice
# Should successfully authenticate via GSSAPI
```

---

### Issue 2: "GSSAPI handshake failed"

**Symptom**: Connection times out or fails during GSSAPI negotiation

**Root Cause**: Keytab permissions, KDC unavailable, or service principal mismatch

**Solution**:

1. **Check keytab file permissions**:
   ```bash
   # Keytab must be readable by PGWire process
   ls -l /etc/krb5.keytab
   # Should show: -r-------- 1 root root (chmod 400)

   # Fix permissions if wrong
   sudo chmod 400 /etc/krb5.keytab
   sudo chown root:root /etc/krb5.keytab
   ```

2. **Verify service principal matches**:
   ```bash
   # PGWire expects: postgres@HOSTNAME
   # Check keytab has correct principal
   klist -k /etc/krb5.keytab | grep postgres

   # Should show:
   # postgres/pgwire-host.example.com@EXAMPLE.COM
   ```

3. **Test KDC connectivity**:
   ```bash
   # Check KDC is reachable
   nc -zv kdc.example.com 88

   # Expected: Connection succeeded
   # Problem: Connection refused → KDC not running or firewall blocking port 88
   ```

4. **Test ticket acquisition manually**:
   ```bash
   # Try acquiring ticket with keytab
   kinit -k -t /etc/krb5.keytab postgres/pgwire-host.example.com@EXAMPLE.COM

   # If fails:
   # - "Cannot find KDC" → Check /etc/krb5.conf realm configuration
   # - "Preauthentication failed" → Principal not registered in KDC
   # - "Key table entry not found" → Keytab doesn't contain principal
   ```

5. **Check GSSAPI library installed**:
   ```bash
   # Verify python-gssapi installed
   docker exec iris-pgwire-db python -c "import gssapi; print(gssapi.__version__)"

   # Should print version (e.g., "1.8.2")
   # If ImportError: pip install gssapi
   ```

**Verification**:
```bash
# Test GSSAPI handshake manually (after Phase 3.6)
KRB5CCNAME=/tmp/krb5cc_test kinit alice@EXAMPLE.COM
psql -h pgwire-host.example.com -p 5432 -U alice
# Should authenticate without password prompt
```

---

### Issue 3: "Principal mapping failed"

**Symptom**: "Invalid principal format" or mapping returns wrong username

**Root Cause**: Principal format doesn't match expected pattern

**Solution**:

1. **Verify principal format**:
   ```python
   # Supported formats:
   # - alice@EXAMPLE.COM → ALICE
   # - bob/admin@EXAMPLE.COM → BOB (strips instance)
   # - service@EXAMPLE.COM → SERVICE

   # Unsupported formats (will fail):
   # - alice (no realm) → Error: "Principal must include realm"
   # - alice@EXAMPLE.COM@BACKUP.COM (double realm) → Error: "Invalid format"
   ```

2. **Check principal extraction in logs**:
   ```bash
   # View extracted principal
   docker exec iris-pgwire-db grep "Kerberos principal extracted" /tmp/pgwire.log

   # Should show: principal=alice@EXAMPLE.COM
   ```

3. **Test mapping algorithm**:
   ```python
   # From Python
   def map_principal(principal: str) -> str:
       # Strip realm: alice@EXAMPLE.COM → alice
       username = principal.split('@')[0]

       # Strip instance: bob/admin → bob
       username = username.split('/')[0]

       # Uppercase: alice → ALICE
       return username.upper()

   print(map_principal("alice@EXAMPLE.COM"))  # → ALICE
   print(map_principal("bob/admin@EXAMPLE.COM"))  # → BOB
   ```

4. **Verify IRIS user case**:
   ```objectscript
   # IRIS usernames are case-sensitive
   # Check exact case of user
   Write ##class(%SQL.Statement).%ExecDirect(,
     "SELECT Name FROM INFORMATION_SCHEMA.USERS").%Display()
   # Lists all users with exact case
   ```

**Verification**:
```bash
# Check mapping in PGWire logs
docker exec iris-pgwire-db grep "mapped to IRIS user" /tmp/pgwire.log

# Should show: principal=alice@EXAMPLE.COM mapped to IRIS user=ALICE
```

---

### Issue 4: "GSSAPI timeout during handshake"

**Symptom**: Connection hangs for 5 seconds then fails

**Root Cause**: Multi-step GSSAPI handshake timeout (FR-028 requirement)

**Solution**:

1. **Check network latency to KDC**:
   ```bash
   # Measure round-trip time
   ping -c 10 kdc.example.com

   # RTT should be <50ms for LAN, <200ms for WAN
   # If >200ms, consider local KDC replica
   ```

2. **Verify KDC response time**:
   ```bash
   # Test ticket acquisition time
   time kinit alice@EXAMPLE.COM

   # Should complete in <1 second
   # If >2 seconds, check KDC load
   ```

3. **Check PGWire GSSAPI timeout configuration**:
   ```python
   # Default timeout: 5 seconds (constitutional requirement)
   # See src/iris_pgwire/auth/gssapi_auth.py:95
   security_context = await asyncio.wait_for(
       self._gssapi_handshake_steps(service_name),
       timeout=5.0  # 5-second timeout
   )
   ```

4. **Monitor GSSAPI handshake steps**:
   ```bash
   # Enable debug logging
   export LOG_LEVEL=DEBUG

   # Check logs for handshake progress
   docker exec iris-pgwire-db grep "GSSAPI step" /tmp/pgwire.log

   # Should show:
   # Step 1: Client initial token received
   # Step 2: Server challenge sent
   # Step 3: Client response received
   # Step 4: Authentication complete
   ```

**Verification**:
```bash
# Measure authentication time
time psql -h pgwire-host.example.com -p 5432 -U alice -c "SELECT 1"

# Should complete in <5 seconds (constitutional SLA)
```

---

### Issue 5: "IRIS Kerberos validation failed"

**Symptom**: GSSAPI handshake succeeds but IRIS rejects ticket

**Root Cause**: IRIS %Service_Bindings cannot validate GSSAPI token

**Solution**:

1. **Verify IRIS Kerberos support enabled**:
   ```objectscript
   # From IRIS Terminal
   Write ##class(%SYS.Security.System).GetSetting("KerberosEnabled")
   # Should return 1

   # If disabled:
   Do ##class(%SYS.Security.System).SetSetting("KerberosEnabled", 1)
   ```

2. **Check IRIS service principal configured**:
   ```objectscript
   # Verify IRIS has keytab configured
   Write ##class(%SYS.Security.Kerberos).GetServicePrincipal()
   # Should return: iris/iris-host.example.com@EXAMPLE.COM
   ```

3. **Test IRIS Kerberos validation directly**:
   ```objectscript
   # From IRIS Terminal, test token validation
   Set token = "base64_encoded_gssapi_token"
   Set result = ##class(%Service_Bindings).ValidateGSSAPIToken(token)
   Write result  ; Should return 1 (valid)
   ```

4. **Check IRIS keytab location**:
   ```objectscript
   # Verify IRIS knows where keytab is
   Write ##class(%SYS.Security.Kerberos).GetKeytabPath()
   # Should return: /usr/irissys/mgr/iris.keytab
   ```

**Verification**:
```bash
# Check IRIS logs for Kerberos validation
docker exec iris-enterprise iris session IRIS -U%SYS <<EOF
Write \$SYSTEM.Security.Login("alice@EXAMPLE.COM", "", 128)
Halt
EOF

# Should return positive value (successful login)
```

---

## Debug Mode

### Enable Detailed Kerberos Logging

**Method 1: Kerberos Trace**
```bash
# Enable Kerberos library tracing
export KRB5_TRACE=/tmp/krb5_trace.log

# Restart PGWire
docker compose restart iris

# View trace
docker exec iris-pgwire-db cat /tmp/krb5_trace.log
```

**Method 2: GSSAPI Debug Logging**
```python
# In src/iris_pgwire/auth/gssapi_auth.py
import structlog
logger = structlog.get_logger(__name__)
logger.setLevel("DEBUG")
```

### Capture GSSAPI Traffic

```bash
# Use tcpdump to capture Kerberos traffic (port 88)
docker exec iris-pgwire-db tcpdump -i any -s 0 'tcp port 88' -w /tmp/kerberos.pcap

# Analyze with Wireshark
# Look for: AS-REQ, AS-REP, TGS-REQ, TGS-REP, AP-REQ, AP-REP
```

---

## Performance Issues

### Issue: "Kerberos authentication takes >5 seconds"

**Constitutional Requirement**: <5s authentication latency (FR-028)

**Solution**:

1. **Check KDC latency**:
   ```bash
   # Measure ticket acquisition time
   time kinit alice@EXAMPLE.COM

   # Should be <1 second
   # If >2 seconds, consider:
   # - Local KDC replica
   # - KDC load balancing
   # - Network path optimization
   ```

2. **Monitor GSSAPI handshake steps**:
   ```bash
   # Count handshake round-trips
   docker exec iris-pgwire-db grep "GSSAPI step" /tmp/pgwire.log | wc -l

   # Typical: 2-4 round-trips
   # If >6, investigate client configuration
   ```

3. **Check DNS resolution time**:
   ```bash
   # Measure DNS lookup for KDC
   time nslookup kdc.example.com

   # Should be <100ms
   # If >500ms, add KDC to /etc/hosts
   ```

**Verification**:
```bash
# Benchmark authentication end-to-end
time psql -h pgwire-host.example.com -p 5432 -U alice -c "SELECT 1"

# Should complete in <5 seconds
```

---

## Testing Kerberos Integration

### Manual GSSAPI Test (after Phase 3.6)

```bash
# 1. Acquire Kerberos ticket
kinit alice@EXAMPLE.COM
klist  # Verify ticket obtained

# 2. Connect with GSSAPI (no password)
psql -h pgwire-host.example.com -p 5432 -U alice
# Should authenticate without password prompt

# 3. Run test query
SELECT CURRENT_USER;
# Should return: ALICE
```

### Automated Kerberos Test Script

```python
import subprocess
import psycopg
import time

def test_kerberos_authentication():
    """Test Kerberos GSSAPI authentication"""

    # 1. Acquire ticket
    result = subprocess.run(
        ["kinit", "-k", "-t", "/etc/krb5.keytab", "alice@EXAMPLE.COM"],
        capture_output=True
    )
    assert result.returncode == 0, f"kinit failed: {result.stderr}"

    # 2. Measure GSSAPI authentication time
    start = time.time()
    conn = psycopg.connect(
        "host=pgwire-host.example.com port=5432 user=alice dbname=USER gssapi=1"
    )
    auth_time = time.time() - start

    print(f"Kerberos authentication time: {auth_time:.2f}s")

    # 3. Verify authenticated user
    cur = conn.cursor()
    cur.execute("SELECT CURRENT_USER")
    username = cur.fetchone()[0]
    print(f"Authenticated as: {username}")

    # 4. Verify performance
    assert auth_time < 5.0, f"Kerberos auth took {auth_time}s (>5s SLA)"
    assert username == "ALICE", f"Expected ALICE, got {username}"

    print("✅ Kerberos authentication validated")

if __name__ == "__main__":
    test_kerberos_authentication()
```

---

## Reference

### Kerberos Configuration Files

- **PGWire Configuration**: See `src/iris_pgwire/auth/gssapi_auth.py`
- **Protocol Integration**: See `src/iris_pgwire/protocol.py` (Phase 3.6 pending)
- **Kerberos Config**: `/etc/krb5.conf`
- **Keytab File**: `/etc/krb5.keytab`

### Related Documentation

- **Implementation**: `CLAUDE.md` - "Enterprise Authentication Bridge - IMPLEMENTATION COMPLETE"
- **Specification**: `specs/024-research-and-implement/spec.md`
- **Contract Tests**: `tests/contract/test_gssapi_auth_contract.py` (19 tests)
- **Integration Tests**: `tests/integration/test_kerberos_integration.py` (10 tests)

### Kerberos Principal Format

**Standard Format**: `primary/instance@REALM`

**Examples**:
- User principal: `alice@EXAMPLE.COM`
- Service principal: `postgres/pgwire-host.example.com@EXAMPLE.COM`
- Service with instance: `postgres/replica@EXAMPLE.COM`

**PGWire Service Principal**: `postgres@{hostname}`

### Support

For additional help:
1. Check PGWire logs: `docker exec iris-pgwire-db tail -100 /tmp/pgwire.log`
2. Check Kerberos trace: `KRB5_TRACE=/tmp/krb5_trace.log`
3. Review PHASE_3_5_COMPLETION.md for implementation status
4. File issue on GitLab with logs, keytab listing (klist -k), and krb5.conf

---

**Last Updated**: 2025-11-15
**Feature**: 024-research-and-implement
**Phase**: 3.10 (Documentation & Finalization)
**Implementation Status**: Core complete (Phase 3.4), protocol wiring pending (Phase 3.6)
