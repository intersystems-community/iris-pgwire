"""
OAuth Bridge Interface Contract

This contract defines the API for OAuth 2.0 token exchange and validation.
Tests MUST be written against this interface BEFORE implementation.

Constitutional Requirements:
- Test-First Development (Principle II)
- IRIS Integration via embedded Python (Principle IV)
- Performance: <5s authentication (FR-028)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


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
        return datetime.utcnow() >= self.expires_at


class OAuthBridgeProtocol(Protocol):
    """
    Protocol for OAuth 2.0 authentication bridge.

    Implements FR-006 through FR-012 from spec.md.
    """

    async def exchange_password_for_token(self, username: str, password: str) -> OAuthToken:
        """
        Exchange username/password for IRIS OAuth 2.0 access token.

        Implements FR-007: System MUST exchange username/password for IRIS OAuth 2.0
        access token via IRIS OAuth server token endpoint.

        Args:
            username: PostgreSQL username from SCRAM handshake
            password: PostgreSQL password from SCRAM handshake

        Returns:
            OAuthToken with access_token, refresh_token, expiry

        Raises:
            OAuthAuthenticationError: If token exchange fails (invalid credentials,
                                     OAuth server unavailable, etc.)
            OAuthConfigurationError: If OAuth client credentials not configured

        Performance:
            - MUST complete within 5 seconds (FR-028)
            - Typical: 100-200ms for IRIS OAuth server call

        Example:
            token = await oauth_bridge.exchange_password_for_token('alice', 'secret123')
            assert token.access_token is not None
            assert not token.is_expired
        """
        ...

    async def validate_token(self, access_token: str) -> bool:
        """
        Validate OAuth token against IRIS OAuth 2.0 server.

        Implements FR-008: System MUST validate OAuth tokens against IRIS OAuth 2.0
        server (not local verification). Uses token introspection endpoint.

        Args:
            access_token: OAuth access token to validate

        Returns:
            True if token is active (not expired, not revoked)
            False if token is inactive

        Raises:
            OAuthValidationError: If validation request fails (network error, etc.)

        Performance:
            - MUST complete within 1 second
            - Typical: 50-100ms for IRIS OAuth server call

        Example:
            is_valid = await oauth_bridge.validate_token(token.access_token)
            assert is_valid is True
        """
        ...

    async def refresh_token(self, refresh_token: str) -> OAuthToken:
        """
        Refresh expired OAuth token using refresh token.

        Implements FR-010: System MUST handle OAuth token expiry and refresh
        transparently. Uses OAuth refresh token grant type.

        Args:
            refresh_token: OAuth refresh token from previous token exchange

        Returns:
            New OAuthToken with updated access_token and expiry

        Raises:
            OAuthRefreshError: If refresh fails (invalid refresh token, etc.)

        Performance:
            - MUST complete within 5 seconds
            - Typical: 100-200ms for IRIS OAuth server call

        Example:
            new_token = await oauth_bridge.refresh_token(old_token.refresh_token)
            assert new_token.access_token != old_token.access_token
            assert not new_token.is_expired
        """
        ...

    async def get_client_credentials(self) -> tuple[str, str]:
        """
        Retrieve OAuth client ID and secret for PGWire server.

        Implements FR-009: System MUST store PGWire OAuth client credentials
        securely (preferably in IRIS Wallet).

        Returns:
            Tuple of (client_id, client_secret)

        Raises:
            OAuthConfigurationError: If client credentials not configured or
                                    Wallet retrieval fails

        Example:
            client_id, client_secret = await oauth_bridge.get_client_credentials()
            assert client_id == 'pgwire-server'
            assert len(client_secret) >= 32  # Minimum secret length
        """
        ...


# Error Classes


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


# Configuration


@dataclass
class OAuthConfig:
    """OAuth bridge configuration from environment variables"""

    client_id: str  # PGWIRE_OAUTH_CLIENT_ID
    token_endpoint: str  # PGWIRE_OAUTH_TOKEN_ENDPOINT (e.g., http://iris:52773/oauth2/token)
    introspection_endpoint: str  # PGWIRE_OAUTH_INTROSPECTION_ENDPOINT
    use_wallet_for_secret: bool = True  # PGWIRE_OAUTH_USE_WALLET (default: true, Phase 4)


# Test Contract Requirements

"""
Contract tests MUST verify:

1. Token Exchange (FR-007):
   - Valid credentials → returns OAuthToken with access_token
   - Invalid credentials → raises OAuthAuthenticationError
   - OAuth server down → raises OAuthAuthenticationError
   - Completes within 5 seconds

2. Token Validation (FR-008):
   - Valid active token → returns True
   - Expired token → returns False
   - Revoked token → returns False
   - Invalid token → raises OAuthValidationError

3. Token Refresh (FR-010):
   - Valid refresh token → returns new OAuthToken
   - Invalid refresh token → raises OAuthRefreshError
   - Expired refresh token → raises OAuthRefreshError

4. Client Credentials (FR-009):
   - Wallet configured → retrieves from IRIS Wallet
   - Environment variable → retrieves from env var
   - Not configured → raises OAuthConfigurationError

5. Integration with IRIS (Principle IV):
   - Uses iris.cls('OAuth2.Client') for token operations
   - Uses asyncio.to_thread() for blocking IRIS calls
   - No external HTTP client (embedded Python only)

6. Error Handling (FR-027):
   - All errors surface clear messages to PostgreSQL clients
   - Error codes: SQLSTATE 28000 (invalid authorization specification)

7. Audit Trail (FR-026):
   - All token exchanges logged with username, timestamp, success/failure
   - Failed attempts logged for security monitoring
"""
