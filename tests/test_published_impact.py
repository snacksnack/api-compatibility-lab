"""The published impact report, as tests.

Phase 4's claims come out of three committed inputs — `replay/pairs.jsonl`,
`findings/findings.jsonl`, and `workflows/` — and three committed outputs:
`pins/pins.jsonl`, `docs/impact-report.md`, and `docs/impact-report.html`. A
claim is only as good as the guarantee that the artifact still matches the
code that produced it, so these tests re-derive everything and fail if any of
it has drifted.

The gate that matters is the same shape as Phase 3's: a precision figure is
not publishable while any claim is unconfirmed, so the suite goes red rather
than printing a flattering number computed over whichever claims verified.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from compatlab import VERSION_A, VERSION_B, scoring
from compatlab.canonical import canonical_side
from compatlab.cli import _findings_from, seeded_policy
from compatlab.differ import diff_pairs, sides
from compatlab.impact import BLOCKS, CORRUPTS, map_findings, pins
from compatlab.impact_html import render_html
from compatlab.impact_report import headline, render
from compatlab.verify import ground_truth_coverage, verify
from compatlab.workflows import load_all, validate

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAIRS = ROOT / "replay" / "pairs.jsonl"
FINDINGS = ROOT / "findings" / "findings.jsonl"
WORKFLOWS = ROOT / "workflows"
PINS = ROOT / "pins" / "pins.jsonl"
REPORT = ROOT / "docs" / "impact-report.md"
HTML = ROOT / "docs" / "impact-report.html"

pytestmark = pytest.mark.skipif(
    not PAIRS.exists(), reason="no replay output committed")


def pairs() -> list[dict]:
    return [json.loads(line) for line in PAIRS.read_text().splitlines() if line]


def canon() -> tuple[dict, dict]:
    side_a, side_b = sides(pairs())
    return canonical_side(side_a), canonical_side(side_b)


def built():
    """The whole Phase 4 pipeline, from the committed inputs."""
    declared = load_all(WORKFLOWS)
    report = map_findings(declared, _findings_from(FINDINGS),
                          version_a=VERSION_A, version_b=VERSION_B)
    canon_a, canon_b = canon()
    verification = verify(report, pairs(), canon_a, canon_b)
    diff = diff_pairs(pairs())
    caught, keys = [], {}
    for item in scoring.GROUND_TRUTH:
        found = scoring.evidence(diff, item)
        keys[item.id] = {f.key for f in found}
        if found:
            caught.append({"id": item.id, "summary": item.summary})
    verification.coverage = ground_truth_coverage(report, caught, keys)
    return declared, report, verification


def test_the_inventory_is_not_empty():
    declared = load_all(WORKFLOWS)
    assert declared, f"no workflow declarations under {WORKFLOWS}"


def test_the_committed_inventory_validates_against_the_captured_traffic():
    canon_a, _ = canon()
    seqs = {(p["workflow"], p["step"]): p["seq"] for p in pairs()}
    result = validate(load_all(WORKFLOWS), canon_a, seqs)
    assert result.problems == []


def test_the_committed_pins_match_what_the_mapper_now_produces():
    _, report, _ = built()
    produced = [json.dumps(p, sort_keys=True) for p in pins(report)]
    committed = [line for line in PINS.read_text().splitlines() if line]
    assert produced == committed, (
        "pins/pins.jsonl is stale; re-run `compatlab impact`")


def test_every_impact_claim_is_confirmed_against_the_replay_record():
    _, _, verification = built()
    unconfirmed = [f"{c.claim}: {c.detail}" for c in verification.unconfirmed]
    assert unconfirmed == [], (
        "the workflow-mapping precision is not publishable while any claim "
        "is unverified")


def test_the_mapping_still_reaches_every_break_phase_three_caught():
    """A regression guard, not evidence. See ADR 0005 D6."""
    _, _, verification = built()
    lost = [item["id"] for item in verification.coverage
            if item["mapped_findings"] == 0]
    assert lost == [], (
        "a break the differ caught is no longer reported against any declared "
        "workflow; a step or a locus has dropped out of the inventory")


def test_the_written_reports_still_lead_with_the_computed_headline():
    _, report, verification = built()
    assert REPORT.exists() and HTML.exists(), "run `compatlab impact --out --html`"
    assert headline(report, verification) in REPORT.read_text()


def test_the_committed_markdown_report_matches_the_renderer():
    _, report, verification = built()
    produced = render(report, verification, pins(report)) + "\n"
    assert produced == REPORT.read_text(), (
        "docs/impact-report.md is stale; re-run `compatlab impact --out`")


def test_the_committed_html_report_matches_the_renderer():
    _, report, verification = built()
    produced = render_html(report, verification, pins(report))
    assert produced == HTML.read_text(), (
        "docs/impact-report.html is stale; re-run `compatlab impact --html`")


def test_the_html_report_is_self_contained():
    """The artifact is emailed, so it cannot fetch anything."""
    page = HTML.read_text()
    for forbidden in ("<script", "<link", "<img", "src=", "@import", "http://",
                      "https://"):
        assert forbidden not in page, f"{forbidden} in the HTML report"


def test_the_html_report_leaves_no_markdown_backticks_in_its_prose():
    body = HTML.read_text().split("</style>", 1)[1]
    assert "`" not in body


def test_the_inventory_does_not_only_confirm_its_own_author():
    """Guards the shape a rigged inventory would take.

    A declaration written backwards from the findings would touch every read
    it declares and leave nothing uncovered. Both numbers are published in
    the report; this asserts they stay real.
    """
    _, report, _ = built()
    summary = report.to_dict()
    assert summary["reads_touched"] < summary["reads_declared"], (
        "every declared read is affected, which is what an inventory written "
        "from the findings would look like")
    assert report.by_verdict("clear"), (
        "no declared workflow came out clear")
    assert summary["findings_outside_inventory"] > 0, (
        "the inventory covers every difference the differ found, which no "
        "real integration inventory does")


def test_the_report_states_what_it_does_not_cover():
    _, report, _ = built()
    text = REPORT.read_text()
    assert "declared read covers" in text
    assert "no declared workflow replays" in text
    assert "What this report does not cover" in text


def test_the_live_breaks_land_on_the_workflows_that_exercise_them():
    """The four live-confirmed breaks, mapped to a named customer workflow."""
    _, _, verification = built()
    landed = {item["id"]: item["workflows"] for item in verification.coverage}
    assert landed["M2"] == ["guest_checkout_capture"]
    assert landed["M3"] == ["nightly_refund_reconciliation"]
    assert landed["M4"] == ["subscription_renewal_billing"]


def test_the_inventory_exercises_every_verdict_the_report_can_give():
    """Otherwise a whole branch of the derivation ships unexercised."""
    _, report, _ = built()
    assert report.by_verdict(BLOCKS)
    assert report.by_verdict(CORRUPTS)
    assert report.by_verdict("degrades")
    assert report.by_verdict("clear")


def test_a_risky_finding_is_resolved_by_a_declared_read():
    """The argument for the inventory, asserted against the real corpus."""
    _, report, _ = built()
    promoted = [i for i in report.impacts
                if i.severity == "risky" and i.consequence == CORRUPTS]
    assert promoted, (
        "no risky finding was resolved into a concrete consequence by a "
        "declared read, which is the inventory's main reason to exist")


def test_the_pins_carry_no_fixture_value_or_secret():
    """A derived artifact outside `corpus/` gets its own gate (ADR 0002 D3)."""
    policy = seeded_policy()
    stored = PINS.read_text()
    assert "sk_test" not in stored and "sk_live" not in stored
    leaks = [
        f"{record.get('pin')}: {finding}"
        for line in stored.splitlines() if line
        for record in [json.loads(line)]
        for finding in policy.scan(record)
    ]
    assert leaks == []


def test_the_rendered_reports_carry_no_fixture_value_or_secret():
    for path in (REPORT, HTML):
        stored = path.read_text()
        assert "sk_test" not in stored and "sk_live" not in stored
