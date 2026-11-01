"""The payments service and the Lane 1 API over HTTPS with self-signed certificates, and callers that verify them."""

import datetime
import ssl
import stat

import httpx
import pytest
from cryptography import x509

from paidonce import audit, config, tls
from paidonce.lane1 import api as lane1_api
from paidonce.lane1.graph import call_payments
from paidonce.payments import ledger
from paidonce.payments.service import app as payments_app
from tests.helpers import Server

SERVICES = ["payments", "lane1_api"]


@pytest.fixture(autouse=True)
def fresh_trust():
    tls._trust.cache_clear()
    yield
    tls._trust.cache_clear()


def https_server(app, service):
    """`app` served over HTTPS with `service`'s certificate. Its readiness probe trusts only that certificate."""
    tls.ensure_certs()
    return Server(
        app,
        ssl_certfile=str(tls.server_pem(service)),
        ssl_keyfile=str(tls.server_pem(service)),
        verify=tls._trust((service,)),
    )


@pytest.fixture
def https_payments(monkeypatch):
    with https_server(payments_app, "payments") as srv:
        monkeypatch.setattr(config, "PAYMENTS_URL", srv.url)
        yield srv


@pytest.fixture
def https_lane1(monkeypatch):
    with https_server(lane1_api.app, "lane1_api") as srv:
        monkeypatch.setattr(config, "LANE1_URL", srv.url)
        yield srv


@pytest.mark.parametrize("service", SERVICES)
def test_certificate_names_the_loopback_addresses(service):
    tls.ensure_certs()
    cert = x509.load_pem_x509_certificate(tls.cert_path(service).read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "127.0.0.1" in {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    assert "localhost" in san.get_values_for_type(x509.DNSName)
    assert cert.not_valid_after_utc - datetime.datetime.now(datetime.UTC) > datetime.timedelta(days=300)


@pytest.mark.parametrize("service", SERVICES)
def test_private_key_is_for_the_service_only(service):
    tls.ensure_certs()
    assert stat.S_IMODE(tls.server_pem(service).stat().st_mode) == 0o600
    assert b"PRIVATE KEY" in tls.server_pem(service).read_bytes()
    assert b"PRIVATE KEY" not in tls.cert_path(service).read_bytes()  # what callers read


def test_each_service_has_its_own_certificate():
    tls.ensure_certs()
    assert tls.cert_path("payments").read_bytes() != tls.cert_path("lane1_api").read_bytes()


def test_certificates_are_created_once_and_reused():
    tls.ensure_certs()
    first = {s: tls.cert_path(s).read_bytes() for s in SERVICES}
    tls.ensure_certs()
    assert {s: tls.cert_path(s).read_bytes() for s in SERVICES} == first


def test_a_certificate_close_to_expiry_is_replaced(monkeypatch):
    tls.ensure_certs()
    first = tls.cert_path("payments").read_bytes()
    monkeypatch.setattr(tls, "RENEW_BEFORE_DAYS", 400)  # a 365-day certificate now counts as expiring
    tls.ensure_certs()
    assert tls.cert_path("payments").read_bytes() != first


def test_a_caller_that_trusts_the_certificate_reaches_payments(https_payments):
    assert httpx.get(f"{https_payments.url}/healthz", verify=tls.client_verify()).status_code == 200


def test_a_caller_that_trusts_the_certificate_reaches_the_lane1_api(https_lane1):
    assert httpx.get(f"{https_lane1.url}/healthz", verify=tls.client_verify("lane1_api")).status_code == 200


def test_a_caller_with_only_the_system_roots_refuses_the_certificate(https_payments):
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        httpx.get(f"{https_payments.url}/healthz")


def test_the_payments_certificate_does_not_open_the_lane1_api(https_lane1):
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        httpx.get(f"{https_lane1.url}/healthz", verify=tls._trust(("payments",)))


def test_one_client_can_trust_both_services(https_payments, https_lane1):
    verify = tls.client_verify("payments", "lane1_api")
    assert httpx.get(f"{https_payments.url}/healthz", verify=verify).status_code == 200
    assert httpx.get(f"{https_lane1.url}/healthz", verify=verify).status_code == 200


def test_a_different_self_signed_certificate_is_refused(https_payments, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TLS_DIR", tmp_path / "other")
    tls.ensure_certs()  # a second, unrelated pair of certificates
    context = ssl.create_default_context(cafile=str(tls.cert_path("payments")))
    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
        httpx.get(f"{https_payments.url}/healthz", verify=context)


def test_plain_http_urls_need_no_trust_store(monkeypatch):
    monkeypatch.setattr(config, "PAYMENTS_URL", "http://127.0.0.1:1")
    assert tls.client_verify() is True


def test_missing_certificate_says_where_it_comes_from(monkeypatch):
    monkeypatch.setattr(config, "PAYMENTS_URL", "https://127.0.0.1:1")
    with pytest.raises(FileNotFoundError, match="created when the show or the service starts"):
        tls.client_verify()


@pytest.mark.parametrize(("service", "flag"), [("payments", "PAYMENTS_TLS"), ("lane1_api", "LANE1_TLS")])
def test_server_kwargs_are_empty_when_that_services_tls_is_off(service, flag, monkeypatch):
    assert set(tls.server_ssl_kwargs(service)) == {"ssl_certfile", "ssl_keyfile"}
    monkeypatch.setattr(config, flag, False)
    assert tls.server_ssl_kwargs(service) == {}


def test_urls_default_to_https():
    assert config.PAYMENTS_URL.startswith("https://")
    assert config.LANE1_URL.startswith("https://")


@pytest.mark.usefixtures("https_payments")
def test_lane1_refund_goes_over_https():
    audit.record_ticket("lane1", "t1", "test", 2500)
    assert call_payments("t1", 2500)
    assert len(ledger.all_refunds("lane1")) == 1


def test_a_ticket_reaches_the_lane1_api_over_https(https_lane1):
    body = {"ticket_id": "t1", "customer": "c", "order_id": "o", "amount_cents": 2500, "message": "broken"}
    r = httpx.post(f"{https_lane1.url}/tickets", json=body, verify=tls.client_verify("lane1_api"))
    assert r.json() == {"created": True}
