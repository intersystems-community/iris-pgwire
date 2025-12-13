"""
GSSAPI Authentication Interface Contract (Kerberos)

Implements FR-013 through FR-019 from spec.md.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class KerberosPrincipal:
    """Kerberos authenticated identity"""

    principal: str  # e.g., 'alice@EXAMPLE.COM'
    username: str  # e.g., 'alice'
    realm: str  # e.g., 'EXAMPLE.COM'
    mapped_iris_user: str  # e.g., 'ALICE'
    authenticated_at: datetime
    ticket_expiry: datetime | None = None


class GSSAPIAuthenticatorProtocol(Protocol):
    """Protocol for Kerberos GSSAPI authentication (FR-013 to FR-019)"""

    async def handle_gssapi_handshake(self, connection_id: str) -> KerberosPrincipal:
        """
        Handle multi-step GSSAPI authentication (FR-013, FR-019).

        Returns:
            KerberosPrincipal with authenticated user identity

        Raises:
            KerberosAuthenticationError: If GSSAPI handshake fails
            KerberosTimeoutError: If handshake exceeds 5 seconds (FR-028)
        """
        ...

    async def validate_kerberos_ticket(self, gssapi_token: bytes) -> bool:
        """Validate Kerberos ticket via IRIS %Service_Bindings (FR-014)"""
        ...

    async def extract_principal(self, security_context) -> str:
        """Extract username from Kerberos principal (FR-015)"""
        ...

    async def map_principal_to_iris_user(self, principal: str) -> str:
        """Map Kerberos principal to IRIS username (FR-016, FR-017)"""
        ...


class KerberosAuthenticationError(Exception):
    pass


class KerberosTimeoutError(Exception):
    pass


@dataclass
class KerberosConfig:
    """Kerberos configuration"""

    service_name: str = "postgres"  # PGWIRE_KERBEROS_SERVICE_NAME
    keytab_path: str = "/etc/krb5.keytab"  # KRB5_KTNAME
    realm: str | None = None  # Optional realm restriction
    handshake_timeout: int = 5  # Seconds (FR-028)
