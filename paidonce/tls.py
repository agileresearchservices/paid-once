"""TLS for the payments service and the Lane 1 API: a self-signed certificate each serves, and the trust their callers
verify it against.

Each service has its own certificate and key, generated once under data/tls/ (gitignored) the first time the show or
the service starts. Callers do not skip verification: they load the certificate of the service they call as their only
trust anchor, so a different certificate on that port fails the handshake, and the payments certificate does not open
the Lane 1 API. Only a service has its private key (<name>.pem, 0600); callers read the public certificate
(<name>.crt).

PAIDONCE_PAYMENTS_TLS=0 and PAIDONCE_LANE1_TLS=0 serve that service over plain HTTP. The tests do that for the
payments app, which they start on a free port without a certificate.
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

SERVICES = ("payments", "lane1_api")
VALID_DAYS = 365
RENEW_BEFORE_DAYS = 30


def server_pem(service: str) -> Path:
    """Private key + certificate: that service only."""
    return config.TLS_DIR / f"{service}.pem"


def cert_path(service: str) -> Path:
    """The certificate alone: what callers of the service trust."""
    return config.TLS_DIR / f"{service}.crt"


def _fresh(service: str) -> bool:
    """Both files exist and the certificate has more than RENEW_BEFORE_DAYS left."""
    try:
        cert = x509.load_pem_x509_certificate(cert_path(service).read_bytes())
        left = cert.not_valid_after_utc - datetime.datetime.now(datetime.UTC)
        return server_pem(service).is_file() and left > datetime.timedelta(days=RENEW_BEFORE_DAYS)
    except (OSError, ValueError):
        return False


def _generate(service: str) -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"paid-once {service} (self-signed)")])
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
    for path, data, mode in ((server_pem(service), key_pem + cert_pem, 0o600), (cert_path(service), cert_pem, 0o644)):
        tmp = path.with_suffix(path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)


def ensure_certs() -> Path:
    """Create each service's certificate if it is missing or close to expiry. Safe to call from several processes."""
    config.TLS_DIR.mkdir(parents=True, exist_ok=True)

    def make_stale() -> None:
        for service in SERVICES:
            if not _fresh(service):
                _generate(service)

    if all(_fresh(service) for service in SERVICES):
        return config.TLS_DIR
    try:
        import fcntl
    except ImportError:  # no flock (Windows): the show server generates them before it starts anything else
        make_stale()
        return config.TLS_DIR
    with open(config.TLS_DIR / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        make_stale()  # another process may have generated them while we waited: only stale ones are made
    return config.TLS_DIR


def _enabled(service: str) -> bool:
    return config.PAYMENTS_TLS if service == "payments" else config.LANE1_TLS


def _url(service: str) -> str:
    return config.PAYMENTS_URL if service == "payments" else config.LANE1_URL


def server_ssl_kwargs(service: str) -> dict:
    """What uvicorn needs to serve `service` over HTTPS, or nothing when its TLS is off."""
    if not _enabled(service):
        return {}
    ensure_certs()
    return {"ssl_certfile": str(server_pem(service)), "ssl_keyfile": str(server_pem(service))}


@lru_cache(maxsize=4)
def _trust(services: tuple[str, ...]) -> ssl.SSLContext:
    certs = [cert_path(service) for service in services]
    for cert in certs:
        if not cert.is_file():
            raise FileNotFoundError(f"{cert} not found: the certificate is created when the show or the service starts")
    context = ssl.create_default_context(cafile=str(certs[0]))  # a cafile means no system roots
    for cert in certs[1:]:
        context.load_verify_locations(cafile=str(cert))
    return context


def client_verify(*services: str):
    """The `verify` argument for an httpx client that calls `services` (default: payments).

    For each service served over https it trusts that service's certificate and nothing else; if none is, httpx's
    default."""
    services = services or ("payments",)
    secure = tuple(s for s in services if _url(s).startswith("https://"))
    return _trust(secure) if secure else True
