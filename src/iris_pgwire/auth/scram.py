"""SCRAM-SHA-256 authentication with IRIS integration and constitutional compliance."""

import asyncio
import base64
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

from iris_pgwire.constitutional import get_governor
from iris_pgwire.performance_monitor import get_monitor

logger = structlog.get_logger(__name__)


class AuthenticationState(Enum):
    """Authentication flow states"""

    INITIAL = "initial"
    SASL_STARTED = "sasl_started"
    SASL_CHALLENGE_SENT = "sasl_challenge_sent"
    AUTHENTICATED = "authenticated"
    FAILED = "failed"


class AuthenticationMethod(Enum):
    """Supported authentication methods"""

    TRUST = "trust"  # Development only
    SCRAM_SHA_256 = "scram-sha-256"  # Production
    MD5 = "md5"  # Deprecated, security fallback


@dataclass
class AuthenticationResult:
    """Result of authentication attempt"""

    success: bool
    username: str | None = None
    iris_session: Any | None = None
    error_message: str | None = None
    auth_time_ms: float = 0.0
    sla_compliant: bool = True
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class ScramCredentials:
    """SCRAM-SHA-256 stored credentials"""

    username: str
    stored_key: bytes
    server_key: bytes
    salt: bytes
    iteration_count: int = 4096  # RFC 7677 recommendation


class IRISAuthenticationProvider:
    """IRIS-integrated authentication provider"""

    def __init__(self, iris_config: dict[str, str]):
        self.iris_config = iris_config
        self._credential_cache: dict[str, ScramCredentials] = {}
        self._failed_attempts: dict[str, list] = {}

    @staticmethod
    def _check_sla_compliance(
        operation_name: str, auth_time: float, success: bool, **log_kwargs: Any
    ) -> bool:
        """Check SLA compliance, record metrics, and log violations. Returns sla_compliant."""
        monitor = get_monitor()
        governor = get_governor()
        sla_compliant = auth_time < 5.0

        monitor.record_operation(operation=operation_name, duration_ms=auth_time, success=success)

        logger.info(
            f"{operation_name} completed",
            auth_time_ms=auth_time,
            sla_compliant=sla_compliant,
            success=success,
            constitutional_compliance=True,
            **log_kwargs,
        )

        if not sla_compliant:
            logger.warning(
                f"Constitutional SLA violation in {operation_name}",
                auth_time_ms=auth_time,
                sla_threshold_ms=5.0,
                violation_severity="HIGH",
                **log_kwargs,
            )
            governor.check_compliance()

        return sla_compliant

    async def validate_iris_user(self, username: str, password: str) -> tuple[bool, str | None]:
        """
        Validate user credentials against IRIS with constitutional compliance monitoring.
        Returns (success, iris_session_id).
        """
        start_time = time.perf_counter()

        logger.info(
            "IRIS authentication attempt initiated",
            username=username,
            constitutional_compliance_enabled=True,
        )

        try:

            def iris_auth():
                try:
                    import iris

                    connection = iris.createConnection(
                        hostname=self.iris_config["host"],
                        port=int(self.iris_config["port"]),
                        namespace=self.iris_config["namespace"],
                        username=username,
                        password=password,
                    )

                    cursor = connection.cursor()
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()

                    if result and result[0] == 1:
                        session_id = f"iris_session_{secrets.token_hex(16)}"
                        return True, session_id
                    else:
                        return False, None

                except Exception as e:
                    logger.warning(f"IRIS authentication failed for user {username}: {e}")
                    return False, None

            success, session_id = await asyncio.to_thread(iris_auth)

            auth_time = (time.perf_counter() - start_time) * 1000
            self._check_sla_compliance("iris_authentication", auth_time, success, username=username)

            return success, session_id

        except Exception as e:
            auth_time = (time.perf_counter() - start_time) * 1000
            get_monitor().record_operation(
                operation="iris_authentication", duration_ms=auth_time, success=False
            )

            logger.error(
                "IRIS authentication error", username=username, error=str(e), auth_time_ms=auth_time
            )
            return False, None

    async def validate_iris_user_exists(self, username: str) -> tuple[bool, str | None]:
        """
        Validate that user exists in IRIS (for SCRAM where password is already verified)
        Returns (success, iris_session_id)
        """
        start_time = time.perf_counter()

        try:
            # Use asyncio.to_thread to avoid blocking event loop
            def iris_user_check():
                try:
                    import iris

                    # Create IRIS connection with system credentials to check user existence
                    connection = iris.createConnection(
                        hostname=self.iris_config["host"],
                        port=int(self.iris_config["port"]),
                        namespace=self.iris_config["namespace"],
                        username=self.iris_config.get("system_user", "_SYSTEM"),
                        password=self.iris_config.get("system_password", "SYS"),
                    )

                    # Check if user exists in IRIS security tables
                    cursor = connection.cursor()
                    cursor.execute("SELECT COUNT(*) FROM Security.Users WHERE Name = ?", [username])
                    result = cursor.fetchone()

                    if result and result[0] > 0:
                        session_id = f"iris_session_{secrets.token_hex(16)}"
                        return True, session_id
                    else:
                        return False, None

                except Exception as e:
                    logger.warning(f"IRIS user existence check failed for user {username}: {e}")
                    return False, None

            success, session_id = await asyncio.to_thread(iris_user_check)

            auth_time = (time.perf_counter() - start_time) * 1000
            sla_compliant = auth_time < 5.0  # Constitutional requirement

            if not sla_compliant:
                logger.warning(
                    f"IRIS user check SLA violation: {auth_time:.2f}ms for user {username}"
                )

            return success, session_id

        except Exception as e:
            logger.error(f"IRIS user existence check error for user {username}: {e}")
            return False, None

    def get_stored_credentials(self, username: str) -> ScramCredentials | None:
        """Get stored SCRAM credentials for user"""
        return self._credential_cache.get(username)

    def store_credentials(self, username: str, password: str) -> ScramCredentials:
        """Generate and store SCRAM credentials for user"""
        salt = secrets.token_bytes(16)
        iteration_count = 4096

        # Generate SCRAM keys according to RFC 7677
        salted_password = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iteration_count
        )

        client_key = hmac.new(salted_password, b"Client Key", hashlib.sha256).digest()
        stored_key = hashlib.sha256(client_key).digest()
        server_key = hmac.new(salted_password, b"Server Key", hashlib.sha256).digest()

        credentials = ScramCredentials(
            username=username,
            stored_key=stored_key,
            server_key=server_key,
            salt=salt,
            iteration_count=iteration_count,
        )

        self._credential_cache[username] = credentials
        return credentials


class SCRAMAuthenticator:
    """SCRAM-SHA-256 authentication implementation"""

    def __init__(self, iris_provider: IRISAuthenticationProvider):
        self.iris_provider = iris_provider
        self._active_sessions: dict[str, dict] = {}

    def generate_server_nonce(self) -> str:
        """Generate cryptographically secure server nonce"""
        return base64.b64encode(secrets.token_bytes(18)).decode("ascii")

    def parse_client_first_message(self, message: str) -> tuple[str, str, str]:
        """
        Parse SCRAM client-first-message
        Returns (username, client_nonce, gs2_header)
        """
        try:
            # Format: n,,n=username,r=client_nonce
            if not message.startswith("n,,"):
                raise ValueError("Invalid GS2 header")

            attributes = message[3:]  # Remove 'n,,'
            parts = {}

            for attr in attributes.split(","):
                if "=" in attr:
                    key, value = attr.split("=", 1)
                    parts[key] = value

            username = parts.get("n", "").replace("=2C", ",").replace("=3D", "=")
            client_nonce = parts.get("r", "")

            if not username or not client_nonce:
                raise ValueError("Missing required attributes")

            return username, client_nonce, "n,,"

        except Exception as e:
            logger.error(f"Failed to parse client-first-message: {e}")
            raise ValueError(f"Invalid client-first-message: {e}") from e

    def create_server_first_message(self, client_nonce: str, username: str) -> tuple[str, str]:
        """
        Create SCRAM server-first-message
        Returns (server_message, server_nonce)
        """
        credentials = self.iris_provider.get_stored_credentials(username)
        if not credentials:
            # Generate temporary credentials for unknown users (prevent enumeration)
            logger.warning(f"Unknown user {username}, generating temporary credentials")
            credentials = ScramCredentials(
                username=username,
                stored_key=secrets.token_bytes(32),
                server_key=secrets.token_bytes(32),
                salt=secrets.token_bytes(16),
                iteration_count=4096,
            )

        server_nonce = self.generate_server_nonce()
        combined_nonce = client_nonce + server_nonce

        salt_b64 = base64.b64encode(credentials.salt).decode("ascii")

        server_message = f"r={combined_nonce},s={salt_b64},i={credentials.iteration_count}"

        return server_message, server_nonce

    def verify_client_final_message(
        self, message: str, session_data: dict
    ) -> tuple[bool, str | None]:
        """
        Verify SCRAM client-final-message
        Returns (success, error_message)
        """
        try:
            # Parse client-final-message
            # Format: c=biws,r=nonce,p=client_proof
            parts = {}
            for attr in message.split(","):
                if "=" in attr:
                    key, value = attr.split("=", 1)
                    parts[key] = value

            channel_binding = parts.get("c", "")
            received_nonce = parts.get("r", "")
            client_proof_b64 = parts.get("p", "")

            # Verify nonce
            expected_nonce = session_data["client_nonce"] + session_data["server_nonce"]
            if received_nonce != expected_nonce:
                return False, "Invalid nonce"

            # Verify channel binding (for now, just check it's base64 encoded 'n,,')
            try:
                decoded_cb = base64.b64decode(channel_binding)
                if decoded_cb != b"n,,":
                    logger.warning(f"Unexpected channel binding: {decoded_cb}")
            except Exception:
                return False, "Invalid channel binding"

            # Get stored credentials
            credentials = self.iris_provider.get_stored_credentials(session_data["username"])
            if not credentials:
                return False, "Authentication failed"

            # Reconstruct auth message
            client_first_bare = f"n={session_data['username']},r={session_data['client_nonce']}"
            server_first = session_data["server_first_message"]
            client_final_without_proof = f"c={channel_binding},r={received_nonce}"

            auth_message = f"{client_first_bare},{server_first},{client_final_without_proof}"

            # Verify client proof
            client_signature = hmac.new(
                credentials.stored_key, auth_message.encode("utf-8"), hashlib.sha256
            ).digest()

            client_proof = base64.b64decode(client_proof_b64)
            client_key = bytes(a ^ b for a, b in zip(client_signature, client_proof, strict=False))

            # Verify stored key
            if hashlib.sha256(client_key).digest() != credentials.stored_key:
                return False, "Authentication failed"

            # Generate server signature for server-final-message
            server_signature = hmac.new(
                credentials.server_key, auth_message.encode("utf-8"), hashlib.sha256
            ).digest()

            session_data["server_signature"] = server_signature
            return True, None

        except Exception as e:
            logger.error(f"Error verifying client-final-message: {e}")
            return False, "Authentication failed"

    def create_server_final_message(self, session_data: dict) -> str:
        """Create SCRAM server-final-message"""
        server_signature_b64 = base64.b64encode(session_data["server_signature"]).decode("ascii")
        return f"v={server_signature_b64}"


class PostgreSQLAuthenticator:
    """Main PostgreSQL authentication handler"""

    def __init__(
        self,
        iris_config: dict[str, str],
        auth_method: AuthenticationMethod = AuthenticationMethod.SCRAM_SHA_256,
    ):
        self.auth_method = auth_method
        self.iris_provider = IRISAuthenticationProvider(iris_config)
        self.scram_authenticator = SCRAMAuthenticator(self.iris_provider)
        self._active_sessions: dict[str, dict] = {}

    async def authenticate(
        self, connection_id: str, username: str, auth_data: bytes = None
    ) -> AuthenticationResult:
        """Main authentication entry point with constitutional compliance."""
        start_time = time.perf_counter()

        logger.info(
            "PostgreSQL authentication initiated",
            connection_id=connection_id,
            username=username,
            auth_method=self.auth_method.value,
            constitutional_compliance_enabled=True,
        )

        try:
            result = await self._run_authentication_method(
                connection_id, username, auth_data, start_time
            )
        except Exception as e:
            return self._handle_authentication_error(connection_id, username, start_time, e)

        return self._finalize_auth_result(result, start_time, connection_id, username)

    async def _run_authentication_method(
        self, connection_id: str, username: str, auth_data: bytes, start_time: float
    ) -> AuthenticationResult:
        if self.auth_method == AuthenticationMethod.TRUST:
            return await self._authenticate_trust(username, start_time)
        if self.auth_method == AuthenticationMethod.SCRAM_SHA_256:
            return await self._authenticate_scram(connection_id, username, auth_data, start_time)

        return AuthenticationResult(
            success=False,
            error_message=f"Unsupported authentication method: {self.auth_method}",
            auth_time_ms=(time.perf_counter() - start_time) * 1000,
        )

    def _finalize_auth_result(
        self,
        result: AuthenticationResult,
        start_time: float,
        connection_id: str,
        username: str,
    ) -> AuthenticationResult:
        auth_time = (time.perf_counter() - start_time) * 1000
        result.auth_time_ms = auth_time
        result.sla_compliant = IRISAuthenticationProvider._check_sla_compliance(
            "postgresql_authentication",
            auth_time,
            result.success,
            connection_id=connection_id,
            username=username,
            auth_method=self.auth_method.value,
        )

        return result

    def _handle_authentication_error(
        self, connection_id: str, username: str, start_time: float, exc: Exception
    ) -> AuthenticationResult:
        auth_time = (time.perf_counter() - start_time) * 1000
        get_monitor().record_operation(
            operation="postgresql_authentication", duration_ms=auth_time, success=False
        )

        logger.error(
            "PostgreSQL authentication error",
            connection_id=connection_id,
            username=username,
            auth_method=self.auth_method.value,
            error=str(exc),
            auth_time_ms=auth_time,
        )

        return AuthenticationResult(
            success=False, error_message="Authentication failed", auth_time_ms=auth_time
        )

    async def _authenticate_trust(self, username: str, start_time: float) -> AuthenticationResult:
        """Trust authentication (development only)"""
        auth_time = (time.perf_counter() - start_time) * 1000

        logger.warning(f"Trust authentication used for user {username} - DEVELOPMENT ONLY")

        return AuthenticationResult(
            success=True,
            username=username,
            auth_time_ms=auth_time,
            sla_compliant=auth_time < 5.0,
            metadata={"method": "trust", "warning": "insecure"},
        )

    async def _authenticate_scram(
        self, connection_id: str, username: str, auth_data: bytes, start_time: float
    ) -> AuthenticationResult:
        """SCRAM-SHA-256 authentication with full state machine"""
        auth_time = (time.perf_counter() - start_time) * 1000

        try:
            # Get or create session state
            if connection_id not in self._active_sessions:
                self._active_sessions[connection_id] = {
                    "state": AuthenticationState.INITIAL,
                    "username": username,
                    "start_time": start_time,
                }

            session = self._active_sessions[connection_id]
            current_state = session["state"]

            if current_state == AuthenticationState.INITIAL:
                return await self._handle_sasl_initial(connection_id, username, auth_time)

            elif current_state == AuthenticationState.SASL_STARTED:
                return await self._handle_client_first_message(connection_id, auth_data, auth_time)

            elif current_state == AuthenticationState.SASL_CHALLENGE_SENT:
                return await self._handle_client_final_message(connection_id, auth_data, auth_time)

            else:
                return AuthenticationResult(
                    success=False,
                    error_message=f"Invalid authentication state: {current_state}",
                    auth_time_ms=auth_time,
                    sla_compliant=auth_time < 5.0,
                )

        except Exception as e:
            logger.error(f"SCRAM authentication error for {username}: {e}")
            return AuthenticationResult(
                success=False,
                error_message="Authentication failed",
                auth_time_ms=auth_time,
                sla_compliant=auth_time < 5.0,
            )

    async def _handle_sasl_initial(
        self, connection_id: str, username: str, auth_time: float
    ) -> AuthenticationResult:
        """Handle initial SASL negotiation"""
        session = self._active_sessions[connection_id]
        session["state"] = AuthenticationState.SASL_STARTED

        return AuthenticationResult(
            success=False,  # Not complete yet
            username=username,
            auth_time_ms=auth_time,
            sla_compliant=auth_time < 5.0,
            metadata={
                "method": "SCRAM-SHA-256",
                "state": "sasl_started",
                "next_step": "client_first_message",
            },
        )

    async def _handle_client_first_message(
        self, connection_id: str, auth_data: bytes, auth_time: float
    ) -> AuthenticationResult:
        """Handle SCRAM client-first-message"""
        session = self._active_sessions[connection_id]

        try:
            # Parse client-first-message
            client_message = auth_data.decode("utf-8")
            username, client_nonce, gs2_header = (
                self.scram_authenticator.parse_client_first_message(client_message)
            )

            # Store session data
            session.update(
                {
                    "username": username,
                    "client_nonce": client_nonce,
                    "gs2_header": gs2_header,
                    "state": AuthenticationState.SASL_CHALLENGE_SENT,
                }
            )

            # Create server-first-message
            server_message, server_nonce = self.scram_authenticator.create_server_first_message(
                client_nonce, username
            )
            session["server_nonce"] = server_nonce
            session["server_first_message"] = server_message

            return AuthenticationResult(
                success=False,  # Not complete yet
                username=username,
                auth_time_ms=auth_time,
                sla_compliant=auth_time < 5.0,
                metadata={
                    "method": "SCRAM-SHA-256",
                    "state": "challenge_sent",
                    "server_message": server_message,
                    "next_step": "client_final_message",
                },
            )

        except Exception as e:
            logger.error(f"Error parsing client-first-message: {e}")
            session["state"] = AuthenticationState.FAILED
            return AuthenticationResult(
                success=False,
                error_message="Invalid client-first-message",
                auth_time_ms=auth_time,
                sla_compliant=auth_time < 5.0,
            )

    async def _complete_iris_validation(
        self, session: dict, auth_time: float
    ) -> AuthenticationResult:
        """Validate IRIS user and build final authentication result."""
        username = session["username"]
        iris_success, iris_session_id = await self.iris_provider.validate_iris_user_exists(username)

        if not iris_success:
            session["state"] = AuthenticationState.FAILED
            return AuthenticationResult(
                success=False,
                error_message="IRIS user validation failed",
                auth_time_ms=auth_time,
                sla_compliant=auth_time < 5.0,
            )

        session["state"] = AuthenticationState.AUTHENTICATED
        session["iris_session_id"] = iris_session_id
        server_final = self.scram_authenticator.create_server_final_message(session)

        return AuthenticationResult(
            success=True,
            username=username,
            iris_session=iris_session_id,
            auth_time_ms=auth_time,
            sla_compliant=auth_time < 5.0,
            metadata={
                "method": "SCRAM-SHA-256",
                "state": "authenticated",
                "server_final_message": server_final,
                "iris_session_id": iris_session_id,
            },
        )

    async def _handle_client_final_message(
        self, connection_id: str, auth_data: bytes, auth_time: float
    ) -> AuthenticationResult:
        """Handle SCRAM client-final-message and complete authentication."""
        session = self._active_sessions[connection_id]

        try:
            client_message = auth_data.decode("utf-8")
            success, error_message = self.scram_authenticator.verify_client_final_message(
                client_message, session
            )

            if not success:
                return self._client_final_failure(session, auth_time, error_message)

            return await self._complete_iris_validation(session, auth_time)

        except Exception as e:
            logger.error(f"Error processing client-final-message: {e}")
            return self._client_final_failure(session, auth_time, None)

    def _client_final_failure(
        self, session: dict, auth_time: float, message: str | None
    ) -> AuthenticationResult:
        session["state"] = AuthenticationState.FAILED
        return AuthenticationResult(
            success=False,
            error_message=message or "Authentication failed",
            auth_time_ms=auth_time,
            sla_compliant=auth_time < 5.0,
        )

    def register_user_credentials(self, username: str, password: str) -> bool:
        """Register user credentials for SCRAM authentication"""
        try:
            self.iris_provider.store_credentials(username, password)
            logger.info(f"Stored SCRAM credentials for user {username}")
            return True
        except Exception as e:
            logger.error(f"Failed to store credentials for user {username}: {e}")
            return False

    def get_authentication_methods(self) -> list[str]:
        """Get supported authentication methods"""
        return ["SCRAM-SHA-256"]

    def cleanup_session(self, connection_id: str):
        """Clean up authentication session data"""
        if connection_id in self._active_sessions:
            del self._active_sessions[connection_id]

    def get_sasl_mechanisms(self) -> list[str]:
        """Get supported SASL mechanisms"""
        return ["SCRAM-SHA-256"]

    def requires_password(self) -> bool:
        """Check if authentication method requires password"""
        return self.auth_method not in [AuthenticationMethod.TRUST]

    def get_session_state(self, connection_id: str) -> dict | None:
        """Get current session authentication state"""
        return self._active_sessions.get(connection_id)

    def is_authenticated(self, connection_id: str) -> bool:
        """Check if connection is authenticated"""
        session = self._active_sessions.get(connection_id)
        return bool(session and session.get("state") == AuthenticationState.AUTHENTICATED)

    def get_user_info(self, connection_id: str) -> dict[str, str] | None:
        """Get authenticated user information"""
        session = self._active_sessions.get(connection_id)
        if session and session.get("state") == AuthenticationState.AUTHENTICATED:
            return {
                "username": session.get("username"),
                "iris_session_id": session.get("iris_session_id"),
                "auth_method": self.auth_method.value,
            }
        return None


# Protocol message helpers for PostgreSQL wire protocol
def create_authentication_ok() -> bytes:
    """Create AuthenticationOk message (type R, status 0)"""
    length = 8  # 4 bytes length + 4 bytes status
    return struct.pack("!cI", b"R", length) + struct.pack("!I", 0)


def create_authentication_sasl(methods: list[str]) -> bytes:
    """Create AuthenticationSASL message (type R, status 10)"""
    method_data = b"\x00".join(method.encode("utf-8") for method in methods) + b"\x00\x00"
    length = 4 + 4 + len(method_data)  # length field + status + methods
    return struct.pack("!cI", b"R", length) + struct.pack("!I", 10) + method_data


def create_authentication_sasl_continue(server_data: str) -> bytes:
    """Create AuthenticationSASLContinue message (type R, status 11)"""
    data = server_data.encode("utf-8")
    length = 4 + 4 + len(data)  # length field + status + data
    return struct.pack("!cI", b"R", length) + struct.pack("!I", 11) + data


def create_authentication_sasl_final(server_data: str) -> bytes:
    """Create AuthenticationSASLFinal message (type R, status 12)"""
    data = server_data.encode("utf-8")
    length = 4 + 4 + len(data)  # length field + status + data
    return struct.pack("!cI", b"R", length) + struct.pack("!I", 12) + data


def create_error_response(code: str, message: str) -> bytes:
    """Create ErrorResponse message for authentication failures"""
    fields = [
        b"S" + b"FATAL" + b"\x00",  # Severity
        b"C" + code.encode("ascii") + b"\x00",  # Code
        b"M" + message.encode("utf-8") + b"\x00",  # Message
        b"\x00",  # Terminator
    ]

    data = b"".join(fields)
    length = 4 + len(data)  # length field + data
    return struct.pack("!cI", b"E", length) + data


# Export main components
__all__ = [
    "PostgreSQLAuthenticator",
    "AuthenticationResult",
    "AuthenticationMethod",
    "AuthenticationState",
    "IRISAuthenticationProvider",
    "SCRAMAuthenticator",
    "create_authentication_ok",
    "create_authentication_sasl",
    "create_authentication_sasl_continue",
    "create_authentication_sasl_final",
    "create_error_response",
]
