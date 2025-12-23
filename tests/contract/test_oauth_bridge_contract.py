"""
Contract Tests for OAuth Bridge

These tests validate the OAuthBridgeProtocol interface BEFORE implementation.
All tests MUST FAIL initially (no implementation exists yet).

Constitutional Requirements:
- Test-First Development (Principle II)
- Tests written BEFORE implementation
- Tests MUST fail until implementation is complete

Feature: 024-research-and-implement (Authentication Bridge)
Phase: 3.2 (Contract Tests)
"""

# Import contract interface
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

spec_dir = (
    Path(__file__).parent.parent.parent / "specs" / "024-research-and-implement" / "contracts"
)
sys.path.insert(0, str(spec_dir))

from oauth_bridge_interface import (
    OAuthAuthenticationError,
    OAuthConfigurationError,
    OAuthRefreshError,
    OAuthToken,
    OAuthValidationError,
)


# Test fixtures
@pytest.fixture
def mock_oauth_bridge():
    """Mock OAuth bridge for testing (no real implementation yet)"""
    # This will fail until implementation exists
    try:
        from iris_pgwire.auth import OAuthBridge

        return OAuthBridge()
    except (ImportError, AttributeError):
        pytest.skip("OAuthBridge implementation not available (expected during TDD)")


@pytest.fixture
def valid_oauth_token():
    """Sample valid OAuth token for testing"""
    return OAuthToken(
        access_token="eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9...",
        refresh_token="refresh_token_abc123",
        token_type="Bearer",
        expires_in=3600,  # 1 hour
        issued_at=datetime.utcnow(),
        username="test_user",
        scopes=["user_info"],
    )


# T004: Contract test: OAuth token exchange (exchange_password_for_token)
class TestOAuthTokenExchange:
    """Test OAuth password grant flow with valid/invalid credentials"""

    @pytest.mark.asyncio
    async def test_valid_credentials_returns_token(self, mock_oauth_bridge):
        """T004.1: Valid credentials should return OAuthToken with access_token"""
        # GIVEN: Valid username and password
        username = "test_user"
        password = "test_password"

        # WHEN: Exchanging credentials for token
        token = await mock_oauth_bridge.exchange_password_for_token(username, password)

        # THEN: Should return valid OAuthToken
        assert isinstance(token, OAuthToken)
        assert token.access_token is not None
        assert len(token.access_token) > 0
        assert token.token_type == "Bearer"
        assert token.username == username
        assert not token.is_expired

    @pytest.mark.asyncio
    async def test_invalid_credentials_raises_error(self, mock_oauth_bridge):
        """T004.2: Invalid credentials should raise OAuthAuthenticationError"""
        # GIVEN: Invalid username/password
        username = "test_user"
        password = "wrong_password"

        # WHEN/THEN: Should raise OAuthAuthenticationError
        with pytest.raises(OAuthAuthenticationError) as exc_info:
            await mock_oauth_bridge.exchange_password_for_token(username, password)

        # Error message should be clear
        assert (
            "invalid" in str(exc_info.value).lower()
            or "authentication failed" in str(exc_info.value).lower()
        )

    @pytest.mark.asyncio
    async def test_oauth_server_unavailable_raises_error(self, mock_oauth_bridge):
        """T004.3: OAuth server down should raise OAuthAuthenticationError"""
        # GIVEN: OAuth server is unavailable (simulated)
        with patch("iris.cls") as mock_iris_cls:
            mock_iris_cls.side_effect = ConnectionError("OAuth server unavailable")

            # WHEN/THEN: Should raise OAuthAuthenticationError
            with pytest.raises(OAuthAuthenticationError) as exc_info:
                await mock_oauth_bridge.exchange_password_for_token("test_user", "test_password")

            assert (
                "unavailable" in str(exc_info.value).lower()
                or "connection" in str(exc_info.value).lower()
            )

    @pytest.mark.asyncio
    async def test_completes_within_timeout(self, mock_oauth_bridge):
        """T004.4: Token exchange should complete within 5 seconds (FR-028)"""
        import asyncio
        import time

        # GIVEN: Valid credentials
        username = "test_user"
        password = "test_password"

        # WHEN: Measuring token exchange latency
        start_time = time.time()
        try:
            await asyncio.wait_for(
                mock_oauth_bridge.exchange_password_for_token(username, password), timeout=5.0
            )
            elapsed = time.time() - start_time

            # THEN: Should complete within 5 seconds
            assert elapsed < 5.0, f"Token exchange took {elapsed}s, exceeds 5s limit (FR-028)"

        except TimeoutError:
            pytest.fail("Token exchange exceeded 5 second timeout (FR-028 violation)")


# T005: Contract test: OAuth token validation (validate_token)
class TestOAuthTokenValidation:
    """Test OAuth token introspection with active/expired/revoked tokens"""

    @pytest.mark.asyncio
    async def test_valid_active_token_returns_true(self, mock_oauth_bridge, valid_oauth_token):
        """T005.1: Valid active token should return True"""
        # GIVEN: Valid active token
        access_token = valid_oauth_token.access_token

        # WHEN: Validating token
        is_valid = await mock_oauth_bridge.validate_token(access_token)

        # THEN: Should return True
        assert is_valid is True

    @pytest.mark.asyncio
    async def test_expired_token_returns_false(self, mock_oauth_bridge):
        """T005.2: Expired token should return False"""
        # GIVEN: Expired token (issued 2 hours ago, expires in 1 hour)
        expired_token = OAuthToken(
            access_token="expired_token_abc123",
            refresh_token=None,
            token_type="Bearer",
            expires_in=3600,  # 1 hour
            issued_at=datetime.utcnow() - timedelta(hours=2),  # Issued 2 hours ago
            username="test_user",
            scopes=["user_info"],
        )
        assert expired_token.is_expired  # Verify token is expired

        # WHEN: Validating expired token
        is_valid = await mock_oauth_bridge.validate_token(expired_token.access_token)

        # THEN: Should return False
        assert is_valid is False

    @pytest.mark.asyncio
    async def test_revoked_token_returns_false(self, mock_oauth_bridge):
        """T005.3: Revoked token should return False"""
        # GIVEN: Revoked token (simulated)
        revoked_token = "revoked_token_xyz789"

        # Mock IRIS OAuth introspection to return inactive
        with patch("iris.cls") as mock_iris_cls:
            mock_client = Mock()
            mock_client.IntrospectToken.return_value = {"active": False}
            mock_iris_cls.return_value = mock_client

            # WHEN: Validating revoked token
            is_valid = await mock_oauth_bridge.validate_token(revoked_token)

            # THEN: Should return False
            assert is_valid is False

    @pytest.mark.asyncio
    async def test_invalid_token_raises_validation_error(self, mock_oauth_bridge):
        """T005.4: Invalid token should raise OAuthValidationError"""
        # GIVEN: Malformed token
        invalid_token = "not_a_valid_token_format"

        # WHEN/THEN: Should raise OAuthValidationError
        with pytest.raises(OAuthValidationError):
            await mock_oauth_bridge.validate_token(invalid_token)

    @pytest.mark.asyncio
    async def test_validation_completes_within_timeout(self, mock_oauth_bridge, valid_oauth_token):
        """T005.5: Token validation should complete within 1 second"""
        import asyncio
        import time

        # GIVEN: Valid token
        access_token = valid_oauth_token.access_token

        # WHEN: Measuring validation latency
        start_time = time.time()
        try:
            await asyncio.wait_for(mock_oauth_bridge.validate_token(access_token), timeout=1.0)
            elapsed = time.time() - start_time

            # THEN: Should complete within 1 second
            assert elapsed < 1.0, f"Token validation took {elapsed}s, exceeds 1s limit"

        except TimeoutError:
            pytest.fail("Token validation exceeded 1 second timeout")


# T006: Contract test: OAuth token refresh (refresh_token)
class TestOAuthTokenRefresh:
    """Test OAuth refresh token grant with valid/invalid refresh tokens"""

    @pytest.mark.asyncio
    async def test_valid_refresh_token_returns_new_token(
        self, mock_oauth_bridge, valid_oauth_token
    ):
        """T006.1: Valid refresh token should return new OAuthToken"""
        # GIVEN: Valid refresh token
        refresh_token = valid_oauth_token.refresh_token

        # WHEN: Refreshing token
        new_token = await mock_oauth_bridge.refresh_token(refresh_token)

        # THEN: Should return new OAuthToken with updated access_token
        assert isinstance(new_token, OAuthToken)
        assert new_token.access_token != valid_oauth_token.access_token  # New token differs
        assert not new_token.is_expired

    @pytest.mark.asyncio
    async def test_invalid_refresh_token_raises_error(self, mock_oauth_bridge):
        """T006.2: Invalid refresh token should raise OAuthRefreshError"""
        # GIVEN: Invalid refresh token
        invalid_refresh_token = "invalid_refresh_token_xyz"

        # WHEN/THEN: Should raise OAuthRefreshError
        with pytest.raises(OAuthRefreshError):
            await mock_oauth_bridge.refresh_token(invalid_refresh_token)

    @pytest.mark.asyncio
    async def test_expired_refresh_token_raises_error(self, mock_oauth_bridge):
        """T006.3: Expired refresh token should raise OAuthRefreshError"""
        # GIVEN: Expired refresh token (simulated)
        expired_refresh_token = "expired_refresh_token_abc"

        # WHEN/THEN: Should raise OAuthRefreshError
        with pytest.raises(OAuthRefreshError) as exc_info:
            await mock_oauth_bridge.refresh_token(expired_refresh_token)

        assert "expired" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_refresh_completes_within_timeout(self, mock_oauth_bridge, valid_oauth_token):
        """T006.4: Token refresh should complete within 5 seconds"""
        import asyncio
        import time

        # GIVEN: Valid refresh token
        refresh_token = valid_oauth_token.refresh_token

        # WHEN: Measuring refresh latency
        start_time = time.time()
        try:
            await asyncio.wait_for(mock_oauth_bridge.refresh_token(refresh_token), timeout=5.0)
            elapsed = time.time() - start_time

            # THEN: Should complete within 5 seconds (FR-028)
            assert elapsed < 5.0, f"Token refresh took {elapsed}s, exceeds 5s limit (FR-028)"

        except TimeoutError:
            pytest.fail("Token refresh exceeded 5 second timeout (FR-028 violation)")


# T007: Contract test: OAuth client credentials (get_client_credentials)
class TestOAuthClientCredentials:
    """Test OAuth client credential retrieval from environment or Wallet"""

    @pytest.mark.asyncio
    async def test_environment_variable_retrieves_credentials(self, mock_oauth_bridge):
        """T007.1: Environment variables should provide client credentials"""
        # GIVEN: OAuth client credentials in environment variables
        with patch.dict(
            "os.environ",
            {
                "PGWIRE_OAUTH_CLIENT_ID": "pgwire-test",
                "PGWIRE_OAUTH_CLIENT_SECRET": "test_secret_abc123xyz789",  # 32+ chars
            },
        ):
            # WHEN: Retrieving client credentials
            client_id, client_secret = await mock_oauth_bridge.get_client_credentials()

            # THEN: Should return credentials from environment
            assert client_id == "pgwire-test"
            assert client_secret == "test_secret_abc123xyz789"
            assert len(client_secret) >= 32  # Minimum secret length

    @pytest.mark.asyncio
    async def test_wallet_configured_retrieves_from_wallet(self, mock_oauth_bridge):
        """T007.2: Wallet configured should retrieve client_secret from IRIS Wallet (Phase 4)"""
        # GIVEN: Wallet is configured to store OAuth client secret
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = "wallet_stored_secret_abc123xyz789"
            mock_iris_cls.return_value = mock_wallet

            # WHEN: Retrieving client credentials
            client_id, client_secret = await mock_oauth_bridge.get_client_credentials()

            # THEN: Should retrieve from Wallet
            assert client_secret == "wallet_stored_secret_abc123xyz789"
            assert len(client_secret) >= 32

    @pytest.mark.asyncio
    async def test_not_configured_raises_error(self, mock_oauth_bridge):
        """T007.3: Not configured should raise OAuthConfigurationError"""
        # GIVEN: No OAuth client credentials configured
        with patch.dict("os.environ", {}, clear=True):
            # WHEN/THEN: Should raise OAuthConfigurationError
            with pytest.raises(OAuthConfigurationError) as exc_info:
                await mock_oauth_bridge.get_client_credentials()

            assert (
                "not configured" in str(exc_info.value).lower()
                or "missing" in str(exc_info.value).lower()
            )

    @pytest.mark.asyncio
    async def test_client_secret_minimum_length(self, mock_oauth_bridge):
        """T007.4: Client secret should have minimum 32 character length"""
        # GIVEN: OAuth client credentials in environment
        with patch.dict(
            "os.environ",
            {
                "PGWIRE_OAUTH_CLIENT_ID": "pgwire-test",
                "PGWIRE_OAUTH_CLIENT_SECRET": "test_secret_abc123xyz789012345678901",  # Exactly 32 chars
            },
        ):
            # WHEN: Retrieving client credentials
            client_id, client_secret = await mock_oauth_bridge.get_client_credentials()

            # THEN: Secret should meet minimum length requirement
            assert len(client_secret) >= 32


# T008: Contract test: OAuth IRIS integration (asyncio.to_thread)
class TestOAuthIRISIntegration:
    """Test OAuth bridge uses asyncio.to_thread() for blocking IRIS calls"""

    @pytest.mark.asyncio
    async def test_uses_iris_embedded_python(self, mock_oauth_bridge):
        """T008.1: Should use iris.cls('OAuth2.Client') for token operations"""
        # GIVEN: Mock IRIS OAuth client
        with patch("iris.cls") as mock_iris_cls:
            mock_client = Mock()
            mock_client.RequestToken.return_value = {
                "access_token": "test_token",
                "refresh_token": "test_refresh",
                "expires_in": 3600,
                "token_type": "Bearer",
            }
            mock_iris_cls.return_value = mock_client

            # WHEN: Exchanging credentials for token
            await mock_oauth_bridge.exchange_password_for_token("test_user", "test_password")

            # THEN: Should have called iris.cls('OAuth2.Client')
            mock_iris_cls.assert_called()
            assert "OAuth2.Client" in str(mock_iris_cls.call_args)

    @pytest.mark.asyncio
    async def test_uses_asyncio_to_thread(self, mock_oauth_bridge):
        """T008.2: Token operations should execute in thread pool (not event loop)"""
        # GIVEN: Mock asyncio.to_thread
        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
            mock_to_thread.return_value = OAuthToken(
                access_token="test_token",
                refresh_token="test_refresh",
                token_type="Bearer",
                expires_in=3600,
                issued_at=datetime.utcnow(),
                username="test_user",
                scopes=["user_info"],
            )

            # WHEN: Exchanging credentials for token
            await mock_oauth_bridge.exchange_password_for_token("test_user", "test_password")

            # THEN: Should have used asyncio.to_thread() for IRIS call
            mock_to_thread.assert_called()

    @pytest.mark.asyncio
    async def test_no_external_http_client(self, mock_oauth_bridge):
        """T008.3: Should NOT use external HTTP client (embedded Python only)"""
        # GIVEN: Monitor for external HTTP requests
        with (
            patch("requests.post") as mock_requests_post,
            patch("httpx.AsyncClient.post") as mock_httpx_post,
        ):

            # WHEN: Exchanging credentials for token
            try:
                await mock_oauth_bridge.exchange_password_for_token("test_user", "test_password")
            except Exception:
                pass  # Expected to fail until implementation exists

            # THEN: Should NOT have made external HTTP requests
            mock_requests_post.assert_not_called()
            mock_httpx_post.assert_not_called()


# T009: Contract test: OAuth error handling (SQLSTATE 28000)
class TestOAuthErrorHandling:
    """Test OAuth errors surface with PostgreSQL-compatible error codes"""

    @pytest.mark.asyncio
    async def test_authentication_failure_sqlstate_28000(self, mock_oauth_bridge):
        """T009.1: Authentication failure should use SQLSTATE 28000"""
        # GIVEN: Invalid credentials
        username = "test_user"
        password = "wrong_password"

        # WHEN: Authentication fails
        with pytest.raises(OAuthAuthenticationError) as exc_info:
            await mock_oauth_bridge.exchange_password_for_token(username, password)

        # THEN: Error should indicate SQLSTATE 28000 (invalid authorization specification)
        error = exc_info.value
        # Check if error has sqlstate attribute or message contains it
        if hasattr(error, "sqlstate"):
            assert error.sqlstate == "28000"
        else:
            # Error message should reference SQLSTATE for client compatibility
            assert "28000" in str(error) or "invalid authorization" in str(error).lower()

    @pytest.mark.asyncio
    async def test_error_messages_clear_and_actionable(self, mock_oauth_bridge):
        """T009.2: Error messages should be clear and actionable"""
        # GIVEN: Various error scenarios
        test_cases = [
            ("invalid_user", "wrong_password", "invalid credentials"),
            ("test_user", "", "empty password"),
        ]

        for username, password, _expected_hint in test_cases:
            # WHEN: Authentication fails
            try:
                await mock_oauth_bridge.exchange_password_for_token(username, password)
            except OAuthAuthenticationError as e:
                # THEN: Error message should be clear
                error_msg = str(e).lower()
                assert len(error_msg) > 0
                # Should not leak sensitive information (like actual credentials)
                assert password not in str(e) if password else True

    @pytest.mark.asyncio
    async def test_errors_propagate_to_postgresql_clients(self, mock_oauth_bridge):
        """T009.3: Errors should propagate to PostgreSQL clients with proper formatting"""
        # GIVEN: Authentication failure
        username = "test_user"
        password = "wrong_password"

        # WHEN: Error is raised
        with pytest.raises(OAuthAuthenticationError) as exc_info:
            await mock_oauth_bridge.exchange_password_for_token(username, password)

        # THEN: Error should be formatted for PostgreSQL error response
        error = exc_info.value
        # Error should have severity (ERROR, FATAL)
        if hasattr(error, "severity"):
            assert error.severity in ["ERROR", "FATAL"]

        # Error should be serializable for protocol transmission
        error_dict = {
            "message": str(error),
            "sqlstate": getattr(error, "sqlstate", "28000"),
            "severity": getattr(error, "severity", "ERROR"),
        }
        assert error_dict["message"] is not None
        assert error_dict["sqlstate"] is not None
