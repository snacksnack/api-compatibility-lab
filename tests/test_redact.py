from __future__ import annotations

from compatlab.redact import REDACTED, scrub


def test_client_secret_is_scrubbed_at_any_depth():
    out = scrub({"id": "pi_1", "client_secret": "pi_1_secret_abc",
                 "nested": {"client_secret": "deep"}})
    assert out["client_secret"] == REDACTED
    assert out["nested"]["client_secret"] == REDACTED
    assert out["id"] == "pi_1"


def test_request_log_url_is_scrubbed():
    out = scrub({"error": {"message": "nope",
                           "request_log_url": "https://dashboard.stripe.com/acct_123/..."}})
    assert out["error"]["request_log_url"] == REDACTED
    assert out["error"]["message"] == "nope"


def test_suffix_rules_cover_secret_and_key_variants():
    out = scrub({"ephemeral_secret": "x", "publishable_key": "y", "monkey": "safe"})
    assert out["ephemeral_secret"] == REDACTED
    assert out["publishable_key"] == REDACTED
    assert out["monkey"] == "safe"


def test_sensitive_object_values_are_replaced_whole():
    out = scrub({"secret": {"inner": "value"}})
    assert out["secret"] == REDACTED


def test_lists_are_traversed():
    out = scrub({"data": [{"client_secret": "a"}, {"client_secret": "b"}]})
    assert [d["client_secret"] for d in out["data"]] == [REDACTED, REDACTED]


def test_scalars_pass_through():
    assert scrub("plain") == "plain"
    assert scrub(None) is None
    assert scrub(42) == 42
