"""The pin compiler: what gets asserted, and what refuses to compile."""

from __future__ import annotations

import pytest

from compatlab.pinning import (
    EQUALS,
    LENGTH,
    NON_EMPTY,
    PRESENT,
    REACHABLE,
    STATUS,
    CompileError,
    Pin,
    PinUnreached,
    canonical_of,
    compile_all,
    compile_pin,
    name_for,
    pin_from,
    reached,
)


def make_pin(**over) -> Pin:
    base = {
        "pin": "w.s $.body.count",
        "corpus": "w.s",
        "locus": "$.body.count",
        "declared_read": "$.body.count",
        "rule": "value-changed",
        "axis": "value",
        "consequence": "corrupts",
        "assertion": "`$.body.count` equals 1",
        "workflows": ["a_workflow"],
        "caveat": None,
        "expect_on_a": "1",
        "observed_on_b": "0",
    }
    return pin_from({**base, **over})


def record(body: dict, status: int = 200, step: str | None = None) -> dict:
    return {"workflow": "w", "step": step or "s", "status": status,
            "body": body}


def test_a_scalar_is_pinned_exactly():
    test = compile_pin(make_pin(), record({"count": 1}))
    assert (test.kind, test.expected) == (EQUALS, 1)


def test_the_expected_value_comes_from_the_record_not_the_pin():
    """The pin's own rendering is truncated; the record's is not.

    ADR 0005 D7 had the pin name a property when its value did not fit. The
    compiler has the record the pin was derived from, so it does not have to:
    this is the assertion built from the whole value where the pin string
    carries a clipped one.
    """
    long = "x" * 400
    test = compile_pin(make_pin(expect_on_a=f'"{long[:40]}..."'),
                       record({"count": long}))
    assert test.expected == long
    assert test.kind == EQUALS


def test_a_nested_structure_is_pinned_on_presence_not_deep_equality():
    """A deep-equality pin would fail on any unrelated change inside it."""
    body = {"count": {"nested": {"deeper": [1, 2, 3]}}}
    test = compile_pin(make_pin(), record(body))
    assert test.kind == PRESENT
    assert "deep equality" in test.reason


def test_a_long_flat_list_is_too_long_to_read_so_it_is_pinned_on_presence():
    test = compile_pin(make_pin(), record({"count": [f"item-{i}" for i in range(40)]}))
    assert test.kind == PRESENT


def test_a_short_flat_list_is_pinned_exactly_because_the_set_is_the_behavior():
    test = compile_pin(make_pin(rule="enum-set-grew"), record({"count": ["card"]}))
    assert (test.kind, test.expected) == (EQUALS, ["card"])


def test_a_status_pin_is_about_the_call():
    pin = make_pin(locus="$.status", axis="status", rule="status-class-changed",
                   assertion="`w.s` returns status 200 and not 404")
    test = compile_pin(pin, record({}, status=200))
    assert (test.kind, test.expected) == (STATUS, 200)


def test_an_emptied_list_is_pinned_on_being_non_empty():
    pin = make_pin(rule="list-emptied", locus="$.body.data")
    test = compile_pin(pin, record({"data": [{"amount": 3000}]}))
    assert test.kind == NON_EMPTY


def test_a_truncated_list_is_pinned_on_its_length():
    pin = make_pin(rule="list-truncated", locus="$.body.data")
    test = compile_pin(pin, record({"data": [1, 2, 3]}))
    assert (test.kind, test.expected) == (LENGTH, 3)


def test_a_truncation_pin_on_something_that_is_not_a_list_refuses():
    pin = make_pin(rule="list-truncated", locus="$.body.data")
    with pytest.raises(CompileError):
        compile_pin(pin, record({"data": "not a list"}))


def test_a_missing_step_is_pinned_on_the_call_running_at_all():
    pin = make_pin(rule="step-missing", locus="$.status")
    test = compile_pin(pin, None)
    assert test.kind == REACHABLE


def test_a_pin_with_no_version_a_record_refuses_to_compile():
    """There is no old behavior to pin, so there is no test to write."""
    with pytest.raises(CompileError, match="no version-A record"):
        compile_pin(make_pin(), None)


def test_a_pin_on_a_locus_absent_from_version_a_refuses_to_compile():
    with pytest.raises(CompileError, match="absent from the version-A"):
        compile_pin(make_pin(), record({"other": 1}))


def test_a_wildcard_locus_is_pinned_on_presence():
    pin = make_pin(locus="$.body.data[].amount")
    test = compile_pin(pin, record({"data": [{"amount": 1}, {"amount": 2}]}))
    assert test.kind == PRESENT


def test_names_are_derived_from_the_step_and_the_locus():
    assert name_for(make_pin()) == "test_w_s__count"
    assert name_for(make_pin(locus="$.status")) == "test_w_s__status"


def test_two_pins_compiling_to_one_name_is_an_error_not_a_rename():
    """A renamed test silently invalidates every certification of it."""
    one = make_pin(locus="$.body.count", pin="one")
    two = make_pin(locus="$.body.count", pin="two")
    side = {("w", "s"): record({"count": 1})}
    with pytest.raises(CompileError, match="shadow"):
        compile_all([one, two], side)


def test_the_fingerprint_moves_when_the_assertion_moves():
    """Certifying a pin and then changing what it asserts must not survive."""
    first = compile_pin(make_pin(), record({"count": 1}))
    second = compile_pin(make_pin(), record({"count": 2}))
    assert first.fingerprint != second.fingerprint


def test_the_fingerprint_moves_when_the_specification_moves():
    first = compile_pin(make_pin(), record({"count": 1}))
    second = compile_pin(make_pin(consequence="blocks"), record({"count": 1}))
    assert first.fingerprint != second.fingerprint


def test_an_unreached_step_fails_with_the_marker_not_an_assertion():
    """The third outcome. A replay that died earlier did not exercise the pin."""
    with pytest.raises(PinUnreached, match=r"\[unreached\]"):
        canonical_of({}, "w.s")
    assert canonical_of({("w", "s"): record({"count": 1})}, "w.s")["status"] == 200


def test_reached_answers_whether_the_step_ran():
    side = {("w", "s"): record({})}
    assert reached(side, "w.s")
    assert not reached(side, "w.other")


def test_a_pin_whose_corpus_is_not_workflow_dot_step_refuses():
    with pytest.raises(CompileError):
        pin_from({"corpus": "no-dot"})
