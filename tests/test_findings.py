"""The finding type: its vocabulary, its identity, and how it prints."""

from __future__ import annotations

import pytest

from compatlab.findings import (
    ABSENT,
    AXES,
    MISSING,
    SEVERITIES,
    DiffReport,
    Finding,
    leaf,
    normalize,
    short,
)


def finding(**overrides) -> Finding:
    base = {
        "workflow": "w", "step": "s", "seq": 0, "method": "GET",
        "path_template": "/v1/things", "axis": "value",
        "locus": "$.body.amount", "rule": "value-changed",
        "severity": "breaking", "rationale": "because",
    }
    return Finding(**{**base, **overrides})


def test_an_unknown_severity_or_axis_is_refused_at_construction():
    with pytest.raises(ValueError, match="severity"):
        finding(severity="catastrophic")
    with pytest.raises(ValueError, match="axis"):
        finding(axis="vibes")


def test_the_vocabulary_is_exactly_three_severities():
    assert SEVERITIES == ("breaking", "risky", "benign")
    assert "availability" in AXES


def test_a_findings_key_names_the_step_and_the_place_inside_it():
    assert finding().key == "w.s $.body.amount"


def test_an_absent_value_prints_differently_from_a_json_null():
    absent = finding(a=short(None), b=short(MISSING))
    assert "null -> " + ABSENT in absent.line()


def test_short_truncates_without_lying_about_it():
    text = short({"k": "x" * 400})
    assert len(text) <= 120
    assert text.endswith("...")


def test_short_of_the_missing_sentinel_is_none_not_the_string_none():
    assert short(MISSING) is None
    assert short(None) == "null"


def test_normalize_collapses_list_indices_so_repeats_are_one_finding():
    assert normalize("$.body.data[2].lines.data[0].type") == \
        "$.body.data[].lines.data[].type"


@pytest.mark.parametrize("locus,expected", [
    ("$.body.data", "data"),
    ("$.body.data[0]", "data"),
    ("$.body.data[0].lines.data[1].amount_excluding_tax",
     "amount_excluding_tax"),
    ("$.status", "status"),
])
def test_leaf_reads_the_field_name_off_the_end_of_a_locus(locus, expected):
    assert leaf(locus) == expected
    assert finding(locus=locus).field_name == expected


def test_a_report_counts_by_any_attribute_and_sorts_by_severity():
    report = DiffReport(findings=[
        finding(severity="risky", seq=2),
        finding(severity="breaking", seq=1),
        finding(severity="benign", axis="timing", rule="timing-shifted", seq=0),
    ], steps_compared=3)
    assert report.counts("severity") == {"benign": 1, "breaking": 1, "risky": 1}
    assert [f.severity for f in report.sorted_findings()] == [
        "breaking", "risky", "benign"]
    assert report.steps_with_findings == 1
    assert report.to_dict()["findings"] == 3


def test_a_findings_endpoint_is_method_and_template():
    assert finding().endpoint == "GET /v1/things"
