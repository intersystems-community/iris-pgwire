"""
OAuth 2.0 Authentication Bridge for IRIS PGWire

This module implements OAuth 2.0 token exchange and validation using IRIS's
embedded Python OAuth client. It bridges PostgreSQL password authentication
to IRIS OAuth tokens for secure authentication.

Architecture:
    PostgreSQL Client (password) → OAuthBridge → IRIS OAuth Server → OAuth Token

Key Features:
    - Password grant flow (RFC 6749 Section 4.3)
    - Token introspection for validation
    - Token refresh for expiry handling
    - Dual-mode client secret: Wallet (preferred) or environment variable

Constitutional Requirements:
    - Uses iris.cls('OAuth2.Client') for IRIS integration (Principle IV)
    - Uses asyncio.to_thread() for non-blocking execution
    - <5s authentication latency (FR-028)
    - Audit trail for all token exchanges (FR-026)

Feature: 024-research-and-implement (Authentication Bridge)
Phase: 3.4 (Core Implementation)
"""

import asyncio
import os

# Import contract interface
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog

logger = structlog.get_logger(__name__)


# Re-export contract types
@dataclass
class OAuthToken:
    """OAuth 2.0 access token issued by IRIS OAuth server"""

    access_token: str
    refresh_token: str | None
    token_type: str  # 'Bearer'
    expires_in: int  # Seconds
    issued_at: datetime
    username: str
    scopes: list[str]

    @property
    def expires_at(self) -> datetime:
        """Calculate token expiry timestamp"""
        from datetime import timedelta

        return self.issued_at + timedelta(seconds=self.expires_in)

    @property
    def is_expired(self) -> bool:
        """Check if token has expired"""
        return datetime.now(UTC) >= self.expires_at


# Error classes
class OAuthAuthenticationError(Exception):
    """Raised when OAuth token exchange fails"""

    pass


class OAuthValidationError(Exception):
    """Raised when OAuth token validation request fails"""

    pass


class OAuthRefreshError(Exception):
    """Raised when OAuth token refresh fails"""

    pass


class OAuthConfigurationError(Exception):
    """Raised when OAuth client credentials not configured"""

    pass


@dataclass
class OAuthConfig:
    """OAuth bridge configuration from environment variables"""

    client_id: str  # PGWIRE_OAUTH_CLIENT_ID
    token_endpoint: str  # PGWIRE_OAUTH_TOKEN_ENDPOINT
    introspection_endpoint: str  # PGWIRE_OAUTH_INTROSPECTION_ENDPOINT
    use_wallet_for_secret: bool = True  # PGWIRE_OAUTH_USE_WALLET


class OAuthBridge:
    """
    OAuth 2.0 authentication bridge using IRIS embedded Python.

    Implements OAuthBridgeProtocol contract for token exchange, validation,
    and refresh operations.
    """

    def __init__(self, config: OAuthConfig | None = None):
        """
        Initialize OAuth bridge with configuration.

        Args:
            config: OAuth configuration (defaults to environment variables)
        """
        self.config = config or self._load_config_from_env()
        self._wallet_credentials: any | None = None  # Lazy-loaded WalletCredentials

        logger.info(
            "oauth_bridge_initialized",
            client_id=self.config.client_id,
            use_wallet=self.config.use_wallet_for_secret,
        )

    def _load_config_from_env(self) -> OAuthConfig:
        """Load OAuth configuration from environment variables"""
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

    async def exchange_password_for_token(self, username: str, password: str) -> OAuthToken:
        """
        Exchange username/password for IRIS OAuth 2.0 access token.

        Implements FR-007: Password grant flow (RFC 6749 Section 4.3).

        Args:
            username: PostgreSQL username from SCRAM handshake
            password: PostgreSQL password from SCRAM handshake

        Returns:
            OAuthToken with access_token, refresh_token, expiry

        Raises:
            OAuthAuthenticationError: If token exchange fails
            OAuthConfigurationError: If client credentials not configured

        Performance: <5s (FR-028)
        """
        logger.info(
            "oauth_token_exchange_start",
            username=username,
            client_id=self.config.client_id,
        )

        try:
            # Get OAuth client credentials
            client_id, client_secret = await self.get_client_credentials()

            # Execute token exchange in thread pool (blocking IRIS call)
            def _iris_token_exchange():
                """Execute IRIS OAuth2.Client.RequestToken() (blocking)"""
                try:
                    import iris

                    # Get IRIS OAuth2.Client instance
                    oauth_client = iris.cls("OAuth2.Client")

                    # Request token using password grant
                    # OAuth2.Client.RequestToken(appname, username, password) -> token response
                    token_response = oauth_client.RequestToken(
                        client_id,  # Application name
                        username,  # Resource owner username
                        password,  # Resource owner password
                    )

                    # Parse token response
                    # Expected structure: {"access_token": "...", "refresh_token": "...", "expires_in": 3600}
                    if not token_response or "access_token" not in token_response:
                        raise OAuthAuthenticationError(
                            "Invalid token response from IRIS OAuth server"
                        )

                    return token_response

                except Exception as e:
                    logger.error(
                        "iris_oauth_token_exchange_failed",
                        username=username,
                        error=str(e),
                    )
                    raise OAuthAuthenticationError(f"OAuth token exchange failed: {e}")

            # Execute in thread pool to avoid blocking event loop
            token_response = await asyncio.to_thread(_iris_token_exchange)

            # Create OAuthToken from response
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

        except OAuthAuthenticationError:
            # Re-raise OAuth errors as-is
            raise
        except Exception as e:
            # Wrap unexpected errors
            logger.error(
                "oauth_token_exchange_error",
                username=username,
                error=str(e),
            )
            raise OAuthAuthenticationError(f"Unexpected error during token exchange: {e}")

    async def validate_token(self, access_token: str) -> bool:
        """
        Validate OAuth token against IRIS OAuth 2.0 server.

        Implements FR-008: Token introspection for validation.

        Args:
            access_token: OAuth access token to validate

        Returns:
            True if token is active, False if inactive

        Raises:
            OAuthValidationError: If validation request fails

        Performance: <1s
        """
        logger.debug(
            "oauth_token_validation_start",
            token_preview=access_token[:20] + "..." if len(access_token) > 20 else access_token,
        )

        try:
            # Execute token validation in thread pool (blocking IRIS call)
            def _iris_token_validation():
                """Execute IRIS OAuth2.Client.IntrospectToken() (blocking)"""
                try:
                    import iris

                    # Get IRIS OAuth2.Client instance
                    oauth_client = iris.cls("OAuth2.Client")

                    # Get client credentials for introspection
                    client_id, client_secret = self._get_client_credentials_sync()

                    # Introspect token
                    # OAuth2.Client.IntrospectToken(token, client_id, client_secret) -> introspection response
                    introspection_response = oauth_client.IntrospectToken(
                        access_token, client_id, client_secret
                    )

                    # Parse introspection response
                    # Expected structure: {"active": true/false, ...}
                    if introspection_response is None:
                        return False

                    return introspection_response.get("active", False)

                except Exception as e:
                    logger.error(
                        "iris_oauth_token_validation_failed",
                        error=str(e),
                    )
                    raise OAuthValidationError(f"OAuth token validation failed: {e}")

            # Execute in thread pool
            is_active = await asyncio.to_thread(_iris_token_validation)

            logger.debug(
                "oauth_token_validation_complete",
                is_active=is_active,
            )

            return is_active

        except OAuthValidationError:
            raise
        except Exception as e:
            logger.error(
                "oauth_token_validation_error",
                error=str(e),
            )
            raise OAuthValidationError(f"Unexpected error during token validation: {e}")

    async def refresh_token(self, refresh_token: str) -> OAuthToken:
        """
        Refresh expired OAuth token using refresh token.

        Implements FR-010: Token refresh for expiry handling.

        Args:
            refresh_token: OAuth refresh token from previous token exchange

        Returns:
            New OAuthToken with updated access_token

        Raises:
            OAuthRefreshError: If refresh fails

        Performance: <5s
        """
        logger.info("oauth_token_refresh_start")

        try:
            # Get OAuth client credentials
            client_id, client_secret = await self.get_client_credentials()

            # Execute token refresh in thread pool (blocking IRIS call)
            def _iris_token_refresh():
                """Execute IRIS OAuth2.Client.RefreshToken() (blocking)"""
                try:
                    import iris

                    # Get IRIS OAuth2.Client instance
                    oauth_client = iris.cls("OAuth2.Client")

                    # Refresh token using refresh grant
                    # OAuth2.Client.RefreshToken(appname, refresh_token) -> token response
                    token_response = oauth_client.RefreshToken(client_id, refresh_token)

                    # Parse token response
                    if not token_response or "access_token" not in token_response:
                        raise OAuthRefreshError(
                            "Invalid refresh token response from IRIS OAuth server"
                        )

                    return token_response

                except Exception as e:
                    logger.error(
                        "iris_oauth_token_refresh_failed",
                        error=str(e),
                    )
                    raise OAuthRefreshError(f"OAuth token refresh failed: {e}")

            # Execute in thread pool
            token_response = await asyncio.to_thread(_iris_token_refresh)

            # Create new OAuthToken from response
            new_token = OAuthToken(
                access_token=token_response["access_token"],
                refresh_token=token_response.get(
                    "refresh_token", refresh_token
                ),  # May return new refresh token
                token_type=token_response.get("token_type", "Bearer"),
                expires_in=token_response.get("expires_in", 3600),
                issued_at=datetime.now(UTC),
                username="",  # Username not available in refresh response
                scopes=(
                    token_response.get("scope", "").split() if token_response.get("scope") else []
                ),
            )

            logger.info(
                "oauth_token_refresh_success",
                expires_in=new_token.expires_in,
            )

            return new_token

        except OAuthRefreshError:
            raise
        except Exception as e:
            logger.error(
                "oauth_token_refresh_error",
                error=str(e),
            )
            raise OAuthRefreshError(f"Unexpected error during token refresh: {e}")

    async def get_client_credentials(self) -> tuple[str, str]:
        """
        Retrieve OAuth client ID and secret for PGWire server.

        Implements FR-009: Client secret from Wallet (preferred) or environment.

        Returns:
            Tuple of (client_id, client_secret)

        Raises:
            OAuthConfigurationError: If client credentials not configured
        """
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
        """Synchronous version of get_client_credentials() for use in blocking IRIS calls"""
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
        """Retrieve OAuth client secret from IRIS Wallet (Phase 4 integration)"""
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
