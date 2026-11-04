"""Reading a locus out of a response, and deciding when two are the same place.

`touches` carries more weight than it looks: it decides whether a finding is
about a field the client reads, and both a false positive and a false negative
there turn into a wrong sentence in a customer-facing report.
"""

from __future__ import annotations

import pytest

from compatlab.findings import MISSING
from compatlab.loci import (
    LocusError,
    parse,
    readable,
    resolve,
    touches,
    value_at,
    wildcarded,
)

BODY = {
    "status": 200,
    "body": {
        "count": 1,
        "has_more": False,
        "nothing": None,
        "data": [
            {"amount": 3000, "lines": {"data": [{"plan": {"id": "p1"}}]}},
            {"amount": 500, "lines": {"data": [{"plan": {"id": "p2"}}]}},
        ],
    },
}


def test_parse_splits_keys_and_indices():
    assert parse("$.body.data[].amount") == (
        ("key", "body"), ("key", "data"), ("index", None), ("key", "amount"))
    assert parse("$.body.data[1]") == (
        ("key", "body"), ("key", "data"), ("index", 1))
    assert parse("$") == ()


@pytest.mark.parametrize("locus", ["body.count", "$.body.", "$.body..x", "$["])
def test_parse_refuses_what_is_not_a_locus(locus: str):
    with pytest.raises(LocusError):
        parse(locus)


def test_resolve_expands_a_wildcard_over_every_element():
    found = resolve(BODY, "$.body.data[].amount")
    assert found == [("$.body.data[0].amount", 3000),
                     ("$.body.data[1].amount", 500)]


def test_resolve_reaches_through_nested_lists():
    found = resolve(BODY, "$.body.data[].lines.data[].plan.id")
    assert [value for _, value in found] == ["p1", "p2"]


def test_resolve_returns_nothing_for_a_field_that_is_not_there():
    assert resolve(BODY, "$.body.nope") == []
    assert resolve(BODY, "$.body.data[9].amount") == []


def test_resolve_keeps_a_present_null_distinct_from_an_absent_field():
    assert resolve(BODY, "$.body.nothing") == [("$.body.nothing", None)]
    assert value_at(BODY, "$.body.nothing") is None
    assert value_at(BODY, "$.body.nope") is MISSING


def test_value_at_collapses_a_wildcard_to_the_list_of_matches():
    assert value_at(BODY, "$.body.data[].amount") == [3000, 500]
    assert value_at(BODY, "$.body.count") == 1
    assert wildcarded("$.body.data[].amount")
    assert not wildcarded("$.body.count")


def test_an_empty_wildcard_match_reads_as_an_empty_list():
    # Deliberate: a client reading `data[].amount` cannot tell an empty list
    # from a missing one either.
    assert value_at({"body": {"data": []}}, "$.body.data[].amount") == []
    assert value_at({"body": {}}, "$.body.data[].amount") == []


def test_touches_is_true_for_the_same_place():
    assert touches("$.body.count", "$.body.count")
    assert touches("$.body.data[0].amount", "$.body.data[1].amount")


def test_touches_is_true_when_the_finding_is_above_the_read():
    # A removed subtree covers every declared read inside it.
    assert touches("$.body.data[].lines", "$.body.data[].lines.data[].plan")


def test_touches_is_true_when_the_finding_is_below_the_read():
    # A changed element is a change to the collection the client stores whole.
    assert touches("$.body.data[0].amount", "$.body.data")


def test_touches_stops_at_a_segment_boundary():
    assert not touches("$.body.count", "$.body.counts")
    assert not touches("$.body.amount", "$.body.amount_refunded")


def test_touches_is_false_across_the_status_and_body_roots():
    assert not touches("$.status", "$.body.amount_due")


def test_the_root_touches_everything():
    assert touches("$", "$.body.data[].amount")


@pytest.mark.parametrize("locus,ok", [
    ("$.status", True),
    ("$.body", True),
    ("$.body.error.code", True),
    ("$.duration_ms", False),
    ("$", False),
])
def test_only_the_status_and_the_body_may_be_declared_as_reads(locus, ok):
    # `$.duration_ms` is refused because the timing axis is benign by rule
    # forever (ADR 0004 D7); a declared read of it could only produce a claim
    # the project has promised not to make.
    assert readable(locus) is ok
