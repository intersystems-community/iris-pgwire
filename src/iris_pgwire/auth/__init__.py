"""Authentication components that are not wired into the server.

What the server actually does is in ``iris_pgwire.password_auth``: the client sends its IRIS
password and the server checks it by logging in to IRIS.

This package once also held SCRAM-SHA-256, OAuth 2.0 and IRIS Wallet code (feature 024). It was
removed on 2026-10-24. None of it was ever reachable in a way that verified anything: the SCRAM
exchange accepted any client proof, handed the next stage the literal password
``"placeholder_password"`` and answered with a constant server signature. It is in git history,
and ``docs/adr/0003-password-auth-verified-by-iris-login.md`` records why it was not kept.

What remains is the Kerberos/GSSAPI authenticator, which is also not wired in.
"""

from .gssapi_auth import (
    GSSAPIAuthenticator,
    KerberosAuthenticationError,
    KerberosConfig,
    KerberosPrincipal,
    KerberosTimeoutError,
)

__all__ = [
    "GSSAPIAuthenticator",
    "KerberosAuthenticationError",
    "KerberosConfig",
    "KerberosPrincipal",
    "KerberosTimeoutError",
]
