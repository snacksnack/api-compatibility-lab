"""The structural walk: what differs, and where the walk stops."""

from __future__ import annotations

from compatlab.deltas import (
    LENGTH,
    ONLY_IN_A,
    ONLY_IN_B,
    ORDER,
    VALUE,
    deltas,
    has_payload,
    leaf_values,
)
from compatlab.findings import MISSING


def kinds(items) -> list[tuple[str, str]]:
    return [(d.kind, d.locus) for d in items]


def test_identical_structures_produce_nothing():
    body = {"a": 1, "b": {"c": [1, 2]}}
    assert deltas(body, dict(body), "$") == []


def test_a_missing_key_is_reported_once_at_its_root():
    out = deltas({"plan": {"amount": 2500, "nested": {"x": 1}}}, {}, "$")
    assert kinds(out) == [(ONLY_IN_A, "$.plan")]
    assert out[0].a == {"amount": 2500, "nested": {"x": 1}}
    assert out[0].b is MISSING


def test_an_added_key_is_reported_as_only_in_b():
    assert kinds(deltas({}, {"pricing": {}}, "$")) == [(ONLY_IN_B, "$.pricing")]


def test_a_changed_scalar_is_one_value_delta():
    out = deltas({"capture_method": "automatic"},
                 {"capture_method": "automatic_async"}, "$")
    assert kinds(out) == [(VALUE, "$.capture_method")]
    assert (out[0].a, out[0].b) == ("automatic", "automatic_async")


def test_null_against_a_value_is_a_value_delta_not_a_shape_one():
    # The distinction the whole project turns on: absent is not null.
    out = deltas({"apm": None}, {"apm": {"enabled": True}}, "$")
    assert kinds(out) == [(VALUE, "$.apm")]
    assert out[0].a is None


def test_a_list_whose_length_changed_yields_one_delta_and_no_element_diffs():
    out = deltas({"types": ["card"]},
                 {"types": ["card", "link", "klarna"]}, "$")
    assert kinds(out) == [(LENGTH, "$.types")]


def test_a_reordered_list_yields_one_order_delta():
    out = deltas({"data": [{"id": 1}, {"id": 2}]},
                 {"data": [{"id": 2}, {"id": 1}]}, "$")
    assert kinds(out) == [(ORDER, "$.data")]


def test_same_length_lists_are_compared_elementwise():
    out = deltas({"data": [{"amount": 1}, {"amount": 2}]},
                 {"data": [{"amount": 1}, {"amount": 9}]}, "$")
    assert kinds(out) == [(VALUE, "$.data[1].amount")]


def test_nested_loci_read_as_json_paths():
    out = deltas({"data": [{"lines": {"data": [{"type": "subscription"}]}}]},
                 {"data": [{"lines": {"data": [{}]}}]}, "$")
    assert kinds(out) == [(ONLY_IN_A, "$.data[0].lines.data[0].type")]


def test_a_container_against_a_scalar_is_a_value_delta():
    assert kinds(deltas({"x": {"a": 1}}, {"x": "str"}, "$")) == [(VALUE, "$.x")]


def test_has_payload_distinguishes_an_empty_shell_from_a_populated_one():
    assert has_payload({"id": "pmc_1", "parent": None})
    assert not has_payload({"preferred_locale": None})
    assert not has_payload([])
    assert not has_payload("")
    assert not has_payload(None)
    assert not has_payload(MISSING)
    assert has_payload(False) is True  # a boolean false is still a value


def test_leaf_values_counts_what_a_subsumed_subtree_held():
    assert leaf_values({"a": 1, "b": {"c": 2, "d": 3}}) == 3
    assert leaf_values([]) == 1
    assert leaf_values("x") == 1
