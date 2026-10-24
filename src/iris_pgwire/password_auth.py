"""Password authentication for the PostgreSQL wire protocol.

The server asks the client for its password (`AuthenticationCleartextPassword`) and checks it by
logging into IRIS with it. IRIS stays the only store of users and passwords: pgwire keeps no
verifier of its own. A password sent in the clear is only safe over TLS, so a configuration that
would accept one over plaintext is refused at startup unless the operator opts in.

What a successful check proves: the client knows the password of an IRIS user. It does **not**
change who the session runs as. Statements still execute as the service account the server is
configured with, so every authenticated user has that account's privileges.

Two verifiers, one per backend, because the backends cannot reach IRIS the same way:

* DBAPI backend: open (and immediately close) a DBAPI connection with the client's credentials.
* Embedded backend: `%SYSTEM.Security.Login` in a short-lived child process. It has to be a child.
  A successful `Login` switches the calling process to the logged-in user, which in the shared
  server process would silently change the identity of every concurrent query. The DBAPI route is
  not available under `irispython` at all.

Both distinguish *denied* from *could not check*. An IRIS outage must never read as a wrong
password, and a wrong password must never read as an outage.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)

AUTH_MODES = ("password", "trust")

# A password longer than this is not a password: refuse it before reading it all.
MAX_PASSWORD_BYTES = 1024

# IRIS makes a failed login wait about two seconds (measured, 2026.2). A refusal that never reaches
# IRIS waits the same, so that how long a refusal takes does not reveal why it happened.
FAILED_LOGIN_DELAY_SECONDS = 2.0


class AuthConfigError(ValueError):
    """The server was configured in a way that would weaken or break authentication."""


class AuthRefused(Exception):
    """The connection must be refused. Carries the SQLSTATE and the client-safe message."""

    def __init__(self, sqlstate: str, message: str):
        super().__init__(message)
        self.sqlstate = sqlstate
        self.message = message


class AuthUnavailable(Exception):
    """The password could not be checked (IRIS unreachable, check could not run)."""


class PasswordVerifier(Protocol):
    async def verify(self, user: str, password: str) -> bool:
        """True if IRIS accepts the credentials, False if it denies them.

        Raises AuthUnavailable when the question could not be answered.
        """
        ...


def validate_auth_config(
    *,
    auth_mode: str,
    enable_ssl: bool,
    allow_plaintext_password: bool,
    enable_scram: bool = False,
) -> None:
    """Refuse, at startup, a configuration that cannot authenticate safely."""
    if enable_scram:
        raise AuthConfigError(
            "SCRAM-SHA-256 is not implemented: the server never checked the client proof, so "
            "enabling it would have given the appearance of authentication without any. Use "
            "password authentication over TLS (the default), or --trust for local development."
        )
    if auth_mode not in AUTH_MODES:
        raise AuthConfigError(f"auth_mode must be one of {AUTH_MODES}, got {auth_mode!r}")
    if auth_mode == "password" and not (enable_ssl or allow_plaintext_password):
        raise AuthConfigError(
            "Password authentication sends the password in the clear, so it requires TLS. "
            "Choose one: enable TLS (PGWIRE_SSL_ENABLED=true with PGWIRE_SSL_CERT and "
            "PGWIRE_SSL_KEY); pass --allow-plaintext-password (PGWIRE_ALLOW_PLAINTEXT_PASSWORD="
            "true) to accept passwords over an unencrypted connection on a network you trust; "
            "or pass --trust (PGWIRE_AUTH_MODE=trust) to run with no authentication at all, for "
            "local development only."
        )


def resolve_allowed_users(
    configured: str | list[str] | tuple[str, ...] | None, service_account: str
):
    """The login users allowed to connect, case-folded.

    A correct password proves the client knows an IRIS user's password. It does not make that user
    safe to run as the service account, because statements execute as the service account whatever
    the login user's own privileges are. So unless the operator lists who may connect, only the
    service account itself may. An explicit list replaces that default; it does not extend it.
    """
    if isinstance(configured, str):
        configured = configured.split(",")
    names = frozenset(n.strip().casefold() for n in (configured or ()) if n and n.strip())
    return names or frozenset({service_account.casefold()})


def parse_password_message(body: bytes) -> str:
    """Decode the body of a PasswordMessage: one UTF-8 string, NUL-terminated."""
    if len(body) > MAX_PASSWORD_BYTES + 1:
        raise AuthRefused("08P01", "password message too long")
    if not body.endswith(b"\x00") or b"\x00" in body[:-1]:
        raise AuthRefused("08P01", "invalid password message")
    try:
        return body[:-1].decode("utf-8")
    except UnicodeDecodeError:
        raise AuthRefused("08P01", "invalid password message") from None


class DbapiPasswordVerifier:
    """Check a password by opening a DBAPI connection to IRIS with it."""

    # What IRIS says for a wrong password, an unknown user and an empty password alike, which is
    # also what keeps the answer from revealing which accounts exist (measured, IRIS 2026.2).
    _DENIED = "Access Denied"

    def __init__(self, host: str, port: int, namespace: str, *, timeout: float = 30.0):
        self.host = host
        self.port = port
        self.namespace = namespace
        self.timeout = timeout

    def _check(self, user: str, password: str) -> bool:
        try:
            import iris.dbapi as dbapi

            connection = dbapi.connect(
                hostname=self.host,
                port=self.port,
                namespace=self.namespace,
                username=user,
                password=password,
            )
        except Exception as exc:
            if self._DENIED in str(exc):
                return False
            raise AuthUnavailable(f"{type(exc).__name__}: {exc}") from exc

        # "connect() returned" is not proof of a login. A stand-in `iris.dbapi` (the embedded
        # wrapper hands out MagicMocks; tests leave fakes in sys.modules) returns an object from
        # connect() for any credentials. Ask a question only a real connection can answer, and
        # fail closed on anything else. `type(...) is int` because a mock compares equal to nothing
        # but is happy to be indexed.
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            confirmed = row is not None and type(row[0]) is int and row[0] == 1
        except Exception as exc:
            raise AuthUnavailable(f"login could not be confirmed: {exc}") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass
        if not confirmed:
            raise AuthUnavailable("login could not be confirmed: unexpected reply to SELECT 1")
        return True

    async def verify(self, user: str, password: str) -> bool:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._check, user, password), self.timeout
            )
        except TimeoutError as exc:
            raise AuthUnavailable(f"login check timed out after {self.timeout}s") from exc


# Runs in the child. The result is only trusted when it is a real 0 or 1: on a host with
# `iris-embedded-python-wrapper`, `iris.cls(...)` answers with a mock whose comparisons are False,
# and "denied" must not be the answer to a question that was never asked.
_CHILD_SCRIPT = """
import json, sys
request = json.load(sys.stdin)
import iris
result = iris.cls("%SYSTEM.Security").Login(request["user"], request["password"])
if type(result) is int and result == 1:
    print("PGWIRE-LOGIN OK")
elif type(result) is int and result == 0:
    print("PGWIRE-LOGIN DENIED")
else:
    print("PGWIRE-LOGIN UNKNOWN")
"""


class EmbeddedPasswordVerifier:
    """Check a password with `%SYSTEM.Security.Login` in a throwaway child process."""

    def __init__(self, python: str | None = None, *, timeout: float = 30.0):
        self.python = python or sys.executable
        self.timeout = timeout

    async def verify(self, user: str, password: str) -> bool:
        # The password goes to the child on stdin, never on the command line where `ps` shows it.
        request = json.dumps({"user": user, "password": password}).encode()
        try:
            process = await asyncio.create_subprocess_exec(
                self.python,
                "-c",
                _CHILD_SCRIPT,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise AuthUnavailable(f"could not start the login check: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(request), self.timeout)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise AuthUnavailable(f"login check timed out after {self.timeout}s") from exc

        verdict = stdout.decode(errors="replace").strip().splitlines()[-1:] or [""]
        if process.returncode == 0 and verdict[0] == "PGWIRE-LOGIN OK":
            return True
        if process.returncode == 0 and verdict[0] == "PGWIRE-LOGIN DENIED":
            return False
        tail = stderr.decode(errors="replace").strip().splitlines()[-1:] or ["no output"]
        raise AuthUnavailable(f"login check did not run (exit {process.returncode}): {tail[0]}")
