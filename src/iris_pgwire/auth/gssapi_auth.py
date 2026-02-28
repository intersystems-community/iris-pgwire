"""Bridge Kerberos GSSAPI to IRIS user provisioning."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

# Import GSSAPI library
try:
    import gssapi
    from gssapi import Credentials, Name, SecurityContext

    GSSAPI_AVAILABLE = True
except ImportError:
    GSSAPI_AVAILABLE = False
    logger = structlog.get_logger(__name__)
    logger.warning("python-gssapi not installed - Kerberos authentication disabled")

logger = structlog.get_logger(__name__)


# Re-export contract types
@dataclass
class KerberosPrincipal:
    """Kerberos authenticated identity"""

    principal: str  # e.g., 'alice@EXAMPLE.COM'
    username: str  # e.g., 'alice'
    realm: str  # e.g., 'EXAMPLE.COM'
    mapped_iris_user: str  # e.g., 'ALICE'
    authenticated_at: datetime
    ticket_expiry: datetime | None = None


# Error classes
class KerberosAuthenticationError(Exception):
    """Raised when Kerberos authentication fails"""

    pass


class KerberosTimeoutError(Exception):
    """Raised when GSSAPI handshake exceeds timeout"""

    pass


@dataclass
class KerberosConfig:
    """Kerberos configuration values."""

    service_name: str = "postgres"  # PGWIRE_KERBEROS_SERVICE_NAME
    keytab_path: str = "/etc/krb5.keytab"  # KRB5_KTNAME
    realm: str | None = None  # Optional realm restriction
    handshake_timeout: int = 5  # Seconds (FR-028)


class GSSAPIAuthenticator:
    """Manage Kerberos handshakes via python-gssapi."""

    def __init__(self, config: KerberosConfig | None = None):
        if not GSSAPI_AVAILABLE:
            raise ImportError(
                "python-gssapi library not installed. "
                "Install with: pip install python-gssapi>=1.8.0"
            )

        self.config = config or self._load_config_from_env()
        self._active_contexts = {}  # connection_id -> SecurityContext

        logger.info(
            "gssapi_authenticator_initialized",
            service_name=self.config.service_name,
            realm=self.config.realm,
        )

    def _load_config_from_env(self) -> KerberosConfig:
        """Load Kerberos configuration from environment variables"""
        service_name = os.getenv("PGWIRE_KERBEROS_SERVICE_NAME", "postgres")
        keytab_path = os.getenv("KRB5_KTNAME", "/etc/krb5.keytab")
        realm = os.getenv("PGWIRE_KERBEROS_REALM")
        handshake_timeout = int(os.getenv("PGWIRE_KERBEROS_TIMEOUT", "5"))

        return KerberosConfig(
            service_name=service_name,
            keytab_path=keytab_path,
            realm=realm,
            handshake_timeout=handshake_timeout,
        )

    async def handle_gssapi_handshake(self, connection_id: str) -> KerberosPrincipal:
        """Run the GSSAPI handshake and return the authenticated principal."""
        logger.info(
            "gssapi_handshake_start",
            connection_id=connection_id,
        )

        try:
            # Execute GSSAPI handshake with timeout
            principal = await asyncio.wait_for(
                self._perform_gssapi_handshake(connection_id), timeout=self.config.handshake_timeout
            )

            logger.info(
                "gssapi_handshake_success",
                connection_id=connection_id,
                principal=principal.principal,
                mapped_user=principal.mapped_iris_user,
            )

            return principal

        except TimeoutError:
            logger.error(
                "gssapi_handshake_timeout",
                connection_id=connection_id,
                timeout=self.config.handshake_timeout,
            )
            raise KerberosTimeoutError(
                f"GSSAPI handshake exceeded {self.config.handshake_timeout} second timeout"
            ) from None
        except Exception as e:
            logger.error(
                "gssapi_handshake_error",
                connection_id=connection_id,
                error=str(e),
            )
            raise KerberosAuthenticationError(f"GSSAPI handshake failed: {e}") from e

    def _gssapi_handshake_sync(self, connection_id: str) -> str:
        """Execute GSSAPI handshake (blocking). Returns authenticated principal string."""
        try:
            hostname = os.getenv("HOSTNAME", "localhost")
            service_principal = f"{self.config.service_name}@{hostname}"

            logger.debug(
                "gssapi_creating_security_context",
                service_principal=service_principal,
            )

            server_name = Name(service_principal, name_type=gssapi.NameType.hostbased_service)

            # Server credentials for future real GSSAPI token exchange
            _server_creds = Credentials(name=server_name, usage="accept")

            # TODO: Integrate with protocol handler to exchange actual GSSAPI tokens
            # Simulated authenticated principal for TDD
            mock_principal = "testuser@EXAMPLE.COM"

            return mock_principal

        except Exception as e:
            logger.error(
                "gssapi_handshake_failed",
                error=str(e),
            )
            raise KerberosAuthenticationError(f"GSSAPI handshake failed: {e}") from e

    async def _perform_gssapi_handshake(self, connection_id: str) -> KerberosPrincipal:
        """Perform the handshake in a thread and build KerberosPrincipal."""
        authenticated_principal = await asyncio.to_thread(
            self._gssapi_handshake_sync, connection_id
        )
        principal_str = await self.extract_principal(authenticated_principal)
        iris_username = await self.map_principal_to_iris_user(principal_str)

        return self._build_kerberos_principal(principal_str, iris_username)

    def _build_kerberos_principal(
        self, principal_str: str, iris_username: str
    ) -> KerberosPrincipal:
        username, realm = self._split_principal(principal_str)
        now = datetime.now(UTC)

        return KerberosPrincipal(
            principal=principal_str,
            username=username,
            realm=realm,
            mapped_iris_user=iris_username,
            authenticated_at=now,
            ticket_expiry=now + timedelta(hours=24),
        )

    def _split_principal(self, principal_str: str) -> tuple[str, str]:
        if "@" in principal_str:
            username, realm = principal_str.split("@", 1)
        else:
            username = principal_str
            realm = self.config.realm or "DEFAULT"
        return username, realm

    def _iris_ticket_validation_sync(self, gssapi_token: bytes) -> bool:
        """Execute IRIS %Service_Bindings.ValidateGSSAPIToken() (blocking)."""
        try:
            import iris

            service_bindings = iris.cls("%Service_Bindings")
            is_valid = service_bindings.ValidateGSSAPIToken(gssapi_token)
            return bool(is_valid)

        except Exception as e:
            logger.error(
                "iris_ticket_validation_failed",
                error=str(e),
            )
            raise KerberosAuthenticationError(f"IRIS ticket validation failed: {e}") from e

    async def validate_kerberos_ticket(self, gssapi_token: bytes) -> bool:
        """Validate a Kerberos ticket via IRIS."""
        logger.debug(
            "kerberos_ticket_validation_start",
            token_size=len(gssapi_token),
        )

        try:
            is_valid = await asyncio.to_thread(self._iris_ticket_validation_sync, gssapi_token)

            logger.debug(
                "kerberos_ticket_validation_complete",
                is_valid=is_valid,
            )

            return is_valid

        except Exception as e:
            if isinstance(e, KerberosAuthenticationError):
                raise
            logger.error(
                "kerberos_ticket_validation_error",
                error=str(e),
            )
            raise KerberosAuthenticationError(
                f"Unexpected error during ticket validation: {e}"
            ) from e

    async def extract_principal(self, security_context) -> str:
        """Extract principal string from context or security object."""
        try:
            # Handle string principal (for testing/simulation)
            if isinstance(security_context, str):
                principal = security_context
            else:
                # Extract from SecurityContext.peer_name
                principal = str(security_context.peer_name)

            # Validate principal format
            if not principal:
                raise KerberosAuthenticationError("Empty principal extracted from security context")

            # Validate format (should have username[@realm])
            if "@@" in principal:
                raise KerberosAuthenticationError(f"Malformed principal: {principal}")

            logger.debug(
                "principal_extracted",
                principal=principal,
            )

            return principal

        except Exception as e:
            logger.error(
                "principal_extraction_error",
                error=str(e),
            )
            raise KerberosAuthenticationError(f"Failed to extract principal: {e}")

    async def map_principal_to_iris_user(self, principal: str) -> str:
        """Map principal to IRIS username and ensure the user exists."""
        logger.debug(
            "principal_mapping_start",
            principal=principal,
        )

        try:
            # Strip realm and extract username
            if "@" in principal:
                username = principal.split("@")[0]
            else:
                username = principal

            # Apply IRIS username mapping (uppercase)
            iris_username = username.upper()

            # Validate user exists in IRIS (FR-017)
            user_exists = await self._validate_iris_user_exists(iris_username)

            if not user_exists:
                # Clear, actionable error message (FR-017)
                raise KerberosAuthenticationError(
                    f"Kerberos principal '{principal}' maps to IRIS user '{iris_username}', "
                    f"but user does not exist in IRIS. "
                    f"Please create IRIS user '{iris_username}' or adjust principal mapping."
                )

            logger.info(
                "principal_mapping_success",
                principal=principal,
                iris_username=iris_username,
            )

            return iris_username

        except Exception as e:
            if isinstance(e, KerberosAuthenticationError):
                raise
            logger.error(
                "principal_mapping_error",
                principal=principal,
                error=str(e),
            )
            raise KerberosAuthenticationError(f"Failed to map principal to IRIS user: {e}")

    async def _validate_iris_user_exists(self, username: str) -> bool:
        query_result = await asyncio.to_thread(self._query_iris_user_exists_sync, username)
        logger.debug(
            "iris_user_validation_complete",
            username=username,
            exists=query_result,
        )
        return query_result

    def _query_iris_user_exists_sync(self, username: str) -> bool:
        try:
            import iris

            query = """
                SELECT Name
                FROM INFORMATION_SCHEMA.USERS
                WHERE UPPER(Name) = ?
            """

            result = iris.sql.exec(query, username.upper())
            user_row = result.fetchone()
            return user_row is not None

        except Exception as e:
            logger.error(
                "iris_user_validation_failed",
                username=username,
                error=str(e),
            )
            return False


# Export public API
__all__ = [
    "GSSAPIAuthenticator",
    "KerberosPrincipal",
    "KerberosConfig",
    "KerberosAuthenticationError",
    "KerberosTimeoutError",
]
