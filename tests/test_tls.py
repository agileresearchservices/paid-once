"""The payments service over HTTPS with a self-signed certificate, and callers that verify it."""

import datetime
import ssl
import stat

import httpx
import pytest
from cryptography import x509

from paidonce import audit, config, tls
from paidonce.lane1.graph import call_payments
from paidonce.payments import ledger
from paidonce.payments.service import app as payments_app
from tests.helpers import Server


@pytest.fixture(autouse=True)
def fresh_trust():
    tls._trust.cache_clear()
    yield
    tls._trust.cache_clear()


@pytest.fixture
def https_payments(monkeypatch):
    tls.ensure_certs()
    kwargs = {"ssl_certfile": str(tls.server_pem()), "ssl_keyfile": str(tls.server_pem()), "verify": tls._trust()}
    with Server(payments_app, **kwargs) as srv:
        monkeypatch.setattr(config, "PAYMENTS_URL", srv.url)
        yield srv


def test_certificate_names_the_loopback_addresses():
    tls.ensure_certs()
    cert = x509.load_pem_x509_certificate(tls.cert_path().read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "127.0.0.1" in {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert cert.not_valid_after_utc - datetime.datetime.now(datetime.UTC) > datetime.timedelta(days=300)


def test_private_key_is_for_the_payments_service_only():
    tls.ensure_certs()
    assert stat.S_IMODE(tls.server_pem().stat().st_mode) == 0o600
    assert b"PRIVATE KEY" in tls.server_pem().read_bytes()
    assert b"PRIVATE KEY" not in tls.cert_path().read_bytes()  # what callers read


def test_certificate_is_created_once_and_reused():
    tls.ensure_certs()
    first = tls.cert_path().read_bytes()
    tls.ensure_certs()
    assert tls.cert_path().read_bytes() == first


def test_certificate_close_to_expiry_is_replaced(monkeypatch):
    tls.ensure_certs()
    first = tls.cert_path().read_bytes()
    monkeypatch.setattr(tls, "RENEW_BEFORE_DAYS", 400)  # a 365-day certificate now counts as expiring
    tls.ensure_certs()
    assert tls.cert_path().read_bytes() != first


def test_a_caller_that_trusts_the_certificate_reaches_payments(https_payments):
    r = httpx.get(f"{https_payments.url}/healthz", verify=tls.client_verify())
    assert r.status_code == 200


def test_a_caller_with_only_the_system_roots_refuses_the_certificate(https_payments):
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        httpx.get(f"{https_payments.url}/healthz")


def test_a_different_self_signed_certificate_is_refused(https_payments, tmp_path, monkeypatch):
    other = tmp_path / "other"
    monkeypatch.setattr(config, "TLS_DIR", other)
    tls.ensure_certs()  # a second, unrelated certificate
    context = ssl.create_default_context(cafile=str(tls.cert_path()))
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        httpx.get(f"{https_payments.url}/healthz", verify=context)


def test_plain_http_urls_need_no_trust_store(monkeypatch):
    monkeypatch.setattr(config, "PAYMENTS_URL", "http://127.0.0.1:1")
    assert tls.client_verify() is True


def test_missing_certificate_says_where_it_comes_from():
    with pytest.raises(FileNotFoundError, match="created when the show or the payments service starts"):
        tls.client_verify("https://127.0.0.1:1")


def test_server_kwargs_are_empty_when_tls_is_off(monkeypatch):
    monkeypatch.setattr(config, "PAYMENTS_TLS", False)
    assert tls.server_ssl_kwargs() == {}


def test_lane1_refund_goes_over_https(https_payments):
    audit.record_ticket("lane1", "t1", "test", 2500)
    refund_id = call_payments("t1", 2500)
    assert refund_id
    assert len(ledger.all_refunds("lane1")) == 1
