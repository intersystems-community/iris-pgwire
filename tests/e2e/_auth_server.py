"""Start one pgwire server in a given authentication posture, for tests/e2e/test_auth_defaults.py.

    python tests/e2e/_auth_server.py <port> <posture> [backend]

postures:
    password   password auth, plaintext allowed (the explicit opt-in); default login users
               (only the service account)
    allowlist  as password, but only SuperUser may log in (replaces the default list)
    tls        password auth, TLS enabled with a throwaway self-signed certificate,
               plaintext NOT allowed
    trust      no authentication (--trust)

Start one at a time: two servers installing the pg_catalog views at once collide on a
licence-limited IRIS.
"""

import asyncio
import datetime
import os
import sys
import tempfile

from iris_pgwire.server import PGWireServer


def self_signed(directory: str) -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = os.path.join(directory, "cert.pem"), os.path.join(directory, "key.pem")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
    return cert_path, key_path


async def main() -> None:
    port, posture = int(sys.argv[1]), sys.argv[2]
    backend = sys.argv[3] if len(sys.argv) > 3 else "dbapi"
    kwargs: dict = {}
    if posture == "password":
        kwargs = {"auth_mode": "password", "allow_plaintext_password": True}
    elif posture == "allowlist":
        kwargs = {
            "auth_mode": "password",
            "allow_plaintext_password": True,
            "allowed_users": "SuperUser",
        }
    elif posture == "tls":
        cert, key = self_signed(tempfile.mkdtemp(prefix="pgwire-tls-"))
        kwargs = {
            "auth_mode": "password",
            "enable_ssl": True,
            "ssl_cert_path": cert,
            "ssl_key_path": key,
        }
    elif posture == "trust":
        kwargs = {"auth_mode": "trust"}
    else:
        raise SystemExit(f"unknown posture {posture!r}")

    server = PGWireServer(
        host=os.environ.get("PGWIRE_HOST", "127.0.0.1"),
        port=port,
        iris_host=os.environ.get("IRIS_HOST", "127.0.0.1"),
        iris_port=int(os.environ.get("IRIS_PORT", "2972")),
        iris_username=os.environ.get("IRIS_USERNAME", "_SYSTEM"),
        iris_password=os.environ.get("IRIS_PASSWORD", "SYS"),
        iris_namespace=os.environ.get("IRIS_NAMESPACE", "USER"),
        backend_type=backend,
        connection_pool_size=2,
        **kwargs,
    )
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
