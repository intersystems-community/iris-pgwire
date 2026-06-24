"""
Extended unit tests for auth/auth_selector.py

Covers all branches of select_authentication_method, should_try_wallet_first,
and get_authentication_chain.
"""

from __future__ import annotations

import pytest

from iris_pgwire.auth.auth_selector import AuthenticationSelector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def selector_all_enabled():
    return AuthenticationSelector(oauth_enabled=True, kerberos_enabled=True, wallet_enabled=True)


@pytest.fixture
def selector_all_disabled():
    return AuthenticationSelector(oauth_enabled=False, kerberos_enabled=False, wallet_enabled=False)


@pytest.fixture
def selector_oauth_only():
    return AuthenticationSelector(oauth_enabled=True, kerberos_enabled=False, wallet_enabled=True)


@pytest.fixture
def selector_kerberos_only():
    return AuthenticationSelector(oauth_enabled=False, kerberos_enabled=True, wallet_enabled=True)


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

class TestInit:
    def test_stores_flags(self):
        sel = AuthenticationSelector(oauth_enabled=False, kerberos_enabled=True, wallet_enabled=False)
        assert sel.oauth_enabled is False
        assert sel.kerberos_enabled is True
        assert sel.wallet_enabled is False

    def test_defaults_all_true(self):
        sel = AuthenticationSelector()
        assert sel.oauth_enabled is True
        assert sel.kerberos_enabled is True
        assert sel.wallet_enabled is True


# ---------------------------------------------------------------------------
# select_authentication_method
# ---------------------------------------------------------------------------

class TestSelectAuthenticationMethod:
    @pytest.mark.asyncio
    async def test_gssapi_kerberos_enabled(self, selector_all_enabled):
        ctx = {"auth_method": "gssapi", "username": "alice"}
        result = await selector_all_enabled.select_authentication_method(ctx)
        assert result == "kerberos"

    @pytest.mark.asyncio
    async def test_sasl_kerberos_enabled(self, selector_all_enabled):
        ctx = {"auth_method": "sasl", "username": "alice"}
        result = await selector_all_enabled.select_authentication_method(ctx)
        assert result == "kerberos"

    @pytest.mark.asyncio
    async def test_gssapi_kerberos_disabled(self, selector_oauth_only):
        ctx = {"auth_method": "gssapi", "username": "alice"}
        result = await selector_oauth_only.select_authentication_method(ctx)
        assert result == "password"

    @pytest.mark.asyncio
    async def test_sasl_kerberos_disabled(self, selector_oauth_only):
        ctx = {"auth_method": "sasl", "username": "alice"}
        result = await selector_oauth_only.select_authentication_method(ctx)
        assert result == "password"

    @pytest.mark.asyncio
    async def test_password_oauth_enabled_and_available(self, selector_all_enabled):
        ctx = {"auth_method": "password", "username": "alice", "oauth_available": True}
        result = await selector_all_enabled.select_authentication_method(ctx)
        assert result == "oauth"

    @pytest.mark.asyncio
    async def test_scram_sha_256_oauth_enabled(self, selector_all_enabled):
        ctx = {"auth_method": "scram-sha-256", "username": "alice", "oauth_available": True}
        result = await selector_all_enabled.select_authentication_method(ctx)
        assert result == "oauth"

    @pytest.mark.asyncio
    async def test_md5_oauth_enabled(self, selector_all_enabled):
        ctx = {"auth_method": "md5", "username": "alice", "oauth_available": True}
        result = await selector_all_enabled.select_authentication_method(ctx)
        assert result == "oauth"

    @pytest.mark.asyncio
    async def test_password_oauth_disabled(self, selector_all_disabled):
        ctx = {"auth_method": "password", "username": "alice", "oauth_available": True}
        result = await selector_all_disabled.select_authentication_method(ctx)
        assert result == "password"

    @pytest.mark.asyncio
    async def test_password_oauth_enabled_but_unavailable(self, selector_all_enabled):
        ctx = {"auth_method": "password", "username": "alice", "oauth_available": False}
        result = await selector_all_enabled.select_authentication_method(ctx)
        assert result == "password"

    @pytest.mark.asyncio
    async def test_unknown_auth_method_defaults_password(self, selector_all_enabled):
        ctx = {"auth_method": "unknown_method", "username": "alice"}
        result = await selector_all_enabled.select_authentication_method(ctx)
        assert result == "password"

    @pytest.mark.asyncio
    async def test_missing_auth_method_defaults_password(self, selector_all_enabled):
        # No auth_method key → defaults to "password" → routes into password branch
        ctx = {"username": "alice", "oauth_available": False}
        result = await selector_all_enabled.select_authentication_method(ctx)
        # oauth_available False → password
        assert result == "password"

    @pytest.mark.asyncio
    async def test_default_oauth_available_true(self, selector_all_enabled):
        # oauth_available defaults to True when not in context
        ctx = {"auth_method": "password", "username": "alice"}
        result = await selector_all_enabled.select_authentication_method(ctx)
        assert result == "oauth"


# ---------------------------------------------------------------------------
# should_try_wallet_first
# ---------------------------------------------------------------------------

class TestShouldTryWalletFirst:
    @pytest.mark.asyncio
    async def test_wallet_disabled_returns_false(self, selector_all_disabled):
        result = await selector_all_disabled.should_try_wallet_first("oauth", "alice")
        assert result is False

    @pytest.mark.asyncio
    async def test_wallet_enabled_oauth_returns_true(self, selector_all_enabled):
        result = await selector_all_enabled.should_try_wallet_first("oauth", "alice")
        assert result is True

    @pytest.mark.asyncio
    async def test_wallet_enabled_password_returns_true(self, selector_all_enabled):
        result = await selector_all_enabled.should_try_wallet_first("password", "alice")
        assert result is True

    @pytest.mark.asyncio
    async def test_wallet_enabled_kerberos_returns_false(self, selector_all_enabled):
        result = await selector_all_enabled.should_try_wallet_first("kerberos", "alice")
        assert result is False


# ---------------------------------------------------------------------------
# get_authentication_chain
# ---------------------------------------------------------------------------

class TestGetAuthenticationChain:
    def test_oauth_enabled_chain(self, selector_all_enabled):
        chain = selector_all_enabled.get_authentication_chain("oauth")
        assert chain == ["oauth", "password"]

    def test_oauth_disabled_chain(self, selector_all_disabled):
        chain = selector_all_disabled.get_authentication_chain("oauth")
        assert chain == ["password"]

    def test_kerberos_enabled_chain(self, selector_all_enabled):
        chain = selector_all_enabled.get_authentication_chain("kerberos")
        assert chain == ["kerberos", "password"]

    def test_kerberos_disabled_chain(self, selector_all_disabled):
        chain = selector_all_disabled.get_authentication_chain("kerberos")
        assert chain == ["password"]

    def test_password_chain(self, selector_all_enabled):
        chain = selector_all_enabled.get_authentication_chain("password")
        assert chain == ["password"]

    def test_unknown_key_defaults_password(self, selector_all_enabled):
        chain = selector_all_enabled.get_authentication_chain("unknown")  # type: ignore[arg-type]
        assert chain == ["password"]
