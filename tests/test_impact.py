"""The join: findings plus declared reads, consequence out.

Three classes of test here. The table invariants guard against a rule or a use
being added without being placed, which is the quiet way a mapping stops
reporting something. The derivation tests check the cells that carry real
judgment. The rest check the parts that are easy to get subtly wrong and hard
to notice: a finding above a read, a call that stopped working, and the
findings nothing covers.
"""

from __future__ import annotations

import pytest

from compatlab.classify import RULES
from compatlab.findings import BENIGN, BREAKING, RISKY, Finding
from compatlab.impact import (
    ADDITION,
    BLOCKS,
    CALL,
    CALL_LEVEL_RULES,
    CHANGE,
    CONSEQUENCE_SUMMARY,
    CONSEQUENCE_TABLE,
    CONSEQUENCES,
    CORRUPTS,
    DEGRADES,
    EFFECT_OF_RULE,
    EFFECT_SUMMARY,
    EFFECTS,
    LOSS,
    NOVEL,
    REASON,
    TOLERATES,
    effect_of,
    map_findings,
    map_workflow,
    pins,
)
from compatlab.impact_html import _VERDICT_BADGE
from compatlab.impact_report import VERDICT_LABEL
from compatlab.workflows import DECISION, DISPLAY, RECORD, REQUEST_INPUT, USES, Call, Read, Workflow


def finding(**overrides) -> Finding:
    base = {
        "workflow": "checkout", "step": "create_intent", "seq": 0,
        "method": "POST", "path_template": "/v1/payment_intents",
        "axis": "value", "locus": "$.body.capture_method",
        "rule": "value-changed", "severity": BREAKING,
        "rationale": "it changed", "a": '"automatic"', "b": '"manual"',
    }
    return Finding(**{**base, **overrides})


def workflow(*reads: Read, step: str = "create_intent",
             name: str = "card_payment") -> Workflow:
    return Workflow(
        name=name, purpose="p", criticality="high", owner="o",
        sequence=(Call(corpus=f"checkout.{step}", reads=reads),),
        source="test.json",
    )


def read(locus="$.body.capture_method", use=DECISION, **kw) -> Read:
    return Read(locus=locus, use=use, note=kw.pop("note", "it decides"), **kw)


# --- table invariants: a new rule or use cannot be silently ignored


def test_every_classification_rule_is_placed_in_an_effect_class():
    missing = sorted({rule.id for rule in RULES} - set(EFFECT_OF_RULE))
    assert missing == [], (
        "every rule in classify.RULES needs an entry in EFFECT_OF_RULE, or "
        "the mapping quietly stops reporting it")


def test_the_effect_table_names_no_rule_the_classifier_cannot_produce():
    stale = sorted(set(EFFECT_OF_RULE) - {rule.id for rule in RULES})
    assert stale == []


def test_an_unplaced_rule_raises_rather_than_defaulting():
    with pytest.raises(KeyError, match="no effect class"):
        effect_of(finding(rule="invented-rule"))


def test_every_effect_and_use_pair_has_a_consequence_and_a_reason():
    expected = {(effect, use) for effect in EFFECTS for use in USES}
    assert set(CONSEQUENCE_TABLE) == expected
    assert set(REASON) == expected


def test_every_consequence_and_effect_has_a_summary_for_the_report():
    assert set(CONSEQUENCE_SUMMARY) == set(CONSEQUENCES)
    assert set(EFFECT_SUMMARY) == set(EFFECTS)


def test_every_consequence_can_be_labelled_and_badged_by_both_renderers():
    """A new consequence must not reach a renderer as a KeyError.

    Adding `unblocks` in RC1-618 broke the HTML report at the badge lookup,
    which only the published-artifact test caught, and only because a real
    workflow happened to hit it.
    """
    for consequence in CONSEQUENCES:
        assert consequence in VERDICT_LABEL, consequence
        assert consequence in _VERDICT_BADGE, consequence
    assert "clear" in VERDICT_LABEL and "clear" in _VERDICT_BADGE


def test_the_call_level_rules_are_classified_as_losses():
    for rule in CALL_LEVEL_RULES:
        assert EFFECT_OF_RULE[rule] == LOSS


# --- the cells that carry judgment


@pytest.mark.parametrize("use,expected", [
    (REQUEST_INPUT, BLOCKS),
    (DECISION, CORRUPTS),
    (RECORD, CORRUPTS),
    (DISPLAY, DEGRADES),
])
def test_losing_a_value_blocks_only_where_a_later_call_needs_it(use, expected):
    assert CONSEQUENCE_TABLE[(LOSS, use)] == expected


def test_a_value_the_client_has_never_seen_corrupts_a_decision():
    """The exhaustive-switch case, and the reason risky findings are joined."""
    assert CONSEQUENCE_TABLE[(NOVEL, DECISION)] == CORRUPTS
    assert CONSEQUENCE_TABLE[(NOVEL, RECORD)] == DEGRADES


def test_purely_additive_material_is_tolerated_except_where_it_is_stored():
    assert CONSEQUENCE_TABLE[(ADDITION, DECISION)] == TOLERATES
    assert CONSEQUENCE_TABLE[(ADDITION, REQUEST_INPUT)] == TOLERATES
    assert CONSEQUENCE_TABLE[(ADDITION, RECORD)] == DEGRADES


def test_a_change_never_tolerates():
    assert TOLERATES not in {CONSEQUENCE_TABLE[(CHANGE, use)] for use in USES}


# --- the join


def test_a_finding_on_a_declared_read_produces_one_impact():
    item = map_workflow(workflow(read()), [finding()])
    assert len(item.impacts) == 1
    impact = item.impacts[0]
    assert impact.consequence == CORRUPTS
    assert impact.position == 1 and impact.length == 1
    assert impact.use == DECISION
    assert "it decides" in impact.reason
    assert item.verdict == CORRUPTS
    assert item.first_break is impact


def test_a_finding_on_a_field_nobody_declared_produces_no_impact():
    item = map_workflow(workflow(read(locus="$.body.amount")), [finding()])
    assert item.impacts == []
    assert item.verdict == "clear"
    assert item.first_break is None
    assert [f.key for f in item.uncovered] == [finding().key]


def test_a_removed_subtree_covers_every_declared_read_inside_it():
    item = map_workflow(
        workflow(read(locus="$.body.lines.data[].plan.id", use=RECORD)),
        [finding(locus="$.body.lines", rule="populated-field-removed",
                 axis="shape")],
    )
    assert [i.consequence for i in item.impacts] == [CORRUPTS]


def test_a_benign_rule_about_the_comparison_produces_no_impact():
    """`status-body-subsumed` and `timing-shifted` describe the comparison."""
    item = map_workflow(
        workflow(read(locus="$.body", use=RECORD)),
        [finding(locus="$.body", rule="status-body-subsumed", axis="shape",
                 severity=BENIGN, subsumed=85)],
    )
    assert item.impacts == []


def test_an_untouched_read_is_reported_rather_than_dropped():
    item = map_workflow(
        workflow(read(), read(locus="$.body.amount", use=RECORD)), [finding()])
    assert [r.locus for _, r in item.untouched_reads] == ["$.body.amount"]


def test_a_benign_finding_is_never_reported_as_uncovered():
    """Uncovered means a real difference nothing declared covers."""
    item = map_workflow(
        workflow(read(locus="$.body.amount")),
        [finding(locus="$.body.new_field", rule="field-added-empty",
                 axis="shape", severity=BENIGN)],
    )
    assert item.uncovered == []


# --- the two rules that are about the call, not about a value in it


def test_a_call_that_stops_working_blocks_whatever_the_read_is_for():
    item = map_workflow(
        workflow(read(locus="$.body.amount_due", use=DISPLAY)),
        [finding(locus="$.status", rule="status-class-changed", axis="status",
                 a="200", b="404")],
    )
    assert [i.consequence for i in item.impacts] == [BLOCKS]
    assert "404" in item.impacts[0].reason


def test_a_call_that_stops_working_blocks_even_with_no_declared_read():
    """Otherwise a workflow whose call now 404s reports as unaffected."""
    item = map_workflow(
        workflow(), [finding(locus="$.status", rule="status-class-changed",
                             axis="status", a="200", b="404")])
    assert item.verdict == BLOCKS
    assert item.impacts[0].use == CALL
    assert item.impacts[0].locus == "$"
    assert CALL not in USES, "a declaration must not be able to say `call`"


def test_a_step_that_could_not_be_replayed_at_all_blocks():
    item = map_workflow(
        workflow(read()),
        [finding(locus="$", rule="step-missing", axis="availability")])
    assert [i.consequence for i in item.impacts] == [BLOCKS]


def test_a_blocked_call_marks_its_reads_touched_whatever_their_locus():
    """A read on a call that now 404s is affected, not untouched.

    The untouched list means "this version change does not reach this read",
    and for a read on a call that stopped working that is simply false — the
    client cannot make the read at all. The locus never matches `$.status`,
    so without the call-level path these would be listed as unaffected.
    """
    item = map_workflow(
        workflow(read(), read(locus="$.body.amount", use=RECORD)),
        [finding(locus="$.status", rule="status-class-changed", axis="status",
                 a="200", b="404")])
    assert item.untouched_reads == []
    assert {i.locus for i in item.impacts} == {"$.body.capture_method",
                                               "$.body.amount"}
    assert {i.consequence for i in item.impacts} == {BLOCKS}


# --- verdicts and ordering


def test_a_workflow_verdict_is_its_worst_consequence():
    item = map_workflow(
        workflow(read(locus="$.body.capture_method", use=DISPLAY),
                 read(locus="$.body.amount", use=RECORD)),
        [finding(), finding(locus="$.body.amount")],
    )
    assert {i.consequence for i in item.impacts} == {DEGRADES, CORRUPTS}
    assert item.verdict == CORRUPTS
    assert item.first_break.consequence == CORRUPTS


def test_the_report_orders_by_verdict_then_criticality_then_name():
    blocked = workflow(read(), name="b")
    clear = workflow(read(locus="$.body.amount"), name="a")
    report = map_findings([clear, blocked], [finding()])
    assert [w.workflow.name for w in report.ordered()] == ["b", "a"]
    assert [w.workflow.name for w in report.affected] == ["b"]
    assert [w.workflow.name for w in report.by_verdict("clear")] == ["a"]


def test_a_finding_on_a_call_no_workflow_replays_is_reported_as_outside():
    report = map_findings([workflow(read())],
                          [finding(step="some_other_step")])
    assert len(report.outside) == 1
    assert report.to_dict()["findings_outside_inventory"] == 1


def test_a_benign_finding_outside_the_inventory_is_not_reported():
    report = map_findings(
        [workflow(read())],
        [finding(step="elsewhere", rule="field-added-empty", axis="shape",
                 severity=BENIGN)])
    assert report.outside == []


def test_the_summary_counts_reads_touched_against_reads_declared():
    report = map_findings(
        [workflow(read(), read(locus="$.body.amount", use=RECORD))],
        [finding()])
    summary = report.to_dict()
    assert summary["reads_declared"] == 2
    assert summary["reads_touched"] == 1


# --- pins


def test_a_pin_is_emitted_for_every_blocked_or_corrupted_read():
    report = map_findings([workflow(read())], [finding()])
    assert [p["assertion"] for p in pins(report)] == [
        '`$.body.capture_method` equals "automatic"']


def test_a_degraded_read_is_not_pinned():
    report = map_findings([workflow(read(use=DISPLAY))], [finding()])
    assert pins(report) == []


def test_two_workflows_hitting_one_place_share_a_single_pin():
    one = workflow(read(), name="one")
    two = workflow(read(), name="two")
    pin_list = pins(map_findings([one, two], [finding()]))
    assert len(pin_list) == 1
    assert pin_list[0]["workflows"] == ["one", "two"]


def test_a_pin_keeps_the_worst_consequence_and_all_its_workflows():
    """The worse claim must not drop the workflows the milder one named."""
    mild = workflow(read(use=RECORD), name="mild")
    severe = workflow(read(use=REQUEST_INPUT, feeds="checkout.later"),
                      name="severe")
    report = map_findings(
        [mild, severe],
        [finding(rule="populated-field-removed", axis="shape", b=None)])
    pin_list = pins(report)
    assert len(pin_list) == 1
    assert pin_list[0]["consequence"] == BLOCKS
    assert sorted(pin_list[0]["workflows"]) == ["mild", "severe"]


def test_a_pin_on_a_clipped_value_names_the_property_not_the_literal():
    """An assertion built from truncated JSON is a test nobody can write."""
    long = '{"a": 1, "b": 2' + "..."
    report = map_findings(
        [workflow(read(locus="$.body.data", use=RECORD))],
        [finding(locus="$.body.data", rule="populated-field-removed",
                 axis="shape", a=long, b=None)])
    assert pins(report)[0]["assertion"] == (
        "`$.body.data` is present and unchanged from the old version")
    assert pins(report)[0]["expect_on_a"] == long


def test_an_emptied_collection_is_pinned_on_being_non_empty():
    report = map_findings(
        [workflow(read(locus="$.body.data", use=RECORD))],
        [finding(locus="$.body.data", rule="list-emptied", axis="truncation",
                 a="[1]", b="[]")])
    assert pins(report)[0]["assertion"] == (
        "`$.body.data` comes back as a non-empty collection")


def test_a_blocked_call_is_pinned_on_its_status():
    report = map_findings(
        [workflow(read())],
        [finding(locus="$.status", rule="status-class-changed", axis="status",
                 a="200", b="404")])
    assert pins(report)[0]["assertion"] == (
        "`checkout.create_intent` returns status 200 and not 404")


def test_a_risky_finding_becomes_a_pin_once_a_read_declares_the_use():
    """The whole argument for the inventory, as a test.

    Phase 3 cannot rank `enum-set-grew` higher than risky, because whether it
    breaks depends on how the client was written. The declaration is that
    fact, so the same finding yields a pinned regression test here.
    """
    grew = finding(rule="enum-set-grew", axis="enum", severity=RISKY,
                   locus="$.body.payment_method_types",
                   a='["card"]', b='["card", "klarna"]')
    report = map_findings(
        [workflow(read(locus="$.body.payment_method_types", use=DECISION))],
        [grew])
    assert report.impacts[0].severity == RISKY
    assert report.impacts[0].consequence == CORRUPTS
    assert len(pins(report)) == 1


def test_a_call_level_impact_is_not_counted_as_a_touched_read():
    """`$` is not a declared read; counting it could exceed reads_declared."""
    report = map_findings(
        [workflow()],
        [finding(locus="$.status", rule="status-class-changed", axis="status",
                 a="200", b="404")])
    summary = report.to_dict()
    assert summary["reads_declared"] == 0
    assert summary["reads_touched"] == 0
    assert summary["impacts"] == 1
