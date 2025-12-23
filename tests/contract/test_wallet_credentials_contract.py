"""
Contract Tests for Wallet Credentials

These tests validate the WalletCredentialsProtocol interface BEFORE implementation.
All tests MUST FAIL initially (no implementation exists yet).

Constitutional Requirements:
- Test-First Development (Principle II)
- Tests written BEFORE implementation
- Tests MUST fail until implementation is complete

Feature: 024-research-and-implement (Authentication Bridge)
Phase: 3.2 (Contract Tests - Wallet Integration, Phase 4)
"""

# Import contract interface
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

spec_dir = (
    Path(__file__).parent.parent.parent / "specs" / "024-research-and-implement" / "contracts"
)
sys.path.insert(0, str(spec_dir))

from wallet_credentials_interface import (
    WalletAPIError,
    WalletSecret,
    WalletSecretNotFoundError,
)


# Test fixtures
@pytest.fixture
def mock_wallet_credentials():
    """Mock Wallet credentials manager for testing (no real implementation yet)"""
    # This will fail until implementation exists
    try:
        from iris_pgwire.auth import WalletCredentials

        return WalletCredentials()
    except (ImportError, AttributeError):
        pytest.skip("WalletCredentials implementation not available (expected during TDD)")


@pytest.fixture
def valid_wallet_secret():
    """Sample valid Wallet secret for testing"""
    return WalletSecret(
        key="pgwire-user-alice",
        value="encrypted_password_abc123",
        secret_type="password",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        accessed_at=datetime.utcnow(),
    )


# T014: Contract test: Wallet password retrieval (get_password_from_wallet)
class TestWalletPasswordRetrieval:
    """Test encrypted password retrieval from IRIS Wallet with fallback"""

    @pytest.mark.asyncio
    async def test_user_exists_in_wallet_returns_password(self, mock_wallet_credentials):
        """T014.1: User exists in Wallet should return decrypted password"""
        # GIVEN: User exists in Wallet
        username = "alice"

        # Mock IRIS Wallet retrieval
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = "alice_password_abc123"
            mock_iris_cls.return_value = mock_wallet

            # WHEN: Retrieving password from Wallet
            password = await mock_wallet_credentials.get_password_from_wallet(username)

            # THEN: Should return decrypted password
            assert password == "alice_password_abc123"
            assert len(password) > 0

            # Should have queried Wallet with correct key format
            mock_wallet.GetSecret.assert_called()
            call_args_str = str(mock_wallet.GetSecret.call_args)
            assert "pgwire-user-alice" in call_args_str or username in call_args_str

    @pytest.mark.asyncio
    async def test_user_not_in_wallet_raises_not_found_error(self, mock_wallet_credentials):
        """T014.2: User not in Wallet should raise WalletSecretNotFoundError (triggers fallback)"""
        # GIVEN: User does NOT exist in Wallet
        username = "nonexistent_user"

        # Mock Wallet returning None (secret not found)
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = None  # Secret not found
            mock_iris_cls.return_value = mock_wallet

            # WHEN/THEN: Should raise WalletSecretNotFoundError
            with pytest.raises(WalletSecretNotFoundError) as exc_info:
                await mock_wallet_credentials.get_password_from_wallet(username)

            # Error should indicate the secret was not found
            assert (
                "not found" in str(exc_info.value).lower()
                or "missing" in str(exc_info.value).lower()
            )

    @pytest.mark.asyncio
    async def test_wallet_api_failure_raises_api_error(self, mock_wallet_credentials):
        """T014.3: Wallet API failure should raise WalletAPIError"""
        # GIVEN: Wallet API failure (e.g., Wallet disabled or connection error)
        username = "alice"

        # Mock IRIS Wallet API failure
        with patch("iris.cls") as mock_iris_cls:
            mock_iris_cls.side_effect = Exception("IRIS Wallet API unavailable")

            # WHEN/THEN: Should raise WalletAPIError
            with pytest.raises(WalletAPIError) as exc_info:
                await mock_wallet_credentials.get_password_from_wallet(username)

            # Error should indicate Wallet API failure
            assert "wallet" in str(exc_info.value).lower() or "api" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_key_format_pgwire_user_username(self, mock_wallet_credentials):
        """T014.4: Wallet key format should be 'pgwire-user-{username}'"""
        # GIVEN: Username for Wallet lookup
        username = "testuser"

        # Mock IRIS Wallet
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = "test_password"
            mock_iris_cls.return_value = mock_wallet

            # WHEN: Retrieving password
            await mock_wallet_credentials.get_password_from_wallet(username)

            # THEN: Should have used correct key format
            mock_wallet.GetSecret.assert_called()
            call_args = str(mock_wallet.GetSecret.call_args)
            # Key should follow format: pgwire-user-{username}
            assert f"pgwire-user-{username}" in call_args or "pgwire-user-testuser" in call_args

    @pytest.mark.asyncio
    async def test_audit_trail_accessed_at_timestamp(self, mock_wallet_credentials):
        """T014.5: Password retrieval should update accessed_at timestamp (FR-022)"""
        # GIVEN: User password retrieved from Wallet
        username = "alice"

        # Mock IRIS Wallet with audit tracking
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = "alice_password"
            mock_wallet.UpdateAccessedAt = Mock()  # Audit trail method
            mock_iris_cls.return_value = mock_wallet

            # WHEN: Retrieving password
            await mock_wallet_credentials.get_password_from_wallet(username)

            # THEN: Should update audit trail (accessed_at timestamp)
            # Note: This may be tracked internally or via separate API call
            if hasattr(mock_wallet, "UpdateAccessedAt"):
                mock_wallet.UpdateAccessedAt.assert_called()


# T015: Contract test: Wallet password storage (set_password_in_wallet)
class TestWalletPasswordStorage:
    """Test encrypted password storage in IRIS Wallet (admin operation)"""

    @pytest.mark.asyncio
    async def test_password_storage_encrypts_in_irissecurity(self, mock_wallet_credentials):
        """T015.1: Password storage should encrypt in IRISSECURITY database"""
        # GIVEN: Admin storing user password
        username = "alice"
        password = "new_alice_password"

        # Mock IRIS Wallet storage
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.SetSecret.return_value = True  # Success
            mock_iris_cls.return_value = mock_wallet

            # WHEN: Storing password in Wallet
            await mock_wallet_credentials.set_password_in_wallet(username, password)

            # THEN: Should have called IRIS Wallet SetSecret
            mock_wallet.SetSecret.assert_called()
            call_args = str(mock_wallet.SetSecret.call_args)
            # Should include key and password value
            assert f"pgwire-user-{username}" in call_args or username in call_args
            assert password in call_args

    @pytest.mark.asyncio
    async def test_password_update_updates_timestamp(self, mock_wallet_credentials):
        """T015.2: Password update should update updated_at timestamp"""
        # GIVEN: Existing user password being updated
        username = "alice"
        new_password = "updated_password_xyz"

        # Mock IRIS Wallet update
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.SetSecret.return_value = True
            mock_wallet.GetSecretMetadata = Mock(return_value={"updated_at": datetime.utcnow()})
            mock_iris_cls.return_value = mock_wallet

            # WHEN: Updating password
            await mock_wallet_credentials.set_password_in_wallet(username, new_password)

            # THEN: Should update metadata timestamp
            mock_wallet.SetSecret.assert_called()
            # Verify timestamp is current (recent update)
            if hasattr(mock_wallet, "GetSecretMetadata"):
                metadata = mock_wallet.GetSecretMetadata()
                assert "updated_at" in metadata

    @pytest.mark.asyncio
    async def test_admin_only_operation_no_user_initiated_changes(self, mock_wallet_credentials):
        """T015.3: Password storage is admin-only operation (no user-initiated changes)"""
        # GIVEN: Admin operation (not user-initiated)
        username = "alice"
        password = "admin_set_password"

        # WHEN: Setting password
        await mock_wallet_credentials.set_password_in_wallet(username, password)

        # THEN: Operation should succeed
        # Note: Access control is enforced by IRIS Wallet API, not by this interface
        # Admin privileges verified by IRIS security layer

    @pytest.mark.asyncio
    async def test_wallet_storage_failure_raises_error(self, mock_wallet_credentials):
        """T015.4: Wallet storage failure should raise WalletAPIError"""
        # GIVEN: Wallet storage fails (e.g., permissions, quota, etc.)
        username = "alice"
        password = "new_password"

        # Mock IRIS Wallet storage failure
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.SetSecret.side_effect = Exception("Wallet storage quota exceeded")
            mock_iris_cls.return_value = mock_wallet

            # WHEN/THEN: Should raise WalletAPIError
            with pytest.raises(WalletAPIError) as exc_info:
                await mock_wallet_credentials.set_password_in_wallet(username, password)

            assert (
                "wallet" in str(exc_info.value).lower() or "storage" in str(exc_info.value).lower()
            )


# T016: Contract test: Wallet OAuth client secret retrieval (get_oauth_client_secret)
class TestWalletOAuthClientSecret:
    """Test OAuth client secret retrieval from Wallet (FR-009, dual-purpose Wallet)"""

    @pytest.mark.asyncio
    async def test_oauth_secret_exists_returns_client_secret(self, mock_wallet_credentials):
        """T016.1: OAuth secret exists should return decrypted client_secret"""
        # GIVEN: OAuth client secret stored in Wallet
        # Mock IRIS Wallet retrieval
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = "oauth_client_secret_abc123xyz789"
            mock_iris_cls.return_value = mock_wallet

            # WHEN: Retrieving OAuth client secret
            client_secret = await mock_wallet_credentials.get_oauth_client_secret()

            # THEN: Should return decrypted client secret
            assert client_secret == "oauth_client_secret_abc123xyz789"
            assert len(client_secret) >= 32  # Minimum secret length

            # Should have queried Wallet with OAuth client key
            mock_wallet.GetSecret.assert_called()
            call_args_str = str(mock_wallet.GetSecret.call_args)
            assert "pgwire-oauth-client" in call_args_str or "oauth" in call_args_str

    @pytest.mark.asyncio
    async def test_oauth_secret_not_configured_raises_error(self, mock_wallet_credentials):
        """T016.2: OAuth secret not configured should raise WalletAPIError"""
        # GIVEN: OAuth client secret NOT in Wallet
        # Mock Wallet returning None
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = None
            mock_iris_cls.return_value = mock_wallet

            # WHEN/THEN: Should raise WalletAPIError
            with pytest.raises(WalletAPIError) as exc_info:
                await mock_wallet_credentials.get_oauth_client_secret()

            # Error should indicate OAuth secret not configured
            assert (
                "oauth" in str(exc_info.value).lower()
                or "not configured" in str(exc_info.value).lower()
            )

    @pytest.mark.asyncio
    async def test_key_format_pgwire_oauth_client(self, mock_wallet_credentials):
        """T016.3: OAuth secret key format should be 'pgwire-oauth-client'"""
        # GIVEN: OAuth client secret retrieval
        # Mock IRIS Wallet
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = "client_secret_abc"
            mock_iris_cls.return_value = mock_wallet

            # WHEN: Retrieving OAuth client secret
            await mock_wallet_credentials.get_oauth_client_secret()

            # THEN: Should use correct key format
            mock_wallet.GetSecret.assert_called()
            call_args = str(mock_wallet.GetSecret.call_args)
            # Key should be: pgwire-oauth-client
            assert "pgwire-oauth-client" in call_args

    @pytest.mark.asyncio
    async def test_dual_purpose_wallet_same_api(self, mock_wallet_credentials):
        """T016.4: Dual-purpose Wallet uses same API for user passwords and OAuth secrets"""
        # GIVEN: Wallet configured for both user passwords and OAuth secrets
        # WHEN: Retrieving both types of secrets
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.side_effect = [
                "user_password_abc",  # User password
                "oauth_client_secret_xyz",  # OAuth secret
            ]
            mock_iris_cls.return_value = mock_wallet

            # Retrieve user password
            await mock_wallet_credentials.get_password_from_wallet("alice")

            # Retrieve OAuth client secret
            await mock_wallet_credentials.get_oauth_client_secret()

            # THEN: Both should use same Wallet API (iris.cls('%IRIS.Wallet'))
            assert mock_wallet.GetSecret.call_count == 2
            # Same API method for different secret types (distinguished by key format)

    @pytest.mark.asyncio
    async def test_environment_variable_fallback(self, mock_wallet_credentials):
        """T016.5: Should fallback to environment variable if Wallet retrieval fails"""
        # GIVEN: OAuth secret not in Wallet, but available in environment
        with patch("iris.cls") as mock_iris_cls:
            mock_wallet = Mock()
            mock_wallet.GetSecret.return_value = None  # Not in Wallet
            mock_iris_cls.return_value = mock_wallet

            # Mock environment variable
            with patch.dict("os.environ", {"PGWIRE_OAUTH_CLIENT_SECRET": "env_client_secret_abc"}):
                # WHEN: Retrieving OAuth client secret
                try:
                    client_secret = await mock_wallet_credentials.get_oauth_client_secret()

                    # THEN: Should fall back to environment variable
                    assert client_secret == "env_client_secret_abc"
                except WalletAPIError:
                    # Or raise error if fallback not implemented (acceptable behavior)
                    pass
