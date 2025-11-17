# OAuth 2.0 Authentication Troubleshooting Guide

**Feature**: 024-research-and-implement (Authentication Bridge)
**Component**: OAuthBridge
**Last Updated**: 2025-11-15

This guide helps diagnose and resolve common OAuth 2.0 authentication issues with PGWire.

---

## Quick Diagnostics

### Check OAuth Server Health

```bash
# Verify IRIS OAuth server is accessible
curl -v http://localhost:52773/oauth2/token

# Expected: 401 Unauthorized (server is responding)
# Problem: Connection refused → OAuth server not running
```

### Check PGWire Logs

```bash
# View authentication logs
docker exec iris-pgwire-db tail -50 /tmp/pgwire.log | grep -i oauth

# Look for:
# ✅ "OAuth authentication successful" → Working correctly
# ❌ "OAuth authentication failed" → See error-specific sections below
```

### Verify OAuth Configuration

```python
# Check if OAuth bridge is initialized
docker exec iris-pgwire-db grep "Authentication bridge initialized" /tmp/pgwire.log

# Expected output:
# Authentication bridge initialized, connection_id=conn-XXX, oauth_enabled=True
```

---

## Common Issues

### Issue 1: "OAuth authentication failed: invalid_client"

**Symptom**: Client connection fails with authentication error

**Root Cause**: OAuth client credentials are incorrect or missing

**Solution**:

1. **Verify client credentials exist**:
   ```bash
   # Check environment variables
   docker exec iris-pgwire-db env | grep OAUTH

   # Should show:
   # OAUTH_CLIENT_ID=pgwire-server
   # OAUTH_CLIENT_SECRET=your-secret-here
   ```

2. **Verify credentials in IRIS Wallet** (recommended):
   ```objectscript
   # From IRIS Terminal
   Write ##class(%IRIS.Wallet).GetSecret("pgwire-oauth-client")

   # Should return client secret (not empty)
   ```

3. **Verify client registered in IRIS**:
   ```objectscript
   # Check OAuth client exists
   Set client = ##class(OAuth2.Client).Open("pgwire-server")
   Write $IsObject(client)  ; Should return 1
   ```

4. **Re-register OAuth client**:
   ```objectscript
   # From IRIS Terminal
   Set client = ##class(OAuth2.Client).%New()
   Set client.ClientId = "pgwire-server"
   Set client.Name = "PGWire Server"
   Set client.ClientSecret = "your-secure-secret-here"
   Set client.GrantTypes = "password,refresh_token"
   Write client.%Save()
   ```

**Verification**:
```bash
psql -h localhost -p 5432 -U testuser -d USER
# Should successfully authenticate
```

---

### Issue 2: "OAuth server unavailable"

**Symptom**: Connection times out or fails immediately

**Root Cause**: Cannot reach IRIS OAuth server endpoint

**Solution**:

1. **Check IRIS is running**:
   ```bash
   docker ps | grep iris
   # Should show iris-enterprise container running
   ```

2. **Verify OAuth endpoint accessible**:
   ```bash
   # From PGWire container
   docker exec iris-pgwire-db curl -v http://iris:52773/oauth2/token

   # Expected: 401 Unauthorized (server responding)
   # Problem: "Could not resolve host" → DNS issue
   # Problem: "Connection refused" → IRIS not listening on 52773
   ```

3. **Check network connectivity**:
   ```bash
   # Verify PGWire can reach IRIS
   docker exec iris-pgwire-db ping -c 3 iris

   # Should show successful pings
   ```

4. **Verify IRIS OAuth service enabled**:
   ```objectscript
   # From IRIS Terminal
   Write ##class(%SYS.OAuth2.Server).IsEnabled()
   # Should return 1

   # If disabled, enable OAuth:
   Do ##class(%SYS.OAuth2.Server).Enable()
   ```

**Verification**:
```bash
# Test OAuth endpoint from PGWire container
docker exec iris-pgwire-db curl http://iris:52773/oauth2/token
# Should return 401 (not connection error)
```

---

### Issue 3: "Token validation failed"

**Symptom**: Authentication succeeds initially but subsequent queries fail

**Root Cause**: OAuth token expired or introspection endpoint unavailable

**Solution**:

1. **Check token expiry**:
   ```bash
   # View PGWire logs for token TTL
   docker exec iris-pgwire-db grep "expires_in" /tmp/pgwire.log

   # Typical: expires_in=3600 (1 hour)
   # If too short, increase in OAuth client configuration
   ```

2. **Verify introspection endpoint**:
   ```bash
   # Check if token introspection works
   curl -u pgwire-server:secret http://localhost:52773/oauth2/introspect \
     -d "token=YOUR_ACCESS_TOKEN"

   # Should return: {"active": true} or {"active": false}
   ```

3. **Check token refresh works**:
   ```objectscript
   # From IRIS Terminal, verify refresh token grant enabled
   Set client = ##class(OAuth2.Client).Open("pgwire-server")
   Write client.GrantTypes
   # Should include "refresh_token"
   ```

4. **Increase token TTL** (if needed):
   ```objectscript
   # Extend token lifetime
   Set client = ##class(OAuth2.Client).Open("pgwire-server")
   Set client.AccessTokenTTL = 7200  ; 2 hours
   Write client.%Save()
   ```

**Verification**:
```python
import psycopg

# Connect and run multiple queries
conn = psycopg.connect("host=localhost port=5432 user=testuser dbname=USER")
for i in range(10):
    cur = conn.cursor()
    cur.execute("SELECT 1")
    print(f"Query {i+1}: {cur.fetchone()}")
# All queries should succeed with cached token
```

---

### Issue 4: "Password grant not supported"

**Symptom**: "unsupported_grant_type" error

**Root Cause**: OAuth client not configured for password grant flow

**Solution**:

1. **Verify password grant enabled**:
   ```objectscript
   # From IRIS Terminal
   Set client = ##class(OAuth2.Client).Open("pgwire-server")
   Write client.GrantTypes
   # Should include "password"
   ```

2. **Enable password grant**:
   ```objectscript
   Set client = ##class(OAuth2.Client).Open("pgwire-server")
   Set client.GrantTypes = "password,refresh_token"
   Write client.%Save()
   ```

**Verification**:
```bash
# Test password grant directly
curl -X POST http://localhost:52773/oauth2/token \
  -u pgwire-server:secret \
  -d "grant_type=password&username=testuser&password=testpass"

# Should return access_token (not error)
```

---

### Issue 5: "Wallet credential retrieval failed"

**Symptom**: Falls back to password authentication even though Wallet enabled

**Root Cause**: Wallet secret not found or Wallet API error

**Solution**:

1. **Verify secret stored in Wallet**:
   ```objectscript
   # From IRIS Terminal
   Write ##class(%IRIS.Wallet).GetSecret("pgwire-user-testuser")
   # Should return password (not empty)
   ```

2. **Store password in Wallet**:
   ```objectscript
   Do ##class(%IRIS.Wallet).SetSecret("pgwire-user-testuser", "secure_password")
   ```

3. **Check Wallet enabled**:
   ```objectscript
   Write ##class(%IRIS.Wallet).IsEnabled()
   # Should return 1
   ```

4. **Verify IRIS version supports Wallet**:
   ```objectscript
   Write $ZVERSION
   # Should be 2025.3.0 or later for Wallet support
   ```

**Verification**:
```bash
# Check PGWire logs for Wallet retrieval
docker exec iris-pgwire-db grep "Password retrieved from Wallet" /tmp/pgwire.log

# Should show successful Wallet retrieval
```

---

## Debug Mode

### Enable Detailed OAuth Logging

**Method 1: Environment Variable**
```bash
# In docker-compose.yml or runtime
export LOG_LEVEL=DEBUG

# Restart PGWire server
docker compose restart iris
```

**Method 2: Python Logging Configuration**
```python
# In src/iris_pgwire/auth/oauth_bridge.py
import structlog
logger = structlog.get_logger(__name__)
logger.setLevel("DEBUG")  # Enable debug logging
```

### Capture OAuth HTTP Traffic

```bash
# Use tcpdump to capture OAuth requests
docker exec iris-pgwire-db tcpdump -i any -A 'tcp port 52773' -w /tmp/oauth.pcap

# Analyze in Wireshark or with tcpdump
docker exec iris-pgwire-db tcpdump -r /tmp/oauth.pcap -A
```

---

## Performance Issues

### Issue: "OAuth authentication takes >5 seconds"

**Constitutional Requirement**: <5s authentication latency (FR-028)

**Solution**:

1. **Check network latency**:
   ```bash
   # Measure round-trip time to IRIS
   docker exec iris-pgwire-db ping -c 10 iris
   # RTT should be <10ms for same host
   ```

2. **Check IRIS CPU usage**:
   ```bash
   # Monitor IRIS container CPU
   docker stats iris-enterprise
   # CPU should be <80% during authentication
   ```

3. **Verify no DNS delays**:
   ```bash
   # Check DNS resolution time
   docker exec iris-pgwire-db time nslookup iris
   # Should complete in <100ms
   ```

4. **Check OAuth server load**:
   ```objectscript
   # From IRIS Terminal, check OAuth server metrics
   Write ##class(%SYS.OAuth2.Server).GetMetrics()
   ```

**Verification**:
```bash
# Measure authentication time
time psql -h localhost -p 5432 -U testuser -d USER -c "SELECT 1"

# Should complete in <5 seconds total
```

---

## Testing OAuth Integration

### Manual OAuth Token Flow Test

```bash
# 1. Request token
TOKEN=$(curl -s -X POST http://localhost:52773/oauth2/token \
  -u pgwire-server:secret \
  -d "grant_type=password&username=testuser&password=testpass" \
  | jq -r '.access_token')

echo "Token: $TOKEN"

# 2. Introspect token
curl -s -u pgwire-server:secret http://localhost:52773/oauth2/introspect \
  -d "token=$TOKEN" | jq .

# Expected: {"active": true, "username": "testuser"}

# 3. Use token (if supported by IRIS)
curl -H "Authorization: Bearer $TOKEN" http://localhost:52773/api/endpoint
```

### Automated OAuth Test Script

```python
import psycopg
import time

def test_oauth_authentication():
    """Test OAuth authentication performance and caching"""

    # Measure first connection (with OAuth exchange)
    start = time.time()
    conn1 = psycopg.connect("host=localhost port=5432 user=testuser password=testpass dbname=USER")
    first_auth_time = time.time() - start
    print(f"First authentication: {first_auth_time:.2f}s")

    # Measure subsequent query (with cached token)
    start = time.time()
    cur = conn1.cursor()
    cur.execute("SELECT 1")
    cached_query_time = time.time() - start
    print(f"Cached token query: {cached_query_time:.3f}s")

    # Verify performance requirements
    assert first_auth_time < 5.0, f"OAuth authentication took {first_auth_time}s (>5s SLA)"
    assert cached_query_time < 0.1, f"Cached query took {cached_query_time}s (should be <100ms)"

    print("✅ OAuth authentication performance validated")

if __name__ == "__main__":
    test_oauth_authentication()
```

---

## Reference

### OAuth Configuration Files

- **PGWire Configuration**: See `src/iris_pgwire/auth/oauth_bridge.py`
- **Protocol Integration**: See `src/iris_pgwire/protocol.py:931-1040`
- **Environment Variables**: `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_TOKEN_ENDPOINT`

### Related Documentation

- **Implementation**: `CLAUDE.md` - "Enterprise Authentication Bridge - IMPLEMENTATION COMPLETE"
- **Specification**: `specs/024-research-and-implement/spec.md`
- **Contract Tests**: `tests/contract/test_oauth_bridge_contract.py` (23 tests)
- **Integration Tests**: `tests/integration/test_oauth_integration.py` (10 tests)

### Support

For additional help:
1. Check PGWire logs: `docker exec iris-pgwire-db tail -100 /tmp/pgwire.log`
2. Review PHASE_3_5_COMPLETION.md for known limitations
3. File issue on GitLab with logs and configuration

---

**Last Updated**: 2025-11-15
**Feature**: 024-research-and-implement
**Phase**: 3.10 (Documentation & Finalization)
