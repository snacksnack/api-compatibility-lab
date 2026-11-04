"""The independent check on every impact claim.

The verifier exists because the mapper reads the findings and the findings
came from the classifier, so scoring the mapping against the findings would
score it against its own input. These tests are mostly about claims that are
*wrong*: if nothing here can fail, the precision number means nothing.
"""

from __future__ import annotations

from compatlab.findings import BREAKING, Finding
from compatlab.impact import BLOCKS, CORRUPTS, map_findings
from compatlab.verify import (
    CONFIRMED,
    UNCONFIRMED,
    Verification,
    check,
    ground_truth_coverage,
    verify,
)
from compatlab.workflows import DECISION, RECORD, REQUEST_INPUT, Call, Read, Workflow


def record(step: str, status: int, body: dict, seq: int = 0) -> dict:
    return {
        "workflow": "checkout", "step": step, "seq": seq, "method": "POST",
        "path": "/v1/payment_intents", "path_template": "/v1/payment_intents",
        "query": {}, "request_body": {}, "stripe_version": "x",
        "response": {"status": status, "headers": {}, "body": body},
    }


def canon(step: str, status: int, body: dict) -> dict:
    return {"workflow": "checkout", "step": step, "method": "POST",
            "path": "/v1/payment_intents", "query": {}, "request_body": {},
            "status": status, "headers": {}, "body": body}


def finding(**overrides) -> Finding:
    base = {
        "workflow": "checkout", "step": "create_intent", "seq": 0,
        "method": "POST", "path_template": "/v1/payment_intents",
        "axis": "value", "locus": "$.body.capture_method",
        "rule": "value-changed", "severity": BREAKING,
        "rationale": "it changed", "a": '"automatic"', "b": '"manual"',
    }
    return Finding(**{**base, **overrides})


def workflow(*reads: Read, name: str = "card_payment") -> Workflow:
    return Workflow(name=name, purpose="p", criticality="high", owner="o",
                    sequence=(Call(corpus="checkout.create_intent",
                                   reads=reads),),
                    source="t.json")


def one_impact(declared: Read, found: Finding):
    return map_findings([workflow(declared)], [found]).impacts[0]


KEY = ("checkout", "create_intent")
PAIR = {"workflow": "checkout", "step": "create_intent", "seq": 0,
        "method": "POST", "path_template": "/v1/payment_intents",
        "a": record("create_intent", 200, {}), "b": None}


def test_a_claim_whose_read_really_changed_is_confirmed():
    impact = one_impact(Read("$.body.capture_method", DECISION, "decides"),
                        finding())
    result = check(impact, PAIR,
                   canon("create_intent", 200, {"capture_method": "automatic"}),
                   canon("create_intent", 200, {"capture_method": "manual"}))
    assert result.verdict == CONFIRMED
    assert "'automatic'" in result.detail and "'manual'" in result.detail


def test_a_claim_whose_read_resolves_identically_is_refused():
    """The mapping bug this is here to catch: a claim about nothing."""
    impact = one_impact(Read("$.body.capture_method", DECISION, "decides"),
                        finding())
    result = check(impact, PAIR,
                   canon("create_intent", 200, {"capture_method": "automatic"}),
                   canon("create_intent", 200, {"capture_method": "automatic"}))
    assert result.verdict == UNCONFIRMED
    assert "resolves identically" in result.detail


def test_a_claim_with_no_replay_pair_is_refused():
    impact = one_impact(Read("$.body.capture_method", DECISION, "d"), finding())
    assert check(impact, None, None, None).verdict == UNCONFIRMED


def test_a_step_missing_claim_is_confirmed_only_when_a_side_is_really_absent():
    impact = one_impact(
        Read("$.body.capture_method", DECISION, "d"),
        finding(locus="$", rule="step-missing", axis="availability"))
    absent = check(impact, PAIR, canon("create_intent", 200, {}), None)
    assert absent.verdict == CONFIRMED
    both = check(impact, PAIR, canon("create_intent", 200, {}),
                 canon("create_intent", 200, {}))
    assert both.verdict == UNCONFIRMED
    assert "both sides replayed" in both.detail


def test_only_a_step_missing_claim_may_be_made_about_a_one_sided_step():
    impact = one_impact(Read("$.body.capture_method", DECISION, "d"), finding())
    result = check(impact, PAIR, canon("create_intent", 200, {}), None)
    assert result.verdict == UNCONFIRMED


def test_a_blocking_status_claim_is_checked_against_the_two_status_codes():
    impact = one_impact(
        Read("$.body.amount_due", DECISION, "decides"),
        finding(locus="$.status", rule="status-class-changed", axis="status",
                a="200", b="404"))
    assert impact.consequence == BLOCKS
    good = check(impact, PAIR, canon("create_intent", 200, {"amount_due": 1}),
                 canon("create_intent", 404, {"error": {}}))
    assert good.verdict == CONFIRMED
    # Same class on both sides: the call did not stop working.
    bad = check(impact, PAIR, canon("create_intent", 200, {"amount_due": 1}),
                canon("create_intent", 201, {"amount_due": 2}))
    assert bad.verdict == UNCONFIRMED
    assert "recorded statuses are 200 and 201" in bad.detail


def test_a_blocking_propagation_claim_needs_nothing_left_to_send():
    impact = one_impact(
        Read("$.body.id", REQUEST_INPUT, "sent on", feeds="checkout.later"),
        finding(locus="$.body.id", rule="populated-field-removed",
                axis="shape", a='"pi_1"', b=None))
    assert impact.consequence == BLOCKS
    gone = check(impact, PAIR, canon("create_intent", 200, {"id": "pi_1"}),
                 canon("create_intent", 200, {}))
    assert gone.verdict == CONFIRMED
    # The value changed but is still there, so the next call can still be made.
    still = check(impact, PAIR, canon("create_intent", 200, {"id": "pi_1"}),
                  canon("create_intent", 200, {"id": "pi_2"}))
    assert still.verdict == UNCONFIRMED
    assert "still returns" in still.detail


def test_an_empty_collection_counts_as_nothing_left_to_send():
    impact = one_impact(
        Read("$.body.data", REQUEST_INPUT, "paged on", feeds="checkout.later"),
        finding(locus="$.body.data", rule="list-emptied", axis="truncation",
                a="[1]", b="[]"))
    result = check(impact, PAIR, canon("create_intent", 200, {"data": [1]}),
                   canon("create_intent", 200, {"data": []}))
    assert result.verdict == CONFIRMED


# --- the gate


def test_precision_is_confirmed_over_all_claims_and_gates_the_report():
    pairs = [{**PAIR, "b": record("create_intent", 200, {})}]
    canon_a = {KEY: canon("create_intent", 200, {"capture_method": "automatic",
                                                 "amount": 1})}
    canon_b = {KEY: canon("create_intent", 200, {"capture_method": "manual",
                                                 "amount": 1})}
    report = map_findings(
        [workflow(Read("$.body.capture_method", DECISION, "decides"),
                  Read("$.body.amount", RECORD, "stored"))],
        [finding(), finding(locus="$.body.amount", a="1", b="1")])
    result = verify(report, pairs, canon_a, canon_b)
    assert len(result.checks) == 2
    assert result.precision == 0.5
    assert not result.ok
    assert result.to_dict()["precision"] == 0.5


def test_a_report_with_no_claims_publishes_no_precision():
    result = Verification()
    assert result.precision is None
    assert result.ok
    assert result.to_dict()["precision"] is None


def test_an_all_confirmed_report_passes_the_gate():
    pairs = [{**PAIR, "b": record("create_intent", 200, {})}]
    canon_a = {KEY: canon("create_intent", 200, {"capture_method": "automatic"})}
    canon_b = {KEY: canon("create_intent", 200, {"capture_method": "manual"})}
    report = map_findings(
        [workflow(Read("$.body.capture_method", DECISION, "decides"))],
        [finding()])
    result = verify(report, pairs, canon_a, canon_b)
    assert result.ok and result.precision == 1.0
    assert result.checks[0].consequence == CORRUPTS


# --- the regression guard


def test_ground_truth_coverage_names_the_workflows_a_break_landed_on():
    report = map_findings(
        [workflow(Read("$.body.capture_method", DECISION, "decides"))],
        [finding(targets=("M2",))])
    coverage = ground_truth_coverage(
        report, [{"id": "M2", "summary": "capture_method default"}],
        {"M2": {finding(targets=("M2",)).key}})
    assert coverage == [{"id": "M2", "summary": "capture_method default",
                         "evidence_findings": 1, "mapped_findings": 1,
                         "workflows": ["card_payment"]}]


def test_ground_truth_coverage_reports_a_break_the_mapping_lost():
    """The guard's whole job: a break Phase 3 caught that nothing maps."""
    report = map_findings([workflow(Read("$.body.amount", RECORD, "stored"))],
                          [finding(targets=("M2",))])
    coverage = ground_truth_coverage(
        report, [{"id": "M2", "summary": "capture_method default"}],
        {"M2": {finding(targets=("M2",)).key}})
    assert coverage[0]["mapped_findings"] == 0
    assert coverage[0]["workflows"] == []
