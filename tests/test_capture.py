from __future__ import annotations

import httpx
import pytest

from compatlab.capture import CaptureError, record
from compatlab.redact import REDACTED


def make_client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://api.example.test",
                        transport=httpx.MockTransport(handler))


def test_record_scrubs_body_and_whitelists_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Stripe-Version"] == "2022-11-15"
        return httpx.Response(
            200,
            headers={"request-id": "req_1", "stripe-version": "2022-11-15",
                     "server": "nginx", "set-cookie": "nope"},
            json={"id": "pi_1", "client_secret": "pi_1_secret_abc", "amount": 1099},
        )

    with make_client(handler) as client:
        rec = record(client, "2022-11-15", "create_pi", "POST",
                     "/v1/payment_intents", {"amount": "1099"}, seq=0)
    assert rec["response"]["body"]["client_secret"] == REDACTED
    assert rec["response"]["body"]["amount"] == 1099
    assert set(rec["response"]["headers"]) == {"request-id", "stripe-version"}
    assert rec["stripe_version"] == "2022-11-15"
    assert rec["response"]["status"] == 200


def test_record_wraps_non_json_bodies():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with make_client(handler) as client:
        rec = record(client, "2022-11-15", "call", "GET", "/v1/x", None, seq=0)
    assert rec["response"]["status"] == 502
    assert rec["response"]["body"]["_non_json_body"].startswith("<html>")


def test_record_raises_capture_error_on_transport_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with make_client(handler) as client:
        with pytest.raises(CaptureError, match="GET /v1/x"):
            record(client, "2022-11-15", "call", "GET", "/v1/x", None, seq=0)
