"""
Authentication Selector for Dual-Mode Authentication Routing

This module implements intelligent authentication method selection based on
PostgreSQL client authentication requests. It routes between OAuth, Kerberos,
and password authentication with automatic fallback chains.

Architecture:
    PostgreSQL Client → AuthenticationSelector → [OAuth | Kerberos | Password]

Key Features:
    - Automatic OAuth vs Kerberos detection (FR-024)
    - Wallet → password authentication fallback chain (FR-021)
    - Password → OAuth transparent routing
    - Backward compatibility with password-only authentication

Constitutional Requirements:
    - Maintains 100% backward compatibility (Principle III)
    - Clear error messages for routing decisions
    - <5s authentication latency (FR-028)

Feature: 024-research-and-implement (Authentication Bridge)
Phase: 3.4 (Core Implementation)
"""

from typing import Any, Literal

import structlog

logger = structlog.get_logger(__name__)


# Authentication method types
AuthMethod = Literal["oauth", "kerberos", "password"]


class AuthenticationSelector:
    """
    Intelligent authentication method selector with fallback chains.

    Routes PostgreSQL authentication requests to appropriate backend:
    - GSSAPI → Kerberos authentication
    - SCRAM-SHA-256 password → OAuth (with Wallet fallback) or password
    """

    def __init__(
        self,
        oauth_enabled: bool = True,
        kerberos_enabled: bool = True,
        wallet_enabled: bool = True,
    ):
        """
        Initialize authentication selector with feature flags.

        Args:
            oauth_enabled: Enable OAuth authentication (default: True)
            kerberos_enabled: Enable Kerberos GSSAPI authentication (default: True)
            wallet_enabled: Enable IRIS Wallet integration (default: True)
        """
        self.oauth_enabled = oauth_enabled
        self.kerberos_enabled = kerberos_enabled
        self.wallet_enabled = wallet_enabled

        logger.info(
            "authentication_selector_initialized",
            oauth_enabled=oauth_enabled,
            kerberos_enabled=kerberos_enabled,
            wallet_enabled=wallet_enabled,
        )

    async def select_authentication_method(self, connection_context: dict[str, Any]) -> AuthMethod:
        """
        Select authentication method based on client request.

        Implements FR-024: Dual-mode authentication routing.

        Args:
            connection_context: Connection metadata including:
                - auth_method: PostgreSQL auth method ('password', 'gssapi', 'sasl')
                - username: PostgreSQL username
                - database: Target database
                - oauth_available: Optional flag to disable OAuth (default: True)

        Returns:
            Selected authentication method: 'oauth', 'kerberos', or 'password'

        Routing Logic:
            1. GSSAPI auth method → Kerberos (if enabled)
            2. Password auth method:
                a. OAuth enabled + configured → OAuth
                b. OAuth unavailable/fails → Password fallback
            3. Backward compatibility: password-only always supported

        Example:
            # Kerberos request
            context = {'auth_method': 'gssapi', 'username': 'alice@EXAMPLE.COM'}
            method = await selector.select_authentication_method(context)
            # Returns: 'kerberos'

            # Password request (OAuth enabled)
            context = {'auth_method': 'password', 'username': 'alice'}
            method = await selector.select_authentication_method(context)
            # Returns: 'oauth'

            # Password request (OAuth disabled)
            context = {'auth_method': 'password', 'username': 'alice', 'oauth_available': False}
            method = await selector.select_authentication_method(context)
            # Returns: 'password'
        """
        auth_method = connection_context.get("auth_method", "password")
        username = connection_context.get("username", "unknown")
        oauth_available = connection_context.get("oauth_available", True)

        logger.debug(
            "authentication_method_selection_start",
            auth_method=auth_method,
            username=username,
            oauth_available=oauth_available,
        )

        # Route 1: GSSAPI → Kerberos (if enabled)
        if auth_method in ["gssapi", "sasl"]:
            if self.kerberos_enabled:
                logger.info(
                    "authentication_method_selected",
                    method="kerberos",
                    reason="GSSAPI authentication requested",
                    username=username,
                )
                return "kerberos"
            else:
                logger.warning(
                    "kerberos_disabled",
                    username=username,
                    falling_back_to="password",
                )
                return "password"

        # Route 2: Password → OAuth (if enabled and available)
        if auth_method in ["password", "scram-sha-256", "md5"]:
            # Check if OAuth is enabled and available
            if self.oauth_enabled and oauth_available:
                logger.info(
                    "authentication_method_selected",
                    method="oauth",
                    reason="OAuth enabled for password authentication",
                    username=username,
                )
                return "oauth"
            else:
                # Fallback to password authentication
                reason = "OAuth disabled" if not self.oauth_enabled else "OAuth unavailable"
                logger.info(
                    "authentication_method_selected",
                    method="password",
                    reason=reason,
                    username=username,
                )
                return "password"

        # Default: Password authentication (backward compatibility)
        logger.info(
            "authentication_method_selected",
            method="password",
            reason="Unknown auth method, defaulting to password",
            auth_method=auth_method,
            username=username,
        )
        return "password"

    async def should_try_wallet_first(self, auth_method: AuthMethod, username: str) -> bool:
        """
        Determine if Wallet password retrieval should be attempted first.

        Implements FR-021: Wallet → password fallback chain.

        Args:
            auth_method: Selected authentication method
            username: PostgreSQL username

        Returns:
            True if Wallet should be tried before password authentication

        Wallet Priority Logic:
            - OAuth authentication: YES (for client secret)
            - Password authentication: YES (for user password)
            - Kerberos authentication: NO (doesn't use passwords)
        """
        # Wallet is used for OAuth (client secret) and password (user password)
        if not self.wallet_enabled:
            return False

        if auth_method in ["oauth", "password"]:
            logger.debug(
                "wallet_priority_check",
                auth_method=auth_method,
                username=username,
                try_wallet=True,
            )
            return True

        logger.debug(
            "wallet_priority_check",
            auth_method=auth_method,
            username=username,
            try_wallet=False,
        )
        return False

    def get_authentication_chain(self, primary_method: AuthMethod) -> list[AuthMethod]:
        """
        Get authentication fallback chain for a primary method.

        Implements FR-021: Automatic fallback chains.

        Args:
            primary_method: Primary authentication method

        Returns:
            List of authentication methods to try in order

        Fallback Chains:
            - OAuth: ['oauth', 'password']
            - Kerberos: ['kerberos', 'password']
            - Password: ['password']

        Example:
            chain = selector.get_authentication_chain('oauth')
            # Returns: ['oauth', 'password']
            # Try OAuth first, fallback to password if OAuth fails
        """
        # Define fallback chains
        fallback_chains: dict[AuthMethod, list[AuthMethod]] = {
            "oauth": ["oauth", "password"] if self.oauth_enabled else ["password"],
            "kerberos": ["kerberos", "password"] if self.kerberos_enabled else ["password"],
            "password": ["password"],
        }

        chain = fallback_chains.get(primary_method, ["password"])

        logger.debug(
            "authentication_chain_determined",
            primary_method=primary_method,
            chain=chain,
        )

        return chain


# Export public API
__all__ = [
    "AuthenticationSelector",
    "AuthMethod",
]
