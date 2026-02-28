"""Bridge OAuth token exchange and validation via embedded IRIS."""

import asyncio
import os

# Import contract interface
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn

import structlog

logger = structlog.get_logger(__name__)


# Re-export contract types
@dataclass
class OAuthToken:
    """OAuth 2.0 token response."""

    access_token: str
    refresh_token: str | None
    token_type: str  # 'Bearer'
    expires_in: int  # Seconds
    issued_at: datetime
    username: str
    scopes: list[str]

    @property
    def expires_at(self) -> datetime:
        from datetime import timedelta

        return self.issued_at + timedelta(seconds=self.expires_in)

    @property
    def is_expired(self) -> bool:
        """Check if token has expired"""
        return datetime.now(UTC) >= self.expires_at


# Error classes
class OAuthAuthenticationError(Exception):
    """Raised when OAuth token exchange fails."""

    pass


class OAuthValidationError(Exception):
    """Raised when OAuth token validation fails."""

    pass


class OAuthRefreshError(Exception):
    """Raised when OAuth token refresh fails."""

    pass


class OAuthConfigurationError(Exception):
    """Raised when OAuth client credentials are missing."""

    pass


@dataclass
class OAuthConfig:
    """OAuth bridge configuration."""

    client_id: str  # PGWIRE_OAUTH_CLIENT_ID
    token_endpoint: str  # PGWIRE_OAUTH_TOKEN_ENDPOINT
    introspection_endpoint: str  # PGWIRE_OAUTH_INTROSPECTION_ENDPOINT
    use_wallet_for_secret: bool = True  # PGWIRE_OAUTH_USE_WALLET


class OAuthBridge:
    """Perform OAuth token exchange, refresh, and validation."""

    def __init__(self, config: OAuthConfig | None = None):
        self.config = config or self._load_config_from_env()
        self._wallet_credentials: any | None = None  # Lazy-loaded WalletCredentials

        logger.info(
            "oauth_bridge_initialized",
            client_id=self.config.client_id,
            use_wallet=self.config.use_wallet_for_secret,
        )

    def _load_config_from_env(self) -> OAuthConfig:
        """Load OAuth configuration from the environment."""
        client_id = os.getenv("PGWIRE_OAUTH_CLIENT_ID", "pgwire-server")

        # Default IRIS OAuth endpoints (localhost for embedded Python)
        iris_host = os.getenv("IRIS_HOST", "localhost")
        iris_port = os.getenv("IRIS_PORT", "52773")
        token_endpoint = os.getenv(
            "PGWIRE_OAUTH_TOKEN_ENDPOINT", f"http://{iris_host}:{iris_port}/oauth2/token"
        )
        introspection_endpoint = os.getenv(
            "PGWIRE_OAUTH_INTROSPECTION_ENDPOINT",
            f"http://{iris_host}:{iris_port}/oauth2/introspect",
        )
        use_wallet = os.getenv("PGWIRE_OAUTH_USE_WALLET", "true").lower() == "true"

        return OAuthConfig(
            client_id=client_id,
            token_endpoint=token_endpoint,
            introspection_endpoint=introspection_endpoint,
            use_wallet_for_secret=use_wallet,
        )

    def _raise_with_context(
        self,
        exc: Exception,
        error_cls: type[Exception],
        log_event: str,
        message: str,
        **log_context: str,
    ) -> NoReturn:
        """Log and raise the requested error class, preserving prior exceptions."""
        if isinstance(exc, error_cls):
            raise exc

        logger.error(log_event, error=str(exc), **{k: v for k, v in log_context.items() if v})
        raise error_cls(f"{message}: {exc}") from exc

    def _iris_token_exchange_sync(self, client_id: str, username: str, password: str) -> dict:
        """Blocking token exchange against IRIS."""
        try:
            import iris

            oauth_client = iris.cls("OAuth2.Client")
            token_response = oauth_client.RequestToken(client_id, username, password)

            if not token_response or "access_token" not in token_response:
                raise OAuthAuthenticationError("Invalid token response from IRIS OAuth server")

            return token_response

        except OAuthAuthenticationError:
            raise
        except Exception as e:
            logger.error(
                "iris_oauth_token_exchange_failed",
                username=username,
                error=str(e),
            )
            raise OAuthAuthenticationError(f"OAuth token exchange failed: {e}")

    async def exchange_password_for_token(self, username: str, password: str) -> OAuthToken:
        """Exchange credentials for an OAuth token."""
        logger.info(
            "oauth_token_exchange_start",
            username=username,
            client_id=self.config.client_id,
        )

        try:
            client_id, _ = await self.get_client_credentials()

            token_response = await asyncio.to_thread(
                self._iris_token_exchange_sync, client_id, username, password
            )

            token = OAuthToken(
                access_token=token_response["access_token"],
                refresh_token=token_response.get("refresh_token"),
                token_type=token_response.get("token_type", "Bearer"),
                expires_in=token_response.get("expires_in", 3600),
                issued_at=datetime.now(UTC),
                username=username,
                scopes=(
                    token_response.get("scope", "").split() if token_response.get("scope") else []
                ),
            )

            logger.info(
                "oauth_token_exchange_success",
                username=username,
                expires_in=token.expires_in,
                has_refresh_token=token.refresh_token is not None,
            )

            return token

        except Exception as e:
            self._raise_with_context(
                e,
                OAuthAuthenticationError,
                "oauth_token_exchange_error",
                "Unexpected error during token exchange",
                username=username,
            )

    def _iris_token_validation_sync(self, access_token: str) -> bool:
        """Blocking introspection against IRIS."""
        try:
            import iris

            oauth_client = iris.cls("OAuth2.Client")
            client_id, client_secret = self._get_client_credentials_sync()

            introspection_response = oauth_client.IntrospectToken(
                access_token, client_id, client_secret
            )

            if introspection_response is None:
                return False

            return introspection_response.get("active", False)

        except Exception as e:
            logger.error(
                "iris_oauth_token_validation_failed",
                error=str(e),
            )
            raise OAuthValidationError(f"OAuth token validation failed: {e}")

    async def validate_token(self, access_token: str) -> bool:
        """Validate an OAuth token."""
        logger.debug(
            "oauth_token_validation_start",
            token_preview=access_token[:20] + "..." if len(access_token) > 20 else access_token,
        )

        try:
            is_active = await asyncio.to_thread(self._iris_token_validation_sync, access_token)

            logger.debug(
                "oauth_token_validation_complete",
                is_active=is_active,
            )

            return is_active

        except Exception as e:
            self._raise_with_context(
                e,
                OAuthValidationError,
                "oauth_token_validation_error",
                "Unexpected error during token validation",
            )

    def _iris_token_refresh_sync(self, client_id: str, refresh_token: str) -> dict:
        """Blocking refresh call."""
        try:
            import iris

            oauth_client = iris.cls("OAuth2.Client")
            token_response = oauth_client.RefreshToken(client_id, refresh_token)

            if not token_response or "access_token" not in token_response:
                raise OAuthRefreshError("Invalid refresh token response from IRIS OAuth server")

            return token_response

        except OAuthRefreshError:
            raise
        except Exception as e:
            logger.error(
                "iris_oauth_token_refresh_failed",
                error=str(e),
            )
            raise OAuthRefreshError(f"OAuth token refresh failed: {e}")

    async def refresh_token(self, refresh_token: str) -> OAuthToken:
        """Refresh expired OAuth token using refresh token."""
        logger.info("oauth_token_refresh_start")

        try:
            client_id, _ = await self.get_client_credentials()

            token_response = await asyncio.to_thread(
                self._iris_token_refresh_sync, client_id, refresh_token
            )

            new_token = OAuthToken(
                access_token=token_response["access_token"],
                refresh_token=token_response.get("refresh_token", refresh_token),
                token_type=token_response.get("token_type", "Bearer"),
                expires_in=token_response.get("expires_in", 3600),
                issued_at=datetime.now(UTC),
                username="",
                scopes=(
                    token_response.get("scope", "").split() if token_response.get("scope") else []
                ),
            )

            logger.info(
                "oauth_token_refresh_success",
                expires_in=new_token.expires_in,
            )

            return new_token

        except Exception as e:
            self._raise_with_context(
                e,
                OAuthRefreshError,
                "oauth_token_refresh_error",
                "Unexpected error during token refresh",
            )

    async def get_client_credentials(self) -> tuple[str, str]:
        """Return OAuth client credentials, preferring the Wallet."""
        client_id = self.config.client_id

        # Try Wallet first (if enabled)
        if self.config.use_wallet_for_secret:
            try:
                client_secret = await self._get_client_secret_from_wallet()
                logger.debug(
                    "oauth_client_credentials_from_wallet",
                    client_id=client_id,
                )
                return client_id, client_secret
            except Exception as e:
                logger.warning(
                    "wallet_client_secret_retrieval_failed",
                    error=str(e),
                    falling_back_to_env=True,
                )
                # Fall through to environment variable

        # Fallback to environment variable
        client_secret = os.getenv("PGWIRE_OAUTH_CLIENT_SECRET")
        if not client_secret:
            raise OAuthConfigurationError(
                "OAuth client secret not configured. "
                "Set PGWIRE_OAUTH_CLIENT_SECRET environment variable or configure IRIS Wallet."
            )

        # Validate minimum secret length
        if len(client_secret) < 32:
            raise OAuthConfigurationError(
                f"OAuth client secret too short ({len(client_secret)} chars). "
                "Minimum length: 32 characters for security."
            )

        logger.debug(
            "oauth_client_credentials_from_env",
            client_id=client_id,
        )

        return client_id, client_secret

    def _get_client_credentials_sync(self) -> tuple[str, str]:
        """Synchronous credentials helper."""
        client_id = self.config.client_id

        # Try environment variable (Wallet access requires async)
        client_secret = os.getenv("PGWIRE_OAUTH_CLIENT_SECRET")
        if not client_secret:
            raise OAuthConfigurationError(
                "OAuth client secret not configured in environment. "
                "Set PGWIRE_OAUTH_CLIENT_SECRET or use async get_client_credentials() for Wallet access."
            )

        return client_id, client_secret

    async def _get_client_secret_from_wallet(self) -> str:
        """Retrieve OAuth client secret from the Wallet."""
        # Lazy-load WalletCredentials to avoid circular import
        if self._wallet_credentials is None:
            from .wallet_credentials import WalletCredentials

            self._wallet_credentials = WalletCredentials()

        # Retrieve OAuth client secret from Wallet
        client_secret = await self._wallet_credentials.get_oauth_client_secret()
        return client_secret


# Export public API
__all__ = [
    "OAuthBridge",
    "OAuthToken",
    "OAuthConfig",
    "OAuthAuthenticationError",
    "OAuthValidationError",
    "OAuthRefreshError",
    "OAuthConfigurationError",
]
