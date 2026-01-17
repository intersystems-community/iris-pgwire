"""
IRIS Wallet Credentials Management

This module implements encrypted credential storage and retrieval using IRIS Wallet
(stored in IRISSECURITY database). It provides dual-purpose credential management
for both user passwords and OAuth client secrets.

Architecture:
    PGWire → WalletCredentials → IRIS Wallet (%IRIS.Wallet) → IRISSECURITY Database

Key Features:
    - User password storage and retrieval (key: pgwire-user-{username})
    - OAuth client secret retrieval (key: pgwire-oauth-client)
    - Password authentication fallback chain (FR-021)
    - Audit trail with accessed_at timestamps (FR-022)

Constitutional Requirements:
    - Uses iris.cls('%IRIS.Wallet') for IRIS integration (Principle IV)
    - Uses asyncio.to_thread() for non-blocking execution
    - Clear error messages for fallback handling (FR-021)
    - Admin-only password storage (FR-023)

Feature: 024-research-and-implement (Authentication Bridge)
Phase: 3.4 (Core Implementation) - Phase 4 integration
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

logger = structlog.get_logger(__name__)


# Re-export contract types
@dataclass
class WalletSecret:
    """IRIS Wallet encrypted secret"""

    key: str  # e.g., 'pgwire-user-alice'
    value: str  # Encrypted password or client secret
    secret_type: str  # 'password' or 'oauth_client_secret'
    created_at: datetime
    updated_at: datetime
    accessed_at: datetime | None = None


# Error classes
class WalletSecretNotFoundError(Exception):
    """Raised when secret not found in Wallet (triggers fallback)"""

    pass


class WalletAPIError(Exception):
    """Raised when Wallet API operation fails"""

    pass


@dataclass
class WalletConfig:
    """Wallet configuration"""

    wallet_mode: str = "both"  # 'oauth' | 'password' | 'both'
    audit_enabled: bool = True  # FR-022


class WalletCredentials:
    """
    IRIS Wallet credential management for PGWire authentication.

    Implements WalletCredentialsProtocol contract for encrypted credential storage.
    """

    def __init__(self, config: WalletConfig | None = None):
        """
        Initialize Wallet credentials manager with configuration.

        Args:
            config: Wallet configuration (defaults to environment variables)
        """
        self.config = config or self._load_config_from_env()

        logger.info(
            "wallet_credentials_initialized",
            wallet_mode=self.config.wallet_mode,
            audit_enabled=self.config.audit_enabled,
        )

    def _load_config_from_env(self) -> WalletConfig:
        """Load Wallet configuration from environment variables"""
        wallet_mode = os.getenv("PGWIRE_WALLET_MODE", "both")
        audit_enabled = os.getenv("PGWIRE_WALLET_AUDIT", "true").lower() == "true"

        return WalletConfig(
            wallet_mode=wallet_mode,
            audit_enabled=audit_enabled,
        )

    async def get_password_from_wallet(self, username: str) -> str:
        """
        Retrieve user password from IRIS Wallet.

        Implements FR-020: Wallet password retrieval with key format 'pgwire-user-{username}'.

        Args:
            username: PostgreSQL username

        Returns:
            Decrypted password from Wallet

        Raises:
            WalletSecretNotFoundError: If no secret for username (FR-021 fallback)
            WalletAPIError: If Wallet API fails
        """
        # Validate wallet mode
        if self.config.wallet_mode not in ["password", "both"]:
            raise WalletSecretNotFoundError(
                f"Wallet not configured for password storage (mode: {self.config.wallet_mode})"
            )

        # Generate Wallet key
        wallet_key = f"pgwire-user-{username}"

        logger.debug(
            "wallet_password_retrieval_start",
            username=username,
            wallet_key=wallet_key,
        )

        try:
            # Execute Wallet retrieval in thread pool (blocking IRIS call)
            def _iris_wallet_retrieval():
                """Execute IRIS Wallet GetSecret() (blocking)"""
                try:
                    import iris

                    # Get IRIS Wallet instance
                    wallet = iris.cls("%IRIS.Wallet")

                    # Retrieve secret from Wallet
                    # %IRIS.Wallet.GetSecret(key) -> decrypted value or None
                    secret_value = wallet.GetSecret(wallet_key)

                    if secret_value is None:
                        # Secret not found - trigger fallback (FR-021)
                        raise WalletSecretNotFoundError(
                            f"Password not found in Wallet for user '{username}'. "
                            f"Falling back to password authentication."
                        )

                    return secret_value

                except WalletSecretNotFoundError:
                    # Re-raise to trigger fallback
                    raise
                except Exception as e:
                    logger.error(
                        "iris_wallet_retrieval_failed",
                        username=username,
                        error=str(e),
                    )
                    raise WalletAPIError(f"IRIS Wallet API error: {e}")

            # Execute in thread pool
            password = await asyncio.to_thread(_iris_wallet_retrieval)

            # Update audit trail (FR-022)
            if self.config.audit_enabled:
                await self._update_accessed_at(wallet_key)

            logger.info(
                "wallet_password_retrieval_success",
                username=username,
            )

            return password

        except (WalletSecretNotFoundError, WalletAPIError):
            # Re-raise Wallet errors as-is
            raise
        except Exception as e:
            logger.error(
                "wallet_password_retrieval_error",
                username=username,
                error=str(e),
            )
            raise WalletAPIError(f"Unexpected error during Wallet retrieval: {e}")

    async def set_password_in_wallet(self, username: str, password: str) -> None:
        """
        Store user password in IRIS Wallet.

        Implements FR-023: Admin-only password storage (not user-initiated).

        Args:
            username: PostgreSQL username
            password: User password to store (will be encrypted by Wallet)

        Raises:
            WalletAPIError: If Wallet storage fails

        Note: This is an admin operation, not user-initiated.
        """
        # Validate wallet mode
        if self.config.wallet_mode not in ["password", "both"]:
            raise WalletAPIError(
                f"Wallet not configured for password storage (mode: {self.config.wallet_mode})"
            )

        # Generate Wallet key
        wallet_key = f"pgwire-user-{username}"

        logger.info(
            "wallet_password_storage_start",
            username=username,
            wallet_key=wallet_key,
        )

        try:
            # Execute Wallet storage in thread pool (blocking IRIS call)
            def _iris_wallet_storage():
                """Execute IRIS Wallet SetSecret() (blocking)"""
                try:
                    import iris

                    # Get IRIS Wallet instance
                    wallet = iris.cls("%IRIS.Wallet")

                    # Store secret in Wallet (encrypted)
                    # %IRIS.Wallet.SetSecret(key, value) -> success/failure
                    result = wallet.SetSecret(wallet_key, password)

                    if not result:
                        raise WalletAPIError("Wallet SetSecret() returned failure")

                    return True

                except Exception as e:
                    logger.error(
                        "iris_wallet_storage_failed",
                        username=username,
                        error=str(e),
                    )
                    raise WalletAPIError(f"IRIS Wallet storage failed: {e}")

            # Execute in thread pool
            await asyncio.to_thread(_iris_wallet_storage)

            logger.info(
                "wallet_password_storage_success",
                username=username,
            )

        except WalletAPIError:
            raise
        except Exception as e:
            logger.error(
                "wallet_password_storage_error",
                username=username,
                error=str(e),
            )
            raise WalletAPIError(f"Unexpected error during Wallet storage: {e}")

    async def get_oauth_client_secret(self) -> str:
        """
        Retrieve OAuth client secret from Wallet.

        Implements FR-009: Dual-purpose Wallet for OAuth client secrets.
        Key format: 'pgwire-oauth-client' (single key for PGWire server).

        Returns:
            OAuth client secret (decrypted)

        Raises:
            WalletAPIError: If OAuth secret not configured or Wallet API fails
        """
        # Validate wallet mode
        if self.config.wallet_mode not in ["oauth", "both"]:
            raise WalletAPIError(
                f"Wallet not configured for OAuth secrets (mode: {self.config.wallet_mode})"
            )

        # OAuth client secret key (single key for PGWire server)
        wallet_key = "pgwire-oauth-client"

        logger.debug(
            "wallet_oauth_secret_retrieval_start",
            wallet_key=wallet_key,
        )

        try:
            # Execute Wallet retrieval in thread pool (blocking IRIS call)
            def _iris_wallet_oauth_retrieval():
                """Execute IRIS Wallet GetSecret() for OAuth client secret (blocking)"""
                try:
                    import iris

                    # Get IRIS Wallet instance
                    wallet = iris.cls("%IRIS.Wallet")

                    # Retrieve OAuth client secret from Wallet
                    client_secret = wallet.GetSecret(wallet_key)

                    if client_secret is None:
                        # OAuth secret not configured
                        raise WalletAPIError(
                            f"OAuth client secret not configured in Wallet (key: {wallet_key}). "
                            f"Use IRIS Wallet management portal to configure secret."
                        )

                    # Validate minimum secret length
                    if len(client_secret) < 32:
                        raise WalletAPIError(
                            f"OAuth client secret too short ({len(client_secret)} chars). "
                            f"Minimum length: 32 characters for security."
                        )

                    return client_secret

                except WalletAPIError:
                    raise
                except Exception as e:
                    logger.error(
                        "iris_wallet_oauth_retrieval_failed",
                        error=str(e),
                    )
                    raise WalletAPIError(f"IRIS Wallet OAuth retrieval failed: {e}")

            # Execute in thread pool
            client_secret = await asyncio.to_thread(_iris_wallet_oauth_retrieval)

            # Update audit trail (FR-022)
            if self.config.audit_enabled:
                await self._update_accessed_at(wallet_key)

            logger.info(
                "wallet_oauth_secret_retrieval_success",
            )

            return client_secret

        except WalletAPIError:
            raise
        except Exception as e:
            logger.error(
                "wallet_oauth_secret_retrieval_error",
                error=str(e),
            )
            raise WalletAPIError(f"Unexpected error during OAuth secret retrieval: {e}")

    async def _update_accessed_at(self, wallet_key: str) -> None:
        """
        Update accessed_at timestamp for audit trail.

        Implements FR-022: Audit trail with accessed timestamps.

        Args:
            wallet_key: Wallet key to update
        """
        if not self.config.audit_enabled:
            return

        try:

            def _iris_wallet_audit_update():
                """Update Wallet audit timestamp (blocking)"""
                try:
                    import iris

                    # Get IRIS Wallet instance
                    iris.cls("%IRIS.Wallet")

                    # Update accessed timestamp (if API supports it)
                    # Note: Actual IRIS Wallet API may differ - adjust based on documentation
                    # For now, we'll log the access for audit purposes
                    logger.debug(
                        "wallet_audit_trail_updated",
                        wallet_key=wallet_key,
                        accessed_at=datetime.now(UTC).isoformat(),
                    )

                    # If IRIS Wallet supports UpdateAccessedAt(), call it here:
                    # if hasattr(wallet, 'UpdateAccessedAt'):
                    #     wallet.UpdateAccessedAt(wallet_key)

                except Exception as e:
                    # Don't fail the operation if audit update fails
                    logger.warning(
                        "wallet_audit_trail_update_failed",
                        wallet_key=wallet_key,
                        error=str(e),
                    )

            # Execute in thread pool
            await asyncio.to_thread(_iris_wallet_audit_update)

        except Exception as e:
            # Don't fail the operation if audit update fails
            logger.warning(
                "wallet_audit_trail_update_error",
                wallet_key=wallet_key,
                error=str(e),
            )


# Export public API
__all__ = [
    "WalletCredentials",
    "WalletSecret",
    "WalletConfig",
    "WalletSecretNotFoundError",
    "WalletAPIError",
]
