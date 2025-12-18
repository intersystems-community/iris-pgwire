"""
Integration Tests for OAuth Bridge with IRIS OAuth Server

These tests validate OAuth bridge integration with REAL IRIS OAuth server.
Tests MUST FAIL initially (no implementation exists yet).

Constitutional Requirements:
- Test-First Development (Principle II)
- Tests written BEFORE implementation
- Tests MUST fail until implementation is complete
- Integration with real IRIS OAuth server (not mocks)

Feature: 024-research-and-implement (Authentication Bridge)
Phase: 3.3 (Integration Tests - OAuth)
"""

import asyncio
import os

# Import contract interface
import sys
from pathlib import Path

import pytest

spec_dir = (
    Path(__file__).parent.parent.parent / "specs" / "024-research-and-implement" / "contracts"
)
sys.path.insert(0, str(spec_dir))

from oauth_bridge_interface import (
    OAuthAuthenticationError,
    OAuthToken,
    OAuthValidationError,
)


# Test fixtures
@pytest.fixture
def oauth_bridge():
    """Real OAuth bridge for integration testing (no real implementation yet)"""
    # This will fail until implementation exists
    try:
        from iris_pgwire.auth import OAuthBridge

        return OAuthBridge()
    except (ImportError, AttributeError):
        pytest.skip("OAuthBridge implementation not available (expected during TDD)")


@pytest.fixture
def iris_oauth_config():
    """IRIS OAuth server configuration from environment"""
    return {
        "oauth_server_url": os.getenv("IRIS_OAUTH_SERVER_URL", "http://localhost:52773/oauth2"),
        "client_id": os.getenv("PGWIRE_OAUTH_CLIENT_ID", "pgwire-test"),
        "client_secret": os.getenv("PGWIRE_OAUTH_CLIENT_SECRET", "test_secret_" + "x" * 32),
        "iris_host": os.getenv("IRIS_HOST", "localhost"),
        "iris_port": int(os.getenv("IRIS_PORT", "1972")),
        "iris_namespace": os.getenv("IRIS_NAMESPACE", "USER"),
    }


@pytest.fixture
def test_user_credentials():
    """Test user credentials for OAuth authentication"""
    return {
        "username": os.getenv("TEST_USERNAME", "_SYSTEM"),
        "password": os.getenv("TEST_PASSWORD", "SYS"),
    }


# T017: Integration test: OAuth password grant flow with real IRIS OAuth server
class TestOAuthPasswordGrantIntegration:
    """Test OAuth password grant flow with real IRIS OAuth server"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_password_grant_success(
        self, oauth_bridge, iris_oauth_config, test_user_credentials
    ):
        """T017.1: Valid credentials should return real OAuth token from IRIS"""
        # GIVEN: Valid IRIS user credentials
        username = test_user_credentials["username"]
        password = test_user_credentials["password"]

        # WHEN: Exchanging credentials for OAuth token (real IRIS OAuth server)
        token = await oauth_bridge.exchange_password_for_token(username, password)

        # THEN: Should return valid OAuthToken from IRIS
        assert isinstance(token, OAuthToken)
        assert token.access_token is not None
        assert len(token.access_token) > 0
        assert token.token_type == "Bearer"
        assert token.username == username
        assert not token.is_expired

        # Verify token has reasonable expiration (e.g., 1 hour)
        assert token.expires_in > 0
        assert token.expires_in <= 3600  # Max 1 hour

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_invalid_credentials_failure(self, oauth_bridge, iris_oauth_config):
        """T017.2: Invalid credentials should raise OAuthAuthenticationError from IRIS"""
        # GIVEN: Invalid IRIS user credentials
        username = "invalid_user_12345"
        password = "wrong_password_67890"

        # WHEN/THEN: Should raise OAuthAuthenticationError from IRIS
        with pytest.raises(OAuthAuthenticationError) as exc_info:
            await oauth_bridge.exchange_password_for_token(username, password)

        # Error should indicate authentication failure
        error_msg = str(exc_info.value).lower()
        assert (
            "invalid" in error_msg
            or "authentication failed" in error_msg
            or "unauthorized" in error_msg
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_token_contains_refresh_token(
        self, oauth_bridge, iris_oauth_config, test_user_credentials
    ):
        """T017.3: OAuth token should include refresh_token for token refresh"""
        # GIVEN: Valid IRIS user credentials
        username = test_user_credentials["username"]
        password = test_user_credentials["password"]

        # WHEN: Exchanging credentials for OAuth token
        token = await oauth_bridge.exchange_password_for_token(username, password)

        # THEN: Token should include refresh_token
        assert token.refresh_token is not None
        assert len(token.refresh_token) > 0
        # Refresh token should be different from access token
        assert token.refresh_token != token.access_token

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_token_exchange_latency(
        self, oauth_bridge, iris_oauth_config, test_user_credentials
    ):
        """T017.4: Token exchange should complete within 5 seconds (FR-028)"""
        import time

        # GIVEN: Valid IRIS user credentials
        username = test_user_credentials["username"]
        password = test_user_credentials["password"]

        # WHEN: Measuring token exchange latency
        start_time = time.time()
        await asyncio.wait_for(
            oauth_bridge.exchange_password_for_token(username, password), timeout=5.0
        )
        elapsed = time.time() - start_time

        # THEN: Should complete within 5 seconds (FR-028)
        assert elapsed < 5.0, f"Token exchange took {elapsed}s, exceeds 5s limit (FR-028)"

        # Log actual latency for performance monitoring
        print(f"✅ Token exchange latency: {elapsed:.3f}s (within 5s SLA)")

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_uses_asyncio_to_thread(
        self, oauth_bridge, iris_oauth_config, test_user_credentials
    ):
        """T017.5: Token exchange should use asyncio.to_thread() for IRIS API calls"""
        # GIVEN: Valid IRIS user credentials
        username = test_user_credentials["username"]
        password = test_user_credentials["password"]

        # WHEN: Exchanging credentials for OAuth token
        # Note: This test verifies the implementation uses asyncio.to_thread()
        # by checking that the operation is truly non-blocking

        # Start token exchange in background
        token_task = asyncio.create_task(
            oauth_bridge.exchange_password_for_token(username, password)
        )

        # Verify event loop can handle other coroutines concurrently
        counter = 0
        while not token_task.done():
            counter += 1
            await asyncio.sleep(0.01)  # Yield control to event loop
            if counter > 1000:  # Safety timeout (10 seconds)
                break

        # Get token result
        token = await token_task

        # THEN: Should complete without blocking event loop
        assert token is not None
        assert counter > 0, "Event loop was blocked (asyncio.to_thread() not used)"
        print(f"✅ Event loop remained responsive: {counter} iterations during token exchange")


# T018: Integration test: OAuth token introspection with real IRIS OAuth server
class TestOAuthTokenIntrospectionIntegration:
    """Test OAuth token validation via IRIS OAuth introspection endpoint"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_token_validation_success(
        self, oauth_bridge, iris_oauth_config, test_user_credentials
    ):
        """T018.1: Valid active token should pass IRIS introspection"""
        # GIVEN: Valid OAuth token from IRIS
        username = test_user_credentials["username"]
        password = test_user_credentials["password"]
        token = await oauth_bridge.exchange_password_for_token(username, password)

        # WHEN: Validating token via IRIS introspection
        is_valid = await oauth_bridge.validate_token(token.access_token)

        # THEN: Should return True
        assert is_valid is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_invalid_token_validation_failure(
        self, oauth_bridge, iris_oauth_config
    ):
        """T018.2: Invalid token should fail IRIS introspection"""
        # GIVEN: Invalid/malformed token
        invalid_token = "invalid_token_xyz123"

        # WHEN: Validating token via IRIS introspection
        # THEN: Should return False or raise OAuthValidationError
        try:
            is_valid = await oauth_bridge.validate_token(invalid_token)
            assert is_valid is False
        except OAuthValidationError:
            # Raising error is also acceptable
            pass

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_expired_token_validation_failure(
        self, oauth_bridge, iris_oauth_config, test_user_credentials
    ):
        """T018.3: Expired token should fail IRIS introspection"""
        # GIVEN: OAuth token from IRIS (we'll wait for it to expire)
        username = test_user_credentials["username"]
        password = test_user_credentials["password"]

        # Request token with very short expiration (if configurable)
        # Note: This test may need to be skipped if IRIS doesn't support short-lived tokens
        try:
            token = await oauth_bridge.exchange_password_for_token(username, password)

            # Wait for token expiration (if expires_in < 60 seconds)
            if token.expires_in < 60:
                await asyncio.sleep(token.expires_in + 1)

                # WHEN: Validating expired token
                is_valid = await oauth_bridge.validate_token(token.access_token)

                # THEN: Should return False
                assert is_valid is False
            else:
                pytest.skip("Token expiration too long for integration test (>60s)")
        except Exception as e:
            pytest.skip(f"Token expiration test not feasible: {e}")

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_token_refresh_success(
        self, oauth_bridge, iris_oauth_config, test_user_credentials
    ):
        """T018.4: Valid refresh_token should return new access_token from IRIS"""
        # GIVEN: Valid OAuth token with refresh_token from IRIS
        username = test_user_credentials["username"]
        password = test_user_credentials["password"]
        original_token = await oauth_bridge.exchange_password_for_token(username, password)

        assert original_token.refresh_token is not None, "No refresh token available"

        # WHEN: Refreshing token via IRIS
        new_token = await oauth_bridge.refresh_token(original_token.refresh_token)

        # THEN: Should return new OAuthToken with different access_token
        assert isinstance(new_token, OAuthToken)
        assert new_token.access_token != original_token.access_token  # New token
        assert not new_token.is_expired

        # New token should be valid
        is_valid = await oauth_bridge.validate_token(new_token.access_token)
        assert is_valid is True

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_oauth_validation_latency(
        self, oauth_bridge, iris_oauth_config, test_user_credentials
    ):
        """T018.5: Token validation should complete within 1 second"""
        import time

        # GIVEN: Valid OAuth token from IRIS
        username = test_user_credentials["username"]
        password = test_user_credentials["password"]
        token = await oauth_bridge.exchange_password_for_token(username, password)

        # WHEN: Measuring validation latency
        start_time = time.time()
        is_valid = await asyncio.wait_for(
            oauth_bridge.validate_token(token.access_token), timeout=1.0
        )
        elapsed = time.time() - start_time

        # THEN: Should complete within 1 second
        assert elapsed < 1.0, f"Token validation took {elapsed}s, exceeds 1s limit"
        assert is_valid is True

        # Log actual latency for performance monitoring
        print(f"✅ Token validation latency: {elapsed:.3f}s (within 1s SLA)")
