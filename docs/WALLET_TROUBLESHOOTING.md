# IRIS Wallet Integration Troubleshooting Guide

**Feature**: 024-research-and-implement (Authentication Bridge)
**Component**: WalletCredentials
**Last Updated**: 2025-11-15

This guide helps diagnose and resolve common IRIS Wallet integration issues with PGWire.

---

## Quick Diagnostics

### Check Wallet Availability

```objectscript
# From IRIS Terminal
Write ##class(%IRIS.Wallet).IsEnabled()
# Should return: 1 (enabled)

# If returns 0:
# - IRIS version may be too old (requires 2025.3.0+)
# - Wallet feature not installed
```

### List Stored Secrets

```objectscript
# From IRIS Terminal
Set rs = ##class(%SQL.Statement).%ExecDirect(,
  "SELECT SecretName FROM %IRIS.Wallet_Secrets")
While rs.%Next() {
    Write rs.SecretName, !
}

# Should show PGWire secrets:
# pgwire-oauth-client
# pgwire-user-alice
# pgwire-user-bob
```

### Test Secret Retrieval

```objectscript
# From IRIS Terminal
Write ##class(%IRIS.Wallet).GetSecret("pgwire-user-alice")

# Expected: Returns password (not empty)
# Problem: Returns "" → Secret not stored or wrong key name
```

### Check PGWire Logs for Wallet

```bash
# View Wallet integration logs
docker exec iris-pgwire-db tail -50 /tmp/pgwire.log | grep -i wallet

# Look for:
# ✅ "Password retrieved from Wallet" → Working correctly
# ⚠️ "Wallet password retrieval failed" → See error-specific sections below
```

---

## Common Issues

### Issue 1: "Wallet secret not found"

**Symptom**: `WalletSecretNotFoundError: No wallet entry for user alice`

**Root Cause**: Password not stored in Wallet or incorrect secret key

**Solution**:

1. **Verify secret key format**:
   ```python
   # PGWire expects: pgwire-user-{username}
   # Example keys:
   # - pgwire-user-alice → Password for user "alice"
   # - pgwire-user-bob → Password for user "bob"
   # - pgwire-oauth-client → OAuth client secret

   # NOT: alice, user-alice, ALICE (wrong format)
   ```

2. **Check if secret exists**:
   ```objectscript
   # From IRIS Terminal
   Write ##class(%IRIS.Wallet).GetSecret("pgwire-user-alice")

   # Returns: "" (empty) → Secret not stored
   # Returns: "password123" → Secret exists
   ```

3. **Store password in Wallet**:
   ```objectscript
   # From IRIS Terminal
   Do ##class(%IRIS.Wallet).SetSecret("pgwire-user-alice", "secure_password_123")

   # Verify stored
   Write ##class(%IRIS.Wallet).GetSecret("pgwire-user-alice")
   # Should return: secure_password_123
   ```

4. **Check secret length requirement**:
   ```python
   # PGWire requires: Password >= 32 characters (FR-019)
   # If password < 32 chars:
   # ValueError: "Password must be at least 32 characters"
   ```

**Verification**:
```bash
# Connect using Wallet-stored password
psql -h localhost -p 5432 -U alice -d USER
# PGWire retrieves password from Wallet automatically
# Should authenticate without manual password entry (if Wallet configured)
```

---

### Issue 2: "Wallet API failure"

**Symptom**: Connection error, `WalletAPIError` raised

**Root Cause**: IRIS version doesn't support Wallet or Wallet service unavailable

**Solution**:

1. **Check IRIS version**:
   ```objectscript
   # From IRIS Terminal
   Write $ZVERSION

   # Should be: InterSystems IRIS Version 2025.3.0 or later
   # If older: Wallet not available, upgrade IRIS
   ```

2. **Verify Wallet class exists**:
   ```objectscript
   # From IRIS Terminal
   Write ##class(%Dictionary.ClassDefinition).%ExistsId("%IRIS.Wallet")
   # Should return: 1

   # If returns 0:
   # - IRIS version too old
   # - Wallet feature not installed
   ```

3. **Test Wallet API directly**:
   ```objectscript
   # From IRIS Terminal
   Try {
       Set wallet = ##class(%IRIS.Wallet).%New()
       Write "Wallet API available"
   } Catch ex {
       Write "Wallet API error: ", ex.DisplayString()
   }
   ```

4. **Check IRIS embedded Python access**:
   ```python
   # From Python (irispython or external)
   import iris

   try:
       wallet = iris.cls('%IRIS.Wallet')
       print("Wallet accessible from Python")
   except Exception as e:
       print(f"Wallet error: {e}")
   ```

**Verification**:
```bash
# Check PGWire can access Wallet
docker exec iris-pgwire-db python3 -c "
import iris
print(iris.cls('%IRIS.Wallet').IsEnabled())
"
# Should print: 1
```

---

### Issue 3: "Wallet fallback to password authentication"

**Symptom**: Authentication succeeds but Wallet not used (logs show "using SCRAM password")

**Root Cause**: Wallet retrieval failed, triggered fallback chain (FR-021)

**Solution**:

1. **Check PGWire logs for fallback reason**:
   ```bash
   docker exec iris-pgwire-db grep "Wallet password retrieval failed" /tmp/pgwire.log

   # Look for error details:
   # "No wallet entry for user alice" → Secret not stored
   # "Wallet API failure" → IRIS Wallet unavailable
   # "Permission denied" → IRIS security configuration issue
   ```

2. **Verify Wallet enabled in PGWire**:
   ```bash
   # Check authentication bridge initialization
   docker exec iris-pgwire-db grep "wallet_enabled" /tmp/pgwire.log

   # Should show: wallet_enabled=True
   # If False: Wallet disabled in configuration
   ```

3. **Test Wallet retrieval manually**:
   ```python
   # From Python
   import iris
   import asyncio

   async def test_wallet():
       def _get_secret():
           wallet = iris.cls('%IRIS.Wallet')
           return wallet.GetSecret('pgwire-user-alice')

       secret = await asyncio.to_thread(_get_secret)
       print(f"Secret: {secret}")

   asyncio.run(test_wallet())
   ```

4. **Verify fallback chain is correct**:
   ```python
   # Expected fallback: Wallet → SCRAM password → OAuth
   # See src/iris_pgwire/auth/auth_selector.py
   # Fallback is INTENTIONAL for resilience (FR-021)
   ```

**Verification**:
```bash
# Successful Wallet retrieval should show in logs
docker exec iris-pgwire-db grep "Password retrieved from Wallet" /tmp/pgwire.log

# Should show:
# Password retrieved from Wallet, username=alice, wallet_key=pgwire-user-alice
```

---

### Issue 4: "Permission denied when accessing Wallet"

**Symptom**: `WalletAPIError: %IRIS.Wallet permission denied`

**Root Cause**: IRIS security policy blocks Wallet access

**Solution**:

1. **Check IRIS user permissions**:
   ```objectscript
   # From IRIS Terminal
   # Verify PGWire connection user has Wallet access
   Set user = ##class(Security.Users).Open("_SYSTEM")
   Write user.Roles  ; Should include %DB_IRISSECURITY or similar
   ```

2. **Grant Wallet access to PGWire user**:
   ```objectscript
   # From IRIS Terminal
   Do ##class(Security.Users).AddRoles("_SYSTEM", "%DB_IRISSECURITY")
   ```

3. **Check IRISSECURITY database mounted**:
   ```objectscript
   # From IRIS Terminal
   Write ##class(%SYS.Database).Exists("IRISSECURITY")
   # Should return: 1

   # If 0, Wallet database not created
   ```

4. **Test direct Wallet access as connection user**:
   ```objectscript
   # From IRIS Terminal (as _SYSTEM or PGWire user)
   Write ##class(%IRIS.Wallet).GetSecret("test-secret")
   # Should NOT raise <PROTECT> error

   # If <PROTECT> error:
   # - User lacks permission
   # - Add user to appropriate role
   ```

**Verification**:
```bash
# Test Wallet access from PGWire
docker exec iris-pgwire-db python3 -c "
import iris
wallet = iris.cls('%IRIS.Wallet')
try:
    wallet.GetSecret('pgwire-user-alice')
    print('Wallet access OK')
except Exception as e:
    print(f'Wallet access denied: {e}')
"
```

---

### Issue 5: "Audit trail not appearing"

**Symptom**: Wallet retrievals not logged in audit trail

**Root Cause**: Logging level too low or audit logging not enabled

**Solution**:

1. **Check PGWire log level**:
   ```bash
   # Verify INFO-level logging enabled
   docker exec iris-pgwire-db env | grep LOG_LEVEL

   # Should be: INFO or DEBUG
   # If ERROR: Won't log Wallet access
   ```

2. **Check structured logging configuration**:
   ```python
   # In src/iris_pgwire/auth/wallet_credentials.py
   # Wallet access logged at INFO level
   logger.info("Password retrieved from Wallet",
               username=username,
               wallet_key=wallet_key,
               accessed_at=datetime.utcnow().isoformat())
   ```

3. **Enable IRIS audit logging** (optional):
   ```objectscript
   # From IRIS Terminal
   # Enable Wallet audit in IRIS
   Do ##class(%SYS.Audit.System).EnableAudit("%IRIS.Wallet")
   ```

4. **Verify logs are being written**:
   ```bash
   # Check PGWire log file
   ls -lh /tmp/pgwire.log

   # Should be non-empty and growing
   # If empty: Logging not configured
   ```

**Verification**:
```bash
# Connect and check logs
psql -h localhost -p 5432 -U alice -d USER -c "SELECT 1"

# Check audit trail
docker exec iris-pgwire-db grep "Password retrieved from Wallet" /tmp/pgwire.log
# Should show: accessed_at timestamp for credential access
```

---

## Debug Mode

### Enable Detailed Wallet Logging

**Method 1: Environment Variable**
```bash
# Set log level to DEBUG
export LOG_LEVEL=DEBUG

# Restart PGWire
docker compose restart iris

# View detailed Wallet logs
docker exec iris-pgwire-db tail -100 /tmp/pgwire.log | grep -i wallet
```

**Method 2: Python Logging Configuration**
```python
# In src/iris_pgwire/auth/wallet_credentials.py
import structlog
logger = structlog.get_logger(__name__)
logger.setLevel("DEBUG")
```

### Inspect Wallet Database

```objectscript
# From IRIS Terminal
# View all secrets (admin only)
Set rs = ##class(%SQL.Statement).%ExecDirect(,
  "SELECT SecretName, CreatedDate, AccessedDate FROM %IRIS.Wallet_Secrets")
While rs.%Next() {
    Write "Secret: ", rs.SecretName, !
    Write "  Created: ", rs.CreatedDate, !
    Write "  Accessed: ", rs.AccessedDate, !
}
```

---

## Performance Issues

### Issue: "Wallet retrieval takes >1 second"

**Performance Target**: <1 second retrieval (to leave headroom for <5s total auth)

**Solution**:

1. **Measure Wallet query time**:
   ```objectscript
   # From IRIS Terminal
   Set start = $ZH
   Set secret = ##class(%IRIS.Wallet).GetSecret("pgwire-user-alice")
   Set elapsed = $ZH - start
   Write "Wallet retrieval time: ", elapsed, " seconds"

   # Should be: <0.1 seconds
   # If >0.5 seconds: Check IRISSECURITY database performance
   ```

2. **Check IRISSECURITY database status**:
   ```objectscript
   # From IRIS Terminal
   Write ##class(%SYS.Database).DatabaseStatus("IRISSECURITY")
   # Should be: Mounted, Active

   # If degraded: Check disk I/O, fragmentation
   ```

3. **Monitor concurrent Wallet access**:
   ```bash
   # Count Wallet access rate
   docker exec iris-pgwire-db grep "Password retrieved from Wallet" /tmp/pgwire.log | wc -l

   # If >1000/second: Consider caching strategy
   ```

**Verification**:
```python
import time
import psycopg

# Measure authentication time with Wallet
start = time.time()
conn = psycopg.connect("host=localhost port=5432 user=alice dbname=USER")
total_time = time.time() - start

print(f"Total authentication time: {total_time:.2f}s")
# Should be <5 seconds (constitutional requirement)
```

---

## Testing Wallet Integration

### Manual Wallet Test

```objectscript
# From IRIS Terminal

# 1. Store test secret
Do ##class(%IRIS.Wallet).SetSecret("test-secret", "test-value-123")

# 2. Retrieve secret
Write ##class(%IRIS.Wallet).GetSecret("test-secret")
# Should print: test-value-123

# 3. Verify secret exists
Set rs = ##class(%SQL.Statement).%ExecDirect(,
  "SELECT SecretName FROM %IRIS.Wallet_Secrets WHERE SecretName = 'test-secret'")
Write rs.%Next()  ; Should return 1

# 4. Clean up
Do ##class(%IRIS.Wallet).DeleteSecret("test-secret")
```

### Automated Wallet Test Script

```python
import iris
import asyncio
import time

async def test_wallet_integration():
    """Test IRIS Wallet integration from Python"""

    # 1. Store secret
    def _store_secret():
        wallet = iris.cls('%IRIS.Wallet')
        wallet.SetSecret('test-pgwire-user', 'test_password_123456789012345678901234')  # 32+ chars
        return True

    stored = await asyncio.to_thread(_store_secret)
    assert stored, "Failed to store secret"
    print("✅ Secret stored in Wallet")

    # 2. Retrieve secret
    def _get_secret():
        wallet = iris.cls('%IRIS.Wallet')
        return wallet.GetSecret('test-pgwire-user')

    start = time.time()
    secret = await asyncio.to_thread(_get_secret)
    retrieval_time = time.time() - start

    assert secret == 'test_password_123456789012345678901234', f"Wrong secret: {secret}"
    print(f"✅ Secret retrieved in {retrieval_time:.3f}s")

    # 3. Verify performance
    assert retrieval_time < 1.0, f"Retrieval took {retrieval_time}s (>1s threshold)"
    print("✅ Performance validated (<1s)")

    # 4. Clean up
    def _delete_secret():
        wallet = iris.cls('%IRIS.Wallet')
        wallet.DeleteSecret('test-pgwire-user')

    await asyncio.to_thread(_delete_secret)
    print("✅ Cleanup complete")

if __name__ == "__main__":
    asyncio.run(test_wallet_integration())
```

---

## Security Best Practices

### 1. Secret Rotation

```objectscript
# From IRIS Terminal
# Rotate user password in Wallet
Do ##class(%IRIS.Wallet).SetSecret("pgwire-user-alice", "new_password_123...")

# Old connections continue with cached password
# New connections get new password from Wallet
```

### 2. Audit Logging

```bash
# Monitor Wallet access
docker exec iris-pgwire-db grep "Password retrieved from Wallet" /tmp/pgwire.log \
  | tail -20

# Review access patterns:
# - Unusual access times
# - High-frequency access (potential breach)
# - Access from unexpected users
```

### 3. Minimum Secret Length

```python
# PGWire enforces: Password >= 32 characters
# Recommendation: Use password generator
import secrets
import string

def generate_secure_password(length=32):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

password = generate_secure_password(32)
print(f"Generated password: {password}")
```

### 4. Wallet Backup

```objectscript
# From IRIS Terminal
# Export Wallet secrets for backup (secure location!)
Do ##class(%IRIS.Wallet).Export("/secure/backup/wallet_backup.dat")

# Restore from backup if needed
Do ##class(%IRIS.Wallet).Import("/secure/backup/wallet_backup.dat")
```

---

## Reference

### Wallet Configuration Files

- **PGWire Configuration**: See `src/iris_pgwire/auth/wallet_credentials.py`
- **Protocol Integration**: See `src/iris_pgwire/protocol.py:931-1040`
- **Wallet Storage**: IRISSECURITY database (encrypted at rest)

### Related Documentation

- **Implementation**: `CLAUDE.md` - "Enterprise Authentication Bridge - IMPLEMENTATION COMPLETE"
- **Specification**: `specs/024-research-and-implement/spec.md`
- **Contract Tests**: `tests/contract/test_wallet_credentials_contract.py` (14 tests)
- **Integration Tests**: `tests/integration/test_wallet_integration.py` (14 tests)

### Wallet Secret Key Format

**PGWire Secret Keys**:
- User passwords: `pgwire-user-{username}` (e.g., `pgwire-user-alice`)
- OAuth client secret: `pgwire-oauth-client`
- Custom secrets: `pgwire-{purpose}`

**Examples**:
```objectscript
# Store user password
Do ##class(%IRIS.Wallet).SetSecret("pgwire-user-alice", "password")

# Store OAuth client secret
Do ##class(%IRIS.Wallet).SetSecret("pgwire-oauth-client", "secret")
```

### IRIS Wallet Requirements

- **IRIS Version**: 2025.3.0 or later
- **Database**: IRISSECURITY (automatically created)
- **Encryption**: AES-256 at rest
- **Permissions**: User needs %DB_IRISSECURITY role

### Support

For additional help:
1. Check PGWire logs: `docker exec iris-pgwire-db tail -100 /tmp/pgwire.log`
2. Check Wallet status: `Write ##class(%IRIS.Wallet).IsEnabled()`
3. Review PHASE_3_5_COMPLETION.md for implementation details
4. File issue on GitLab with logs and IRIS version

---

**Last Updated**: 2025-11-15
**Feature**: 024-research-and-implement
**Phase**: 3.10 (Documentation & Finalization)
