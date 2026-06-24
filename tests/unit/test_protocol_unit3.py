"""
Unit tests for PGWireProtocol (protocol.py) — Phase 3.

Targets uncovered lines: SSL probe, startup sequence error paths,
SCRAM authentication, handle_ssl_probe, COPY protocol (legacy path),
cancel request, send_copy_*, _decode_binary_parameter edge cases,
message_loop error paths, handle_set_command, _transaction_flags,
infer_parameter_oids_from_casts, _find_limit_offset_param_indexes, etc.

All tests use mocked dependencies — no IRIS connection required.
"""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.protocol import (
    CANCEL_REQUEST_CODE,
    GSSENC_REQUEST_CODE,
    MSG_AUTHENTICATION,
    MSG_BACKEND_KEY_DATA,
    MSG_BIND_COMPLETE,
    MSG_CLOSE_COMPLETE,
    MSG_COMMAND_COMPLETE,
    MSG_COPY_DATA,
    MSG_COPY_DONE,
    MSG_COPY_FAIL,
    MSG_COPY_IN_RESPONSE,
    MSG_COPY_OUT_RESPONSE,
    MSG_DATA_ROW,
    MSG_ERROR_RESPONSE,
    MSG_NO_DATA,
    MSG_PARAMETER_DESCRIPTION,
    MSG_PARAMETER_STATUS,
    MSG_PARSE_COMPLETE,
    MSG_READY_FOR_QUERY,
    MSG_ROW_DESCRIPTION,
    PGWireProtocol,
    SSL_REQUEST_CODE,
    STATUS_IDLE,
    STATUS_IN_TRANSACTION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_protocol(enable_scram: bool = False) -> PGWireProtocol:
    reader = AsyncMock(spec=asyncio.StreamReader)
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    writer.wait_closed = AsyncMock()

    iris_executor = MagicMock()
    iris_executor.sql_pipeline = MagicMock()
    iris_executor.sql_translator = MagicMock()
    iris_executor.sql_translator.translate_postgres_parameters = lambda sql: sql
    iris_executor.sql_parser = MagicMock()
    iris_executor.sql_parser.is_select_statement = MagicMock(return_value=False)
    iris_executor.sql_parser.is_show_statement = MagicMock(return_value=False)
    iris_executor.sql_parser.is_dml_statement = MagicMock(return_value=False)
    iris_executor.sql_parser.has_returning_clause = MagicMock(return_value=False)
    iris_executor.set_session_namespace = MagicMock()
    iris_executor.get_iris_type_mapping = MagicMock(
        return_value={
            "VARCHAR": {"oid": 25, "typlen": -1},
            "INTEGER": {"oid": 23, "typlen": 4},
            "BIGINT": {"oid": 20, "typlen": 8},
            "BOOLEAN": {"oid": 16, "typlen": 1},
            "FLOAT": {"oid": 700, "typlen": 4},
            "DOUBLE": {"oid": 701, "typlen": 8},
            "DATE": {"oid": 1082, "typlen": 4},
            "TIMESTAMP": {"oid": 1114, "typlen": 8},
            "NUMERIC": {"oid": 1700, "typlen": -1},
        }
    )
    iris_executor.close_session = AsyncMock()
    iris_executor.begin_transaction = AsyncMock()
    iris_executor.commit_transaction = AsyncMock()
    iris_executor.rollback_transaction = AsyncMock()
    iris_executor.execute_many = AsyncMock()
    iris_executor.execute_query = AsyncMock(
        return_value={
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "command_tag": "SELECT",
        }
    )
    iris_executor.cancel_query = AsyncMock(return_value=True)
    iris_executor.strict_single_connection = False
    iris_executor.metadata_cache = None

    p = PGWireProtocol(
        reader=reader,
        writer=writer,
        iris_executor=iris_executor,
        connection_id="test-conn-003",
        enable_scram=enable_scram,
    )
    return p


def collected_bytes(writer) -> bytes:
    return b"".join(call.args[0] for call in writer.write.call_args_list)


@pytest.fixture
def protocol():
    return make_protocol()


@pytest.fixture
def scram_protocol():
    return make_protocol(enable_scram=True)


# ===========================================================================
# SSL probe handler
# ===========================================================================


class TestHandleSslProbe:
    @pytest.mark.asyncio
    async def test_ssl_request_no_context_responds_N_then_startup(self, protocol):
        """SSL request with no ssl_context → reply 'N' and loop to startup data."""
        # First read: SSL probe (length=8, code=SSL_REQUEST_CODE)
        ssl_probe = struct.pack("!II", 8, SSL_REQUEST_CODE)
        # Second read: startup message (length=23, protocol=0x00030000, user\x00test\x00\x00)
        startup_payload = struct.pack("!I", 0x00030000) + b"user\x00test\x00\x00"
        startup_msg = struct.pack("!I", 4 + len(startup_payload)) + startup_payload
        protocol.reader.readexactly.side_effect = [
            ssl_probe,
            startup_msg[:8],  # Second probe read returns startup first 8 bytes
        ]
        await protocol.handle_ssl_probe(ssl_context=None)
        # Should have written 'N'
        written = collected_bytes(protocol.writer)
        assert b"N" in written
        # Buffered data should be set from the second read
        assert hasattr(protocol, "_buffered_data")

    @pytest.mark.asyncio
    async def test_gssenc_request_responds_N_continues(self, protocol):
        """GSSENCRequest → reply 'N', continue loop, then read startup data."""
        gssenc_probe = struct.pack("!II", 8, GSSENC_REQUEST_CODE)
        # After GSSENC response, next read is a non-probe startup (small protocol version)
        # Use a real startup message header (length=23, protocol version=0x00030000)
        startup_payload = struct.pack("!I", 0x00030000) + b"user\x00me\x00\x00"
        startup_len = 4 + len(startup_payload)
        startup_first8 = struct.pack("!I", startup_len) + startup_payload[:4]
        protocol.reader.readexactly.side_effect = [
            gssenc_probe,
            startup_first8,
        ]
        await protocol.handle_ssl_probe(ssl_context=None)
        written = collected_bytes(protocol.writer)
        assert b"N" in written

    @pytest.mark.asyncio
    async def test_cancel_request_calls_handle_cancel_and_returns(self, protocol):
        """Cancel request → handle_cancel_request, then return (no further reads)."""
        cancel_probe = struct.pack("!II", 16, CANCEL_REQUEST_CODE)
        # handle_cancel_request reads 8 more bytes
        cancel_payload = struct.pack("!II", 12345, 99999)
        protocol.reader.readexactly.side_effect = [cancel_probe, cancel_payload]
        await protocol.handle_ssl_probe(ssl_context=None)
        # cancel_query should have been called
        protocol.iris_executor.cancel_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_incomplete_read_raises_connection_aborted(self, protocol):
        """IncompleteReadError during probe → ConnectionAbortedError."""
        protocol.reader.readexactly.side_effect = asyncio.IncompleteReadError(b"", 8)
        with pytest.raises(ConnectionAbortedError):
            await protocol.handle_ssl_probe(ssl_context=None)

    @pytest.mark.asyncio
    async def test_non_probe_data_stored_as_buffered(self, protocol):
        """Non-probe first message treated as startup, stored in _buffered_data."""
        # A length/code that is not SSL, GSSENC, or CANCEL
        non_probe = struct.pack("!II", 23, 0x00030000)  # regular startup
        protocol.reader.readexactly.return_value = non_probe
        await protocol.handle_ssl_probe(ssl_context=None)
        assert protocol._buffered_data == non_probe


# ===========================================================================
# parse_startup_message with buffered data
# ===========================================================================


class TestParseStartupMessageBuffered:
    @pytest.mark.asyncio
    async def test_with_buffered_data(self, protocol):
        """Startup message parsed correctly when _buffered_data is set."""
        # Construct a full startup message
        params = b"user\x00testuser\x00database\x00mydb\x00\x00"
        payload = struct.pack("!I", 0x00030000) + params
        total_length = 4 + len(payload)

        # Simulate that ssl_probe stored first 8 bytes
        first8 = struct.pack("!I", total_length) + payload[:4]
        protocol._buffered_data = first8

        # readexactly returns the remaining bytes
        remaining = payload[4:]
        protocol.reader.readexactly.return_value = remaining

        await protocol.parse_startup_message()
        assert protocol.startup_params.get("user") == "testuser"
        assert protocol.startup_params.get("database") == "mydb"

    @pytest.mark.asyncio
    async def test_without_buffered_data_normal_path(self, protocol):
        """Startup message parsed in normal (non-buffered) path."""
        params = b"user\x00alice\x00\x00"
        payload = struct.pack("!I", 0x00030000) + params
        total_length = 4 + len(payload)

        length_bytes = struct.pack("!I", total_length)
        protocol.reader.readexactly.side_effect = [length_bytes, payload]

        await protocol.parse_startup_message()
        assert protocol.startup_params.get("user") == "alice"

    @pytest.mark.asyncio
    async def test_buffered_data_all_already_read(self, protocol):
        """When buffered data already contains all bytes needed."""
        params = b"\x00"  # minimal: just terminator
        payload = struct.pack("!I", 0x00030000) + params
        total_length = 4 + len(payload)

        # Fake: buffered data contains MORE than needed — triggers already_read path
        first8 = struct.pack("!I", total_length) + payload[:4]
        protocol._buffered_data = first8

        # No extra read needed if remaining == already_read length
        protocol.reader.readexactly.return_value = params
        await protocol.parse_startup_message()


# ===========================================================================
# handle_startup_sequence
# ===========================================================================


class TestHandleStartupSequence:
    @pytest.mark.asyncio
    async def test_incomplete_read_raises_connection_aborted(self, protocol):
        """IncompleteReadError during startup → ConnectionAbortedError."""
        with patch.object(
            protocol,
            "parse_startup_message",
            side_effect=asyncio.IncompleteReadError(b"", 4),
        ):
            with pytest.raises(ConnectionAbortedError):
                await protocol.handle_startup_sequence()

    @pytest.mark.asyncio
    async def test_generic_exception_sends_error_and_reraises(self, protocol):
        """Generic error during startup → error response sent and re-raised."""
        with patch.object(
            protocol,
            "parse_startup_message",
            side_effect=ValueError("bad startup"),
        ):
            with pytest.raises(ValueError):
                await protocol.handle_startup_sequence()
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_scram_path_calls_scram_methods(self, scram_protocol):
        """When enable_scram=True, SCRAM sequence methods are called."""
        with (
            patch.object(scram_protocol, "parse_startup_message", new_callable=AsyncMock),
            patch.object(scram_protocol, "start_scram_authentication", new_callable=AsyncMock) as mock_scram,
            patch.object(scram_protocol, "handle_scram_client_final", new_callable=AsyncMock) as mock_final,
            patch.object(scram_protocol, "complete_scram_authentication", new_callable=AsyncMock) as mock_complete,
            patch.object(scram_protocol, "send_parameter_status", new_callable=AsyncMock),
            patch.object(scram_protocol, "send_backend_key_data", new_callable=AsyncMock),
            patch.object(scram_protocol, "send_ready_for_query", new_callable=AsyncMock),
        ):
            await scram_protocol.handle_startup_sequence()
            mock_scram.assert_called_once()
            mock_final.assert_called_once()
            mock_complete.assert_called_once()


# ===========================================================================
# SCRAM authentication methods
# ===========================================================================


class TestScramAuthentication:
    @pytest.mark.asyncio
    async def test_send_sasl_auth_request(self, scram_protocol):
        """send_sasl_auth_request writes SASL message with SCRAM-SHA-256."""
        await scram_protocol.send_sasl_auth_request()
        written = collected_bytes(scram_protocol.writer)
        assert MSG_AUTHENTICATION in written
        assert b"SCRAM-SHA-256" in written

    @pytest.mark.asyncio
    async def test_handle_sasl_initial_response_valid(self, scram_protocol):
        """handle_sasl_initial_response with valid SCRAM-SHA-256 body."""
        mechanism = b"SCRAM-SHA-256\x00"
        initial_response = b"n,,n=user,r=clientnonce123"
        response_length = struct.pack("!I", len(initial_response))
        body = mechanism + response_length + initial_response

        with patch.object(scram_protocol, "process_scram_client_first", new_callable=AsyncMock):
            await scram_protocol.handle_sasl_initial_response(body)

    @pytest.mark.asyncio
    async def test_handle_sasl_initial_response_wrong_mechanism(self, scram_protocol):
        """handle_sasl_initial_response with unsupported mechanism raises."""
        body = b"UNKNOWN-MECH\x00" + struct.pack("!I", 0)
        with pytest.raises(ValueError, match="Unsupported SASL mechanism"):
            await scram_protocol.handle_sasl_initial_response(body)

    @pytest.mark.asyncio
    async def test_handle_sasl_initial_response_missing_mechanism(self, scram_protocol):
        """Body with no null terminator raises."""
        body = b"no-null-here"
        with pytest.raises(ValueError, match="Invalid SASL response"):
            await scram_protocol.handle_sasl_initial_response(body)

    @pytest.mark.asyncio
    async def test_handle_sasl_initial_response_ffff_length(self, scram_protocol):
        """0xFFFFFFFF response length means empty initial response."""
        mechanism = b"SCRAM-SHA-256\x00"
        body = mechanism + struct.pack("!I", 0xFFFFFFFF)
        with patch.object(scram_protocol, "process_scram_client_first", new_callable=AsyncMock) as mock_proc:
            await scram_protocol.handle_sasl_initial_response(body)
            mock_proc.assert_called_once_with(b"")

    @pytest.mark.asyncio
    async def test_process_scram_client_first_valid(self, scram_protocol):
        """process_scram_client_first stores nonce and sends server-first."""
        client_first = b"n,,n=user,r=clientnonce"
        with patch.object(scram_protocol, "send_scram_server_first", new_callable=AsyncMock):
            await scram_protocol.process_scram_client_first(client_first)
        assert scram_protocol.client_nonce == "clientnonce"
        assert scram_protocol.scram_state["username"] == "user"

    @pytest.mark.asyncio
    async def test_process_scram_client_first_missing_prefix_raises(self, scram_protocol):
        """client-first without n,, prefix raises ValueError."""
        client_first = b"bad,n=user,r=nonce"
        with pytest.raises(ValueError):
            await scram_protocol.process_scram_client_first(client_first)

    @pytest.mark.asyncio
    async def test_process_scram_client_first_missing_username_raises(self, scram_protocol):
        """client-first without username raises ValueError."""
        client_first = b"n,,r=clientnonce"
        with pytest.raises(ValueError, match="Missing username"):
            await scram_protocol.process_scram_client_first(client_first)

    @pytest.mark.asyncio
    async def test_send_scram_server_first(self, scram_protocol):
        """send_scram_server_first writes AuthenticationSASLContinue."""
        scram_protocol.client_nonce = "clientnonce"
        scram_protocol.server_nonce = "servernonce"
        scram_protocol.salt = "c2FsdA=="
        scram_protocol.iteration_count = 4096
        await scram_protocol.send_scram_server_first()
        written = collected_bytes(scram_protocol.writer)
        assert MSG_AUTHENTICATION in written
        assert b"clientnonce" in written

    @pytest.mark.asyncio
    async def test_handle_scram_client_final_reads_message(self, scram_protocol):
        """handle_scram_client_final reads and processes SASLResponse."""
        body = b"c=biws,r=clientnonceservernonce,p=proof"
        header = struct.pack("!cI", b"p", 4 + len(body))
        scram_protocol.reader.readexactly.side_effect = [header, body]
        await scram_protocol.handle_scram_client_final()

    @pytest.mark.asyncio
    async def test_handle_scram_client_final_wrong_msg_type(self, scram_protocol):
        """handle_scram_client_final raises if wrong message type."""
        header = struct.pack("!cI", b"Q", 8)
        body = b"some body"
        scram_protocol.reader.readexactly.side_effect = [header, body]
        with pytest.raises(ValueError, match="Expected SASLResponse"):
            await scram_protocol.handle_scram_client_final()

    @pytest.mark.asyncio
    async def test_complete_scram_authentication_trust_mode(self, protocol):
        """complete_scram_authentication without bridge uses trust mode."""
        protocol.auth_bridge_available = False
        protocol.scram_state = {"username": "testuser"}
        with patch.object(protocol, "send_scram_final_success", new_callable=AsyncMock) as mock_final:
            await protocol.complete_scram_authentication()
            mock_final.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_scram_authentication_oauth_path(self, protocol):
        """complete_scram_authentication with bridge uses oauth path."""
        protocol.auth_bridge_available = True
        protocol.scram_state = {"username": "testuser"}

        mock_token = MagicMock()
        mock_token.expires_in = 3600

        protocol.auth_selector = MagicMock()
        protocol.auth_selector.select_authentication_method = AsyncMock(return_value="oauth")
        protocol.auth_selector.should_try_wallet_first = AsyncMock(return_value=False)
        protocol.oauth_bridge = MagicMock()
        protocol.oauth_bridge.exchange_password_for_token = AsyncMock(return_value=mock_token)
        protocol.wallet_credentials = MagicMock()

        with patch.object(protocol, "send_scram_final_success", new_callable=AsyncMock) as mock_final:
            await protocol.complete_scram_authentication()
            mock_final.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_scram_authentication_wallet_path(self, protocol):
        """complete_scram_authentication with wallet retrieval."""
        protocol.auth_bridge_available = True
        protocol.scram_state = {"username": "testuser"}

        protocol.auth_selector = MagicMock()
        protocol.auth_selector.select_authentication_method = AsyncMock(return_value="password")
        protocol.auth_selector.should_try_wallet_first = AsyncMock(return_value=True)
        protocol.wallet_credentials = MagicMock()
        protocol.wallet_credentials.get_password_from_wallet = AsyncMock(return_value="walletpw")
        protocol.oauth_bridge = MagicMock()

        with patch.object(protocol, "send_scram_final_success", new_callable=AsyncMock) as mock_final:
            await protocol.complete_scram_authentication()
            mock_final.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_scram_authentication_wallet_fails_fallback(self, protocol):
        """Wallet retrieval fails, falls back to placeholder password."""
        protocol.auth_bridge_available = True
        protocol.scram_state = {"username": "testuser"}

        protocol.auth_selector = MagicMock()
        protocol.auth_selector.select_authentication_method = AsyncMock(return_value="password")
        protocol.auth_selector.should_try_wallet_first = AsyncMock(return_value=True)
        protocol.wallet_credentials = MagicMock()
        protocol.wallet_credentials.get_password_from_wallet = AsyncMock(
            side_effect=Exception("wallet error")
        )
        protocol.oauth_bridge = MagicMock()

        with patch.object(protocol, "send_scram_final_success", new_callable=AsyncMock) as mock_final:
            await protocol.complete_scram_authentication()
            mock_final.assert_called_once()

    @pytest.mark.asyncio
    async def test_complete_scram_authentication_unsupported_method(self, protocol):
        """Unsupported auth method raises ValueError."""
        protocol.auth_bridge_available = True
        protocol.scram_state = {"username": "testuser"}

        protocol.auth_selector = MagicMock()
        protocol.auth_selector.select_authentication_method = AsyncMock(return_value="kerberos")
        protocol.auth_selector.should_try_wallet_first = AsyncMock(return_value=False)
        protocol.wallet_credentials = MagicMock()
        protocol.oauth_bridge = MagicMock()

        with pytest.raises(ValueError, match="Authentication failed"):
            await protocol.complete_scram_authentication()

    @pytest.mark.asyncio
    async def test_send_scram_final_success(self, scram_protocol):
        """send_scram_final_success writes SASL final and AuthOk."""
        scram_protocol.scram_state = {"username": "testuser"}
        await scram_protocol.send_scram_final_success()
        written = collected_bytes(scram_protocol.writer)
        # SASL final (R + 12) then auth ok (R + 0)
        assert written.count(MSG_AUTHENTICATION) >= 2

    @pytest.mark.asyncio
    async def test_start_scram_authentication_wrong_msg_type(self, scram_protocol):
        """start_scram_authentication raises on non-SASLResponse message."""
        with patch.object(scram_protocol, "send_sasl_auth_request", new_callable=AsyncMock):
            # Return wrong message type header
            header = struct.pack("!cI", b"Q", 8)
            body = b"garbage"
            scram_protocol.reader.readexactly.side_effect = [header, body]
            with pytest.raises(Exception):
                await scram_protocol.start_scram_authentication()


# ===========================================================================
# cancel request
# ===========================================================================


class TestCancelRequest:
    @pytest.mark.asyncio
    async def test_cancel_success(self, protocol):
        """handle_cancel_request reads pid/secret, calls cancel_query."""
        cancel_data = struct.pack("!II", protocol.backend_pid, protocol.backend_secret)
        protocol.reader.readexactly.return_value = cancel_data
        protocol.iris_executor.cancel_query.return_value = True

        await protocol.handle_cancel_request()
        protocol.iris_executor.cancel_query.assert_called_once()
        protocol.writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_failure_logs_warning(self, protocol):
        """handle_cancel_request handles failed cancel gracefully."""
        cancel_data = struct.pack("!II", 99999, 11111)
        protocol.reader.readexactly.return_value = cancel_data
        protocol.iris_executor.cancel_query.return_value = False

        await protocol.handle_cancel_request()
        protocol.iris_executor.cancel_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_request_exception_handled(self, protocol):
        """handle_cancel_request exception does not propagate."""
        protocol.reader.readexactly.side_effect = Exception("read error")
        # Should not raise
        await protocol.handle_cancel_request()


# ===========================================================================
# message_loop paths
# ===========================================================================


class TestMessageLoopPaths:
    @pytest.mark.asyncio
    async def test_terminate_message_breaks_loop(self, protocol):
        """MSG_TERMINATE causes message_loop to exit cleanly."""
        from iris_pgwire.protocol import MSG_TERMINATE

        header = struct.pack("!cI", MSG_TERMINATE, 4)
        protocol.reader.readexactly.side_effect = [header]
        await protocol.message_loop()
        protocol.iris_executor.close_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_message_type_sends_error(self, protocol):
        """Unknown message type gets an error response, then next iteration reads terminate."""
        from iris_pgwire.protocol import MSG_TERMINATE

        unknown_header = struct.pack("!cI", b"Z", 4)
        terminate_header = struct.pack("!cI", MSG_TERMINATE, 4)
        protocol.reader.readexactly.side_effect = [unknown_header, terminate_header]
        await protocol.message_loop()
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_incomplete_read_exits_cleanly(self, protocol):
        """IncompleteReadError exits message_loop cleanly."""
        protocol.reader.readexactly.side_effect = asyncio.IncompleteReadError(b"", 5)
        await protocol.message_loop()
        protocol.iris_executor.close_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_general_exception_sends_fatal_error(self, protocol):
        """General exception in message_loop sends FATAL error response."""
        protocol.reader.readexactly.side_effect = RuntimeError("unexpected")
        await protocol.message_loop()
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_flush_message_dispatched(self, protocol):
        """MSG_FLUSH is handled (drains writer)."""
        from iris_pgwire.protocol import MSG_FLUSH, MSG_TERMINATE

        flush_header = struct.pack("!cI", MSG_FLUSH, 4)
        terminate_header = struct.pack("!cI", MSG_TERMINATE, 4)
        protocol.reader.readexactly.side_effect = [flush_header, terminate_header]
        await protocol.message_loop()
        # drain should have been called at least once for flush
        assert protocol.writer.drain.call_count >= 1

    @pytest.mark.asyncio
    async def test_copy_data_message_dispatched(self, protocol):
        """MSG_COPY_DATA is dispatched to handle_copy_data_message."""
        from iris_pgwire.protocol import MSG_TERMINATE

        copy_data_header = struct.pack("!cI", MSG_COPY_DATA, 9)
        copy_body = b"some,csv"
        terminate_header = struct.pack("!cI", MSG_TERMINATE, 4)
        protocol.reader.readexactly.side_effect = [
            copy_data_header,
            copy_body,
            terminate_header,
        ]
        with patch.object(protocol, "handle_copy_data_message", new_callable=AsyncMock) as mock_copy:
            await protocol.message_loop()
        mock_copy.assert_called_once_with(copy_body)

    @pytest.mark.asyncio
    async def test_copy_done_message_dispatched(self, protocol):
        """MSG_COPY_DONE is dispatched."""
        from iris_pgwire.protocol import MSG_TERMINATE

        copy_done_header = struct.pack("!cI", MSG_COPY_DONE, 4)
        terminate_header = struct.pack("!cI", MSG_TERMINATE, 4)
        protocol.reader.readexactly.side_effect = [
            copy_done_header,
            terminate_header,
        ]
        with patch.object(protocol, "handle_copy_done_message", new_callable=AsyncMock) as mock_done:
            await protocol.message_loop()
        mock_done.assert_called_once()

    @pytest.mark.asyncio
    async def test_copy_fail_message_dispatched(self, protocol):
        """MSG_COPY_FAIL is dispatched."""
        from iris_pgwire.protocol import MSG_TERMINATE

        fail_header = struct.pack("!cI", MSG_COPY_FAIL, 4)
        terminate_header = struct.pack("!cI", MSG_TERMINATE, 4)
        protocol.reader.readexactly.side_effect = [fail_header, terminate_header]
        with patch.object(protocol, "handle_copy_fail_message", new_callable=AsyncMock) as mock_fail:
            await protocol.message_loop()
        mock_fail.assert_called_once()


# ===========================================================================
# handle_set_command
# ===========================================================================


class TestHandleSetCommand:
    @pytest.mark.asyncio
    async def test_set_command_success(self, protocol):
        await protocol.handle_set_command("SET extra_float_digits = 2", send_ready=True)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY in written

    @pytest.mark.asyncio
    async def test_set_without_ready(self, protocol):
        await protocol.handle_set_command("SET application_name = 'myapp'", send_ready=False)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY not in written

    @pytest.mark.asyncio
    async def test_reset_command(self, protocol):
        await protocol.handle_set_command("RESET ALL", send_ready=True)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_reset_single_param(self, protocol):
        await protocol.handle_set_command("RESET search_path", send_ready=True)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_malformed_set_command_sends_error(self, protocol):
        """Malformed SET command (no param name matched) sends error."""
        # Simulate a truly unmatched command by injecting an exception
        with patch("re.match", side_effect=Exception("re error")):
            await protocol.handle_set_command("SET something", send_ready=True)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_set_response_extended_protocol(self, protocol):
        """send_set_response_extended_protocol sends CommandComplete only."""
        await protocol.send_set_response_extended_protocol()
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY not in written

    @pytest.mark.asyncio
    async def test_send_transaction_response_extended_begin(self, protocol):
        """Extended protocol BEGIN updates status and sends CommandComplete."""
        await protocol.send_transaction_response_extended_protocol("BEGIN")
        assert protocol.transaction_status == STATUS_IN_TRANSACTION
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY not in written

    @pytest.mark.asyncio
    async def test_send_transaction_response_extended_commit(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        await protocol.send_transaction_response_extended_protocol("COMMIT")
        assert protocol.transaction_status == STATUS_IDLE

    @pytest.mark.asyncio
    async def test_send_transaction_response_extended_rollback(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        await protocol.send_transaction_response_extended_protocol("ROLLBACK")
        assert protocol.transaction_status == STATUS_IDLE


# ===========================================================================
# _transaction_flags
# ===========================================================================


class TestTransactionFlags:
    def test_idle_returns_false_true(self, protocol):
        protocol.transaction_status = STATUS_IDLE
        in_txn, autocommit = protocol._transaction_flags()
        assert in_txn is False
        assert autocommit is True

    def test_in_transaction_returns_true_false(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        in_txn, autocommit = protocol._transaction_flags()
        assert in_txn is True
        assert autocommit is False


# ===========================================================================
# send_empty_pg_catalog_result
# ===========================================================================


class TestSendEmptyPgCatalogResult:
    @pytest.mark.asyncio
    async def test_sends_row_desc_and_command_complete(self, protocol):
        await protocol.send_empty_pg_catalog_result(send_ready=True)
        written = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in written
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY in written

    @pytest.mark.asyncio
    async def test_no_ready_when_send_ready_false(self, protocol):
        await protocol.send_empty_pg_catalog_result(send_ready=False)
        written = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY not in written


# ===========================================================================
# infer_parameter_oids_from_casts
# ===========================================================================


class TestInferParameterOids:
    def test_cast_integer_returns_23(self, protocol):
        sql = "SELECT CAST(? AS INTEGER)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [23]

    def test_cast_bigint_returns_20(self, protocol):
        sql = "SELECT CAST(? AS BIGINT)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [20]

    def test_cast_varchar_returns_1043(self, protocol):
        sql = "SELECT CAST(? AS VARCHAR)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1043]

    def test_cast_boolean_returns_16(self, protocol):
        sql = "WHERE x = CAST(? AS BOOLEAN)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [16]

    def test_unknown_type_returns_705(self, protocol):
        sql = "WHERE x = CAST(? AS JSONB)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [705]

    def test_any_pattern_returns_1009(self, protocol):
        sql = "WHERE name = ANY(?)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1009]

    def test_multiple_casts(self, protocol):
        sql = "SELECT CAST(? AS INTEGER), CAST(? AS VARCHAR)"
        result = protocol.infer_parameter_oids_from_casts(sql, 2)
        assert result == [23, 1043]

    def test_prisma_column_info_query(self, protocol):
        sql = "SELECT info.column_name, format_type(x, y) FROM information_schema.columns WHERE namespace = ANY(?) AND table_name = ANY(?)"
        result = protocol.infer_parameter_oids_from_casts(sql, 2)
        assert result == [1009]

    def test_prisma_pg_class_query(self, protocol):
        sql = "SELECT * FROM pg_class JOIN pg_namespace ON true WHERE nspname = ANY(?)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1009]

    def test_prisma_pg_namespace_query(self, protocol):
        sql = "SELECT * FROM pg_namespace WHERE nspname = ANY(?)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1009]

    def test_fewer_casts_than_params_fills_with_unknown(self, protocol):
        sql = "SELECT CAST(? AS INTEGER), ?"
        result = protocol.infer_parameter_oids_from_casts(sql, 2)
        assert result[0] == 23
        assert result[1] == 705

    def test_truncates_to_param_count(self, protocol):
        sql = "SELECT CAST(? AS INTEGER), CAST(? AS BIGINT), CAST(? AS VARCHAR)"
        result = protocol.infer_parameter_oids_from_casts(sql, 2)
        assert len(result) == 2

    def test_cast_with_precision(self, protocol):
        sql = "SELECT CAST(? AS VARCHAR(100))"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1043]

    def test_cast_numeric_returns_1700(self, protocol):
        sql = "SELECT CAST(? AS NUMERIC)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1700]

    def test_cast_decimal_returns_1700(self, protocol):
        sql = "SELECT CAST(? AS DECIMAL)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1700]

    def test_cast_double_returns_701(self, protocol):
        sql = "SELECT CAST(? AS DOUBLE)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [701]

    def test_cast_float_returns_700(self, protocol):
        sql = "SELECT CAST(? AS FLOAT)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [700]

    def test_cast_date_returns_1082(self, protocol):
        sql = "SELECT CAST(? AS DATE)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1082]

    def test_cast_timestamp_returns_1114(self, protocol):
        sql = "SELECT CAST(? AS TIMESTAMP)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1114]

    def test_empty_sql_no_params(self, protocol):
        result = protocol.infer_parameter_oids_from_casts("SELECT 1", 0)
        assert result == []


# ===========================================================================
# _find_limit_offset_param_indexes
# ===========================================================================


class TestFindLimitOffsetParamIndexes:
    def test_limit_offset_pattern(self, protocol):
        sql = "SELECT * FROM t LIMIT ? OFFSET ?"
        limit_idxs, offset_idxs = protocol._find_limit_offset_param_indexes(sql)
        assert 1 in limit_idxs
        assert 2 in offset_idxs

    def test_limit_comma_offset_pattern(self, protocol):
        sql = "SELECT * FROM t LIMIT ?, ?"
        limit_idxs, offset_idxs = protocol._find_limit_offset_param_indexes(sql)
        assert len(limit_idxs) > 0 or len(offset_idxs) > 0

    def test_limit_only(self, protocol):
        sql = "SELECT * FROM t LIMIT ?"
        limit_idxs, offset_idxs = protocol._find_limit_offset_param_indexes(sql)
        assert 1 in limit_idxs
        assert len(offset_idxs) == 0

    def test_offset_only(self, protocol):
        sql = "SELECT * FROM t WHERE x=? OFFSET ?"
        limit_idxs, offset_idxs = protocol._find_limit_offset_param_indexes(sql)
        assert 2 in offset_idxs

    def test_no_limit_or_offset(self, protocol):
        sql = "SELECT * FROM t WHERE x = ?"
        limit_idxs, offset_idxs = protocol._find_limit_offset_param_indexes(sql)
        assert len(limit_idxs) == 0
        assert len(offset_idxs) == 0


# ===========================================================================
# _decode_binary_parameter edge cases
# ===========================================================================


class TestDecodeBinaryParameter:
    def test_int2_small_data(self, protocol):
        data = struct.pack("!h", 42)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=21)
        assert result == 42

    def test_int4_small_data(self, protocol):
        data = struct.pack("!i", 1000)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=23)
        assert result == 1000

    def test_int8_small_data(self, protocol):
        data = struct.pack("!q", 999999999)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=20)
        assert result == 999999999

    def test_float4_small_data(self, protocol):
        data = struct.pack("!f", 3.14)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=700)
        assert abs(result - 3.14) < 0.01

    def test_float8_small_data(self, protocol):
        data = struct.pack("!d", 2.718281828)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=701)
        assert abs(result - 2.718281828) < 1e-9

    def test_bool_true(self, protocol):
        data = b"\x01"
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=16)
        assert result == 1

    def test_bool_false(self, protocol):
        data = b"\x00"
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=16)
        assert result == 0

    def test_date_binary(self, protocol):
        """Date OID 1082 decoded as YYYY-MM-DD string."""
        # Days since 2000-01-01
        data = struct.pack("!i", 0)  # 2000-01-01
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=1082)
        assert result == "2000-01-01"

    def test_timestamp_binary(self, protocol):
        """Timestamp OID 1114 decoded as string."""
        data = struct.pack("!q", 0)  # 2000-01-01 00:00:00
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=1114)
        assert "2000-01-01" in result

    def test_array_empty(self, protocol):
        """Array with ndim=0 returns '[]'."""
        # ndim=0, has_null=0, element_oid=700
        data = struct.pack("!III", 0, 0, 700)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=0)
        assert result == "[]"

    def test_array_float4_elements(self, protocol):
        """1D float4 array parsed to vector string."""
        ndim = 1
        has_null = 0
        element_oid = 700  # float4
        dim_size = 3
        lower_bound = 1
        elements = [1.0, 2.0, 3.0]

        data = struct.pack("!III", ndim, has_null, element_oid)
        data += struct.pack("!II", dim_size, lower_bound)
        for e in elements:
            data += struct.pack("!I", 4)
            data += struct.pack("!f", e)

        result = protocol._decode_binary_parameter(data, 0, param_type_oid=0)
        assert result.startswith("[")
        assert result.endswith("]")

    def test_array_float8_elements(self, protocol):
        """1D float8 array."""
        data = struct.pack("!III", 1, 0, 701)
        data += struct.pack("!II", 2, 1)
        for e in [1.0, 2.0]:
            data += struct.pack("!I", 8)
            data += struct.pack("!d", e)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=0)
        assert "[" in result

    def test_array_int4_elements(self, protocol):
        """1D int4 array."""
        data = struct.pack("!III", 1, 0, 23)
        data += struct.pack("!II", 2, 1)
        for e in [10, 20]:
            data += struct.pack("!I", 4)
            data += struct.pack("!i", e)
        result = protocol._decode_binary_parameter(data, 0)
        assert "10" in result

    def test_array_int8_elements(self, protocol):
        """1D int8 array."""
        data = struct.pack("!III", 1, 0, 20)
        data += struct.pack("!II", 1, 1)
        data += struct.pack("!I", 8)
        data += struct.pack("!q", 12345)
        result = protocol._decode_binary_parameter(data, 0)
        assert "12345" in result

    def test_array_text_elements(self, protocol):
        """1D text array."""
        text = b"hello"
        data = struct.pack("!III", 1, 0, 25)  # text OID
        data += struct.pack("!II", 1, 1)
        data += struct.pack("!I", len(text))
        data += text
        result = protocol._decode_binary_parameter(data, 0)
        assert "hello" in result

    def test_array_null_element(self, protocol):
        """Array with NULL element."""
        data = struct.pack("!III", 1, 1, 25)
        data += struct.pack("!II", 1, 1)
        data += struct.pack("!I", 0xFFFFFFFF)  # NULL
        result = protocol._decode_binary_parameter(data, 0)
        assert "NULL" in result

    def test_1byte_fallback_no_oid(self, protocol):
        """1-byte data with no matching OID falls back to bool-like decode."""
        data = b"\x01"
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=0)
        assert result in (0, 1)

    def test_2byte_fallback_no_oid(self, protocol):
        data = struct.pack("!h", 7)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=0)
        assert result == 7

    def test_4byte_fallback_no_oid(self, protocol):
        data = struct.pack("!i", 42)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=0)
        assert result == 42

    def test_8byte_fallback_no_oid(self, protocol):
        data = struct.pack("!q", 100)
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=0)
        assert result == 100

    def test_decode_error_falls_back_to_utf8(self, protocol):
        """Decode error returns utf8 string fallback."""
        # Force error by passing corrupt data that cannot be parsed as array
        data = b"\xff\xff\xff\xff\xff\xff"  # 6 bytes, no matching OID
        result = protocol._decode_binary_parameter(data, 0, param_type_oid=0)
        # Should return a string (decoded or utf8)
        assert isinstance(result, (str, int))


# ===========================================================================
# _encode_binary_column_value
# ===========================================================================


class TestEncodeBinaryColumnValue:
    def test_int4(self, protocol):
        result = protocol._encode_binary_column_value(23, 42, 0)
        assert struct.unpack("!i", result)[0] == 42

    def test_int2(self, protocol):
        result = protocol._encode_binary_column_value(21, 7, 0)
        assert struct.unpack("!h", result)[0] == 7

    def test_int8(self, protocol):
        result = protocol._encode_binary_column_value(20, 999, 0)
        assert struct.unpack("!q", result)[0] == 999

    def test_float4(self, protocol):
        result = protocol._encode_binary_column_value(700, 1.5, 0)
        assert abs(struct.unpack("!f", result)[0] - 1.5) < 0.01

    def test_float8(self, protocol):
        result = protocol._encode_binary_column_value(701, 3.14, 0)
        assert abs(struct.unpack("!d", result)[0] - 3.14) < 1e-9

    def test_oid_26(self, protocol):
        result = protocol._encode_binary_column_value(26, 12345, 0)
        assert struct.unpack("!I", result)[0] == 12345

    def test_name_oid_19(self, protocol):
        result = protocol._encode_binary_column_value(19, "hello", 0)
        assert result == b"hello"

    def test_bool_oid_16(self, protocol):
        result = protocol._encode_binary_column_value(16, True, 0)
        assert struct.unpack("!?", result)[0] is True

    def test_date_oid_1082(self, protocol):
        result = protocol._encode_binary_column_value(1082, 0, 0)
        assert len(result) == 4

    def test_timestamp_from_string(self, protocol):
        result = protocol._encode_binary_column_value(1114, "2000-01-01 00:00:00", 0)
        assert len(result) == 8

    def test_timestamp_with_microseconds(self, protocol):
        result = protocol._encode_binary_column_value(1114, "2000-01-01 00:00:00.000000", 0)
        assert len(result) == 8

    def test_timestamp_datetime_object(self, protocol):
        import datetime
        dt = datetime.datetime(2023, 6, 15, 12, 0, 0)
        result = protocol._encode_binary_column_value(1114, dt, 0)
        assert len(result) == 8

    def test_unknown_oid_text_fallback(self, protocol):
        result = protocol._encode_binary_column_value(9999, "hello", 0)
        assert result == b"hello"

    def test_int4_encoding_error_fallback(self, protocol):
        """Out-of-range int falls back to text."""
        result = protocol._encode_binary_column_value(23, "not-an-int", 0)
        assert b"not-an-int" in result

    def test_timestamp_invalid_format_raises_and_fallback(self, protocol):
        """Invalid timestamp string falls back via exception."""
        # Should not raise — falls through to text fallback
        result = protocol._encode_binary_column_value(1114, "not-a-date", 0)
        # It raises ValueError internally but _encode_binary_column_value catches it
        assert isinstance(result, bytes)


# ===========================================================================
# Legacy COPY message handlers
# ===========================================================================


class TestLegacyCopyHandlers:
    @pytest.mark.asyncio
    async def test_handle_copy_data_message_not_in_copy_mode(self, protocol):
        """handle_copy_data_message when not in COPY mode sends fail."""
        with patch.object(protocol, "send_copy_fail", new_callable=AsyncMock) as mock_fail:
            await protocol.handle_copy_data_message(b"some,data")
        mock_fail.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_copy_data_message_in_copy_mode(self, protocol):
        """handle_copy_data_message buffers data correctly."""
        protocol.copy_mode = "copy_in"
        protocol.copy_data_buffer = []
        protocol.copy_buffer_size = 0
        protocol.copy_max_buffer_size = 10 * 1024 * 1024
        protocol.copy_batch_size = 1000
        await protocol.handle_copy_data_message(b"id,name\n1,alice\n")
        assert len(protocol.copy_data_buffer) == 1

    @pytest.mark.asyncio
    async def test_handle_copy_done_message_not_in_copy_mode(self, protocol):
        """handle_copy_done_message when not in COPY mode calls send_copy_fail."""
        with patch.object(protocol, "send_copy_fail", new_callable=AsyncMock) as mock_fail:
            await protocol.handle_copy_done_message(b"")
        mock_fail.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_copy_fail_message(self, protocol):
        """handle_copy_fail_message cleans up state and sends error."""
        protocol.copy_mode = "copy_in"
        protocol.copy_data_buffer = [b"some data"]
        protocol.copy_buffer_size = 9
        await protocol.handle_copy_fail_message(b"User requested abort")
        assert protocol.copy_mode is None
        assert protocol.copy_data_buffer == []
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_handle_copy_fail_message_empty_body(self, protocol):
        """handle_copy_fail_message with empty body uses default message."""
        protocol.copy_mode = "copy_in"
        protocol.copy_data_buffer = []
        protocol.copy_buffer_size = 0
        await protocol.handle_copy_fail_message(b"")
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_send_copy_in_response(self, protocol):
        """send_copy_in_response sends CopyInResponse message."""
        protocol.copy_columns = None
        await protocol.send_copy_in_response()
        written = collected_bytes(protocol.writer)
        assert MSG_COPY_IN_RESPONSE in written

    @pytest.mark.asyncio
    async def test_send_copy_in_response_with_columns(self, protocol):
        """send_copy_in_response with specified columns."""
        protocol.copy_columns = ["id", "name", "value"]
        await protocol.send_copy_in_response()
        written = collected_bytes(protocol.writer)
        assert MSG_COPY_IN_RESPONSE in written

    @pytest.mark.asyncio
    async def test_send_copy_out_response(self, protocol):
        """send_copy_out_response sends CopyOutResponse message."""
        await protocol.send_copy_out_response()
        written = collected_bytes(protocol.writer)
        assert MSG_COPY_OUT_RESPONSE in written

    @pytest.mark.asyncio
    async def test_send_copy_data(self, protocol):
        """send_copy_data sends CopyData message."""
        await protocol.send_copy_data(b"1,alice\n")
        written = collected_bytes(protocol.writer)
        assert MSG_COPY_DATA in written

    @pytest.mark.asyncio
    async def test_send_copy_done(self, protocol):
        """send_copy_done sends CopyDone message."""
        await protocol.send_copy_done()
        written = collected_bytes(protocol.writer)
        assert MSG_COPY_DONE in written

    @pytest.mark.asyncio
    async def test_send_copy_fail_msg(self, protocol):
        """send_copy_fail sends CopyFail message."""
        await protocol.send_copy_fail("something went wrong")
        written = collected_bytes(protocol.writer)
        assert MSG_COPY_FAIL in written

    @pytest.mark.asyncio
    async def test_send_copy_complete_response(self, protocol):
        """send_copy_complete_response sends CommandComplete + ReadyForQuery."""
        await protocol.send_copy_complete_response(42)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY in written


# ===========================================================================
# handle_copy_from_stdin (legacy path)
# ===========================================================================


class TestHandleCopyFromStdin:
    @pytest.mark.asyncio
    async def test_parses_table_and_columns(self, protocol):
        """handle_copy_from_stdin parses COPY command and sets copy state."""
        with patch.object(protocol, "send_copy_in_response", new_callable=AsyncMock):
            await protocol.handle_copy_from_stdin("COPY mytable (col1, col2) FROM STDIN")
        assert protocol.copy_table == "mytable"
        assert protocol.copy_columns == ["col1", "col2"]
        assert protocol.copy_mode == "copy_in"

    @pytest.mark.asyncio
    async def test_fallback_table_name_when_no_match(self, protocol):
        """Falls back to benchmark_vectors when parse fails."""
        with patch.object(protocol, "send_copy_in_response", new_callable=AsyncMock):
            await protocol.handle_copy_from_stdin("COPY garbage syntax")
        assert protocol.copy_table == "benchmark_vectors"

    @pytest.mark.asyncio
    async def test_no_columns_specified(self, protocol):
        """COPY without column list sets columns to None."""
        with patch.object(protocol, "send_copy_in_response", new_callable=AsyncMock):
            await protocol.handle_copy_from_stdin("COPY orders FROM STDIN")
        assert protocol.copy_table == "orders"
        assert protocol.copy_columns is None


# ===========================================================================
# handle_copy_to_stdout (legacy path)
# ===========================================================================


class TestHandleCopyToStdout:
    @pytest.mark.asyncio
    async def test_sends_data_and_done(self, protocol):
        """handle_copy_to_stdout sends sample data and completes."""
        with (
            patch.object(protocol, "send_copy_out_response", new_callable=AsyncMock),
            patch.object(protocol, "send_copy_data", new_callable=AsyncMock) as mock_data,
            patch.object(protocol, "send_copy_done", new_callable=AsyncMock) as mock_done,
        ):
            await protocol.handle_copy_to_stdout("COPY test TO STDOUT")
        assert mock_data.call_count > 0
        mock_done.assert_called_once()


# ===========================================================================
# flush_batch
# ===========================================================================


class TestFlushBatch:
    @pytest.mark.asyncio
    async def test_flush_batch_empty_is_noop(self, protocol):
        """flush_batch with no batched params does nothing."""
        protocol.batch_params = []
        await protocol.flush_batch()
        protocol.iris_executor.execute_many.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_batch_executes_and_clears(self, protocol):
        """flush_batch calls execute_many and clears state."""
        protocol.batch_params = [[1, "a"], [2, "b"]]
        protocol.batch_sql = "INSERT INTO t VALUES (?, ?)"
        protocol.batch_statement_name = "s1"
        protocol.batch_portal_name = "p1"

        await protocol.flush_batch()

        protocol.iris_executor.execute_many.assert_called_once()
        assert protocol.batch_params == []
        assert protocol.batch_sql is None

    @pytest.mark.asyncio
    async def test_flush_batch_no_sql_is_noop(self, protocol):
        """flush_batch with params but no sql skips execute_many."""
        protocol.batch_params = [[1]]
        protocol.batch_sql = None

        await protocol.flush_batch()
        protocol.iris_executor.execute_many.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_batch_execute_error_sends_error_response(self, protocol):
        """flush_batch handles execute_many failure gracefully."""
        protocol.batch_params = [[1]]
        protocol.batch_sql = "INSERT INTO t VALUES (?)"
        protocol.iris_executor.execute_many.side_effect = Exception("db error")

        await protocol.flush_batch()
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written


# ===========================================================================
# handle_sync_message
# ===========================================================================


class TestHandleSyncMessage:
    @pytest.mark.asyncio
    async def test_sync_flushes_batch_and_sends_ready(self, protocol):
        """Sync with pending batch flushes and sends ReadyForQuery."""
        protocol.batch_params = [[1]]
        protocol.batch_sql = "INSERT INTO t VALUES (?)"

        await protocol.handle_sync_message(b"")
        protocol.iris_executor.execute_many.assert_called_once()
        written = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in written

    @pytest.mark.asyncio
    async def test_sync_without_batch_sends_ready(self, protocol):
        """Sync with no pending batch sends ReadyForQuery."""
        protocol.batch_params = []
        await protocol.handle_sync_message(b"")
        written = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in written

    @pytest.mark.asyncio
    async def test_sync_exception_handled(self, protocol):
        """Sync exception does not propagate."""
        with patch.object(protocol, "send_ready_for_query", side_effect=Exception("write error")):
            # Should not raise
            await protocol.handle_sync_message(b"")


# ===========================================================================
# handle_close_message
# ===========================================================================


class TestHandleCloseMessage:
    @pytest.mark.asyncio
    async def test_close_statement(self, protocol):
        """Close statement removes it from prepared_statements."""
        protocol.prepared_statements["s1"] = {"query": "SELECT 1", "param_types": []}
        body = b"S" + b"s1\x00"
        await protocol.handle_close_message(body)
        assert "s1" not in protocol.prepared_statements
        written = collected_bytes(protocol.writer)
        assert MSG_CLOSE_COMPLETE in written

    @pytest.mark.asyncio
    async def test_close_portal(self, protocol):
        """Close portal removes it from portals."""
        protocol.portals["p1"] = {"statement": "s1", "params": []}
        body = b"P" + b"p1\x00"
        await protocol.handle_close_message(body)
        assert "p1" not in protocol.portals
        written = collected_bytes(protocol.writer)
        assert MSG_CLOSE_COMPLETE in written

    @pytest.mark.asyncio
    async def test_close_nonexistent_statement_still_sends_complete(self, protocol):
        """Closing a nonexistent statement still sends CloseComplete."""
        body = b"S" + b"nonexistent\x00"
        await protocol.handle_close_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_CLOSE_COMPLETE in written

    @pytest.mark.asyncio
    async def test_close_invalid_type_sends_error(self, protocol):
        """Invalid close type sends error response."""
        body = b"X" + b"name\x00"
        await protocol.handle_close_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_close_too_short_sends_error(self, protocol):
        """Too-short body sends error response."""
        body = b"S"  # only 1 byte, need at least 2
        await protocol.handle_close_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written


# ===========================================================================
# handle_parse_message — extended paths
# ===========================================================================


class TestHandleParseMessageExtended:
    def _make_parse_body(self, name: str, query: str, params: list[int] = None) -> bytes:
        params = params or []
        body = name.encode() + b"\x00"
        body += query.encode() + b"\x00"
        body += struct.pack("!H", len(params))
        for p in params:
            body += struct.pack("!I", p)
        return body

    @pytest.mark.asyncio
    async def test_empty_query_stores_marker(self, protocol):
        """Empty query stores is_empty_query marker."""
        body = self._make_parse_body("s1", "")
        await protocol.handle_parse_message(body)
        assert "s1" in protocol.prepared_statements
        assert protocol.prepared_statements["s1"]["translation_metadata"]["is_empty_query"]

    @pytest.mark.asyncio
    async def test_set_command_stores_marker(self, protocol):
        """SET command in Parse stores is_set_command marker."""
        body = self._make_parse_body("s_set", "SET search_path = public")
        await protocol.handle_parse_message(body)
        assert protocol.prepared_statements["s_set"]["translation_metadata"]["is_set_command"]

    @pytest.mark.asyncio
    async def test_begin_command_stores_marker(self, protocol):
        """BEGIN command stores is_transaction_command marker."""
        body = self._make_parse_body("s_begin", "BEGIN")
        await protocol.handle_parse_message(body)
        assert protocol.prepared_statements["s_begin"]["translation_metadata"]["is_transaction_command"]
        assert protocol.prepared_statements["s_begin"]["translation_metadata"]["transaction_type"] == "BEGIN"

    @pytest.mark.asyncio
    async def test_commit_command_stores_marker(self, protocol):
        body = self._make_parse_body("s_commit", "COMMIT")
        await protocol.handle_parse_message(body)
        assert protocol.prepared_statements["s_commit"]["translation_metadata"]["transaction_type"] == "COMMIT"

    @pytest.mark.asyncio
    async def test_rollback_command_stores_marker(self, protocol):
        body = self._make_parse_body("s_rb", "ROLLBACK")
        await protocol.handle_parse_message(body)
        assert protocol.prepared_statements["s_rb"]["translation_metadata"]["transaction_type"] == "ROLLBACK"

    @pytest.mark.asyncio
    async def test_rollback_work_variant(self, protocol):
        body = self._make_parse_body("s_rbw", "ROLLBACK WORK")
        await protocol.handle_parse_message(body)
        assert protocol.prepared_statements["s_rbw"]["translation_metadata"]["transaction_type"] == "ROLLBACK"

    @pytest.mark.asyncio
    async def test_commit_work_variant(self, protocol):
        body = self._make_parse_body("s_cw", "COMMIT WORK")
        await protocol.handle_parse_message(body)
        assert protocol.prepared_statements["s_cw"]["translation_metadata"]["transaction_type"] == "COMMIT"

    @pytest.mark.asyncio
    async def test_end_as_commit(self, protocol):
        body = self._make_parse_body("s_end", "END")
        await protocol.handle_parse_message(body)
        assert protocol.prepared_statements["s_end"]["translation_metadata"]["transaction_type"] == "COMMIT"

    @pytest.mark.asyncio
    async def test_start_transaction_variant(self, protocol):
        body = self._make_parse_body("s_st", "START TRANSACTION")
        await protocol.handle_parse_message(body)
        assert protocol.prepared_statements["s_st"]["translation_metadata"]["transaction_type"] == "BEGIN"

    @pytest.mark.asyncio
    async def test_normal_query_with_params(self, protocol):
        """Normal SELECT query with param types stored."""
        pipeline_result = MagicMock()
        pipeline_result.was_skipped = False
        pipeline_result.skip_reason = None
        pipeline_result.command_tag = "SELECT"
        pipeline_result.performance_stats = MagicMock()
        pipeline_result.performance_stats.translation_time_ms = 0.1
        pipeline_result.performance_stats.cache_hit = False

        protocol.iris_executor.sql_pipeline.process = MagicMock(
            return_value=("SELECT ? FROM t", {}, pipeline_result)
        )
        body = self._make_parse_body("s_q", "SELECT $1 FROM t", [23])
        await protocol.handle_parse_message(body)
        assert "s_q" in protocol.prepared_statements

    @pytest.mark.asyncio
    async def test_missing_statement_name_terminator(self, protocol):
        """Body with no null terminator for statement name sends error."""
        body = b"no_terminator_here"
        await protocol.handle_parse_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written


# ===========================================================================
# handle_execute_message — extended paths
# ===========================================================================


class TestHandleExecuteMessageExtended:
    def _setup_portal(self, protocol, portal_name, stmt_name, query, metadata=None, params=None):
        protocol.prepared_statements[stmt_name] = {
            "original_query": query,
            "translated_query": query,
            "param_types": [],
            "translation_metadata": metadata or {},
            "needs_row_description": False,
        }
        protocol.portals[portal_name] = {
            "statement": stmt_name,
            "params": params or [],
            "result_formats": [],
            "needs_row_description": False,
        }

    def _make_execute_body(self, portal_name: str, max_rows: int = 0) -> bytes:
        return portal_name.encode() + b"\x00" + struct.pack("!I", max_rows)

    @pytest.mark.asyncio
    async def test_empty_query_sends_command_complete(self, protocol):
        self._setup_portal(protocol, "p1", "s1", "", {"is_empty_query": True})
        body = self._make_execute_body("p1")
        await protocol.handle_execute_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_set_command_marker_sends_set_response(self, protocol):
        self._setup_portal(protocol, "p_set", "s_set", "SET x = 1", {"is_set_command": True})
        body = self._make_execute_body("p_set")
        await protocol.handle_execute_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_begin_transaction_marker(self, protocol):
        self._setup_portal(
            protocol, "p_b", "s_b", "BEGIN",
            {"is_transaction_command": True, "transaction_type": "BEGIN"}
        )
        body = self._make_execute_body("p_b")
        await protocol.handle_execute_message(body)
        protocol.iris_executor.begin_transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_transaction_marker(self, protocol):
        self._setup_portal(
            protocol, "p_c", "s_c", "COMMIT",
            {"is_transaction_command": True, "transaction_type": "COMMIT"}
        )
        body = self._make_execute_body("p_c")
        await protocol.handle_execute_message(body)
        protocol.iris_executor.commit_transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_transaction_marker(self, protocol):
        self._setup_portal(
            protocol, "p_r", "s_r", "ROLLBACK",
            {"is_transaction_command": True, "transaction_type": "ROLLBACK"}
        )
        body = self._make_execute_body("p_r")
        await protocol.handle_execute_message(body)
        protocol.iris_executor.rollback_transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_dml_without_returning_fast_path(self, protocol):
        """DML without RETURNING is buffered (fast-batch path)."""
        protocol.iris_executor.sql_parser.is_dml_statement.return_value = True
        protocol.iris_executor.sql_parser.has_returning_clause.return_value = False
        self._setup_portal(protocol, "p_ins", "s_ins", "INSERT INTO t VALUES (?)", params=[1])
        body = self._make_execute_body("p_ins")
        await protocol.handle_execute_message(body)
        assert len(protocol.batch_params) == 1
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_portal_not_found_sends_error(self, protocol):
        body = self._make_execute_body("nonexistent_portal")
        await protocol.handle_execute_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_query_execution_failure_sends_error(self, protocol):
        """Failed execution sends error response."""
        protocol.iris_executor.execute_query.return_value = {
            "success": False,
            "error": "Syntax error",
        }
        self._setup_portal(protocol, "p_err", "s_err", "SELECT bad")
        body = self._make_execute_body("p_err")
        await protocol.handle_execute_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_set_command_detected_by_query_content(self, protocol):
        """SET command intercepted by query content even without marker."""
        self._setup_portal(protocol, "p_s2", "s_s2", "SET enable_seqscan = ON", {})
        body = self._make_execute_body("p_s2")
        await protocol.handle_execute_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written


# ===========================================================================
# handle_query_message paths
# ===========================================================================


class TestHandleQueryMessage:
    @pytest.mark.asyncio
    async def test_begin_transaction(self, protocol):
        """BEGIN command in Simple Query starts transaction."""
        body = b"BEGIN\x00"
        await protocol.handle_query_message(body)
        protocol.iris_executor.begin_transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_commit_transaction(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        body = b"COMMIT\x00"
        await protocol.handle_query_message(body)
        protocol.iris_executor.commit_transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_transaction(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        body = b"ROLLBACK\x00"
        await protocol.handle_query_message(body)
        protocol.iris_executor.rollback_transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_deallocate_command(self, protocol):
        body = b"DEALLOCATE s1\x00"
        await protocol.handle_query_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_unlisten_command(self, protocol):
        body = b"UNLISTEN *\x00"
        await protocol.handle_query_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_set_command_via_query(self, protocol):
        body = b"SET timezone = 'UTC'\x00"
        await protocol.handle_query_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_reset_command_via_query(self, protocol):
        body = b"RESET ALL\x00"
        await protocol.handle_query_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_if_not_exists_duplicate_suppressed(self, protocol):
        """Duplicate-object error for IF NOT EXISTS queries returns fake success."""
        protocol.iris_executor.execute_query.return_value = {
            "success": False,
            "error": "Table already exists",
        }
        with (
            patch("iris_pgwire.protocol.VectorQueryOptimizer.sql_has_if_not_exists", return_value=True),
            patch("iris_pgwire.protocol.VectorQueryOptimizer.is_duplicate_object_error", return_value=True),
        ):
            body = b"CREATE TABLE IF NOT EXISTS t (id INT)\x00"
            await protocol.handle_query_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_query_exception_sends_error_and_ready(self, protocol):
        """Exception in handle_query_message sends error + ReadyForQuery."""
        protocol.iris_executor.execute_query.side_effect = RuntimeError("kaboom")
        body = b"SELECT 1\x00"
        await protocol.handle_query_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written
        assert MSG_READY_FOR_QUERY in written

    @pytest.mark.asyncio
    async def test_multiple_statements_all_processed(self, protocol):
        """Multiple semicolon-separated statements are all executed."""
        with patch.object(protocol, "_handle_single_statement", new_callable=AsyncMock) as mock_stmt:
            body = b"SELECT 1; SELECT 2\x00"
            await protocol.handle_query_message(body)
        assert mock_stmt.call_count == 2


# ===========================================================================
# _maybe_handle_* helpers
# ===========================================================================


class TestMaybeHandleHelpers:
    @pytest.mark.asyncio
    async def test_start_transaction_variant(self, protocol):
        result = await protocol._maybe_handle_transaction_command("START TRANSACTION", True)
        assert result is True

    @pytest.mark.asyncio
    async def test_end_as_commit(self, protocol):
        result = await protocol._maybe_handle_transaction_command("END", True)
        assert result is True
        protocol.iris_executor.commit_transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_transaction_returns_false(self, protocol):
        result = await protocol._maybe_handle_transaction_command("SELECT 1", True)
        assert result is False

    @pytest.mark.asyncio
    async def test_deallocate_all(self, protocol):
        result = await protocol._maybe_handle_deallocate_command("DEALLOCATE ALL", True)
        assert result is True

    @pytest.mark.asyncio
    async def test_non_deallocate_returns_false(self, protocol):
        result = await protocol._maybe_handle_deallocate_command("SELECT 1", True)
        assert result is False

    @pytest.mark.asyncio
    async def test_reset_command_handled(self, protocol):
        result = await protocol._maybe_handle_set_or_reset_command("RESET ALL", True)
        assert result is True

    @pytest.mark.asyncio
    async def test_close_all_pg_command(self, protocol):
        result = await protocol._maybe_handle_postgresql_command("CLOSE ALL", True)
        assert result is True

    @pytest.mark.asyncio
    async def test_unlisten_pg_command(self, protocol):
        result = await protocol._maybe_handle_postgresql_command("UNLISTEN *", True)
        assert result is True

    @pytest.mark.asyncio
    async def test_non_pg_command_returns_false(self, protocol):
        result = await protocol._maybe_handle_postgresql_command("SELECT 1", True)
        assert result is False


# ===========================================================================
# send_query_result with rows
# ===========================================================================


class TestSendQueryResultWithRows:
    @pytest.mark.asyncio
    async def test_select_with_rows(self, protocol):
        """send_query_result sends RowDescription + DataRows + CommandComplete."""
        result = {
            "success": True,
            "rows": [[1, "alice"], [2, "bob"]],
            "columns": [
                {"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1},
                {"name": "name", "type_oid": 25, "type_size": -1, "type_modifier": -1},
            ],
            "row_count": 2,
            "command_tag": "SELECT",
        }
        await protocol.send_query_result(result, send_ready=True)
        written = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in written
        assert MSG_DATA_ROW in written
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY in written

    @pytest.mark.asyncio
    async def test_insert_no_rows(self, protocol):
        """INSERT with no rows sends CommandComplete (RowDescription only for SELECT-like)."""
        result = {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 1,
            "command_tag": "INSERT",
        }
        await protocol.send_query_result(result, send_ready=True)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written
        # MSG_ROW_DESCRIPTION ('T') byte also appears in the CommandComplete tag "INSERT 1\x00"
        # so we can only verify CommandComplete is present without checking for absence of T

    @pytest.mark.asyncio
    async def test_send_ready_false_no_ready_for_query(self, protocol):
        """send_ready=False omits ReadyForQuery."""
        result = {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "command_tag": "SELECT",
        }
        await protocol.send_query_result(result, send_ready=False)
        written = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY not in written


# ===========================================================================
# send_transaction_response
# ===========================================================================


class TestSendTransactionResponse:
    @pytest.mark.asyncio
    async def test_begin_updates_status(self, protocol):
        await protocol.send_transaction_response("BEGIN", send_ready=True)
        assert protocol.transaction_status == STATUS_IN_TRANSACTION
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_commit_updates_status(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        await protocol.send_transaction_response("COMMIT", send_ready=True)
        assert protocol.transaction_status == STATUS_IDLE

    @pytest.mark.asyncio
    async def test_rollback_updates_status(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        await protocol.send_transaction_response("ROLLBACK", send_ready=True)
        assert protocol.transaction_status == STATUS_IDLE

    @pytest.mark.asyncio
    async def test_no_ready_when_send_ready_false(self, protocol):
        await protocol.send_transaction_response("BEGIN", send_ready=False)
        written = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY not in written


# ===========================================================================
# _build_metadata_dummy_params
# ===========================================================================


class TestBuildMetadataDummyParams:
    def test_zero_params(self, protocol):
        result = protocol._build_metadata_dummy_params("SELECT 1", 0)
        assert result == []

    def test_limit_offset_gets_dummy_values(self, protocol):
        sql = "SELECT * FROM t LIMIT ? OFFSET ?"
        result = protocol._build_metadata_dummy_params(sql, 2)
        assert len(result) == 2
        # LIMIT gets 1, OFFSET gets 0
        assert 1 in result
        assert 0 in result

    def test_plain_params_all_none(self, protocol):
        sql = "SELECT * FROM t WHERE x = ? AND y = ?"
        result = protocol._build_metadata_dummy_params(sql, 2)
        assert result == [None, None]


# ===========================================================================
# translate_sql
# ===========================================================================


class TestTranslateSql:
    @pytest.mark.asyncio
    async def test_translation_disabled(self, protocol):
        """When enable_translation=False, returns original SQL."""
        protocol.enable_translation = False
        result = await protocol.translate_sql("SELECT 1")
        assert result["translated_sql"] == "SELECT 1"
        assert result["translation_used"] is False

    @pytest.mark.asyncio
    async def test_translation_success(self, protocol):
        """Successful translation returns translated SQL."""
        pipeline_result = MagicMock()
        pipeline_result.was_skipped = False
        pipeline_result.skip_reason = None
        pipeline_result.command_tag = "SELECT"
        pipeline_result.performance_stats = MagicMock()
        pipeline_result.performance_stats.translation_time_ms = 0.5
        pipeline_result.performance_stats.cache_hit = True

        protocol.iris_executor.sql_pipeline.process = MagicMock(
            return_value=("SELECT 1 FROM DUAL", {}, pipeline_result)
        )
        result = await protocol.translate_sql("SELECT 1")
        assert result["success"] is True
        assert result["translated_sql"] == "SELECT 1 FROM DUAL"

    @pytest.mark.asyncio
    async def test_translation_exception_falls_back(self, protocol):
        """Exception in pipeline returns original SQL with success=False."""
        protocol.iris_executor.sql_pipeline.process = MagicMock(
            side_effect=Exception("pipeline error")
        )
        result = await protocol.translate_sql("SELECT bad$syntax")
        assert result["success"] is False
        assert result["translated_sql"] == "SELECT bad$syntax"


# ===========================================================================
# send_postgresql_command_response
# ===========================================================================


class TestSendPostgresqlCommandResponse:
    @pytest.mark.asyncio
    async def test_unlisten_response(self, protocol):
        await protocol.send_postgresql_command_response("UNLISTEN *", send_ready=True)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY in written

    @pytest.mark.asyncio
    async def test_close_all_response(self, protocol):
        await protocol.send_postgresql_command_response("CLOSE ALL", send_ready=False)
        written = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY not in written


# ===========================================================================
# _determine_row_description_format_code
# ===========================================================================


class TestDetermineRowDescFormatCode:
    def test_empty_formats_returns_0(self, protocol):
        assert protocol._determine_row_description_format_code([], 0) == 0

    def test_single_format_applies_to_all(self, protocol):
        assert protocol._determine_row_description_format_code([1], 5) == 1

    def test_per_column_format(self, protocol):
        assert protocol._determine_row_description_format_code([0, 1, 0], 1) == 1

    def test_out_of_range_returns_0(self, protocol):
        assert protocol._determine_row_description_format_code([1, 1], 5) == 0


# ===========================================================================
# _get_data_row_format_code
# ===========================================================================


class TestGetDataRowFormatCode:
    def test_no_formats_returns_0(self, protocol):
        protocol._current_result_formats = []
        assert protocol._get_data_row_format_code(0) == 0

    def test_single_format_applies_all(self, protocol):
        protocol._current_result_formats = [1]
        assert protocol._get_data_row_format_code(3) == 1

    def test_per_column(self, protocol):
        protocol._current_result_formats = [0, 1, 0]
        assert protocol._get_data_row_format_code(1) == 1

    def test_out_of_range_returns_0(self, protocol):
        protocol._current_result_formats = [1, 1]
        assert protocol._get_data_row_format_code(10) == 0


# ===========================================================================
# _format_text_value edge cases
# ===========================================================================


class TestFormatTextValueEdgeCases:
    def test_bool_string_true(self, protocol):
        assert protocol._format_text_value("true", 16) == "t"

    def test_bool_string_TRUE(self, protocol):
        assert protocol._format_text_value("TRUE", 16) == "t"

    def test_bool_string_false(self, protocol):
        assert protocol._format_text_value("false", 16) == "f"

    def test_bool_string_FALSE(self, protocol):
        assert protocol._format_text_value("FALSE", 16) == "f"

    def test_bool_string_t(self, protocol):
        assert protocol._format_text_value("t", 16) == "t"

    def test_bool_string_f(self, protocol):
        assert protocol._format_text_value("f", 16) == "f"

    def test_bool_int_0(self, protocol):
        assert protocol._format_text_value(0, 16) == "f"

    def test_bool_falsy_value(self, protocol):
        assert protocol._format_text_value(None, 16) == "f"

    def test_non_bool_oid_returns_str(self, protocol):
        assert protocol._format_text_value(42, 23) == "42"

    def test_non_bool_string(self, protocol):
        assert protocol._format_text_value("hello", 25) == "hello"


# ===========================================================================
# send_simple_query_response (legacy)
# ===========================================================================


class TestSendSimpleQueryResponse:
    @pytest.mark.asyncio
    async def test_sends_row_desc_data_row_and_ready(self, protocol):
        await protocol.send_simple_query_response()
        written = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in written
        assert MSG_DATA_ROW in written
        assert MSG_COMMAND_COMPLETE in written
        assert MSG_READY_FOR_QUERY in written


# ===========================================================================
# _convert_postgres_to_iris_syntax (coverage)
# ===========================================================================


class TestConvertPostgresToIrisSyntax:
    def test_passthrough(self, protocol):
        sql = "SELECT * FROM t WHERE x = 1"
        assert protocol._convert_postgres_to_iris_syntax(sql) == sql


# ===========================================================================
# process_copy_batch
# ===========================================================================


class TestProcessCopyBatch:
    @pytest.mark.asyncio
    async def test_empty_buffer_is_noop(self, protocol):
        """process_copy_batch with empty buffer does nothing."""
        protocol.copy_data_buffer = []
        await protocol.process_copy_batch()  # Should not raise

    @pytest.mark.asyncio
    async def test_clears_buffer_after_process(self, protocol):
        """process_copy_batch clears buffer after processing."""
        protocol.copy_data_buffer = [b"1,alice\n"]
        protocol.copy_buffer_size = 8
        protocol.copy_table = "test_table"
        protocol.copy_columns = None

        protocol.iris_executor.execute_query.return_value = {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 1,
            "command_tag": "INSERT",
        }

        import tempfile, os
        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            mock_file = MagicMock()
            mock_file.__enter__ = MagicMock(return_value=mock_file)
            mock_file.__exit__ = MagicMock(return_value=False)
            mock_file.name = "/tmp/test.csv"
            mock_tmp.return_value = mock_file
            with patch("os.unlink"):
                await protocol.process_copy_batch()

        assert protocol.copy_data_buffer == []
        assert protocol.copy_buffer_size == 0


# ===========================================================================
# handle_describe_message — error paths
# ===========================================================================


class TestHandleDescribeErrors:
    @pytest.mark.asyncio
    async def test_describe_nonexistent_statement_sends_error(self, protocol):
        body = b"Sno_such_stmt\x00"
        await protocol.handle_describe_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_describe_nonexistent_portal_sends_error(self, protocol):
        body = b"Pno_such_portal\x00"
        await protocol.handle_describe_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_describe_invalid_type_sends_error(self, protocol):
        body = b"Xsome_name\x00"
        await protocol.handle_describe_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_describe_too_short_sends_error(self, protocol):
        body = b"S"  # too short
        await protocol.handle_describe_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_describe_statement_non_select_sends_no_data(self, protocol):
        """Non-SELECT statement in Describe sends NoData."""
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan
        protocol.prepared_statements["s_ins"] = {
            "original_query": "INSERT INTO t VALUES (?)",
            "translated_query": "INSERT INTO t VALUES (?)",
            "param_types": [23],
            "translation_metadata": {},
        }
        protocol.iris_executor.sql_parser.is_select_statement.return_value = False
        protocol.iris_executor.sql_parser.is_show_statement.return_value = False

        with patch.object(ReturningPlan, "from_sql", return_value=MagicMock(has_returning=False)):
            body = b"Ss_ins\x00"
            await protocol.handle_describe_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_NO_DATA in written

    @pytest.mark.asyncio
    async def test_describe_portal_dml_no_returning(self, protocol):
        """DML portal without RETURNING sends NoData."""
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan
        protocol.prepared_statements["s_d"] = {
            "original_query": "DELETE FROM t WHERE id = ?",
            "translated_query": "DELETE FROM t WHERE id = ?",
            "param_types": [],
            "translation_metadata": {},
        }
        protocol.portals["p_d"] = {
            "statement": "s_d",
            "params": [],
            "result_formats": [],
        }
        protocol.iris_executor.sql_parser.is_dml_statement.return_value = True
        protocol.iris_executor.sql_parser.is_select_statement.return_value = False
        protocol.iris_executor.sql_parser.is_show_statement.return_value = False

        with patch.object(ReturningPlan, "from_sql", return_value=MagicMock(has_returning=False)):
            body = b"Pp_d\x00"
            await protocol.handle_describe_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_NO_DATA in written


# ===========================================================================
# handle_bind_message — error paths
# ===========================================================================


class TestHandleBindErrors:
    @pytest.mark.asyncio
    async def test_bind_nonexistent_statement_sends_error(self, protocol):
        """Bind to nonexistent statement sends error."""
        body = b"portal1\x00no_such_stmt\x00" + struct.pack("!H", 0) + struct.pack("!H", 0) + struct.pack("!H", 0)
        await protocol.handle_bind_message(body)
        written = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in written

    @pytest.mark.asyncio
    async def test_bind_with_null_param(self, protocol):
        """Bind with NULL parameter (0xFFFFFFFF length) stores None."""
        protocol.prepared_statements["s_null"] = {
            "original_query": "SELECT ?",
            "translated_query": "SELECT ?",
            "param_types": [25],
            "translation_metadata": {},
            "needs_row_description": False,
        }
        body = (
            b"p_null\x00"  # portal name
            + b"s_null\x00"  # statement name
            + struct.pack("!H", 0)  # 0 format codes
            + struct.pack("!H", 1)  # 1 param
            + struct.pack("!I", 0xFFFFFFFF)  # NULL param
            + struct.pack("!H", 0)  # 0 result formats
        )
        await protocol.handle_bind_message(body)
        assert "p_null" in protocol.portals
        assert protocol.portals["p_null"]["params"] == [None]
        written = collected_bytes(protocol.writer)
        assert MSG_BIND_COMPLETE in written

    @pytest.mark.asyncio
    async def test_bind_with_binary_param(self, protocol):
        """Bind with binary-format parameter decodes correctly."""
        protocol.prepared_statements["s_bin"] = {
            "original_query": "SELECT ?",
            "translated_query": "SELECT ?",
            "param_types": [23],
            "translation_metadata": {},
            "needs_row_description": False,
        }
        int_data = struct.pack("!i", 42)
        body = (
            b"p_bin\x00"
            + b"s_bin\x00"
            + struct.pack("!H", 1)  # 1 format code
            + struct.pack("!H", 1)  # binary
            + struct.pack("!H", 1)  # 1 param
            + struct.pack("!I", 4)  # 4 bytes
            + int_data
            + struct.pack("!H", 0)  # 0 result formats
        )
        await protocol.handle_bind_message(body)
        assert "p_bin" in protocol.portals
        assert protocol.portals["p_bin"]["params"] == [42]


# ===========================================================================
# handle_flush_message
# ===========================================================================


class TestHandleFlushMessage:
    @pytest.mark.asyncio
    async def test_flush_drains_writer(self, protocol):
        await protocol.handle_flush_message(b"")
        protocol.writer.drain.assert_called()

    @pytest.mark.asyncio
    async def test_flush_exception_handled(self, protocol):
        protocol.writer.drain.side_effect = Exception("drain error")
        # Should not raise
        await protocol.handle_flush_message(b"")


# ===========================================================================
# Constructor auth bridge unavailable path
# ===========================================================================


class TestConstructorAuthBridge:
    def test_auth_bridge_always_has_flag(self):
        """auth_bridge_available attribute always exists on protocol."""
        p = make_protocol()
        assert hasattr(p, "auth_bridge_available")
        assert isinstance(p.auth_bridge_available, bool)

    def test_auth_bridge_available_or_unavailable(self):
        """Protocol sets auth_bridge_available based on import success."""
        p = make_protocol()
        # If import succeeds (normal), it will be True
        # We just verify the attribute is consistent
        if p.auth_bridge_available:
            assert hasattr(p, "auth_selector")
            assert hasattr(p, "oauth_bridge")
            assert hasattr(p, "wallet_credentials")
