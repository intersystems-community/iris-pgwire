"""
Unit tests for auth/gssapi_auth.py

Tests cover all public methods and branches without a live IRIS or gssapi installation.
gssapi is mocked via sys.modules patching before any import of the module under test.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to set up a fake gssapi module so the module-level try/except
# in gssapi_auth.py resolves GSSAPI_AVAILABLE = True when we want it to.
# ---------------------------------------------------------------------------

def _make_fake_gssapi():
    """Return a minimal fake gssapi module tree."""
    fake_gssapi = MagicMock()
    fake_gssapi.NameType = MagicMock()
    fake_gssapi.NameType.hostbased_service = MagicMock()
    fake_name = MagicMock()
    fake_gssapi.Name = MagicMock(return_value=fake_name)
    fake_creds = MagicMock()
    fake_gssapi.Credentials = MagicMock(return_value=fake_creds)
    fake_gssapi.SecurityContext = MagicMock()
    return fake_gssapi


def _import_module_with_gssapi(available: bool):
    """Import gssapi_auth with GSSAPI_AVAILABLE forced to *available*."""
    # Remove cached module if already imported
    for key in list(sys.modules.keys()):
        if "gssapi_auth" in key:
            del sys.modules[key]

    if available:
        fake = _make_fake_gssapi()
        with patch.dict(sys.modules, {"gssapi": fake}):
            import importlib
            import iris_pgwire.auth.gssapi_auth as mod
            importlib.reload(mod)
            return mod, fake
    else:
        # Remove gssapi from sys.modules so the import fails
        sys.modules.pop("gssapi", None)
        import importlib
        import iris_pgwire.auth.gssapi_auth as mod
        importlib.reload(mod)
        return mod, None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _cleanup_module():
    """Ensure no stale cached module between tests."""
    yield
    for key in list(sys.modules.keys()):
        if "gssapi_auth" in key:
            del sys.modules[key]


@pytest.fixture
def gssapi_mod():
    """Module imported with gssapi available."""
    mod, fake = _import_module_with_gssapi(True)
    return mod, fake


@pytest.fixture
def authenticator(gssapi_mod):
    """GSSAPIAuthenticator instance with default config and gssapi available."""
    mod, fake = gssapi_mod
    config = mod.KerberosConfig(
        service_name="postgres",
        keytab_path="/etc/krb5.keytab",
        realm="EXAMPLE.COM",
        handshake_timeout=5,
    )
    auth = mod.GSSAPIAuthenticator(config=config)
    # Attach the fake gssapi module so tests can introspect calls
    auth._fake_gssapi = fake
    auth._mod = mod
    return auth


# ---------------------------------------------------------------------------
# Dataclass / exception basic tests
# ---------------------------------------------------------------------------

class TestKerberosPrincipal:
    def test_fields(self):
        mod, _ = _import_module_with_gssapi(True)
        now = datetime.now(UTC)
        p = mod.KerberosPrincipal(
            principal="alice@EXAMPLE.COM",
            username="alice",
            realm="EXAMPLE.COM",
            mapped_iris_user="ALICE",
            authenticated_at=now,
        )
        assert p.principal == "alice@EXAMPLE.COM"
        assert p.ticket_expiry is None


class TestKerberosConfig:
    def test_defaults(self):
        mod, _ = _import_module_with_gssapi(True)
        cfg = mod.KerberosConfig()
        assert cfg.service_name == "postgres"
        assert cfg.keytab_path == "/etc/krb5.keytab"
        assert cfg.realm is None
        assert cfg.handshake_timeout == 5


class TestExceptions:
    def test_auth_error_is_exception(self):
        mod, _ = _import_module_with_gssapi(True)
        err = mod.KerberosAuthenticationError("bad")
        assert isinstance(err, Exception)

    def test_timeout_error_is_exception(self):
        mod, _ = _import_module_with_gssapi(True)
        err = mod.KerberosTimeoutError("too slow")
        assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# GSSAPIAuthenticator.__init__
# ---------------------------------------------------------------------------

class TestGSSAPIAuthenticatorInit:
    def test_init_raises_when_gssapi_unavailable(self):
        mod, _ = _import_module_with_gssapi(False)
        # Force GSSAPI_AVAILABLE = False
        mod.GSSAPI_AVAILABLE = False
        with pytest.raises(ImportError, match="python-gssapi"):
            mod.GSSAPIAuthenticator()

    def test_init_uses_provided_config(self):
        mod, _ = _import_module_with_gssapi(True)
        mod.GSSAPI_AVAILABLE = True
        cfg = mod.KerberosConfig(service_name="myservice", realm="MYREALM")
        auth = mod.GSSAPIAuthenticator(config=cfg)
        assert auth.config.service_name == "myservice"

    def test_init_loads_from_env_when_no_config(self, monkeypatch):
        mod, _ = _import_module_with_gssapi(True)
        mod.GSSAPI_AVAILABLE = True
        monkeypatch.setenv("PGWIRE_KERBEROS_SERVICE_NAME", "myservice")
        monkeypatch.setenv("KRB5_KTNAME", "/custom.keytab")
        monkeypatch.setenv("PGWIRE_KERBEROS_REALM", "MYREALM")
        monkeypatch.setenv("PGWIRE_KERBEROS_TIMEOUT", "10")
        auth = mod.GSSAPIAuthenticator()
        assert auth.config.service_name == "myservice"
        assert auth.config.keytab_path == "/custom.keytab"
        assert auth.config.realm == "MYREALM"
        assert auth.config.handshake_timeout == 10


# ---------------------------------------------------------------------------
# _load_config_from_env
# ---------------------------------------------------------------------------

class TestLoadConfigFromEnv:
    def test_defaults_when_no_env(self, monkeypatch):
        mod, _ = _import_module_with_gssapi(True)
        mod.GSSAPI_AVAILABLE = True
        for var in ("PGWIRE_KERBEROS_SERVICE_NAME", "KRB5_KTNAME", "PGWIRE_KERBEROS_REALM", "PGWIRE_KERBEROS_TIMEOUT"):
            monkeypatch.delenv(var, raising=False)
        auth = mod.GSSAPIAuthenticator(config=mod.KerberosConfig())
        cfg = auth._load_config_from_env()
        assert cfg.service_name == "postgres"
        assert cfg.keytab_path == "/etc/krb5.keytab"
        assert cfg.realm is None
        assert cfg.handshake_timeout == 5

    def test_custom_values(self, monkeypatch):
        mod, _ = _import_module_with_gssapi(True)
        mod.GSSAPI_AVAILABLE = True
        monkeypatch.setenv("PGWIRE_KERBEROS_SERVICE_NAME", "svc")
        monkeypatch.setenv("KRB5_KTNAME", "/tmp/my.keytab")
        monkeypatch.setenv("PGWIRE_KERBEROS_REALM", "CORP")
        monkeypatch.setenv("PGWIRE_KERBEROS_TIMEOUT", "15")
        auth = mod.GSSAPIAuthenticator(config=mod.KerberosConfig())
        cfg = auth._load_config_from_env()
        assert cfg.service_name == "svc"
        assert cfg.realm == "CORP"
        assert cfg.handshake_timeout == 15


# ---------------------------------------------------------------------------
# extract_principal
# ---------------------------------------------------------------------------

class TestExtractPrincipal:
    @pytest.mark.asyncio
    async def test_string_input(self, authenticator):
        result = await authenticator.extract_principal("alice@EXAMPLE.COM")
        assert result == "alice@EXAMPLE.COM"

    @pytest.mark.asyncio
    async def test_object_with_peer_name(self, authenticator):
        ctx = MagicMock()
        ctx.peer_name = "bob@EXAMPLE.COM"
        result = await authenticator.extract_principal(ctx)
        assert result == "bob@EXAMPLE.COM"

    @pytest.mark.asyncio
    async def test_empty_string_raises(self, authenticator):
        mod = authenticator._mod
        with pytest.raises(mod.KerberosAuthenticationError, match="Failed to extract"):
            await authenticator.extract_principal("")

    @pytest.mark.asyncio
    async def test_double_at_raises(self, authenticator):
        mod = authenticator._mod
        with pytest.raises(mod.KerberosAuthenticationError, match="Failed to extract"):
            await authenticator.extract_principal("user@@realm")


# ---------------------------------------------------------------------------
# _split_principal
# ---------------------------------------------------------------------------

class TestSplitPrincipal:
    def test_with_at(self, authenticator):
        user, realm = authenticator._split_principal("alice@EXAMPLE.COM")
        assert user == "alice"
        assert realm == "EXAMPLE.COM"

    def test_without_at_uses_config_realm(self, authenticator):
        user, realm = authenticator._split_principal("alice")
        assert user == "alice"
        assert realm == "EXAMPLE.COM"  # config.realm

    def test_without_at_falls_back_to_default(self, authenticator):
        authenticator.config.realm = None
        user, realm = authenticator._split_principal("bob")
        assert realm == "DEFAULT"


# ---------------------------------------------------------------------------
# _build_kerberos_principal
# ---------------------------------------------------------------------------

class TestBuildKerberosPrincipal:
    def test_builds_correctly(self, authenticator):
        principal = authenticator._build_kerberos_principal("alice@EXAMPLE.COM", "ALICE")
        assert principal.principal == "alice@EXAMPLE.COM"
        assert principal.username == "alice"
        assert principal.realm == "EXAMPLE.COM"
        assert principal.mapped_iris_user == "ALICE"
        assert principal.ticket_expiry is not None


# ---------------------------------------------------------------------------
# map_principal_to_iris_user
# ---------------------------------------------------------------------------

class TestMapPrincipalToIrisUser:
    @pytest.mark.asyncio
    async def test_maps_and_uppercases(self, authenticator):
        with patch.object(authenticator, "_validate_iris_user_exists", AsyncMock(return_value=True)):
            result = await authenticator.map_principal_to_iris_user("alice@EXAMPLE.COM")
        assert result == "ALICE"

    @pytest.mark.asyncio
    async def test_no_realm(self, authenticator):
        with patch.object(authenticator, "_validate_iris_user_exists", AsyncMock(return_value=True)):
            result = await authenticator.map_principal_to_iris_user("bob")
        assert result == "BOB"

    @pytest.mark.asyncio
    async def test_user_not_found_raises(self, authenticator):
        mod = authenticator._mod
        with patch.object(authenticator, "_validate_iris_user_exists", AsyncMock(return_value=False)):
            with pytest.raises(mod.KerberosAuthenticationError, match="does not exist"):
                await authenticator.map_principal_to_iris_user("ghost@EXAMPLE.COM")

    @pytest.mark.asyncio
    async def test_unexpected_exception_wrapped(self, authenticator):
        mod = authenticator._mod
        with patch.object(authenticator, "_validate_iris_user_exists", AsyncMock(side_effect=RuntimeError("boom"))):
            with pytest.raises(mod.KerberosAuthenticationError):
                await authenticator.map_principal_to_iris_user("alice@EXAMPLE.COM")


# ---------------------------------------------------------------------------
# _validate_iris_user_exists / _query_iris_user_exists_sync
# ---------------------------------------------------------------------------

class TestValidateIrisUserExists:
    @pytest.mark.asyncio
    async def test_returns_true_when_user_found(self, authenticator):
        with patch.object(authenticator, "_query_iris_user_exists_sync", return_value=True):
            result = await authenticator._validate_iris_user_exists("ALICE")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_missing(self, authenticator):
        with patch.object(authenticator, "_query_iris_user_exists_sync", return_value=False):
            result = await authenticator._validate_iris_user_exists("NOBODY")
        assert result is False

    def test_query_sync_returns_false_on_exception(self, authenticator):
        """When iris import fails, returns False."""
        with patch.dict(sys.modules, {"iris": None}):
            result = authenticator._query_iris_user_exists_sync("ALICE")
        assert result is False

    def test_query_sync_returns_true_when_row_found(self, authenticator):
        fake_iris = MagicMock()
        row = MagicMock()
        fake_iris.sql.exec.return_value.fetchone.return_value = row
        with patch.dict(sys.modules, {"iris": fake_iris}):
            result = authenticator._query_iris_user_exists_sync("ALICE")
        assert result is True

    def test_query_sync_returns_false_when_no_row(self, authenticator):
        fake_iris = MagicMock()
        fake_iris.sql.exec.return_value.fetchone.return_value = None
        with patch.dict(sys.modules, {"iris": fake_iris}):
            result = authenticator._query_iris_user_exists_sync("NOBODY")
        assert result is False


# ---------------------------------------------------------------------------
# _iris_ticket_validation_sync
# ---------------------------------------------------------------------------

class TestIrisTicketValidationSync:
    def test_returns_true_on_valid_token(self, authenticator):
        mod = authenticator._mod
        fake_iris = MagicMock()
        fake_svc = MagicMock()
        fake_svc.ValidateGSSAPIToken.return_value = 1
        fake_iris.cls.return_value = fake_svc
        with patch.dict(sys.modules, {"iris": fake_iris}):
            result = authenticator._iris_ticket_validation_sync(b"token")
        assert result is True

    def test_raises_on_iris_exception(self, authenticator):
        mod = authenticator._mod
        fake_iris = MagicMock()
        fake_iris.cls.side_effect = RuntimeError("IRIS down")
        with patch.dict(sys.modules, {"iris": fake_iris}):
            with pytest.raises(mod.KerberosAuthenticationError, match="IRIS ticket validation"):
                authenticator._iris_ticket_validation_sync(b"token")


# ---------------------------------------------------------------------------
# validate_kerberos_ticket (async wrapper)
# ---------------------------------------------------------------------------

class TestValidateKerberosTicket:
    @pytest.mark.asyncio
    async def test_returns_true(self, authenticator):
        with patch.object(authenticator, "_iris_ticket_validation_sync", return_value=True):
            result = await authenticator.validate_kerberos_ticket(b"token")
        assert result is True

    @pytest.mark.asyncio
    async def test_reraises_auth_error(self, authenticator):
        mod = authenticator._mod
        with patch.object(
            authenticator,
            "_iris_ticket_validation_sync",
            side_effect=mod.KerberosAuthenticationError("already typed"),
        ):
            with pytest.raises(mod.KerberosAuthenticationError, match="already typed"):
                await authenticator.validate_kerberos_ticket(b"token")

    @pytest.mark.asyncio
    async def test_wraps_generic_exception(self, authenticator):
        mod = authenticator._mod
        with patch.object(
            authenticator,
            "_iris_ticket_validation_sync",
            side_effect=RuntimeError("unexpected"),
        ):
            with pytest.raises(mod.KerberosAuthenticationError, match="Unexpected error"):
                await authenticator.validate_kerberos_ticket(b"token")


# ---------------------------------------------------------------------------
# handle_gssapi_handshake — timeout and generic error branches
# ---------------------------------------------------------------------------

class TestHandleGSSAPIHandshake:
    @pytest.mark.asyncio
    async def test_timeout_raises_kerberos_timeout_error(self, authenticator):
        mod = authenticator._mod
        with patch.object(
            authenticator,
            "_perform_gssapi_handshake",
            side_effect=TimeoutError,
        ):
            with patch("asyncio.wait_for", side_effect=TimeoutError):
                with pytest.raises(mod.KerberosTimeoutError):
                    await authenticator.handle_gssapi_handshake("conn-1")

    @pytest.mark.asyncio
    async def test_generic_error_raises_auth_error(self, authenticator):
        mod = authenticator._mod
        with patch("asyncio.wait_for", side_effect=ValueError("bad")):
            with pytest.raises(mod.KerberosAuthenticationError):
                await authenticator.handle_gssapi_handshake("conn-1")

    @pytest.mark.asyncio
    async def test_success_returns_principal(self, authenticator):
        mod = authenticator._mod
        cfg = mod.KerberosConfig(service_name="postgres", realm="EXAMPLE.COM")
        expected = authenticator._build_kerberos_principal("alice@EXAMPLE.COM", "ALICE")
        with patch("asyncio.wait_for", new=AsyncMock(return_value=expected)):
            result = await authenticator.handle_gssapi_handshake("conn-1")
        assert result.mapped_iris_user == "ALICE"


# ---------------------------------------------------------------------------
# _perform_gssapi_handshake
# ---------------------------------------------------------------------------

class TestPerformGSSAPIHandshake:
    @pytest.mark.asyncio
    async def test_full_flow(self, authenticator):
        with patch.object(authenticator, "_gssapi_handshake_sync", return_value="alice@EXAMPLE.COM"):
            with patch.object(authenticator, "_validate_iris_user_exists", AsyncMock(return_value=True)):
                result = await authenticator._perform_gssapi_handshake("conn-1")
        assert result.principal == "alice@EXAMPLE.COM"
        assert result.mapped_iris_user == "ALICE"


# ---------------------------------------------------------------------------
# _gssapi_handshake_sync
# ---------------------------------------------------------------------------

class TestGSSAPIHandshakeSync:
    def test_returns_mock_principal(self, authenticator):
        # The method calls gssapi.Name and gssapi.Credentials (both mocked via fixture)
        result = authenticator._gssapi_handshake_sync("conn-1")
        assert result == "testuser@EXAMPLE.COM"

    def test_raises_auth_error_on_exception(self, authenticator):
        mod = authenticator._mod
        authenticator._fake_gssapi.Name.side_effect = RuntimeError("krb5 error")
        with pytest.raises(mod.KerberosAuthenticationError):
            authenticator._gssapi_handshake_sync("conn-1")
