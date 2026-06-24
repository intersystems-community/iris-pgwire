"""
Unit tests for iris_pgwire/auth/scram.py

Covers the uncovered lines (missing lines 97-104, 143, 156-165, 200-202, 210,
216-218, 324-384, 423-424, 436, 465-479, 521-534, 603-606, 617-633, 651-666,
671-672, 685-687, 708, 719) to push coverage above 80%.

No live IRIS required — all IRIS calls are mocked.
"""

import asyncio
import base64
import hashlib
import hmac
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.auth.scram import (
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IRIS_CONFIG = {
    "host": "localhost",
    "port": "1972",
    "namespace": "USER",
    "system_user": "_SYSTEM",
    "system_password": "SYS",
}


def _make_provider() -> IRISAuthenticationProvider:
    return IRISAuthenticationProvider(IRIS_CONFIG)


def _make_scram(provider=None) -> SCRAMAuthenticator:
    if provider is None:
        provider = _make_provider()
    return SCRAMAuthenticator(provider)


def _make_pg_auth(method=AuthenticationMethod.SCRAM_SHA_256) -> PostgreSQLAuthenticator:
    return PostgreSQLAuthenticator(IRIS_CONFIG, auth_method=method)


def _mock_monitor():
    m = MagicMock()
    m.record_operation = MagicMock()
    return m


def _mock_governor():
    g = MagicMock()
    g.check_compliance = MagicMock(return_value={})
    return g


# ---------------------------------------------------------------------------
# IRISAuthenticationProvider – _check_sla_compliance
# ---------------------------------------------------------------------------


class TestCheckSLACompliance:
    """Tests for the static _check_sla_compliance helper (lines 77-106)."""

    def test_compliant_returns_true(self):
        monitor = _mock_monitor()
        governor = _mock_governor()
        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = IRISAuthenticationProvider._check_sla_compliance(
                "test_op", 1.0, True, username="alice"
            )
        assert result is True
        monitor.record_operation.assert_called_once_with(
            operation="test_op", duration_ms=1.0, success=True
        )
        governor.check_compliance.assert_not_called()

    def test_violation_calls_governor(self):
        """Lines 97-104: SLA violation logs warning and calls governor."""
        monitor = _mock_monitor()
        governor = _mock_governor()
        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = IRISAuthenticationProvider._check_sla_compliance(
                "slow_op", 6000.0, False, username="bob"
            )
        assert result is False
        governor.check_compliance.assert_called_once()

    def test_exactly_at_threshold_is_compliant(self):
        """4.999ms is under the 5ms threshold."""
        monitor = _mock_monitor()
        governor = _mock_governor()
        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = IRISAuthenticationProvider._check_sla_compliance(
                "edge_op", 4.999, True
            )
        assert result is True
        governor.check_compliance.assert_not_called()


# ---------------------------------------------------------------------------
# IRISAuthenticationProvider – validate_iris_user (lines 108-165)
# ---------------------------------------------------------------------------


class TestValidateIrisUser:
    """Tests for validate_iris_user (lines 108-165)."""

    @pytest.mark.asyncio
    async def test_validate_iris_user_success(self):
        """Lines 121-154: successful IRIS authentication path."""
        provider = _make_provider()
        monitor = _mock_monitor()
        governor = _mock_governor()

        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_connection.cursor.return_value = mock_cursor

        mock_iris = MagicMock()
        mock_iris.createConnection.return_value = mock_connection

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
            patch.dict("sys.modules", {"iris": mock_iris}),
        ):
            success, session_id = await provider.validate_iris_user("alice", "secret")

        assert success is True
        assert session_id is not None
        assert session_id.startswith("iris_session_")

    @pytest.mark.asyncio
    async def test_validate_iris_user_wrong_result(self):
        """Line 143: fetchone returns something other than 1."""
        provider = _make_provider()
        monitor = _mock_monitor()
        governor = _mock_governor()

        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0,)
        mock_connection.cursor.return_value = mock_cursor

        mock_iris = MagicMock()
        mock_iris.createConnection.return_value = mock_connection

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
            patch.dict("sys.modules", {"iris": mock_iris}),
        ):
            success, session_id = await provider.validate_iris_user("alice", "wrong")

        assert success is False
        assert session_id is None

    @pytest.mark.asyncio
    async def test_validate_iris_user_exception_inside_thread(self):
        """Lines 145-147: exception inside iris_auth inner function."""
        provider = _make_provider()
        monitor = _mock_monitor()
        governor = _mock_governor()

        mock_iris = MagicMock()
        mock_iris.createConnection.side_effect = RuntimeError("connection refused")

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
            patch.dict("sys.modules", {"iris": mock_iris}),
        ):
            success, session_id = await provider.validate_iris_user("alice", "secret")

        assert success is False
        assert session_id is None

    @pytest.mark.asyncio
    async def test_validate_iris_user_outer_exception(self):
        """Lines 156-165: outer exception handler."""
        provider = _make_provider()
        monitor = _mock_monitor()

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch(
                "iris_pgwire.auth.scram.asyncio.to_thread",
                side_effect=RuntimeError("thread pool exhausted"),
            ),
        ):
            success, session_id = await provider.validate_iris_user("alice", "secret")

        assert success is False
        assert session_id is None
        monitor.record_operation.assert_called_once()


# ---------------------------------------------------------------------------
# IRISAuthenticationProvider – validate_iris_user_exists (lines 167-218)
# ---------------------------------------------------------------------------


class TestValidateIrisUserExists:
    """Tests for validate_iris_user_exists (lines 167-218)."""

    @pytest.mark.asyncio
    async def test_user_exists(self):
        """Lines 174-214: user found in Security.Users."""
        provider = _make_provider()

        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_connection.cursor.return_value = mock_cursor

        mock_iris = MagicMock()
        mock_iris.createConnection.return_value = mock_connection

        with patch.dict("sys.modules", {"iris": mock_iris}):
            success, session_id = await provider.validate_iris_user_exists("alice")

        assert success is True
        assert session_id.startswith("iris_session_")

    @pytest.mark.asyncio
    async def test_user_not_found(self):
        """Lines 197-198: count is 0, user not found."""
        provider = _make_provider()

        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0,)
        mock_connection.cursor.return_value = mock_cursor

        mock_iris = MagicMock()
        mock_iris.createConnection.return_value = mock_connection

        with patch.dict("sys.modules", {"iris": mock_iris}):
            success, session_id = await provider.validate_iris_user_exists("ghost")

        assert success is False
        assert session_id is None

    @pytest.mark.asyncio
    async def test_user_exists_sla_violation_logged(self):
        """Line 209-210: slow response triggers SLA warning log."""
        provider = _make_provider()

        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (0,)
        mock_connection.cursor.return_value = mock_cursor

        mock_iris = MagicMock()
        mock_iris.createConnection.return_value = mock_connection

        # Patch time.perf_counter to simulate a slow check
        import time as _time

        call_count = 0
        original = _time.perf_counter

        def fast_slow():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 0.0
            return 6.0  # 6 seconds elapsed → SLA violation

        with (
            patch.dict("sys.modules", {"iris": mock_iris}),
            patch("iris_pgwire.auth.scram.time.perf_counter", side_effect=fast_slow),
        ):
            success, session_id = await provider.validate_iris_user_exists("alice")

        assert success is False

    @pytest.mark.asyncio
    async def test_user_exists_inner_exception(self):
        """Line 200-202: inner exception handler in iris_user_check."""
        provider = _make_provider()

        mock_iris = MagicMock()
        mock_iris.createConnection.side_effect = Exception("no route to host")

        with patch.dict("sys.modules", {"iris": mock_iris}):
            success, session_id = await provider.validate_iris_user_exists("alice")

        assert success is False
        assert session_id is None

    @pytest.mark.asyncio
    async def test_user_exists_outer_exception(self):
        """Lines 216-218: outer exception handler."""
        provider = _make_provider()

        with patch(
            "iris_pgwire.auth.scram.asyncio.to_thread",
            side_effect=RuntimeError("event loop closed"),
        ):
            success, session_id = await provider.validate_iris_user_exists("alice")

        assert success is False
        assert session_id is None


# ---------------------------------------------------------------------------
# PostgreSQLAuthenticator – trust auth (lines 483-495)
# ---------------------------------------------------------------------------


class TestTrustAuthentication:
    """Tests for trust authentication flow."""

    @pytest.mark.asyncio
    async def test_authenticate_trust_success(self):
        """Lines 483-495: trust authentication short-circuits to success."""
        auth = _make_pg_auth(AuthenticationMethod.TRUST)
        monitor = _mock_monitor()
        governor = _mock_governor()
        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = await auth.authenticate("conn-1", "alice")

        assert result.success is True
        assert result.username == "alice"
        assert result.metadata["method"] == "trust"
        assert result.metadata["warning"] == "insecure"

    @pytest.mark.asyncio
    async def test_authenticate_trust_sets_sla_compliant(self):
        """Trust auth fast enough to be SLA-compliant."""
        auth = _make_pg_auth(AuthenticationMethod.TRUST)
        monitor = _mock_monitor()
        governor = _mock_governor()
        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = await auth.authenticate("conn-2", "bob")

        assert result.sla_compliant is True


# ---------------------------------------------------------------------------
# PostgreSQLAuthenticator – unsupported auth method (lines 436)
# ---------------------------------------------------------------------------


class TestUnsupportedAuthMethod:
    """Lines 436: unsupported auth method returns failure."""

    @pytest.mark.asyncio
    async def test_unsupported_method_returns_failure(self):
        auth = PostgreSQLAuthenticator(IRIS_CONFIG, auth_method=AuthenticationMethod.MD5)
        monitor = _mock_monitor()
        governor = _mock_governor()
        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = await auth.authenticate("conn-md5", "alice")

        assert result.success is False
        assert "Unsupported" in result.error_message


# ---------------------------------------------------------------------------
# PostgreSQLAuthenticator – SCRAM state machine (lines 497-677)
# ---------------------------------------------------------------------------


def _make_valid_client_proof(
    username: str,
    client_nonce: str,
    server_nonce: str,
    server_message: str,
    password: str,
    salt: bytes,
    iteration_count: int,
) -> tuple[str, str]:
    """Compute a valid client-final-message for a given SCRAM exchange."""
    combined_nonce = client_nonce + server_nonce
    channel_binding_b64 = base64.b64encode(b"n,,").decode("ascii")
    client_final_without_proof = f"c={channel_binding_b64},r={combined_nonce}"

    salted_password = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iteration_count
    )
    client_key = hmac.new(salted_password, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()

    client_first_bare = f"n={username},r={client_nonce}"
    auth_message = f"{client_first_bare},{server_message},{client_final_without_proof}"

    client_signature = hmac.new(stored_key, auth_message.encode("utf-8"), hashlib.sha256).digest()
    client_proof = bytes(a ^ b for a, b in zip(client_key, client_signature, strict=False))
    client_proof_b64 = base64.b64encode(client_proof).decode("ascii")

    client_final = f"{client_final_without_proof},p={client_proof_b64}"
    return client_final, channel_binding_b64


class TestSCRAMStateMachine:
    """Tests for the full SCRAM state machine inside PostgreSQLAuthenticator."""

    @pytest.mark.asyncio
    async def test_initial_state_transitions_to_sasl_started(self):
        """Lines 515-558: INITIAL → SASL_STARTED."""
        auth = _make_pg_auth()
        monitor = _mock_monitor()
        governor = _mock_governor()
        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = await auth.authenticate("conn-scram", "alice")

        assert result.success is False
        assert result.metadata["state"] == "sasl_started"
        session = auth.get_session_state("conn-scram")
        assert session["state"] == AuthenticationState.SASL_STARTED

    @pytest.mark.asyncio
    async def test_scram_client_first_message_step(self):
        """Lines 560-611: SASL_STARTED → SASL_CHALLENGE_SENT with server message."""
        auth = _make_pg_auth()
        monitor = _mock_monitor()
        governor = _mock_governor()
        username = "alice"
        client_nonce = "clientnonce123456789"

        # Pre-register credentials so server-first-message uses real salt
        auth.register_user_credentials(username, "password123")

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            # Step 1: trigger SASL_STARTED
            await auth.authenticate("conn-s1", username)

            # Step 2: send client-first-message
            client_first = f"n,,n={username},r={client_nonce}"
            result = await auth.authenticate("conn-s1", username, client_first.encode())

        assert result.success is False
        assert result.metadata["state"] == "challenge_sent"
        assert "server_message" in result.metadata

    @pytest.mark.asyncio
    async def test_scram_client_first_invalid_message(self):
        """Lines 603-611: bad client-first-message leads to FAILED state."""
        auth = _make_pg_auth()
        monitor = _mock_monitor()
        governor = _mock_governor()
        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            await auth.authenticate("conn-bad", "alice")
            result = await auth.authenticate("conn-bad", "alice", b"not_a_valid_scram_message")

        assert result.success is False
        assert result.error_message == "Invalid client-first-message"

    @pytest.mark.asyncio
    async def test_scram_full_exchange_success(self):
        """Lines 617-666: complete successful SCRAM exchange."""
        auth = _make_pg_auth()
        monitor = _mock_monitor()
        governor = _mock_governor()
        username = "alice"
        password = "password123"
        client_nonce = "clientnonce987654321"

        auth.register_user_credentials(username, password)
        creds = auth.iris_provider.get_stored_credentials(username)

        # Mock IRIS user-exists check
        auth.iris_provider.validate_iris_user_exists = AsyncMock(
            return_value=(True, "iris_session_mock123")
        )

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            # Step 1: initial
            await auth.authenticate("conn-full", username)

            # Step 2: client-first
            client_first = f"n,,n={username},r={client_nonce}"
            r2 = await auth.authenticate("conn-full", username, client_first.encode())

        server_message = r2.metadata["server_message"]
        # Extract server nonce from the server message
        parts = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in server_message.split(",") if "=" in p}
        combined_nonce = parts["r"]
        server_nonce = combined_nonce[len(client_nonce):]

        client_final, _ = _make_valid_client_proof(
            username,
            client_nonce,
            server_nonce,
            server_message,
            password,
            creds.salt,
            creds.iteration_count,
        )

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = await auth.authenticate("conn-full", username, client_final.encode())

        assert result.success is True
        assert result.username == username
        assert result.iris_session == "iris_session_mock123"
        assert auth.is_authenticated("conn-full")

    @pytest.mark.asyncio
    async def test_scram_full_exchange_wrong_proof(self):
        """Wrong client proof → authentication fails."""
        auth = _make_pg_auth()
        monitor = _mock_monitor()
        governor = _mock_governor()
        username = "alice"
        client_nonce = "wrongproof123"

        auth.register_user_credentials(username, "correct_password")

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            await auth.authenticate("conn-wp", username)
            client_first = f"n,,n={username},r={client_nonce}"
            r2 = await auth.authenticate("conn-wp", username, client_first.encode())

        server_message = r2.metadata["server_message"]
        parts = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in server_message.split(",") if "=" in p}
        combined_nonce = parts["r"]
        server_nonce = combined_nonce[len(client_nonce):]

        # Use the WRONG password to generate a bad proof
        client_final, _ = _make_valid_client_proof(
            username,
            client_nonce,
            server_nonce,
            server_message,
            "wrong_password",
            auth.iris_provider.get_stored_credentials(username).salt,
            4096,
        )

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = await auth.authenticate("conn-wp", username, client_final.encode())

        assert result.success is False

    @pytest.mark.asyncio
    async def test_scram_iris_user_validation_fails(self):
        """Lines 620-627: SCRAM crypto passes but IRIS user-exists returns False."""
        auth = _make_pg_auth()
        monitor = _mock_monitor()
        governor = _mock_governor()
        username = "alice"
        password = "password123"
        client_nonce = "irisvalidfail111"

        auth.register_user_credentials(username, password)
        creds = auth.iris_provider.get_stored_credentials(username)

        auth.iris_provider.validate_iris_user_exists = AsyncMock(return_value=(False, None))

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            await auth.authenticate("conn-iv", username)
            client_first = f"n,,n={username},r={client_nonce}"
            r2 = await auth.authenticate("conn-iv", username, client_first.encode())

        server_message = r2.metadata["server_message"]
        parts = {p.split("=", 1)[0]: p.split("=", 1)[1] for p in server_message.split(",") if "=" in p}
        combined_nonce = parts["r"]
        server_nonce = combined_nonce[len(client_nonce):]

        client_final, _ = _make_valid_client_proof(
            username,
            client_nonce,
            server_nonce,
            server_message,
            password,
            creds.salt,
            creds.iteration_count,
        )

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = await auth.authenticate("conn-iv", username, client_final.encode())

        assert result.success is False
        assert "IRIS user validation failed" in result.error_message

    @pytest.mark.asyncio
    async def test_invalid_state_returns_failure(self):
        """Lines 524-530: manually set an invalid state, expect failure."""
        auth = _make_pg_auth()
        monitor = _mock_monitor()
        governor = _mock_governor()

        auth._active_sessions["conn-inv"] = {
            "state": AuthenticationState.AUTHENTICATED,  # already done
            "username": "alice",
            "start_time": 0.0,
        }

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
        ):
            result = await auth.authenticate("conn-inv", "alice", b"any_data")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_authenticate_error_handler(self):
        """Lines 423-424: exception inside _run_authentication_method is caught."""
        auth = _make_pg_auth()
        monitor = _mock_monitor()
        governor = _mock_governor()

        with (
            patch("iris_pgwire.auth.scram.get_monitor", return_value=monitor),
            patch("iris_pgwire.auth.scram.get_governor", return_value=governor),
            patch.object(
                auth,
                "_run_authentication_method",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = await auth.authenticate("conn-err", "alice")

        assert result.success is False
        assert result.error_message == "Authentication failed"


# ---------------------------------------------------------------------------
# PostgreSQLAuthenticator – session helpers (lines 693-724)
# ---------------------------------------------------------------------------


class TestSessionHelpers:
    """Tests for session state helpers."""

    def test_get_user_info_authenticated(self):
        """Lines 715-724: get_user_info when authenticated."""
        auth = _make_pg_auth()
        auth._active_sessions["conn-ui"] = {
            "state": AuthenticationState.AUTHENTICATED,
            "username": "alice",
            "iris_session_id": "sess-xyz",
        }
        info = auth.get_user_info("conn-ui")
        assert info is not None
        assert info["username"] == "alice"
        assert info["iris_session_id"] == "sess-xyz"
        assert info["auth_method"] == AuthenticationMethod.SCRAM_SHA_256.value

    def test_get_user_info_not_authenticated(self):
        """Line 724: not authenticated returns None."""
        auth = _make_pg_auth()
        assert auth.get_user_info("nonexistent") is None

    def test_get_user_info_wrong_state(self):
        """SASL_STARTED state → get_user_info returns None."""
        auth = _make_pg_auth()
        auth._active_sessions["conn-ns"] = {
            "state": AuthenticationState.SASL_STARTED,
            "username": "alice",
        }
        assert auth.get_user_info("conn-ns") is None

    def test_is_authenticated_false_for_sasl_started(self):
        """Line 710: is_authenticated returns False if not AUTHENTICATED state."""
        auth = _make_pg_auth()
        auth._active_sessions["conn-sa"] = {
            "state": AuthenticationState.SASL_STARTED,
            "username": "alice",
        }
        assert auth.is_authenticated("conn-sa") is False

    def test_cleanup_session(self):
        """cleanup_session removes session."""
        auth = _make_pg_auth()
        auth._active_sessions["conn-cl"] = {"state": AuthenticationState.INITIAL}
        auth.cleanup_session("conn-cl")
        assert auth.get_session_state("conn-cl") is None

    def test_cleanup_nonexistent_session(self):
        """cleanup_session on missing key is a no-op."""
        auth = _make_pg_auth()
        auth.cleanup_session("conn-missing")  # should not raise

    def test_requires_password_trust(self):
        """Line 703: trust method does not require password."""
        auth = _make_pg_auth(AuthenticationMethod.TRUST)
        assert auth.requires_password() is False

    def test_requires_password_scram(self):
        auth = _make_pg_auth(AuthenticationMethod.SCRAM_SHA_256)
        assert auth.requires_password() is True


# ---------------------------------------------------------------------------
# register_user_credentials failure path (line 685-687)
# ---------------------------------------------------------------------------


class TestRegisterUserCredentials:
    def test_register_success(self):
        auth = _make_pg_auth()
        assert auth.register_user_credentials("alice", "pass") is True
        assert auth.iris_provider.get_stored_credentials("alice") is not None

    def test_register_failure_returns_false(self):
        """Lines 685-687: exception during store → returns False."""
        auth = _make_pg_auth()
        with patch.object(
            auth.iris_provider, "store_credentials", side_effect=RuntimeError("disk full")
        ):
            result = auth.register_user_credentials("alice", "pass")
        assert result is False


# ---------------------------------------------------------------------------
# SCRAMAuthenticator – verify_client_final_message edge cases (lines 317-384)
# ---------------------------------------------------------------------------


class TestVerifyClientFinalEdgeCases:
    def setup_method(self):
        provider = _make_provider()
        self.scram = _make_scram(provider)
        # Register a user
        provider.store_credentials("alice", "correctpassword")
        self.creds = provider.get_stored_credentials("alice")

    def _build_session(self, client_nonce: str, server_nonce: str, server_first: str) -> dict:
        return {
            "username": "alice",
            "client_nonce": client_nonce,
            "server_nonce": server_nonce,
            "server_first_message": server_first,
            "state": AuthenticationState.SASL_CHALLENGE_SENT,
        }

    def test_invalid_nonce_returns_false(self):
        """Lines 338-339: nonce mismatch."""
        session = self._build_session("cn", "sn", "r=cnsn,s=AAAA,i=4096")
        # Craft message with wrong nonce
        msg = f"c={base64.b64encode(b'n,,').decode()},r=WRONGNONCE,p=AAAA"
        ok, err = self.scram.verify_client_final_message(msg, session)
        assert ok is False
        assert err == "Invalid nonce"

    def test_invalid_channel_binding(self):
        """Lines 344-348: channel binding decode fails."""
        session = self._build_session("cn", "sn", "r=cnsn,s=AAAA,i=4096")
        # channel binding is not valid base64
        msg = "c=!!!notbase64,r=cnsn,p=AAAA"
        ok, err = self.scram.verify_client_final_message(msg, session)
        assert ok is False

    def test_no_stored_credentials(self):
        """Lines 352-353: no credentials for user → failure."""
        provider = _make_provider()  # fresh, no creds
        scram = _make_scram(provider)
        session = {
            "username": "ghost",
            "client_nonce": "cn",
            "server_nonce": "sn",
            "server_first_message": "r=cnsn,s=AAAA,i=4096",
        }
        msg = f"c={base64.b64encode(b'n,,').decode()},r=cnsn,p=AAAA"
        ok, err = self.scram.verify_client_final_message(msg, session)
        assert ok is False
        assert err == "Authentication failed"

    def test_wrong_channel_binding_value(self):
        """Lines 344-347: channel binding decodes but is not b'n,,'."""
        session = self._build_session("cn", "sn", "r=cnsn,s=AAAA,i=4096")
        # Valid base64 but decodes to something other than b"n,,"
        wrong_cb = base64.b64encode(b"p,,").decode("ascii")
        msg = f"c={wrong_cb},r=cnsn,p=AAAA"
        ok, err = self.scram.verify_client_final_message(msg, session)
        # Should fail at nonce check or credential check — not a hard error
        # (the code only logs a warning for wrong channel binding, still proceeds)
        # The nonce is "cnsn" which matches, but proof will be invalid
        assert ok is False

    def test_bad_proof_not_base64(self):
        """Exception path in verify_client_final_message."""
        session = self._build_session("cn", "sn", "r=cnsn,s=AAAA,i=4096")
        msg = f"c={base64.b64encode(b'n,,').decode()},r=cnsn,p=!!!notbase64!!!"
        ok, err = self.scram.verify_client_final_message(msg, session)
        assert ok is False
        assert err == "Authentication failed"


# ---------------------------------------------------------------------------
# Protocol message helpers
# ---------------------------------------------------------------------------


class TestProtocolHelpers:
    def test_create_authentication_ok(self):
        msg = create_authentication_ok()
        assert msg[0:1] == b"R"
        msg_type, length = struct.unpack("!cI", msg[:5])
        status = struct.unpack("!I", msg[5:9])[0]
        assert status == 0

    def test_create_authentication_sasl_structure(self):
        msg = create_authentication_sasl(["SCRAM-SHA-256"])
        assert msg[0:1] == b"R"
        status = struct.unpack("!I", msg[5:9])[0]
        assert status == 10

    def test_create_authentication_sasl_continue(self):
        msg = create_authentication_sasl_continue("r=nonce,s=salt,i=4096")
        assert msg[0:1] == b"R"
        status = struct.unpack("!I", msg[5:9])[0]
        assert status == 11

    def test_create_authentication_sasl_final(self):
        msg = create_authentication_sasl_final("v=serversig")
        assert msg[0:1] == b"R"
        status = struct.unpack("!I", msg[5:9])[0]
        assert status == 12

    def test_create_error_response(self):
        msg = create_error_response("28P01", "password authentication failed")
        assert msg[0:1] == b"E"
        assert b"28P01" in msg
        assert b"password authentication failed" in msg
