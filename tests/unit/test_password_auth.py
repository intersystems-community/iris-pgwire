"""Password authentication: what the server demands before it opens a session.

The wire exchange is the plain `AuthenticationCleartextPassword` one: the client sends its
password and the server checks it by logging into IRIS with it. IRIS stays the only store of
users and passwords. Because the password crosses the wire, TLS is required unless the operator
says otherwise, and trust (no credentials) is an explicit opt-in.

The verifiers talk to a real IRIS in `tests/e2e/test_auth_defaults.py`. These tests cover the
protocol logic with a stub verifier and the failure classification with a real, unreachable
target.
"""

import asyncio
import struct
import sys

import pytest

from iris_pgwire.password_auth import (
    AuthConfigError,
    AuthRefused,
    AuthUnavailable,
    DbapiPasswordVerifier,
    EmbeddedPasswordVerifier,
    parse_password_message,
    resolve_allowed_users,
    validate_auth_config,
)
from iris_pgwire.protocol import PGWireProtocol

AUTH_CLEARTEXT = 3
AUTH_OK = 0


# ---------------------------------------------------------------------------
# validate_auth_config
# ---------------------------------------------------------------------------


class TestValidateAuthConfig:
    def test_password_over_tls_is_valid(self):
        validate_auth_config(auth_mode="password", enable_ssl=True, allow_plaintext_password=False)

    def test_password_over_plaintext_needs_the_explicit_flag(self):
        validate_auth_config(auth_mode="password", enable_ssl=False, allow_plaintext_password=True)

    def test_password_without_tls_or_the_flag_refuses_to_start(self):
        with pytest.raises(AuthConfigError) as raised:
            validate_auth_config(
                auth_mode="password", enable_ssl=False, allow_plaintext_password=False
            )
        message = str(raised.value)
        assert "TLS" in message
        assert "--trust" in message and "--allow-plaintext-password" in message

    def test_trust_needs_nothing_else(self):
        validate_auth_config(auth_mode="trust", enable_ssl=False, allow_plaintext_password=False)

    def test_an_unknown_mode_is_refused(self):
        with pytest.raises(AuthConfigError, match="auth_mode"):
            validate_auth_config(auth_mode="scram", enable_ssl=True, allow_plaintext_password=False)

    @pytest.mark.parametrize("mode", ["password", "trust"])
    def test_scram_is_refused_loudly_in_every_mode(self, mode):
        # Nothing implemented SCRAM: the proof was never checked. Silently ignoring the flag
        # would leave a deployment believing it had authentication.
        with pytest.raises(AuthConfigError, match="SCRAM"):
            validate_auth_config(
                auth_mode=mode, enable_ssl=True, allow_plaintext_password=True, enable_scram=True
            )


# ---------------------------------------------------------------------------
# parse_password_message
# ---------------------------------------------------------------------------


class TestParsePasswordMessage:
    def test_strips_the_terminator(self):
        assert parse_password_message(b"s3cret\x00") == "s3cret"

    def test_utf8(self):
        assert parse_password_message("pässwörd\x00".encode()) == "pässwörd"

    def test_empty_password(self):
        assert parse_password_message(b"\x00") == ""

    @pytest.mark.parametrize(
        "body",
        [b"", b"no-terminator", b"embedded\x00nul\x00", b"\xff\xfe\x00", b"a" * 2000 + b"\x00"],
        ids=["empty", "unterminated", "embedded-nul", "not-utf8", "oversized"],
    )
    def test_malformed_messages_are_a_protocol_violation(self, body):
        with pytest.raises(AuthRefused) as raised:
            parse_password_message(body)
        assert raised.value.sqlstate == "08P01"


# ---------------------------------------------------------------------------
# The exchange, driven over real asyncio streams
# ---------------------------------------------------------------------------


class RecordingWriter:
    def __init__(self):
        self.out = bytearray()
        self.closed = False

    def write(self, data):
        self.out += data

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    def get_extra_info(self, name, default=None):
        return default


class StubVerifier:
    """Accepts exactly one (user, password) pair; records every call."""

    def __init__(self, user="alice", password="right", raises=None):
        self.accepts = (user, password)
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    async def verify(self, user: str, password: str) -> bool:
        self.calls.append((user, password))
        if self.raises:
            raise self.raises
        return (user, password) == self.accepts


def startup_message(user: str | None = "alice") -> bytes:
    params = b"database\x00USER\x00"
    if user is not None:
        params = b"user\x00" + user.encode() + b"\x00" + params
    body = struct.pack("!I", 196608) + params + b"\x00"
    return struct.pack("!I", 4 + len(body)) + body


def password_message(password: str) -> bytes:
    body = password.encode() + b"\x00"
    return b"p" + struct.pack("!I", 4 + len(body)) + body


def messages(data: bytes) -> list[tuple[bytes, bytes]]:
    out, pos = [], 0
    while pos < len(data):
        kind = data[pos : pos + 1]
        (length,) = struct.unpack("!I", data[pos + 1 : pos + 5])
        out.append((kind, data[pos + 5 : pos + 1 + length]))
        pos += 1 + length
    return out


def auth_codes(data: bytes) -> list[int]:
    return [struct.unpack("!I", body[:4])[0] for kind, body in messages(data) if kind == b"R"]


def error_fields(data: bytes) -> dict[str, str]:
    for kind, body in messages(data):
        if kind == b"E":
            fields = {}
            for part in body.split(b"\x00"):
                if part:
                    fields[chr(part[0])] = part[1:].decode()
            return fields
    return {}


async def run_startup(
    client_bytes: bytes,
    verifier=None,
    *,
    auth_mode="password",
    ssl_enabled=False,
    allow_plaintext_password=True,
    allowed_users=None,
    failed_login_delay=0.0,
):
    reader = asyncio.StreamReader()
    reader.feed_data(client_bytes)
    reader.feed_eof()
    writer = RecordingWriter()
    from unittest.mock import MagicMock

    protocol = PGWireProtocol(
        reader,
        writer,
        MagicMock(),
        "unit-test",
        auth_mode=auth_mode,
        password_verifier=verifier,
        allow_plaintext_password=allow_plaintext_password,
        allowed_users=allowed_users,
        failed_login_delay=failed_login_delay,
    )
    protocol.ssl_enabled = ssl_enabled
    error = None
    try:
        await protocol.handle_startup_sequence()
    except Exception as exc:
        error = exc
    return bytes(writer.out), error, protocol


class TestPasswordExchange:
    async def test_a_stranger_is_asked_for_a_password_before_anything_else(self):
        out, _, _ = await run_startup(startup_message("alice"), StubVerifier())
        assert auth_codes(out)[0] == AUTH_CLEARTEXT

    async def test_the_right_password_opens_a_session(self):
        verifier = StubVerifier()
        out, error, protocol = await run_startup(
            startup_message("alice") + password_message("right"), verifier
        )
        assert error is None
        assert auth_codes(out)[:2] == [AUTH_CLEARTEXT, AUTH_OK]
        assert verifier.calls == [("alice", "right")]
        assert protocol.authenticated

    async def test_a_wrong_password_is_refused_with_28P01_and_never_authenticated(self):
        out, error, protocol = await run_startup(
            startup_message("alice") + password_message("wrong"), StubVerifier()
        )
        assert AUTH_OK not in auth_codes(out)
        fields = error_fields(out)
        assert fields["C"] == "28P01"
        assert fields["S"] == "FATAL"
        assert fields["M"] == 'password authentication failed for user "alice"'
        assert error is not None
        assert not protocol.authenticated

    async def test_an_unknown_user_gets_the_same_answer_as_a_wrong_password(self):
        # Otherwise the error tells an attacker which accounts exist.
        known, _, _ = await run_startup(
            startup_message("alice") + password_message("wrong"), StubVerifier()
        )
        unknown, _, _ = await run_startup(
            startup_message("mallory") + password_message("wrong"), StubVerifier()
        )
        a, b = error_fields(known), error_fields(unknown)
        assert a["C"] == b["C"] == "28P01"
        assert a["M"].replace("alice", "X") == b["M"].replace("mallory", "X")

    async def test_an_empty_password_is_refused_without_asking_iris(self):
        verifier = StubVerifier()
        out, _, _ = await run_startup(startup_message("alice") + password_message(""), verifier)
        assert error_fields(out)["C"] == "28P01"
        assert verifier.calls == []

    async def test_no_user_in_the_startup_packet_is_refused_before_any_prompt(self):
        verifier = StubVerifier()
        out, _, _ = await run_startup(startup_message(None), verifier)
        assert error_fields(out)["C"] == "28000"
        assert auth_codes(out) == []
        assert verifier.calls == []

    async def test_a_reply_that_is_not_a_password_message_is_a_protocol_violation(self):
        junk = b"Q" + struct.pack("!I", 5) + b"\x00"
        out, _, _ = await run_startup(startup_message("alice") + junk, StubVerifier())
        assert AUTH_OK not in auth_codes(out)
        assert error_fields(out)["C"] == "08P01"

    async def test_when_iris_cannot_be_reached_the_client_is_not_told_the_password_was_wrong(self):
        verifier = StubVerifier(raises=AuthUnavailable("connection refused on 10.0.0.5:1972"))
        out, _, _ = await run_startup(
            startup_message("alice") + password_message("right"), verifier
        )
        fields = error_fields(out)
        assert AUTH_OK not in auth_codes(out)
        assert fields["C"] == "57P03"
        assert "10.0.0.5" not in fields["M"], "internal addresses must not reach the client"
        assert "password authentication failed" not in fields["M"]


class TestTransportRequirement:
    async def test_plaintext_is_refused_before_the_password_is_requested(self):
        verifier = StubVerifier()
        out, _, _ = await run_startup(
            startup_message("alice") + password_message("right"),
            verifier,
            ssl_enabled=False,
            allow_plaintext_password=False,
        )
        assert auth_codes(out) == [], "a password prompt over plaintext invites sending it"
        fields = error_fields(out)
        assert fields["C"] == "28000"
        assert "TLS" in fields["M"]
        assert verifier.calls == []

    async def test_tls_satisfies_the_requirement(self):
        out, error, _ = await run_startup(
            startup_message("alice") + password_message("right"),
            StubVerifier(),
            ssl_enabled=True,
            allow_plaintext_password=False,
        )
        assert error is None
        assert auth_codes(out)[:2] == [AUTH_CLEARTEXT, AUTH_OK]

    async def test_the_explicit_flag_allows_plaintext(self):
        out, error, _ = await run_startup(
            startup_message("alice") + password_message("right"),
            StubVerifier(),
            ssl_enabled=False,
            allow_plaintext_password=True,
        )
        assert error is None
        assert AUTH_OK in auth_codes(out)


class TestTrustMode:
    async def test_trust_authenticates_immediately_and_never_calls_the_verifier(self):
        verifier = StubVerifier()
        out, error, _ = await run_startup(
            startup_message("anyone"),
            verifier,
            auth_mode="trust",
            allow_plaintext_password=False,
        )
        assert error is None
        assert auth_codes(out)[0] == AUTH_OK
        assert verifier.calls == []

    async def test_password_mode_without_a_verifier_fails_closed(self):
        out, _, _ = await run_startup(
            startup_message("alice") + password_message("right"), verifier=None
        )
        assert AUTH_OK not in auth_codes(out)


# ---------------------------------------------------------------------------
# Verifier failure classification, against a real unreachable target
# ---------------------------------------------------------------------------


class TestVerifiersDoNotMistakeAnOutageForAWrongPassword:
    async def test_dbapi_verifier_raises_unavailable_when_iris_is_unreachable(self):
        # Port 1 on loopback: nothing listens there.
        verifier = DbapiPasswordVerifier("127.0.0.1", 1, "USER", timeout=10)
        with pytest.raises(AuthUnavailable):
            await verifier.verify("_SYSTEM", "SYS")

    async def test_embedded_verifier_raises_unavailable_when_the_check_cannot_run(self):
        # On a host without embedded IRIS the child process cannot call %SYSTEM.Security.Login.
        # That is "could not check", never "checked and denied".
        verifier = EmbeddedPasswordVerifier(python=sys.executable, timeout=30)
        with pytest.raises(AuthUnavailable):
            await verifier.verify("_SYSTEM", "SYS")

    async def test_embedded_verifier_does_not_put_the_password_on_the_command_line(self):
        import inspect

        source = inspect.getsource(EmbeddedPasswordVerifier)
        assert "stdin" in source or "input=" in source


class TestVerifierDoesNotTrustAConnectionThatMerelyExists:
    """A stand-in `iris.dbapi` must never turn into a successful login.

    `iris-embedded-python-wrapper` answers any attribute with a MagicMock, and other tests leave a
    fake `iris.dbapi` in `sys.modules`. A verifier that took "connect() returned" for success would
    accept every password on such a host. It confirms with a query whose answer a stand-in cannot
    produce, and fails closed otherwise.
    """

    @staticmethod
    def install(monkeypatch, connection):
        import types

        module = types.ModuleType("iris.dbapi")
        module.connect = lambda **kwargs: connection
        monkeypatch.setitem(sys.modules, "iris.dbapi", module)
        import iris

        monkeypatch.setattr(iris, "dbapi", module, raising=False)

    async def test_a_mock_connection_is_not_a_successful_login(self, monkeypatch):
        from unittest.mock import MagicMock

        self.install(monkeypatch, MagicMock())
        with pytest.raises(AuthUnavailable):
            await DbapiPasswordVerifier("h", 1, "USER").verify("anyone", "anything")

    async def test_a_connection_whose_query_returns_junk_is_not_a_successful_login(
        self, monkeypatch
    ):
        class Cursor:
            def execute(self, sql, *args):
                pass

            def fetchone(self):
                return ("not-one",)

        class Connection:
            def cursor(self):
                return Cursor()

            def close(self):
                pass

        self.install(monkeypatch, Connection())
        with pytest.raises(AuthUnavailable):
            await DbapiPasswordVerifier("h", 1, "USER").verify("anyone", "anything")

    async def test_a_connection_that_answers_select_1_is_a_successful_login(self, monkeypatch):
        closed = []

        class Cursor:
            def execute(self, sql, *args):
                self.sql = sql

            def fetchone(self):
                return (1,)

        class Connection:
            def cursor(self):
                return Cursor()

            def close(self):
                closed.append(True)

        self.install(monkeypatch, Connection())
        assert await DbapiPasswordVerifier("h", 1, "USER").verify("alice", "right") is True
        assert closed, "the verification connection must be closed, it costs a licence unit"


# ---------------------------------------------------------------------------
# Who may log in
# ---------------------------------------------------------------------------


class TestResolveAllowedUsers:
    """A correct password proves the client knows an IRIS user's password. It does not make that
    user safe to run as the service account, so by default only the service account may log in."""

    def test_unset_means_only_the_service_account(self):
        assert resolve_allowed_users(None, "_SYSTEM") == frozenset({"_system"})
        assert resolve_allowed_users("", "_SYSTEM") == frozenset({"_system"})
        assert resolve_allowed_users("  ", "_SYSTEM") == frozenset({"_system"})

    def test_a_list_replaces_the_default_it_does_not_extend_it(self):
        assert resolve_allowed_users("alice,bob", "_SYSTEM") == frozenset({"alice", "bob"})

    def test_whitespace_empty_entries_and_case_are_ignored(self):
        assert resolve_allowed_users(" Alice , ,BOB,", "_SYSTEM") == frozenset({"alice", "bob"})

    def test_a_sequence_is_accepted(self):
        assert resolve_allowed_users(["Alice", "bob"], "_SYSTEM") == frozenset({"alice", "bob"})

    def test_a_list_of_only_blanks_falls_back_to_the_default(self):
        assert resolve_allowed_users(" , ,", "_SYSTEM") == frozenset({"_system"})


class TestAllowedUsersAtLogin:
    async def test_a_user_who_is_not_allowed_is_refused_exactly_like_a_wrong_password(self):
        # Otherwise the answer tells a stranger which accounts are on the list.
        allowed = frozenset({"alice"})
        refused, _, _ = await run_startup(
            startup_message("bob") + password_message("right"),
            StubVerifier(user="bob", password="right"),
            allowed_users=allowed,
        )
        wrong, _, _ = await run_startup(
            startup_message("alice") + password_message("wrong"),
            StubVerifier(),
            allowed_users=allowed,
        )
        a, b = error_fields(refused), error_fields(wrong)
        assert a["C"] == b["C"] == "28P01"
        assert a["M"].replace("bob", "X") == b["M"].replace("alice", "X")
        assert AUTH_OK not in auth_codes(refused)

    async def test_a_user_who_is_not_allowed_never_reaches_iris(self):
        # IRIS locks accounts after repeated failures; do not let strangers spend its attempts.
        verifier = StubVerifier(user="bob", password="right")
        out, _, _ = await run_startup(
            startup_message("bob") + password_message("right"),
            verifier,
            allowed_users=frozenset({"alice"}),
        )
        assert verifier.calls == []
        assert auth_codes(out) == [AUTH_CLEARTEXT], "still asked for a password, so it is not a tell"

    async def test_an_allowed_user_with_the_right_password_logs_in(self):
        out, error, _ = await run_startup(
            startup_message("alice") + password_message("right"),
            StubVerifier(),
            allowed_users=frozenset({"alice"}),
        )
        assert error is None
        assert auth_codes(out)[:2] == [AUTH_CLEARTEXT, AUTH_OK]

    async def test_the_comparison_ignores_case_and_the_verifier_gets_the_name_as_sent(self):
        verifier = StubVerifier(user="ALICE", password="right")
        out, _, _ = await run_startup(
            startup_message("ALICE") + password_message("right"),
            verifier,
            allowed_users=frozenset({"alice"}),
        )
        assert verifier.calls == [("ALICE", "right")]
        assert AUTH_OK in auth_codes(out)

    async def test_no_allowlist_means_no_restriction_at_this_layer(self):
        verifier = StubVerifier(user="anyone", password="right")
        out, _, _ = await run_startup(
            startup_message("anyone") + password_message("right"), verifier, allowed_users=None
        )
        assert AUTH_OK in auth_codes(out)

    async def test_a_refusal_for_a_user_not_allowed_takes_as_long_as_a_real_failed_login(self):
        # IRIS delays a failed login by about two seconds. A refusal that skips IRIS must not be
        # recognisably faster, or the timing gives the allowlist away.
        import time

        started = time.perf_counter()
        await run_startup(
            startup_message("bob") + password_message("right"),
            StubVerifier(),
            allowed_users=frozenset({"alice"}),
            failed_login_delay=0.3,
        )
        assert time.perf_counter() - started >= 0.3
