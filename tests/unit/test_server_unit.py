"""
Unit tests for server.py

The module performs importlib.reload() at module level, so tests mock
BackendSelector and related imports before importing server.
All tests use mocked IRIS dependencies — no live connection required.
"""

from __future__ import annotations

import asyncio
import os
import ssl
import sys
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Helper: build a minimal fake executor satisfying the Executor protocol
# ---------------------------------------------------------------------------

def _make_executor():
    ex = MagicMock()
    ex.backend_type = "embedded"
    ex.sql_pipeline = MagicMock()
    ex.sql_translator = MagicMock()
    ex.sql_parser = MagicMock()
    ex.test_connection = AsyncMock()
    ex.execute_query = AsyncMock()
    ex.set_session_namespace = MagicMock()
    return ex


def _make_protocol(connection_id="127.0.0.1:1234"):
    proto = MagicMock()
    proto.backend_pid = 1234
    proto.backend_secret = 5678
    proto.connection_id = connection_id
    proto.handle_ssl_probe = AsyncMock()
    proto.handle_startup_sequence = AsyncMock()
    proto.message_loop = AsyncMock()
    return proto


# ---------------------------------------------------------------------------
# Import server with mocked heavy dependencies
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def server_module():
    """Import iris_pgwire.server with BackendSelector + IntegratedML mocked."""
    executor = _make_executor()

    fake_selector = MagicMock()
    fake_selector.return_value.select_backend.return_value = executor

    fake_integratedml = MagicMock()
    fake_integratedml.enhance_iris_executor_with_integratedml = lambda ex: ex

    # Patch the two imports that would hit real IRIS
    with patch("iris_pgwire.backend_selector.BackendSelector") as mock_bs_cls, \
         patch.dict(sys.modules, {
             "iris_pgwire.integratedml": fake_integratedml,
         }):
        mock_bs_cls.return_value.select_backend.return_value = executor

        # Remove cached module so it re-imports cleanly
        for key in list(sys.modules):
            if key == "iris_pgwire.server":
                del sys.modules[key]

        import iris_pgwire.server as srv
        yield srv


@pytest.fixture
def server(server_module):
    """PGWireServer instance with mocked executor."""
    executor = _make_executor()
    with patch("iris_pgwire.backend_selector.BackendSelector") as mock_bs_cls, \
         patch("iris_pgwire.server.enhance_iris_executor_with_integratedml", side_effect=lambda x: x):
        mock_bs_cls.return_value.select_backend.return_value = executor
        s = server_module.PGWireServer(
            host="127.0.0.1",
            port=15432,
            iris_host="localhost",
            iris_port=1972,
        )
        s.iris_executor = executor
        return s


# ---------------------------------------------------------------------------
# _gather_main_config
# ---------------------------------------------------------------------------

class TestGatherMainConfig:
    def test_defaults(self, server_module, monkeypatch):
        for var in (
            "PGWIRE_HOST", "PGWIRE_PORT", "IRIS_HOST", "IRIS_PORT",
            "IRIS_USERNAME", "IRIS_PASSWORD", "IRIS_NAMESPACE",
            "PGWIRE_SSL_ENABLED", "PGWIRE_SSL_CERT", "PGWIRE_SSL_KEY",
            "PGWIRE_POOL_SIZE", "PGWIRE_POOL_TIMEOUT", "PGWIRE_QUERY_TIMEOUT",
            "PGWIRE_QUERY_CACHE_ENABLED", "PGWIRE_QUERY_CACHE_SIZE", "PGWIRE_DEBUG",
        ):
            monkeypatch.delenv(var, raising=False)

        cfg = server_module._gather_main_config()
        assert cfg["host"] == "0.0.0.0"
        assert cfg["port"] == 5432
        assert cfg["iris_host"] == "localhost"
        assert cfg["iris_port"] == 1972
        assert cfg["iris_username"] == "_SYSTEM"
        assert cfg["iris_password"] == "SYS"
        assert cfg["iris_namespace"] == "USER"
        assert cfg["enable_ssl"] is False
        assert cfg["ssl_cert_path"] is None
        assert cfg["ssl_key_path"] is None
        assert cfg["connection_pool_size"] == 10
        assert cfg["query_timeout"] == 30.0
        assert cfg["enable_query_cache"] is True
        assert cfg["debug"] is False

    def test_custom_env(self, server_module, monkeypatch):
        monkeypatch.setenv("PGWIRE_HOST", "0.0.0.0")
        monkeypatch.setenv("PGWIRE_PORT", "9999")
        monkeypatch.setenv("IRIS_HOST", "iris-server")
        monkeypatch.setenv("PGWIRE_SSL_ENABLED", "true")
        monkeypatch.setenv("PGWIRE_DEBUG", "true")
        cfg = server_module._gather_main_config()
        assert cfg["port"] == 9999
        assert cfg["iris_host"] == "iris-server"
        assert cfg["enable_ssl"] is True
        assert cfg["debug"] is True


# ---------------------------------------------------------------------------
# PGWireServer.__init__
# ---------------------------------------------------------------------------

class TestPGWireServerInit:
    def test_basic_attributes(self, server):
        assert server.host == "127.0.0.1"
        assert server.port == 15432
        assert server.enable_ssl is False
        assert server.server is None
        assert server.ssl_context is None
        assert isinstance(server.active_connections, set)
        assert isinstance(server.connection_registry, dict)

    def test_iris_config_stored(self, server):
        assert server.iris_config["host"] == "localhost"
        assert server.iris_config["port"] == 1972


# ---------------------------------------------------------------------------
# register_connection / unregister_connection / find_connection_for_cancellation
# ---------------------------------------------------------------------------

class TestConnectionRegistry:
    def test_register_adds_entry(self, server):
        proto = _make_protocol()
        server.register_connection(proto)
        assert 1234 in server.connection_registry

    def test_unregister_removes_entry(self, server):
        proto = _make_protocol()
        server.register_connection(proto)
        server.unregister_connection(proto)
        assert 1234 not in server.connection_registry

    def test_unregister_nonexistent_is_noop(self, server):
        proto = _make_protocol()
        # Should not raise even if not registered
        server.unregister_connection(proto)

    def test_find_connection_success(self, server):
        proto = _make_protocol()
        server.register_connection(proto)
        found = server.find_connection_for_cancellation(1234, 5678)
        assert found is proto

    def test_find_connection_wrong_secret(self, server):
        proto = _make_protocol()
        server.register_connection(proto)
        found = server.find_connection_for_cancellation(1234, 9999)
        assert found is None

    def test_find_connection_wrong_pid(self, server):
        found = server.find_connection_for_cancellation(9999, 5678)
        assert found is None


# ---------------------------------------------------------------------------
# setup_ssl_context
# ---------------------------------------------------------------------------

class TestSetupSSLContext:
    @pytest.mark.asyncio
    async def test_ssl_disabled_returns_none(self, server):
        server.enable_ssl = False
        result = await server.setup_ssl_context()
        assert result is None

    @pytest.mark.asyncio
    async def test_ssl_enabled_no_paths_returns_none(self, server):
        server.enable_ssl = True
        server.ssl_cert_path = None
        server.ssl_key_path = None
        result = await server.setup_ssl_context()
        assert result is None

    @pytest.mark.asyncio
    async def test_ssl_enabled_with_paths_success(self, server, tmp_path):
        cert = tmp_path / "cert.pem"
        key = tmp_path / "key.pem"
        cert.write_text("CERT")
        key.write_text("KEY")
        server.enable_ssl = True
        server.ssl_cert_path = str(cert)
        server.ssl_key_path = str(key)

        fake_ctx = MagicMock(spec=ssl.SSLContext)
        with patch("ssl.create_default_context", return_value=fake_ctx):
            result = await server.setup_ssl_context()

        assert result is fake_ctx
        fake_ctx.load_cert_chain.assert_called_once_with(str(cert), str(key))

    @pytest.mark.asyncio
    async def test_ssl_exception_returns_none(self, server, tmp_path):
        server.enable_ssl = True
        server.ssl_cert_path = "/nonexistent/cert.pem"
        server.ssl_key_path = "/nonexistent/key.pem"

        with patch("ssl.create_default_context", side_effect=ssl.SSLError("bad cert")):
            result = await server.setup_ssl_context()

        assert result is None


# ---------------------------------------------------------------------------
# handle_client
# ---------------------------------------------------------------------------

class TestHandleClient:
    @pytest.mark.asyncio
    async def test_handle_client_normal_flow(self, server, server_module):
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock()
        writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 9999))
        writer.is_closing = MagicMock(return_value=True)
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        proto = _make_protocol()

        with patch.object(server_module, "PGWireProtocol", return_value=proto):
            await server.handle_client(reader, writer)

        proto.handle_ssl_probe.assert_called_once()
        proto.handle_startup_sequence.assert_called_once()
        proto.message_loop.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_client_protocol_error(self, server, server_module):
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock()
        writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 9999))
        writer.is_closing = MagicMock(return_value=True)
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        proto = _make_protocol()
        proto.message_loop.side_effect = RuntimeError("protocol error")

        with patch.object(server_module, "PGWireProtocol", return_value=proto):
            # Should not propagate — error is caught and logged
            await server.handle_client(reader, writer)

    @pytest.mark.asyncio
    async def test_handle_client_cancelled(self, server, server_module):
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock()
        writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 9999))
        writer.is_closing = MagicMock(return_value=True)
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        proto = _make_protocol()
        proto.handle_ssl_probe.side_effect = asyncio.CancelledError

        with patch.object(server_module, "PGWireProtocol", return_value=proto):
            await server.handle_client(reader, writer)

    @pytest.mark.asyncio
    async def test_handle_client_connection_aborted(self, server, server_module):
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock()
        writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 9999))
        writer.is_closing = MagicMock(return_value=True)
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        proto = _make_protocol()
        proto.handle_ssl_probe.side_effect = ConnectionAbortedError("client gone")

        with patch.object(server_module, "PGWireProtocol", return_value=proto):
            await server.handle_client(reader, writer)

    @pytest.mark.asyncio
    async def test_handle_client_closes_writer_when_not_closing(self, server, server_module):
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock()
        writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 9999))
        writer.is_closing = MagicMock(return_value=False)
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        proto = _make_protocol()

        with patch.object(server_module, "PGWireProtocol", return_value=proto):
            await server.handle_client(reader, writer)

        writer.close.assert_called_once()
        writer.wait_closed.assert_called_once()


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

class TestStart:
    @pytest.mark.asyncio
    async def test_start_calls_test_connection_and_start_server(self, server):
        fake_server = MagicMock()
        fake_server.sockets = [MagicMock()]
        fake_server.sockets[0].getsockname.return_value = ("127.0.0.1", 15432)
        fake_server.__aenter__ = AsyncMock(return_value=fake_server)
        fake_server.__aexit__ = AsyncMock(return_value=False)
        fake_server.serve_forever = AsyncMock(side_effect=asyncio.CancelledError)

        with patch("asyncio.start_server", new=AsyncMock(return_value=fake_server)):
            try:
                await server.start()
            except asyncio.CancelledError:
                pass

        server.iris_executor.test_connection.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_propagates_exception(self, server):
        server.iris_executor.test_connection.side_effect = ConnectionRefusedError("no IRIS")
        with pytest.raises(ConnectionRefusedError):
            await server.start()


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

class TestStop:
    @pytest.mark.asyncio
    async def test_stop_with_no_server(self, server):
        server.server = None
        # Should be a no-op
        await server.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_server_and_connections(self, server):
        fake_server = MagicMock()
        fake_server.close = MagicMock()
        fake_server.wait_closed = AsyncMock()
        server.server = fake_server

        writer1 = MagicMock()
        writer1.is_closing = MagicMock(return_value=False)
        writer1.close = MagicMock()
        writer1.wait_closed = AsyncMock()
        server.active_connections = {writer1}

        await server.stop()

        fake_server.close.assert_called_once()
        fake_server.wait_closed.assert_called_once()
        writer1.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_skips_already_closing_connection(self, server):
        fake_server = MagicMock()
        fake_server.close = MagicMock()
        fake_server.wait_closed = AsyncMock()
        server.server = fake_server

        writer1 = MagicMock()
        writer1.is_closing = MagicMock(return_value=True)
        writer1.close = MagicMock()
        writer1.wait_closed = AsyncMock()
        server.active_connections = {writer1}

        await server.stop()

        writer1.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_empty_connections(self, server):
        fake_server = MagicMock()
        fake_server.close = MagicMock()
        fake_server.wait_closed = AsyncMock()
        server.server = fake_server
        server.active_connections = set()

        await server.stop()

        fake_server.close.assert_called_once()
