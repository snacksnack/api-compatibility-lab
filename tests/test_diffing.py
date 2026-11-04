from __future__ import annotations

from compatlab.diffing import NOISE_KEYS, shallow_diff


def test_equal_dicts_produce_no_diff():
    assert shallow_diff({"a": 1, "b": "x"}, {"a": 1, "b": "x"}) == []


def test_key_only_on_one_side_is_reported_per_side():
    lines = shallow_diff({"gone_in_b": 1, "both": 2}, {"both": 2, "new_in_b": 3})
    assert "  only in A: gone_in_b" in lines
    assert "  only in B: new_in_b" in lines
    assert len(lines) == 2


def test_changed_value_is_reported_with_both_values():
    lines = shallow_diff({"capture_method": "automatic"},
                         {"capture_method": "automatic_async"})
    assert lines == ['  value differs: capture_method: "automatic" -> "automatic_async"']


def test_noise_keys_are_ignored_even_when_different():
    a = {k: "a" for k in NOISE_KEYS}
    b = {k: "b" for k in NOISE_KEYS}
    assert shallow_diff(a, b) == []


def test_null_to_object_transition_is_a_value_diff():
    # The APM-default break observed live in the spike: null -> {enabled: true}.
    lines = shallow_diff({"automatic_payment_methods": None},
                         {"automatic_payment_methods": {"enabled": True}})
    assert len(lines) == 1
    assert lines[0].startswith("  value differs: automatic_payment_methods: null")


def test_long_values_are_truncated():
    lines = shallow_diff({"k": "x" * 500}, {"k": "y" * 500})
    assert len(lines) == 1
    assert len(lines[0]) < 200
