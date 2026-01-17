"""
IRIS PGWire Authentication Bridge

This module provides enterprise authentication capabilities for PostgreSQL clients
connecting to InterSystems IRIS via the PGWire protocol. It bridges PostgreSQL
wire protocol authentication (SCRAM-SHA-256, GSSAPI) to IRIS's native authentication
infrastructure (OAuth 2.0, Kerberos, Wallet).

Architecture:
    PostgreSQL Client → PGWire Protocol → Authentication Bridge → IRIS Auth (OAuth/Kerberos/Wallet)

Supported Authentication Methods:
    - OAuth 2.0: Token-based authentication via IRIS OAuth server (RFC 6749)
    - Kerberos (GSSAPI): SSO authentication via Active Directory or MIT Kerberos
    - IRIS Wallet: Encrypted credential storage in IRISSECURITY database
    - Password (fallback): SCRAM-SHA-256 authentication (backward compatibility)

Key Components:
    - OAuthBridge: OAuth 2.0 token exchange and validation
    - GSSAPIAuthenticator: Kerberos GSSAPI authentication with principal mapping
    - WalletCredentials: IRIS Wallet integration for encrypted credential storage
    - AuthenticationSelector: Dual-mode authentication routing with fallback chain

Constitutional Requirements:
    - Protocol Fidelity: Exact PostgreSQL GSSAPI protocol support
    - Test-First Development: All implementations validated with contract tests
    - IRIS Integration: Uses iris.cls() for direct IRIS API access
    - Performance: <5 second authentication latency (FR-028)
    - Backward Compatibility: Password fallback ensures 100% client compatibility

Feature: 024-research-and-implement (Authentication Bridge)
Phase: Implementation (Phase 3.1 - Module Structure)
"""

# Export authentication components (Phase 3.4 - Implementation Complete)
__all__ = [
    "OAuthBridge",
    "GSSAPIAuthenticator",
    "WalletCredentials",
    "AuthenticationSelector",
    # SCRAM components
    "AuthenticationState",
    "AuthenticationMethod",
    "AuthenticationResult",
    "ScramCredentials",
    "IRISAuthenticationProvider",
    "PostgreSQLAuthenticator",
    "SCRAMAuthenticator",
    "create_authentication_ok",
    "create_authentication_sasl",
    "create_authentication_sasl_continue",
    "create_authentication_sasl_final",
    "create_error_response",
    # OAuth types and errors
    "OAuthToken",
    "OAuthConfig",
    "OAuthAuthenticationError",
    "OAuthValidationError",
    "OAuthRefreshError",
    "OAuthConfigurationError",
    # Kerberos types and errors
    "KerberosPrincipal",
    "KerberosConfig",
    "KerberosAuthenticationError",
    "KerberosTimeoutError",
    # Wallet types and errors
    "WalletSecret",
    "WalletConfig",
    "WalletSecretNotFoundError",
    "WalletAPIError",
    # Authentication selector
    "AuthMethod",
]

# Version info
__version__ = "0.1.0"
__feature__ = "024-research-and-implement"

# Import implementations (Phase 3.4 complete)
from .auth_selector import (
    AuthenticationSelector,
    AuthMethod,
)
from .gssapi_auth import (
    GSSAPIAuthenticator,
    KerberosAuthenticationError,
    KerberosConfig,
    KerberosPrincipal,
    KerberosTimeoutError,
)
from .oauth_bridge import (
    OAuthAuthenticationError,
    OAuthBridge,
    OAuthConfig,
    OAuthConfigurationError,
    OAuthRefreshError,
    OAuthToken,
    OAuthValidationError,
)
from .scram import (
    AuthenticationMethod,
    AuthenticationResult,
    AuthenticationState,
    IRISAuthenticationProvider,
    PostgreSQLAuthenticator,
    SCRAMAuthenticator,
    ScramCredentials,
    create_authentication_ok,
    create_authentication_sasl,
    create_authentication_sasl_continue,
    create_authentication_sasl_final,
    create_error_response,
)
from .wallet_credentials import (
    WalletAPIError,
    WalletConfig,
    WalletCredentials,
    WalletSecret,
    WalletSecretNotFoundError,
)
