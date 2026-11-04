"""Capture: redaction at write time, reference resolution, and skipping."""

from __future__ import annotations

import httpx
import pytest

from compatlab.capture import (
    CaptureError,
    RawCall,
    UnresolvedReference,
    capture_scenario,
    dig,
    record,
    resolve,
    split_query,
    template_of,
    to_record,
)
from compatlab.redaction import REDACTED, STRIPE_POLICY
from compatlab.scenarios import parse

POLICY = STRIPE_POLICY.with_salt(b"test-salt")


def make_client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://api.example.test",
                        transport=httpx.MockTransport(handler))


def test_record_redacts_the_body_and_whitelists_headers():
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
                     "/v1/payment_intents", {"amount": "1099"}, seq=0,
                     policy=POLICY)
    assert rec["response"]["body"]["client_secret"] == REDACTED
    assert rec["response"]["body"]["amount"] == 1099
    assert set(rec["response"]["headers"]) == {"request-id", "stripe-version"}
    assert rec["stripe_version"] == "2022-11-15"
    assert rec["response"]["status"] == 200
    assert rec["redaction"]["policy"] == "stripe"


def test_the_request_template_is_redacted_too():
    # Found by the first live capture: the template is where a scenario's
    # literal field values live, so storing it raw leaks what the response
    # path redacted.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "cus_1"})

    with make_client(handler) as client:
        rec = record(client, "2022-11-15", "create_customer", "POST",
                     "/v1/customers", {"email": "ada@lovelace.org"}, seq=0,
                     policy=POLICY)
    assert "lovelace" not in str(rec)
    assert rec["request_template"]["email"] == rec["request_body"]["email"]
    assert POLICY.scan(rec) == []


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


def test_dig_walks_objects_and_list_indexes():
    payload = {"data": [{"id": "cus_1"}, {"id": "cus_2"}]}
    assert dig(payload, "data.1.id") == "cus_2"
    with pytest.raises(UnresolvedReference):
        dig(payload, "data.9.id")
    with pytest.raises(UnresolvedReference):
        dig({"id": None}, "id")


def test_resolve_substitutes_every_reference():
    outputs = {"a": {"id": "cus_1"}, "b": {"data": [{"id": "pi_9"}]}}
    assert resolve("/v1/x/{{a.id}}?after={{b.data.0.id}}", outputs) == \
        "/v1/x/cus_1?after=pi_9"


def test_split_query_and_template_collapse_ids():
    assert split_query("/v1/customers?limit=2&expand[]=total_count") == \
        ("/v1/customers", {"limit": "2", "expand[]": "total_count"})
    assert template_of("/v1/payment_intents/{{create_pi.id}}/capture") == \
        "/v1/payment_intents/{id}/capture"
    # A literal id groups the same way as a reference.
    assert template_of("/v1/customers/cus_MISSING000000") == "/v1/customers/{id}"
    assert template_of("/v1/invoices/upcoming?customer=cus_1") == \
        "/v1/invoices/upcoming"


SCENARIO = parse({
    "workflow": "w",
    "description": "d",
    "targets": ["M1"],
    "steps": [
        {"step": "create", "method": "POST", "path": "/v1/customers",
         "body": {"email": "ada@lovelace.org"}},
        {"step": "fetch", "method": "GET", "path": "/v1/customers/{{create.id}}"},
    ],
})


def test_capture_scenario_resolves_references_against_the_raw_response():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"id": "cus_live_1",
                                         "email": "ada@lovelace.org"})

    with make_client(handler) as client:
        report = capture_scenario(client, SCENARIO, "2022-11-15", policy=POLICY)

    # The surrogate is not a usable object id, so resolution must see the raw
    # response — but nothing raw may reach the record.
    assert seen[1].endswith("/v1/customers/cus_live_1")
    assert [r["seq"] for r in report.records] == [0, 1]
    assert [r["step"] for r in report.records] == ["create", "fetch"]
    assert report.records[0]["targets"] == ["M1"]
    assert report.records[1]["path_template"] == "/v1/customers/{id}"
    assert report.records[1]["path_reference"] == "/v1/customers/{{create.id}}"
    assert "lovelace" not in str(report.records)


def test_a_step_whose_reference_is_unresolvable_is_skipped_and_reported():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "nope"}})

    with make_client(handler) as client:
        report = capture_scenario(client, SCENARIO, "2022-11-15", policy=POLICY)

    # The failing call is still captured — error semantics are a diff axis —
    # but the dependent step is skipped rather than sent with a guessed id.
    assert [r["step"] for r in report.records] == ["create"]
    assert report.skipped == [("w.fetch", "id: no key 'id'")]
    assert len(report.failures) == 1


def test_a_record_carries_the_call_duration_for_the_timing_axis():
    """Stored so the differ has something to read; never scored (ADR 0004 D7)."""
    raw = RawCall(method="GET", path="/v1/customers", query={}, body=None,
                  version="2022-11-15", status=200, headers={}, payload={},
                  duration_ms=123.456)
    record = to_record(raw, seq=0, workflow="w", step="s",
                       path_template="/v1/customers", request_template=None,
                       path_reference="/v1/customers")
    assert record["duration_ms"] == 123.5
