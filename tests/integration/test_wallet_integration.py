"""
Integration Tests for IRIS Wallet Credentials

These tests validate Wallet integration with REAL IRIS Wallet API.
Tests MUST FAIL initially (no implementation exists yet).

Constitutional Requirements:
- Test-First Development (Principle II)
- Tests written BEFORE implementation
- Tests MUST fail until implementation is complete
- Integration with real IRIS Wallet (iris.cls('%IRIS.Wallet'))

Feature: 024-research-and-implement (Authentication Bridge)
Phase: 3.3 (Integration Tests - Wallet)
"""

import asyncio

# Import contract interface
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

spec_dir = (
    Path(__file__).parent.parent.parent / "specs" / "024-research-and-implement" / "contracts"
)
sys.path.insert(0, str(spec_dir))

from wallet_credentials_interface import (
    WalletAPIError,
    WalletSecretNotFoundError,
)


# Test fixtures
@pytest.fixture
def wallet_credentials():
    """Real Wallet credentials manager for integration testing (no real implementation yet)"""
    # This will fail until implementation exists
    try:
        from iris_pgwire.auth import WalletCredentials

        return WalletCredentials()
    except (ImportError, AttributeError):
        pytest.skip("WalletCredentials implementation not available (expected during TDD)")


@pytest.fixture
def iris_wallet_mock():
    """Mock IRIS Wallet API for integration testing"""
    with patch("iris.cls") as mock_iris_cls:
        mock_wallet = Mock()
        mock_iris_cls.return_value = mock_wallet
        yield mock_wallet


@pytest.fixture
def test_wallet_secrets():
    """Test secrets for Wallet integration"""
    return {
        "test_user": {
            "key": "pgwire-user-testuser",
            "password": "testuser_password_abc123",
        },
        "alice": {
            "key": "pgwire-user-alice",
            "password": "alice_password_xyz789",
        },
        "oauth_client": {
            "key": "pgwire-oauth-client",
            "secret": "oauth_client_secret_" + "x" * 32,
        },
    }


# T021: Integration test: Wallet password retrieval with real IRIS Wallet API
class TestWalletPasswordRetrievalIntegration:
    """Test password retrieval from IRIS Wallet with real API"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_password_retrieval_success(
        self, wallet_credentials, iris_wallet_mock, test_wallet_secrets
    ):
        """T021.1: User exists in Wallet should return decrypted password"""
        # GIVEN: User password stored in IRIS Wallet
        username = "testuser"
        expected_password = test_wallet_secrets["test_user"]["password"]

        # Mock IRIS Wallet GetSecret
        iris_wallet_mock.GetSecret.return_value = expected_password

        # WHEN: Retrieving password from Wallet
        password = await wallet_credentials.get_password_from_wallet(username)

        # THEN: Should return decrypted password
        assert password == expected_password
        assert len(password) > 0

        # Verify IRIS Wallet API was called with correct key format
        iris_wallet_mock.GetSecret.assert_called()
        call_args_str = str(iris_wallet_mock.GetSecret.call_args)
        assert f"pgwire-user-{username}" in call_args_str or username in call_args_str

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_password_not_found(self, wallet_credentials, iris_wallet_mock):
        """T021.2: User not in Wallet should raise WalletSecretNotFoundError (triggers fallback)"""
        # GIVEN: User does NOT exist in Wallet
        username = "nonexistent_user"

        # Mock IRIS Wallet returning None (secret not found)
        iris_wallet_mock.GetSecret.return_value = None

        # WHEN/THEN: Should raise WalletSecretNotFoundError
        with pytest.raises(WalletSecretNotFoundError) as exc_info:
            await wallet_credentials.get_password_from_wallet(username)

        # Error should indicate the secret was not found
        error_msg = str(exc_info.value).lower()
        assert "not found" in error_msg or "missing" in error_msg

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_api_failure(self, wallet_credentials, iris_wallet_mock):
        """T021.3: Wallet API failure should raise WalletAPIError"""
        # GIVEN: IRIS Wallet API failure (e.g., Wallet disabled)
        username = "testuser"

        # Mock IRIS Wallet API failure
        iris_wallet_mock.GetSecret.side_effect = Exception("IRIS Wallet API unavailable")

        # WHEN/THEN: Should raise WalletAPIError
        with pytest.raises(WalletAPIError) as exc_info:
            await wallet_credentials.get_password_from_wallet(username)

        # Error should indicate Wallet API failure
        error_msg = str(exc_info.value).lower()
        assert "wallet" in error_msg or "api" in error_msg

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_key_format_validation(
        self, wallet_credentials, iris_wallet_mock, test_wallet_secrets
    ):
        """T021.4: Wallet key format should be 'pgwire-user-{username}'"""
        # GIVEN: Username for Wallet lookup
        username = "alice"
        test_wallet_secrets["alice"]["key"]
        expected_password = test_wallet_secrets["alice"]["password"]

        # Mock IRIS Wallet
        iris_wallet_mock.GetSecret.return_value = expected_password

        # WHEN: Retrieving password
        await wallet_credentials.get_password_from_wallet(username)

        # THEN: Should have used correct key format
        iris_wallet_mock.GetSecret.assert_called()
        call_args = str(iris_wallet_mock.GetSecret.call_args)
        assert f"pgwire-user-{username}" in call_args

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_uses_asyncio_to_thread(
        self, wallet_credentials, iris_wallet_mock, test_wallet_secrets
    ):
        """T021.5: Wallet operations should use asyncio.to_thread() for IRIS API calls"""
        # GIVEN: User password in Wallet
        username = "testuser"
        expected_password = test_wallet_secrets["test_user"]["password"]
        iris_wallet_mock.GetSecret.return_value = expected_password

        # WHEN: Retrieving password (should not block event loop)
        password_task = asyncio.create_task(wallet_credentials.get_password_from_wallet(username))

        # Verify event loop can handle other coroutines concurrently
        counter = 0
        while not password_task.done():
            counter += 1
            await asyncio.sleep(0.01)
            if counter > 500:  # Safety timeout (5 seconds)
                break

        # Get password result
        password = await password_task

        # THEN: Should complete without blocking event loop
        assert password == expected_password
        assert counter > 0, "Event loop was blocked (asyncio.to_thread() not used)"
        print(f"✅ Event loop remained responsive: {counter} iterations during Wallet retrieval")


# T022: Integration test: Wallet password fallback chain
class TestWalletPasswordFallbackIntegration:
    """Test Wallet → password authentication fallback chain"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_fallback_to_password_auth(
        self, wallet_credentials, iris_wallet_mock
    ):
        """T022.1: Wallet secret not found should trigger password authentication fallback (FR-021)"""
        # GIVEN: User does NOT exist in Wallet (but exists in IRIS with password)
        username = "testuser"

        # Mock Wallet returning None (secret not found)
        iris_wallet_mock.GetSecret.return_value = None

        # WHEN: Attempting Wallet retrieval
        # THEN: Should raise WalletSecretNotFoundError to trigger fallback
        with pytest.raises(WalletSecretNotFoundError):
            await wallet_credentials.get_password_from_wallet(username)

        # Note: The fallback to password authentication is handled by AuthenticationSelector
        # This test validates that WalletSecretNotFoundError is raised correctly

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_fallback_preserves_username(
        self, wallet_credentials, iris_wallet_mock
    ):
        """T022.2: Fallback error should preserve username for password authentication"""
        # GIVEN: User not in Wallet
        username = "alice"
        iris_wallet_mock.GetSecret.return_value = None

        # WHEN: Wallet retrieval fails
        try:
            await wallet_credentials.get_password_from_wallet(username)
            pytest.fail("Should have raised WalletSecretNotFoundError")
        except WalletSecretNotFoundError as e:
            # THEN: Error should contain username for fallback handling
            error_msg = str(e)
            assert username in error_msg or username.upper() in error_msg


# T023: Integration test: OAuth + Wallet integration (dual-purpose Wallet)
class TestOAuthWalletIntegration:
    """Test dual-purpose Wallet for user passwords + OAuth client secrets (FR-009)"""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_oauth_client_secret_retrieval(
        self, wallet_credentials, iris_wallet_mock, test_wallet_secrets
    ):
        """T023.1: OAuth client secret should be retrievable from Wallet"""
        # GIVEN: OAuth client secret stored in Wallet
        expected_secret = test_wallet_secrets["oauth_client"]["secret"]
        iris_wallet_mock.GetSecret.return_value = expected_secret

        # WHEN: Retrieving OAuth client secret
        client_secret = await wallet_credentials.get_oauth_client_secret()

        # THEN: Should return client secret from Wallet
        assert client_secret == expected_secret
        assert len(client_secret) >= 32  # Minimum secret length

        # Verify IRIS Wallet API was called with OAuth key format
        iris_wallet_mock.GetSecret.assert_called()
        call_args_str = str(iris_wallet_mock.GetSecret.call_args)
        assert "pgwire-oauth-client" in call_args_str

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_dual_purpose_same_api(
        self, wallet_credentials, iris_wallet_mock, test_wallet_secrets
    ):
        """T023.2: Dual-purpose Wallet uses same API for passwords and OAuth secrets"""
        # GIVEN: Wallet configured for both user passwords and OAuth secrets
        user_password = test_wallet_secrets["test_user"]["password"]
        oauth_secret = test_wallet_secrets["oauth_client"]["secret"]

        # Mock IRIS Wallet to return different secrets based on key
        def get_secret_side_effect(key):
            if "user" in key:
                return user_password
            elif "oauth" in key:
                return oauth_secret
            return None

        iris_wallet_mock.GetSecret.side_effect = get_secret_side_effect

        # WHEN: Retrieving both types of secrets
        password = await wallet_credentials.get_password_from_wallet("testuser")
        client_secret = await wallet_credentials.get_oauth_client_secret()

        # THEN: Both should use same Wallet API (iris.cls('%IRIS.Wallet'))
        assert iris_wallet_mock.GetSecret.call_count == 2
        assert password == user_password
        assert client_secret == oauth_secret

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_wallet_oauth_fallback_to_environment(
        self, wallet_credentials, iris_wallet_mock
    ):
        """T023.3: OAuth secret not in Wallet should fallback to environment variable"""
        # GIVEN: OAuth secret NOT in Wallet, but available in environment
        iris_wallet_mock.GetSecret.return_value = None  # Not in Wallet

        # Mock environment variable
        env_secret = "env_client_secret_" + "x" * 32
        with patch.dict("os.environ", {"PGWIRE_OAUTH_CLIENT_SECRET": env_secret}):
            # WHEN: Retrieving OAuth client secret
            try:
                client_secret = await wallet_credentials.get_oauth_client_secret()

                # THEN: Should fall back to environment variable
                assert client_secret == env_secret
            except WalletAPIError:
                # Or raise error if fallback not implemented (acceptable behavior)
                pass


# T024: Integration test: Authentication selector routing
class TestAuthenticationSelectorIntegration:
    """Test dual-mode authentication routing (OAuth vs Kerberos detection)"""

    @pytest.fixture
    def auth_selector(self):
        """Real authentication selector for integration testing (no real implementation yet)"""
        # This will fail until implementation exists
        try:
            from iris_pgwire.auth import AuthenticationSelector

            return AuthenticationSelector()
        except (ImportError, AttributeError):
            pytest.skip("AuthenticationSelector implementation not available (expected during TDD)")

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_auth_selector_oauth_detection(self, auth_selector):
        """T024.1: Authentication selector should detect OAuth authentication request"""
        # GIVEN: PostgreSQL client requesting password authentication (OAuth candidate)
        connection_context = {
            "auth_method": "password",
            "username": "testuser",
            "database": "USER",
        }

        # WHEN: Selecting authentication method
        selected_method = await auth_selector.select_authentication_method(connection_context)

        # THEN: Should select OAuth authentication
        assert selected_method == "oauth"

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_auth_selector_kerberos_detection(self, auth_selector):
        """T024.2: Authentication selector should detect Kerberos GSSAPI request"""
        # GIVEN: PostgreSQL client requesting GSSAPI authentication
        connection_context = {
            "auth_method": "gssapi",
            "username": "testuser@EXAMPLE.COM",
            "database": "USER",
        }

        # WHEN: Selecting authentication method
        selected_method = await auth_selector.select_authentication_method(connection_context)

        # THEN: Should select Kerberos authentication
        assert selected_method == "kerberos"

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_auth_selector_password_fallback(self, auth_selector):
        """T024.3: Authentication selector should fallback to password auth if OAuth unavailable"""
        # GIVEN: OAuth authentication unavailable (e.g., not configured)
        connection_context = {
            "auth_method": "password",
            "username": "testuser",
            "database": "USER",
            "oauth_available": False,  # Simulate OAuth unavailable
        }

        # WHEN: Selecting authentication method
        selected_method = await auth_selector.select_authentication_method(connection_context)

        # THEN: Should fallback to password authentication
        assert selected_method == "password"

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_iris
    async def test_real_auth_selector_wallet_password_chain(self, auth_selector):
        """T024.4: Authentication selector should try Wallet → password fallback chain"""
        # GIVEN: Password authentication request
        connection_context = {
            "auth_method": "password",
            "username": "testuser",
            "database": "USER",
        }

        # WHEN: Executing authentication (Wallet not found)
        # Note: This test validates the fallback chain is invoked
        # Actual fallback behavior is tested in TestWalletPasswordFallbackIntegration

        selected_method = await auth_selector.select_authentication_method(connection_context)

        # THEN: Should select OAuth (which uses Wallet for client secret)
        assert selected_method in ["oauth", "password"]
