"""Scoring: what counts as caught, what the baseline said, and the gate.

The gate is the test that matters most here. A false-break rate computed over
whichever findings happened to be adjudicated would be a flattering number
produced by accident, so scoring has to refuse to produce one.
"""

from __future__ import annotations

from compatlab.baseline import BaselineIndex, build_index
from compatlab.findings import DiffReport, Finding
from compatlab.scoring import (
    GREEN,
    GROUND_TRUTH,
    NAMED,
    REPORTED,
    Adjudication,
    baseline_verdict,
    evidence,
    exercised_targets,
    headline,
    render,
    score,
)

BREAK = {item.id: item for item in GROUND_TRUTH}

ENTRIES = [
    {"id": "response-property-enum-value-added", "operation": "POST",
     "path": "/v1/payment_intents",
     "text": "added the new `automatic_async` enum value to the "
             "`capture_method` response property for the response status `200`"},
    {"id": "api-path-removed-without-deprecation", "operation": "GET",
     "path": "/v1/invoices/upcoming", "text": "api path removed without deprecation"},
]


def index() -> BaselineIndex:
    return BaselineIndex.from_index(
        build_index(ENTRIES, scope=[], match="^x$", unscoped=254576))


def finding(**overrides) -> Finding:
    base = {
        "workflow": "checkout_card_payment", "step": "create_payment_intent",
        "seq": 0, "method": "POST", "path_template": "/v1/payment_intents",
        "axis": "enum", "locus": "$.body.capture_method",
        "rule": "enum-value-changed", "severity": "breaking",
        "rationale": "changed server default",
    }
    return Finding(**{**base, **overrides})


def test_the_inventory_matches_the_ground_truth_doc():
    assert len(GROUND_TRUTH) == 8
    assert [b.id for b in GROUND_TRUTH] == [f"M{i}" for i in range(1, 9)]
    assert sum(1 for b in GROUND_TRUTH if b.confirmed) == 4
    # Breaks with no loci are the ones no scenario reaches; each must say why.
    for item in GROUND_TRUTH:
        if not item.loci:
            assert item.note, f"{item.id} is unexercised with no reason given"


def test_a_break_is_caught_only_by_a_finding_in_its_own_workflow():
    report = DiffReport(findings=[finding(workflow="some_other_workflow")])
    assert evidence(report, BREAK["M2"]) == []


def test_a_break_is_caught_only_at_a_locus_it_surfaces_at():
    report = DiffReport(findings=[finding(locus="$.body.unrelated")])
    assert evidence(report, BREAK["M2"]) == []


def test_a_benign_finding_does_not_catch_a_break():
    report = DiffReport(findings=[finding(severity="benign", axis="timing",
                                          rule="timing-shifted")])
    assert evidence(report, BREAK["M2"]) == []


def test_a_risky_finding_does_catch_a_break():
    # M1 surfaces as `value-unnulled`, which is risky by rule. "Caught" means
    # reported above benign, not reported as breaking.
    report = DiffReport(findings=[finding(
        severity="risky", axis="nullability", rule="value-unnulled",
        locus="$.body.automatic_payment_methods")])
    assert len(evidence(report, BREAK["M1"])) == 1


def test_list_indices_do_not_stop_a_locus_from_matching():
    report = DiffReport(findings=[finding(
        workflow="partial_capture_reconcile", method="GET",
        path_template="/v1/charges", axis="value", rule="value-changed",
        locus="$.body.data[0].amount_refunded")])
    assert len(evidence(report, BREAK["M3"])) == 1


def test_the_baseline_verdict_distinguishes_green_named_and_reported():
    card = index()
    assert baseline_verdict(card, BREAK["M1"])[0] == GREEN
    assert baseline_verdict(card, BREAK["M2"])[0] == NAMED
    assert baseline_verdict(card, BREAK["M4"])[0] == REPORTED


def test_exercised_targets_are_read_off_the_pairs_not_assumed():
    pairs = [{"targets": ["M1", "M2"]}, {"targets": []}, {"targets": ["M3"]}]
    assert exercised_targets(pairs) == {"M1", "M2", "M3"}


def test_an_unadjudicated_breaking_finding_suppresses_the_rate():
    report = DiffReport(findings=[finding()], steps_compared=1)
    card = score(report, index(), Adjudication(), [{"targets": ["M2"]}])
    assert card["false_breaks"]["rate"] is None
    assert card["false_breaks"]["unadjudicated"]
    assert "not computed" in headline(card)
    assert "no rate is published" in render(card)


def test_an_adjudicated_finding_produces_a_rate():
    report = DiffReport(findings=[finding()], steps_compared=1)
    adjudication = Adjudication(verdicts=[{
        "match": {"rule": "enum-value-changed", "locus": "$.body.capture_method"},
        "verdict": "documented", "reference": "2024-04-10 #1",
    }])
    card = score(report, index(), adjudication, [{"targets": ["M2"]}])
    assert card["false_breaks"]["rate"] == 0.0
    assert card["false_breaks"]["verdicts"]["documented"] == 1


def test_a_false_break_verdict_moves_the_rate():
    findings = [finding(), finding(locus="$.body.other", step="s2")]
    adjudication = Adjudication(verdicts=[
        {"match": {"locus": "$.body.capture_method"}, "verdict": "documented"},
        {"match": {"locus": "$.body.other"}, "verdict": "false-break"},
    ])
    card = score(DiffReport(findings=findings), index(), adjudication, [])
    assert card["false_breaks"]["rate"] == 0.5


def test_an_unrecognized_verdict_counts_as_unadjudicated():
    adjudication = Adjudication(verdicts=[
        {"match": {"locus": "$.body.capture_method"}, "verdict": "probably fine"},
    ])
    card = score(DiffReport(findings=[finding()]), index(), adjudication, [])
    assert card["false_breaks"]["unadjudicated"]


def test_a_verdict_can_be_scoped_by_workflow_and_endpoint():
    adjudication = Adjudication(verdicts=[{
        "match": {"locus": "$.body.capture_method",
                  "workflow": "a_different_workflow"},
        "verdict": "documented",
    }])
    assert adjudication.verdict_for(finding()) is None


def test_the_denominator_reports_unexercised_breaks_rather_than_dropping_them():
    card = score(DiffReport(findings=[finding()]), index(), Adjudication(),
                 [{"targets": ["M2"]}])
    truth = card["ground_truth"]
    assert truth["m"] == 8
    assert truth["exercised"] == 1
    assert "8 in the inventory" in headline(card)
    unexercised = [b for b in truth["breaks"] if not b["exercised"]]
    assert len(unexercised) == 7
