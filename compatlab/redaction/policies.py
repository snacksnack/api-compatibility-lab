"""Shipped policies. A policy is data, so this file is the whole config.

`BASE_POLICY` is the generic starting point: value detectors, no key rules —
what a consumer extends when it does not know the payload's field names.
`STRIPE_POLICY` adds the key rules for the field names Stripe actually uses.

Over-redaction is the safe direction and is chosen on purpose. `name` is
redacted everywhere, including `product_name` and `account_name`, which costs
the readability of a product name in the corpus and buys never having to
reason about whether a given `name` belongs to a person. Fields that are
coarse rather than identifying (`city`, `state`, `country`) are left alone:
they are not worth a surrogate, and `country` changes Stripe's behavior, which
would corrupt the very comparison the corpus exists for.
"""

from __future__ import annotations

from compatlab.redaction.core import KeyRule, Policy
from compatlab.redaction.detectors import (
    DETECTORS,
    DROP,
    IDENTITY,
    PII,
    POSTAL,
    SECRET,
    SURROGATE,
)

BASE_POLICY = Policy(name="base", detectors=DETECTORS)

CREDENTIALS = KeyRule(
    name="credential",
    kind=SECRET,
    action=DROP,
    keys=frozenset({
        "client_secret", "secret", "password", "authorization", "auth",
        "request_log_url", "token", "api_key", "ephemeral_key",
        # Account-bearing URLs with an embedded access token. Named
        # explicitly rather than by a `_url` suffix, so `return_url` — whose
        # value is behavioral signal, not data — survives.
        "receipt_url", "hosted_invoice_url", "invoice_pdf",
    }),
    suffixes=("_secret", "_key", "_password"),
)

# Keys match on underscore tails (see core.tails), so `email` also covers
# `receipt_email` and `customer_email`, and `line1` covers `address_line1`.
PERSON = KeyRule(
    name="person_data",
    kind=PII,
    action=SURROGATE,
    keys=frozenset({
        "email", "name", "nickname", "phone", "id_number", "ssn_last_4",
        "tax_id", "vat_id", "line1", "line2", "ip", "ip_address", "dob",
    }),
)

POSTCODE = KeyRule(
    name="postal_code",
    kind=PII,
    action=SURROGATE,
    keys=frozenset({"postal_code", "zip", "postal"}),
    shape=POSTAL,
)

STATEMENT = KeyRule(
    name="account_reference",
    kind=IDENTITY,
    action=SURROGATE,
    keys=frozenset({"account", "on_behalf_of", "stripe_account"}),
)

# Stripe's published test fixtures. Public by design and meaningless outside a
# sandbox, so they stay legible in the corpus; without this the card-token
# steps would be redacted into something unreplayable.
PUBLIC_TEST_VALUES = frozenset({
    "tok_visa", "tok_mastercard", "tok_amex", "tok_chargeDeclined",
    "tok_visa_debit", "pm_card_visa", "pm_card_mastercard",
    "pm_card_chargeDeclined", "pm_card_visa_debit",
    "4242424242424242", "5555555555554444", "378282246310005",
})

STRIPE_POLICY = Policy(
    name="stripe",
    key_rules=(CREDENTIALS, PERSON, POSTCODE, STATEMENT),
    detectors=DETECTORS,
    allow_values=PUBLIC_TEST_VALUES,
)
