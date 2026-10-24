"""E2E: what a client must prove before iris-pgwire lets it in, against a real IRIS.

Until 2026-10-24 the default launch was trust: `AuthenticationOk` was the first reply and the
password was ignored, and the SCRAM path never checked the client proof (research in
`specs/051-unified-executor/research.md`, measured over a raw socket). Authentication is now
required by default: the server asks for the password (`AuthenticationCleartextPassword`) and
checks it by logging into IRIS with it. TLS is required unless an explicit flag allows plaintext,
and trust is an explicit opt-in.

These tests drive real servers with real clients (psycopg and a raw socket), one posture each:

    python tests/e2e/_auth_server.py 5451 password    # password auth, plaintext allowed
    python tests/e2e/_auth_server.py 5452 tls         # password auth over TLS only
    python tests/e2e/_auth_server.py 5453 trust       # --trust
    python tests/e2e/_auth_server.py 5454 allowlist   # only SuperUser may log in
    PGWIRE_AUTH_TARGETS="password=127.0.0.1:5451,tls=127.0.0.1:5452,trust=127.0.0.1:5453,allowlist=127.0.0.1:5454" \\
        pytest --noconftest tests/e2e/test_auth_defaults.py

Start the servers one at a time. For the embedded backend, run the helper inside the IRIS
container with `backend=embedded` and point the targets at it (see the memory note on testing the
embedded backend); the same file runs unchanged.
"""

import os
import socket
import struct

import psycopg
import pytest


def _targets() -> dict[str, tuple[str, int]]:
    out = {}
    spec = os.environ.get("PGWIRE_AUTH_TARGETS", "")
    for item in filter(None, (s.strip() for s in spec.split(","))):
        kind, _, address = item.partition("=")
        host, _, port = address.rpartition(":")
        out[kind] = (host, int(port))
    return out


TARGETS = _targets()
USER = os.environ.get("PGWIRE_USER", "_SYSTEM")
PASSWORD = os.environ.get("PGWIRE_PASSWORD", "SYS")

AUTH_OK, AUTH_CLEARTEXT = 0, 3


def _need(kind: str) -> tuple[str, int]:
    if kind not in TARGETS:
        pytest.skip(f"set PGWIRE_AUTH_TARGETS={kind}=host:port")
    return TARGETS[kind]


def connect(kind: str, *, user=USER, password=PASSWORD, sslmode="disable"):
    host, port = _need(kind)
    return psycopg.connect(
        host=host, port=port, user=user, password=password, dbname="USER", sslmode=sslmode,
        connect_timeout=30,
    )


def refusal(kind: str, **kwargs) -> psycopg.OperationalError:
    with pytest.raises(psycopg.OperationalError) as raised:
        connect(kind, **kwargs)
    return raised.value


def first_reply(kind: str, user: str) -> tuple[bytes, bytes]:
    """The first message a server sends after the startup packet, over plaintext."""
    host, port = _need(kind)
    sock = socket.create_connection((host, port), timeout=15)
    try:
        params = b"user\0" + user.encode() + b"\0database\0USER\0\0"
        sock.sendall(struct.pack("!II", 8 + len(params), 196608) + params)
        kind_byte = sock.recv(1)
        (length,) = struct.unpack("!I", sock.recv(4))
        body = b""
        while len(body) < length - 4:
            body += sock.recv(length - 4 - len(body))
        return kind_byte, body
    finally:
        sock.close()


def read_message(sock: socket.socket) -> tuple[bytes, bytes]:
    def exact(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise EOFError
            buf += chunk
        return buf

    kind = exact(1)
    (length,) = struct.unpack("!I", exact(4))
    return kind, exact(length - 4)


def raw_login(kind: str, user: str, password: str) -> dict:
    """Answer the password prompt by hand. libpq will not send an empty password and psycopg
    does not expose a connect-time SQLSTATE, so the exact refusal is read off the wire."""
    host, port = _need(kind)
    sock = socket.create_connection((host, port), timeout=60)
    try:
        params = b"user\0" + user.encode() + b"\0database\0USER\0\0"
        sock.sendall(struct.pack("!II", 8 + len(params), 196608) + params)
        msg_kind, body = read_message(sock)
        assert (msg_kind, struct.unpack("!I", body[:4])[0]) == (b"R", AUTH_CLEARTEXT)
        reply = password.encode() + b"\0"
        sock.sendall(b"p" + struct.pack("!I", 4 + len(reply)) + reply)
        result = {"authenticated": False, "sqlstate": None, "message": None}
        while True:
            try:
                msg_kind, body = read_message(sock)
            except EOFError:
                return result
            if msg_kind == b"R" and struct.unpack("!I", body[:4])[0] == AUTH_OK:
                result["authenticated"] = True
            if msg_kind == b"E":
                for field in body.split(b"\0"):
                    if field[:1] == b"C":
                        result["sqlstate"] = field[1:].decode()
                    if field[:1] == b"M":
                        result["message"] = field[1:].decode()
                return result
            if msg_kind == b"Z":
                return result
    finally:
        sock.close()


class TestPasswordIsRequiredByDefault:
    def test_a_stranger_is_asked_for_a_password_not_waved_through(self):
        kind, body = first_reply("password", "a_user_that_does_not_exist")
        assert kind == b"R"
        assert struct.unpack("!I", body[:4])[0] == AUTH_CLEARTEXT

    def test_the_right_password_logs_in(self):
        with connect("password") as conn:
            assert conn.execute("select 1").fetchone() == (1,)

    def test_a_wrong_password_is_refused_with_28P01(self):
        assert "password authentication failed" in str(
            refusal("password", password="definitely-not-the-password")
        )
        result = raw_login("password", USER, "definitely-not-the-password")
        assert not result["authenticated"]
        assert result["sqlstate"] == "28P01"

    def test_an_unknown_user_is_refused_exactly_like_a_wrong_password(self):
        # The text must not reveal which accounts exist.
        wrong = raw_login("password", USER, "definitely-not-the-password")
        unknown = raw_login("password", "nobody_xyz", "x")
        assert not wrong["authenticated"] and not unknown["authenticated"]
        assert wrong["sqlstate"] == unknown["sqlstate"] == "28P01"
        assert wrong["message"].replace(USER, "U") == unknown["message"].replace("nobody_xyz", "U")

    def test_an_empty_password_is_refused(self):
        result = raw_login("password", USER, "")
        assert not result["authenticated"]
        assert result["sqlstate"] == "28P01"


class TestWhoMayLogIn:
    """A correct password proves the client knows an IRIS user's password. Statements still run as
    the service account, so letting every IRIS user in would hand each of them its privileges.
    By default only the service account may log in."""

    def test_by_default_another_real_iris_user_with_the_right_password_is_refused(self):
        # SuperUser exists in the test IRIS and `SYS` is its real password.
        result = raw_login("password", "SuperUser", "SYS")
        assert not result["authenticated"]
        assert result["sqlstate"] == "28P01"

    def test_that_refusal_reads_exactly_like_a_wrong_password(self):
        unlisted = raw_login("password", "SuperUser", "SYS")
        wrong = raw_login("password", USER, "definitely-not-the-password")
        assert unlisted["message"].replace("SuperUser", "U") == wrong["message"].replace(USER, "U")

    def test_a_listed_user_with_the_right_password_logs_in(self):
        with connect("allowlist", user="SuperUser", password="SYS") as conn:
            assert conn.execute("select 1").fetchone() == (1,)

    def test_a_list_replaces_the_default_so_the_service_account_is_refused_too(self):
        result = raw_login("allowlist", USER, PASSWORD)
        assert not result["authenticated"]
        assert result["sqlstate"] == "28P01"

    def test_a_listed_user_with_a_wrong_password_is_still_refused(self):
        assert raw_login("allowlist", "SuperUser", "nope")["sqlstate"] == "28P01"


class TestTransport:
    def test_tls_with_the_right_password_logs_in(self):
        with connect("tls", sslmode="require") as conn:
            assert conn.pgconn.ssl_in_use
            assert conn.execute("select 1").fetchone() == (1,)

    def test_tls_with_a_wrong_password_is_refused(self):
        error = refusal("tls", sslmode="require", password="definitely-not-the-password")
        assert "password authentication failed" in str(error)

    def test_plaintext_is_refused_before_a_password_is_ever_requested(self):
        kind, body = first_reply("tls", USER)
        assert kind == b"E", "the server must refuse, not prompt for a password over plaintext"
        assert b"TLS" in body
        error = refusal("tls", sslmode="disable")
        assert "TLS" in str(error)


class TestTrustIsAnExplicitOptIn:
    def test_trust_accepts_any_password(self):
        with connect("trust", password="definitely-not-the-password") as conn:
            assert conn.execute("select 1").fetchone() == (1,)

    def test_trust_does_not_ask_for_a_password(self):
        kind, body = first_reply("trust", "anyone")
        assert (kind, struct.unpack("!I", body[:4])[0]) == (b"R", AUTH_OK)
