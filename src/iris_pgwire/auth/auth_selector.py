"""Choose OAuth, Kerberos, or password auth based on context."""

from typing import Any, Literal

import structlog

logger = structlog.get_logger(__name__)


# Authentication method types
AuthMethod = Literal["oauth", "kerberos", "password"]


class AuthenticationSelector:
    """Route PostgreSQL auth requests to the best-supported backend."""

    def __init__(
        self,
        oauth_enabled: bool = True,
        kerberos_enabled: bool = True,
        wallet_enabled: bool = True,
    ):
        self.oauth_enabled = oauth_enabled
        self.kerberos_enabled = kerberos_enabled
        self.wallet_enabled = wallet_enabled

        logger.debug(
            "authentication_selector_initialized",
            oauth_enabled=oauth_enabled,
            kerberos_enabled=kerberos_enabled,
            wallet_enabled=wallet_enabled,
        )

    async def select_authentication_method(self, connection_context: dict[str, Any]) -> AuthMethod:
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
            logger.warning(
                "kerberos_disabled",
                username=username,
                falling_back_to="password",
            )
            return "password"

        # Route 2: Password → OAuth (if enabled and available)
        if auth_method in ["password", "scram-sha-256", "md5"]:
            if self.oauth_enabled and oauth_available:
                logger.info(
                    "authentication_method_selected",
                    method="oauth",
                    reason="OAuth enabled for password authentication",
                    username=username,
                )
                return "oauth"
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
        if not self.wallet_enabled:
            return False

        return auth_method in ["oauth", "password"]

    def get_authentication_chain(self, primary_method: AuthMethod) -> list[AuthMethod]:
        fallback_chains: dict[AuthMethod, list[AuthMethod]] = {
            "oauth": ["oauth", "password"] if self.oauth_enabled else ["password"],
            "kerberos": ["kerberos", "password"] if self.kerberos_enabled else ["password"],
            "password": ["password"],
        }

        return fallback_chains.get(primary_method, ["password"])


# Export public API
__all__ = [
    "AuthenticationSelector",
    "AuthMethod",
]
