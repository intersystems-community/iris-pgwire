"""
Wallet Credentials Interface Contract

Implements FR-020 through FR-023 from spec.md (Phase 4).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class WalletSecret:
    """IRIS Wallet encrypted secret"""

    key: str  # e.g., 'pgwire-user-alice'
    value: str  # Encrypted password or client secret
    secret_type: str  # 'password' or 'oauth_client_secret'
    created_at: datetime
    updated_at: datetime
    accessed_at: datetime | None = None


class WalletCredentialsProtocol(Protocol):
    """Protocol for IRIS Wallet credential management (FR-020 to FR-023)"""

    async def get_password_from_wallet(self, username: str) -> str:
        """
        Retrieve user password from IRIS Wallet (FR-020).

        Returns:
            Encrypted password for username

        Raises:
            WalletSecretNotFoundError: If no secret for username (FR-021 fallback)
            WalletAPIError: If Wallet API fails
        """
        ...

    async def set_password_in_wallet(self, username: str, password: str) -> None:
        """Store user password in IRIS Wallet (admin operation, FR-023)"""
        ...

    async def get_oauth_client_secret(self) -> str:
        """Retrieve OAuth client secret from Wallet (FR-009, Phase 4)"""
        ...


class WalletSecretNotFoundError(Exception):
    pass


class WalletAPIError(Exception):
    pass


@dataclass
class WalletConfig:
    """Wallet configuration"""

    wallet_mode: str = "both"  # 'oauth' | 'password' | 'both'
    audit_enabled: bool = True  # FR-022
