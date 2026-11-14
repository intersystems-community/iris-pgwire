"""E2E: the IPM package's IrisPGWire.Service starts, refuses and stops the server for real.

Measured 2026-11-13 in a throwaway IRIS 2026.2 lab, with the package where IPM installs it
(`mgr/python/iris-pgwire/iris_pgwire/`):

- `Start()` could not have worked in any release: it ran `irispython -m iris_pgwire.server` from the
  IRIS process's directory, where the package is not importable (`No module named 'iris_pgwire'`).
- It printed "started successfully" before checking anything, then waited one second.
- It took no options, so under 2.0.0, where a server with no TLS and no explicit choice refuses
  to start, an IPM user had no way to start it.
- `Stop()` sent SIGTERM, which the server ignored, then reported failure. IPM's Deactivate phase
  calls Stop() with CheckStatus, so uninstalling failed.

These tests run *inside* IRIS, because that is where Start() runs, under irispython:

    docker cp ipm/IrisPGWire/Service.cls <lab>:/tmp/Service.cls
    docker cp tests/ipm/test_service_start.py <lab>:/tmp/
    docker exec -e IRISUSERNAME=_SYSTEM -e IRISPASSWORD=SYS -e IRISNAMESPACE=USER <lab> \\
        /usr/irissys/bin/irispython -m pytest -q /tmp/test_service_start.py

They need the package installed where IPM puts it, and pytest under irispython.
"""

from __future__ import annotations

import os
import socket
import struct
import time

import pytest

iris = pytest.importorskip("iris")

CLASS_FILE = os.environ.get("PGWIRE_SERVICE_CLS", "/tmp/Service.cls")
PORT = int(os.environ.get("PGWIRE_IPM_TEST_PORT", "5470"))
LOG = "/usr/irissys/mgr/iris-pgwire.log"


def service():
    return iris.cls("IrisPGWire.Service")


def ok(status) -> bool:
    return bool(iris.cls("%SYSTEM.Status").IsOK(status))


def error_text(status) -> str:
    return str(iris.cls("%SYSTEM.Status").GetErrorText(status))


def port_open(port: int = PORT) -> bool:
    with socket.socket() as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def first_auth_reply(port: int = PORT) -> int:
    """The authentication code the server sends a stranger: 3 = password, 0 = trust."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        params = b"user\0nobody\0database\0USER\0\0"
        sock.sendall(struct.pack("!II", 8 + len(params), 196608) + params)
        kind = sock.recv(1)
        assert kind == b"R", kind
        sock.recv(4)
        return struct.unpack("!I", sock.recv(4))[0]


@pytest.fixture(scope="module", autouse=True)
def loaded_class():
    status = iris.cls("%SYSTEM.OBJ").Load(CLASS_FILE, "ck-d")
    assert ok(status), error_text(status)
    yield
    service().Stop()


@pytest.fixture(autouse=True)
def stopped():
    service().Stop()
    deadline = time.time() + 15
    while port_open() and time.time() < deadline:
        time.sleep(0.5)
    yield
    service().Stop()


class TestStartRefusesClearly:
    def test_no_options_is_an_error_carrying_the_servers_own_reason(self):
        status = service().Start(0, 0, "", "", "", PORT, 30)
        assert not ok(status), "Start() must not report success for a server that refused"
        text = error_text(status)
        assert "TLS" in text and "--allow-plaintext-password" in text, text
        assert service().GetStatus() == "stopped"
        assert not port_open()

    @pytest.mark.parametrize(
        "users",
        ["alice; rm -rf /", "a b", "$(id)", "x`id`", "alice'bob"],
        ids=["semicolon", "space", "subshell", "backtick", "quote"],
    )
    def test_an_allowed_users_value_that_could_reach_the_shell_is_refused(self, users):
        status = service().Start(1, 0, users, "", "", PORT, 30)
        assert not ok(status)
        assert "pAllowedUsers" in error_text(status)
        assert not port_open()

    @pytest.mark.parametrize("port", [0, 70000, "abc"])
    def test_a_bad_port_is_refused(self, port):
        status = service().Start(1, 0, "", "", "", port, 30)
        assert not ok(status)
        assert "pPort" in error_text(status)

    def test_a_certificate_without_its_key_is_refused(self):
        status = service().Start(0, 0, "", "/tmp/cert.pem", "", PORT, 30)
        assert not ok(status)
        assert "pSSLKey" in error_text(status)


class TestStartAndStop:
    def test_plaintext_password_mode_starts_and_asks_for_a_password(self):
        status = service().Start(1, 0, "", "", "", PORT, 60)
        assert ok(status), error_text(status)
        assert service().GetStatus() == "running"
        assert port_open()
        assert first_auth_reply() == 3

    def test_trust_mode_starts_without_authentication(self):
        status = service().Start(0, 1, "", "", "", PORT, 60)
        assert ok(status), error_text(status)
        assert first_auth_reply() == 0

    def test_stop_stops_it_and_reports_success(self):
        assert ok(service().Start(1, 0, "", "", "", PORT, 60))
        status = service().Stop()
        assert ok(status), error_text(status)
        assert service().GetStatus() == "stopped"
        deadline = time.time() + 10
        while port_open() and time.time() < deadline:
            time.sleep(0.5)
        assert not port_open()

    def test_restart_keeps_the_options_it_was_started_with(self):
        assert ok(service().Start(1, 0, "", "", "", PORT, 60))
        status = service().Restart()
        assert ok(status), error_text(status)
        assert first_auth_reply() == 3, "Restart() must not drop to trust or to a refusal"

    def test_starting_twice_does_not_start_a_second_server(self):
        assert ok(service().Start(1, 0, "", "", "", PORT, 60))
        first = service().GetPID()
        assert ok(service().Start(1, 0, "", "", "", PORT, 60))
        assert service().GetPID() == first


def self_signed(directory: str) -> tuple[str, str]:
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256())
    )  # fmt: skip
    cert_path, key_path = os.path.join(directory, "c.pem"), os.path.join(directory, "k.pem")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))  # fmt: skip
    return cert_path, key_path


class TestStartWithTls:
    def test_tls_starts_and_offers_tls(self, tmp_path):
        cert, key = self_signed(str(tmp_path))
        status = service().Start(0, 0, "", cert, key, PORT, 60)
        assert ok(status), error_text(status)
        with socket.create_connection(("127.0.0.1", PORT), timeout=10) as sock:
            sock.sendall(struct.pack("!II", 8, 80877103))  # SSLRequest
            assert sock.recv(1) == b"S", "a TLS-enabled server must accept the upgrade"

    def test_a_path_with_a_quote_is_refused(self, tmp_path):
        status = service().Start(0, 0, "", "/tmp/it's.pem", "/tmp/k.pem", PORT, 30)
        assert not ok(status)
        assert "quote" in error_text(status)
