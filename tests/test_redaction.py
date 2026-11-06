"""The redaction component: both passes, and the asymmetry between them."""

from __future__ import annotations

from compatlab.redaction import (
    BASE_POLICY,
    REDACTED,
    STRIPE_POLICY,
    KeyRule,
    Policy,
    is_surrogate,
    leaf_key,
    luhn,
    mask,
)
from compatlab.redaction.detectors import DROP, PII, SECRET, SURROGATE

SALTED = STRIPE_POLICY.with_salt(b"test-salt")


def test_credentials_are_dropped_not_surrogated():
    out = SALTED.redact({"client_secret": "pi_1_secret_abc", "api_key": "sk_live_x"})
    assert out == {"client_secret": REDACTED, "api_key": REDACTED}


def test_person_data_is_surrogated_type_preserving():
    out = SALTED.redact({"email": "ada@lovelace.org", "phone": "+14155550123",
                         "postal_code": "94105", "name": "Ada Lovelace"})
    assert out["email"].endswith("@example.invalid")
    assert out["phone"].startswith("+1555010")
    assert out["postal_code"].isdigit() and len(out["postal_code"]) == 5
    assert out["name"].startswith("redacted-")


def test_surrogates_are_deterministic_for_the_same_value():
    first = SALTED.redact({"email": "ada@lovelace.org"})
    second = SALTED.redact({"receipt_email": "ada@lovelace.org"})
    assert first["email"] == second["receipt_email"]


def test_the_salt_changes_every_surrogate():
    a = STRIPE_POLICY.with_salt(b"one").redact({"email": "ada@lovelace.org"})
    b = STRIPE_POLICY.with_salt(b"two").redact({"email": "ada@lovelace.org"})
    assert a["email"] != b["email"]


def test_redaction_is_idempotent():
    once = SALTED.redact({"email": "ada@lovelace.org", "client_secret": "x_secret"})
    assert SALTED.redact(once) == once


def test_scan_of_a_redacted_payload_is_empty_and_scan_of_the_raw_one_is_not():
    raw = {"customer": {"email": "ada@lovelace.org", "phone": "415-555-0123"},
           "client_secret": "pi_secret_1"}
    assert SALTED.scan(raw)
    assert SALTED.scan(SALTED.redact(raw)) == []


def test_scan_reports_the_path_rule_and_kind():
    findings = SALTED.scan({"data": [{"billing_details": {"email": "a@b.co"}}]})
    assert len(findings) == 1
    assert findings[0].path == "$.data[0].billing_details.email"
    assert findings[0].rule == "person_data"
    assert findings[0].kind == PII


def test_a_finding_never_carries_the_raw_value():
    finding = SALTED.scan({"email": "ada@lovelace.org"})[0]
    assert "ada" not in finding.preview
    assert "lovelace" not in str(finding)
    assert mask("ada@lovelace.org").startswith("a*")


def test_sensitive_values_inside_free_text_are_replaced_consistently():
    raw = {"error": {"message": "No such customer ada@lovelace.org on "
                                "acct_1AbCdEfG12345"}}
    out = SALTED.redact(raw)
    message = out["error"]["message"]
    assert "ada@lovelace.org" not in message
    assert "acct_1AbCdEfG12345" not in message
    assert "@example.invalid" in message and "acct_redacted" in message
    # Same value, same surrogate: an error message still points at the object
    # the rest of the record talks about.
    assert SALTED.redact({"email": "ada@lovelace.org"})["email"] in message


def test_a_whole_subtree_under_a_sensitive_key_is_redacted():
    out = SALTED.redact({"secret": {"inner": "value", "deeper": ["a", "b"]}})
    assert out["secret"] == {"inner": REDACTED, "deeper": [REDACTED, REDACTED]}


def test_card_numbers_are_detected_by_luhn_and_replaced_with_a_test_card():
    out = SALTED.redact({"note": "card 4000056655665556 declined"})
    assert out["note"] == "card 4242424242424242 declined"
    assert luhn("4000056655665556") and not luhn("4000056655665557")


def test_bare_digit_runs_are_not_read_as_phone_numbers():
    # The first live capture flagged the digit substring of a hex record id.
    # A phone pattern needs a formatting signal; bare-digit phone fields are
    # the `phone` key rule's job.
    payload = {"id": "ce3106309946", "created": 1793791966,
               "fingerprint": "4155550123"}
    assert SALTED.scan(payload) == []


def test_public_test_fixtures_stay_legible():
    out = SALTED.redact({"card[token]": "tok_visa", "payment_method": "pm_card_visa"})
    assert out == {"card[token]": "tok_visa", "payment_method": "pm_card_visa"}


def test_form_bracket_keys_match_the_same_rules():
    assert leaf_key("billing_details[address][line1]") == "line1"
    out = SALTED.redact({"billing_details[address][line1]": "1 Engine Way"})
    assert out["billing_details[address][line1]"].startswith("redacted-")


def test_coarse_location_fields_are_left_alone():
    payload = {"city": "San Francisco", "state": "CA", "country": "US"}
    assert SALTED.redact(payload) == payload


def test_booleans_and_nulls_under_a_rule_pass_through():
    payload = {"name": None, "email": "", "phone": False}
    assert SALTED.redact(payload) == payload


def test_the_base_policy_has_detectors_but_no_key_rules():
    # What a second consumer (RC1-594's diagnostic bundle) starts from.
    assert BASE_POLICY.key_rules == ()
    out = BASE_POLICY.with_salt(b"s").redact({"anything": "ada@lovelace.org"})
    assert out["anything"].endswith("@example.invalid")


def test_a_custom_policy_composes_from_the_same_primitives():
    policy = Policy(
        name="custom",
        key_rules=(KeyRule("patient", PII, SURROGATE, frozenset({"mrn"})),
                   KeyRule("creds", SECRET, DROP, frozenset({"pin"}))),
        salt=b"s",
    )
    out = policy.redact({"mrn": "AB-99", "pin": "1234", "email": "a@b.co"})
    assert out["mrn"].startswith("redacted-")
    assert out["pin"] == REDACTED
    # Detectors still run: the value shapes are policy-independent.
    assert out["email"].endswith("@example.invalid")


def test_surrogates_are_recognizable_as_surrogates():
    assert is_surrogate(REDACTED)
    assert is_surrogate("redacted-0123abcd@example.invalid")
    assert is_surrogate("+15550101234")
    assert not is_surrogate("ada@lovelace.org")


def test_a_known_literal_is_redacted_inside_free_text():
    # Stripe composes an invoice line item's description from the product
    # name, so a name redacted at its own key reappears in prose with nothing
    # to detect. The policy has to be told.
    policy = SALTED.with_known({"Reconciliation Pro": None})
    out = policy.redact({"description": "1 x Reconciliation Pro (at $25.00)"})
    assert "Reconciliation Pro" not in out["description"]
    # Same surrogate as the keyed occurrence, so the corpus stays coherent.
    assert policy.redact({"name": "Reconciliation Pro"})["name"] \
        in out["description"]


def test_scan_reports_a_known_literal_the_detectors_cannot_see():
    policy = SALTED.with_known({"Grace Hopper": None})
    findings = policy.scan({"statement": "paid by Grace Hopper"})
    assert [f.rule for f in findings] == ["known_value"]
    assert SALTED.scan({"statement": "paid by Grace Hopper"}) == []


def test_longer_known_literals_are_replaced_before_shorter_ones():
    policy = SALTED.with_known({"Ada": None, "Ada Lovelace": None})
    out = policy.redact({"text": "Ada Lovelace wrote it"})
    assert out["text"] == \
        f"{policy.redact({'name': 'Ada Lovelace'})['name']} wrote it"


def test_a_hosted_page_url_is_dropped_whatever_field_it_arrives_in():
    """The Checkout Session `url` case (RC1-618).

    The key rules name the fields known to carry a capability URL, so a new
    endpoint family carrying a new one is a hole by construction. Matching the
    host closes the class: the field name here is a bare `url`, which no key
    rule covers and none safely could.
    """
    session = {
        "id": "cs_test_a1Hq7sHLnjaq",
        "url": "https://checkout.stripe.com/c/pay/cs_test_a1Hq7s#fidnandhYHdW",
    }
    assert STRIPE_POLICY.redact(session)["url"] == REDACTED
    assert [f.rule for f in STRIPE_POLICY.scan(session)] == ["hosted_page_url"]
    assert STRIPE_POLICY.scan(STRIPE_POLICY.redact(session)) == []


def test_the_urls_a_request_sent_survive_redaction():
    """`success_url` and friends are behavioral signal, not data.

    This is why the fix is a host detector and not a key rule: keys match on
    underscore tails, so a rule on `url` would swallow all three of these.
    """
    sent = {
        "success_url": "https://example.invalid/success",
        "cancel_url": "https://example.invalid/cancel",
        "return_url": "https://example.invalid/auth/return",
        "url": "/v1/checkout/sessions",
    }
    assert STRIPE_POLICY.redact(sent) == sent


def test_a_documentation_link_in_an_error_body_is_not_dropped():
    """Stripe's error messages cite docs; the differ reads those messages."""
    body = {"error": {"message": "The Checkout Session's total amount due "
                                 "cannot be zero in `payment` mode. Please "
                                 "see https://docs.stripe.com/payments/"
                                 "checkout/no-cost-orders."}}
    assert STRIPE_POLICY.redact(body) == body
