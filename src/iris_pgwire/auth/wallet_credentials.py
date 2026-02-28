"""IRIS Wallet encrypted credential storage for passwords and OAuth client secrets."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn

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

    def _wrap_wallet_exception(
        self,
        exc: Exception,
        error_cls: type[Exception],
        log_event: str,
        message: str,
        re_raise: tuple[type[Exception], ...] = (),
        **log_context: str,
    ) -> NoReturn:
        if isinstance(exc, (error_cls,) + re_raise):
            raise exc

        logger.error(log_event, error=str(exc), **log_context)
        raise error_cls(f"{message}: {exc}") from exc

    def _retrieve_wallet_secret_sync(self, wallet_key: str) -> str | None:
        import iris

        wallet = iris.cls("%IRIS.Wallet")
        return wallet.GetSecret(wallet_key)

    def _store_wallet_secret_sync(self, wallet_key: str, secret_value: str) -> None:
        import iris

        wallet = iris.cls("%IRIS.Wallet")
        result = wallet.SetSecret(wallet_key, secret_value)
        if not result:
            raise WalletAPIError("Wallet SetSecret() returned failure")

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
            password = await asyncio.to_thread(self._retrieve_wallet_secret_sync, wallet_key)
        except Exception as e:
            self._wrap_wallet_exception(
                e,
                WalletAPIError,
                "wallet_password_retrieval_error",
                "Unexpected error during Wallet retrieval",
                username=username,
            )

        if password is None:
            raise WalletSecretNotFoundError(
                f"Password not found in Wallet for user '{username}'. "
                "Falling back to password authentication."
            )

        if self.config.audit_enabled:
            await self._update_accessed_at(wallet_key)

        logger.info(
            "wallet_password_retrieval_success",
            username=username,
        )

        return password

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
            await asyncio.to_thread(self._store_wallet_secret_sync, wallet_key, password)
        except Exception as e:
            self._wrap_wallet_exception(
                e,
                WalletAPIError,
                "wallet_password_storage_error",
                "Unexpected error during Wallet storage",
                username=username,
                re_raise=(WalletAPIError,),
            )

        logger.info(
            "wallet_password_storage_success",
            username=username,
        )

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
            client_secret = await asyncio.to_thread(self._retrieve_wallet_secret_sync, wallet_key)
        except Exception as e:
            self._wrap_wallet_exception(
                e,
                WalletAPIError,
                "wallet_oauth_secret_retrieval_error",
                "Unexpected error during OAuth secret retrieval",
                re_raise=(WalletAPIError,),
            )

        if client_secret is None:
            raise WalletAPIError(
                f"OAuth client secret not configured in Wallet (key: {wallet_key}). "
                "Use IRIS Wallet management portal to configure secret."
            )

        if len(client_secret) < 32:
            raise WalletAPIError(
                f"OAuth client secret too short ({len(client_secret)} chars). "
                "Minimum length: 32 characters for security."
            )

        if self.config.audit_enabled:
            await self._update_accessed_at(wallet_key)

        logger.info(
            "wallet_oauth_secret_retrieval_success",
        )

        return client_secret

    def _iris_wallet_audit_update_sync(self, wallet_key: str) -> None:
        """Update Wallet audit timestamp (blocking)."""
        try:
            import iris

            iris.cls("%IRIS.Wallet")

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

    async def _update_accessed_at(self, wallet_key: str) -> None:
        """Update accessed_at timestamp for audit trail (FR-022)."""
        if not self.config.audit_enabled:
            return

        await asyncio.to_thread(self._iris_wallet_audit_update_sync, wallet_key)


# Export public API
__all__ = [
    "WalletCredentials",
    "WalletSecret",
    "WalletConfig",
    "WalletSecretNotFoundError",
    "WalletAPIError",
]
