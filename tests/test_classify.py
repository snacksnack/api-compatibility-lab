"""The rule table: every rule reachable, and precedence where it matters."""

from __future__ import annotations

import pytest

from compatlab.classify import (
    BY_ID,
    RULES,
    StepContext,
    classify,
    looks_enum,
)
from compatlab.deltas import LENGTH, ONLY_IN_A, ONLY_IN_B, ORDER, VALUE, Delta
from compatlab.findings import AXES, SEVERITIES

CTX = StepContext(method="POST", path_template="/v1/payment_intents", status=200)
LIST_CTX = StepContext(method="GET", path_template="/v1/refunds", status=200,
                       list_body=True)


def verdict(kind: str, locus: str, a=None, b=None, ctx: StepContext = CTX):
    return classify(Delta(kind, locus, a=a, b=b), ctx)


def test_every_rule_is_registered_once_with_a_known_axis_and_severity():
    assert len(BY_ID) == len(RULES)
    for rule in RULES:
        assert rule.axis in AXES
        assert rule.severity in SEVERITIES
        assert rule.summary.endswith(".")


def test_a_populated_field_removed_is_breaking():
    out = verdict(ONLY_IN_A, "$.body.current_period_end", a=1793810218)
    assert (out.rule, out.severity) == ("populated-field-removed", "breaking")


def test_a_field_that_was_always_null_is_only_risky_when_removed():
    out = verdict(ONLY_IN_A, "$.body.invoice", a=None)
    assert (out.rule, out.severity) == ("null-field-removed", "risky")
    assert "indexes the key" in out.rationale


def test_an_added_field_with_a_value_is_risky_and_an_empty_one_is_benign():
    populated = verdict(ONLY_IN_B, "$.body.pricing", b={"unit_amount": 2500})
    empty = verdict(ONLY_IN_B, "$.body.payment_method_options.cashapp", b={})
    assert (populated.rule, populated.severity) == ("field-added-populated",
                                                    "risky")
    assert (empty.rule, empty.severity) == ("field-added-empty", "benign")


def test_nulling_a_value_is_breaking_and_unnulling_one_is_risky():
    nulled = verdict(VALUE, "$.body.charge", a="ch_1", b=None)
    unnulled = verdict(VALUE, "$.body.automatic_payment_methods", a=None,
                       b={"enabled": True})
    assert (nulled.rule, nulled.severity) == ("value-nulled", "breaking")
    assert (unnulled.rule, unnulled.severity) == ("value-unnulled", "risky")


def test_a_changed_default_beats_the_new_enum_rule():
    # The precedence that decides whether M2 is a headline or a footnote: this
    # value is both "changed" and "a member never seen on A", and reporting it
    # as a grown value set would understate it.
    out = verdict(VALUE, "$.body.capture_method", a="automatic",
                  b="automatic_async")
    assert out.rule == "enum-value-changed"
    assert out.severity == "breaking"
    assert "changed server default" in out.rationale


def test_a_changed_value_the_client_asked_for_says_so():
    ctx = StepContext(method="POST", path_template="/v1/payment_intents",
                      status=200, request_keys=frozenset({"capture_method"}))
    out = verdict(VALUE, "$.body.capture_method", a="manual", b="automatic",
                  ctx=ctx)
    assert "the request specified" in out.rationale


def test_a_value_already_seen_on_a_is_not_a_new_enum_member():
    ctx = StepContext(method="GET", path_template="/v1/x", status=200,
                      observed_a={"$.body.status": frozenset(['"paid"'])})
    out = verdict(VALUE, "$.body.status", a="open", b="paid", ctx=ctx)
    assert out.rule == "value-changed"
    assert out.severity == "breaking"


def test_a_type_change_is_reported_as_one():
    out = verdict(VALUE, "$.body.amount_details", a={"tip": {}}, b="any")
    assert out.rule == "type-changed"
    assert "object to string" in out.rationale


def test_an_emptied_collection_is_breaking_and_names_the_reconciliation_risk():
    out = verdict(LENGTH, "$.body.data", a=[{"amount": 3000}], b=[],
                  ctx=LIST_CTX)
    assert (out.rule, out.severity) == ("list-emptied", "breaking")
    assert "reconciles" in out.rationale


def test_a_shorter_collection_is_truncation_and_a_longer_one_is_not():
    short = verdict(LENGTH, "$.body.data", a=[1, 2, 3], b=[1, 2], ctx=LIST_CTX)
    longer = verdict(LENGTH, "$.body.data", a=[{"a": 1}],
                     b=[{"a": 1}, {"a": 2}], ctx=LIST_CTX)
    assert short.rule == "list-truncated"
    assert longer.rule == "list-grew"


def test_a_grown_list_of_enum_members_is_called_out_as_such():
    out = verdict(LENGTH, "$.body.payment_method_types", a=["card"],
                  b=["card", "link", "klarna"])
    assert (out.rule, out.severity) == ("enum-set-grew", "risky")
    assert "switching exhaustively" in out.rationale


def test_a_pagination_key_is_classified_on_its_own_axis():
    out = verdict(VALUE, "$.body.has_more", a=False, b=True, ctx=LIST_CTX)
    assert out.rule == "pagination-boundary-changed"
    assert out.axis == "pagination"


def test_a_pagination_key_on_a_non_list_body_is_an_ordinary_value():
    out = verdict(VALUE, "$.body.has_more", a=False, b=True)
    assert out.rule == "value-changed"


def test_reordering_is_risky_and_says_why():
    out = verdict(ORDER, "$.body.data", a=[1, 2], b=[2, 1], ctx=LIST_CTX)
    assert (out.rule, out.severity) == ("order-changed", "risky")
    assert "by position" in out.rationale


@pytest.mark.parametrize("value,expected", [
    ("automatic_async", True),
    ("charge_automatically", True),
    ("requires_capture", True),
    ("Automatic", False),
    ("a value with spaces", False),
    ("cus_VZFgHmUnwSCu8q", False),
    (2500, False),
    (None, False),
])
def test_looks_enum_accepts_closed_set_members_only(value, expected):
    assert looks_enum(value) is expected
