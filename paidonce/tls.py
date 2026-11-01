"""TLS for the payments service: a self-signed certificate it serves, and the trust its callers verify it against.

The certificate is generated once, under data/tls/ (gitignored), the first time the show or the payments service
starts. Callers do not skip verification: they load the certificate as their only trust anchor, so a different
certificate on that port fails the handshake. Only the payments service has its private key (payments.pem, 0600);
callers read the public certificate (payments.crt).

PAIDONCE_PAYMENTS_TLS=0 turns this off and serves plain HTTP. The tests do that, because they start the payments app on
a free port without a certificate.
"""

from __future__ import annotations

import datetime
import ipaddress
import os
import ssl
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from paidonce import config

VALID_DAYS = 365
RENEW_BEFORE_DAYS = 30


def server_pem() -> Path:
    """Private key + certificate: the payments service only."""
    return config.TLS_DIR / "payments.pem"


def cert_path() -> Path:
    """The certificate alone: what callers trust."""
    return config.TLS_DIR / "payments.crt"


def _fresh() -> bool:
    """Both files exist and the certificate has more than RENEW_BEFORE_DAYS left."""
    try:
        cert = x509.load_pem_x509_certificate(cert_path().read_bytes())
        left = cert.not_valid_after_utc - datetime.datetime.now(datetime.UTC)
        return server_pem().is_file() and left > datetime.timedelta(days=RENEW_BEFORE_DAYS)
    except (OSError, ValueError):
        return False


def _generate() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "paid-once payments (self-signed)")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    x509.IPAddress(ipaddress.ip_address("::1")),
                ]
            ),
            critical=False,
        )
        # Self-signed, so it is its own trust anchor: a CA certificate that may sign itself and a server.
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    # Write beside the target and rename, so a reader never sees half a file. The private key goes first, 0600.
    for path, data, mode in ((server_pem(), key_pem + cert_pem, 0o600), (cert_path(), cert_pem, 0o644)):
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)


def ensure_certs() -> Path:
    """Create the certificate if it is missing or close to expiry. Safe to call from several processes at once."""
    config.TLS_DIR.mkdir(parents=True, exist_ok=True)
    if _fresh():
        return cert_path()
    try:
        import fcntl
    except ImportError:  # no flock (Windows): the show server generates it before it starts anything else
        _generate()
        return cert_path()
    with open(config.TLS_DIR / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not _fresh():  # another process may have generated it while we waited
            _generate()
    return cert_path()


def server_ssl_kwargs() -> dict:
    """What uvicorn needs to serve the payments service over HTTPS, or nothing when TLS is off."""
    if not config.PAYMENTS_TLS:
        return {}
    ensure_certs()
    return {"ssl_certfile": str(server_pem()), "ssl_keyfile": str(server_pem())}


@lru_cache(maxsize=1)
def _trust() -> ssl.SSLContext:
    cert = cert_path()
    if not cert.is_file():
        raise FileNotFoundError(
            f"{cert} not found: the payments certificate is created when the show or the payments service starts"
        )
    return ssl.create_default_context(cafile=str(cert))  # this certificate only: no system roots


def client_verify(url: str | None = None):
    """The `verify` argument for an httpx call to payments: the pinned certificate for https, the default otherwise."""
    return _trust() if (url or config.PAYMENTS_URL).startswith("https://") else True
