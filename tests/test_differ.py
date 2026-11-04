"""The differ: pairing, subsumption, error semantics, caveats, timing."""

from __future__ import annotations

from compatlab.canonical import canonical_side
from compatlab.differ import (
    ACCOUNT_STATE_CAVEAT,
    REQUEST_MISMATCH_CAVEAT,
    diff_pairs,
    observed,
    sides,
)


def record(step: str, body: dict, *, seq: int = 0, status: int = 200,
           workflow: str = "w", method: str = "POST", path: str = "/v1/things",
           request_body: dict | None = None, version: str = "2022-11-15",
           duration_ms: float | None = None) -> dict:
    out = {
        "schema": 1, "id": f"rec{seq}", "workflow": workflow, "step": step,
        "seq": seq, "method": method, "path": path, "path_template": path,
        "path_reference": path, "query": {}, "request_body": request_body,
        "request_template": request_body, "stripe_version": version,
        "captured_at": "2026-11-04T00:00:00Z", "targets": [],
        "redaction": {"policy": "stripe"},
        "response": {"status": status,
                     "headers": {"request-id": f"req_{seq}",
                                 "stripe-version": version},
                     "body": body},
    }
    if duration_ms is not None:
        out["duration_ms"] = duration_ms
    return out


def pair(a: dict | None, b: dict | None, *, targets=()) -> dict:
    anchor = a or b
    assert anchor is not None
    return {
        "workflow": anchor["workflow"], "step": anchor["step"],
        "seq": anchor["seq"], "method": anchor["method"],
        "path_template": anchor["path_template"], "targets": list(targets),
        "a": a, "b": b,
    }


def test_sides_splits_pairs_back_into_runs():
    one, two = sides([pair(record("s1", {}), None),
                      pair(record("s2", {}, seq=1), record("s2", {}, seq=1))])
    assert len(one) == 2
    assert len(two) == 1


def test_a_step_present_on_one_side_only_is_a_breaking_finding():
    report = diff_pairs([pair(record("gone", {"id": "x"}), None)])
    assert [f.rule for f in report.findings] == ["step-missing"]
    assert report.findings[0].severity == "breaking"
    assert "A only" in report.findings[0].rationale


def test_a_changed_status_subsumes_the_body_instead_of_enumerating_it():
    # The 85-line problem from Phase 2: an endpoint that went 200 -> 404 used
    # to report every field of the error document it returned instead.
    big = {f"field_{i}": i for i in range(40)}
    report = diff_pairs([pair(
        record("preview", big, method="GET", path="/v1/invoices/upcoming"),
        record("preview", {"error": {"type": "invalid_request_error"}},
               method="GET", path="/v1/invoices/upcoming", status=404),
    )])
    rules = [f.rule for f in report.findings]
    assert rules == ["status-class-changed", "status-body-subsumed"]
    assert report.findings[0].severity == "breaking"
    subsumed = report.findings[1]
    assert subsumed.severity == "benign"
    assert subsumed.subsumed == 41


def test_a_status_change_within_a_class_is_only_risky():
    report = diff_pairs([pair(record("s", {"a": 1}, status=200),
                              record("s", {"a": 1}, status=201))])
    assert [f.rule for f in report.findings] == ["status-changed"]
    assert report.findings[0].severity == "risky"


def test_an_error_identity_change_outranks_its_message():
    report = diff_pairs([pair(
        record("bad", {"error": {"type": "invalid_request_error",
                                 "code": "resource_missing",
                                 "message": "No such customer"}}, status=404),
        record("bad", {"error": {"type": "invalid_request_error",
                                 "code": "parameter_unknown",
                                 "message": "Unrecognized parameter"}},
               status=404),
    )])
    by_rule = {f.rule: f for f in report.findings}
    assert by_rule["error-identity-changed"].severity == "breaking"
    assert by_rule["error-message-changed"].severity == "risky"


def test_a_reworded_error_under_an_unchanged_identity_is_risky_only():
    # Live example: the `total_count` 400 gained a deprecation hint on A.
    report = diff_pairs([pair(
        record("x", {"error": {"code": "property_forbidden",
                               "message": "cannot be included (Hint: ...)"}},
               status=400),
        record("x", {"error": {"code": "property_forbidden",
                               "message": "cannot be included"}}, status=400),
    )])
    assert [f.rule for f in report.findings] == ["error-message-changed"]


def test_an_error_envelope_that_gained_a_field_is_reported_as_shape():
    report = diff_pairs([pair(
        record("x", {"error": {"code": "c"}}, status=400),
        record("x", {"error": {"code": "c", "request_log_url": "..."}},
               status=400),
    )])
    assert [f.rule for f in report.findings] == ["error-shape-changed"]


def test_a_value_difference_under_data_carries_the_account_state_caveat():
    body_a = {"object": "list", "data": [{"amount_refunded": 3000}],
              "has_more": False}
    body_b = {"object": "list", "data": [{"amount_refunded": 0}],
              "has_more": False}
    report = diff_pairs([pair(record("l", body_a, method="GET"),
                              record("l", body_b, method="GET"))])
    assert report.findings[0].caveat == ACCOUNT_STATE_CAVEAT


def test_a_removed_key_under_data_carries_no_caveat():
    # Which objects a list returns can change between runs; whether a key
    # exists on the object the server serializes cannot.
    body_a = {"object": "list", "data": [{"paid": True}]}
    body_b = {"object": "list", "data": [{}]}
    report = diff_pairs([pair(record("l", body_a, method="GET"),
                              record("l", body_b, method="GET"))])
    assert [f.rule for f in report.findings] == ["populated-field-removed"]
    assert report.findings[0].caveat is None


def test_a_step_whose_two_sides_sent_different_requests_is_flagged_unsound():
    report = diff_pairs([pair(
        record("s", {"amount": 1}, request_body={"amount": "1"}),
        record("s", {"amount": 2}, request_body={"amount": "2"}),
    )])
    assert report.findings[0].caveat == REQUEST_MISMATCH_CAVEAT


def test_timing_is_reported_when_present_and_always_benign():
    report = diff_pairs([pair(record("s", {"a": 1}, duration_ms=100.0),
                              record("s", {"a": 1}, duration_ms=400.0))])
    assert [f.rule for f in report.findings] == ["timing-shifted"]
    assert report.findings[0].severity == "benign"
    assert "never scored" in report.findings[0].rationale


def test_a_small_timing_shift_is_not_reported_at_all():
    report = diff_pairs([pair(record("s", {"a": 1}, duration_ms=100.0),
                              record("s", {"a": 1}, duration_ms=110.0))])
    assert report.findings == []


def test_a_corpus_without_durations_reports_no_timing_axis():
    report = diff_pairs([pair(record("s", {"a": 1}), record("s", {"a": 1}))])
    assert report.findings == []


def test_observed_collects_values_across_the_whole_side():
    one, _ = sides([
        pair(record("s1", {"status": "open"}), None),
        pair(record("s2", {"data": [{"status": "paid"}]}, seq=1), None),
    ])
    seen = observed(canonical_side(one))
    assert seen["$.body.status"] == frozenset(['"open"'])
    assert seen["$.body.data[].status"] == frozenset(['"paid"'])


def test_findings_carry_the_targets_of_the_pair_they_came_from():
    report = diff_pairs([pair(record("s", {"capture_method": "automatic"}),
                              record("s", {"capture_method": "manual"}),
                              targets=("M2",))])
    assert report.findings[0].targets == ("M2",)
