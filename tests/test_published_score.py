"""The published numbers, as tests.

Everything the project claims in public comes out of four committed files:
`replay/pairs.jsonl`, `findings/findings.jsonl`,
`baseline/schema-diff-index.jsonl`, and `scoring/adjudication.json`. A claim
is only as good as the guarantee that the artifact still matches the code that
produced it, so these tests re-derive the findings from the pairs, re-score
them, and fail if the committed artifact, the report, or the adjudication has
drifted away from what the differ now says.

This is also the CI gate on honesty-by-default: a new breaking finding arrives
with no verdict, scoring refuses to publish a rate, and the suite goes red
until somebody adjudicates it.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from compatlab.baseline import BaselineIndex, endpoint_key
from compatlab.cli import seeded_policy
from compatlab.differ import diff_pairs
from compatlab.findings import BREAKING
from compatlab.scoring import FALSE_BREAK, Adjudication, headline, normalize, score

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAIRS = ROOT / "replay" / "pairs.jsonl"
FINDINGS = ROOT / "findings" / "findings.jsonl"
BASELINE = ROOT / "baseline" / "schema-diff-index.jsonl"
ADJUDICATION = ROOT / "scoring" / "adjudication.json"
REPORT = ROOT / "docs" / "behavioral-diff-report.md"

pytestmark = pytest.mark.skipif(
    not PAIRS.exists(), reason="no replay output committed")


def pairs() -> list[dict]:
    return [json.loads(line) for line in PAIRS.read_text().splitlines() if line]


def report():
    return diff_pairs(pairs())


def card():
    return score(report(), BaselineIndex.load(BASELINE),
                 Adjudication.load(ADJUDICATION), pairs())


def test_the_committed_findings_match_what_the_differ_now_produces():
    produced = [json.dumps(f.to_dict(), sort_keys=True)
                for f in report().sorted_findings()]
    committed = [line for line in FINDINGS.read_text().splitlines() if line]
    assert produced == committed, (
        "findings/findings.jsonl is stale; re-run `compatlab diff`")


def test_no_breaking_finding_is_unadjudicated():
    unadjudicated = card()["false_breaks"]["unadjudicated"]
    assert unadjudicated == [], (
        "every breaking finding needs a verdict in scoring/adjudication.json "
        "before a false-break rate can be published")


def test_every_live_confirmed_break_is_caught():
    caught = {b["id"] for b in card()["ground_truth"]["breaks"] if b["caught"]}
    assert {"M1", "M2", "M3", "M4"} <= caught


def test_no_break_the_corpus_cannot_reach_is_reported_as_caught():
    for item in card()["ground_truth"]["breaks"]:
        if not item["exercised"]:
            assert not item["caught"], f"{item['id']} caught without a scenario"


def test_the_false_break_rate_is_stated_and_derived_from_every_finding():
    false = card()["false_breaks"]
    assert false["rate"] is not None
    assert false["breaking_findings"] == len(report().by_severity(BREAKING))
    assert sum(false["verdicts"].values()) == false["breaking_findings"]
    assert false["rate"] == (false["verdicts"][FALSE_BREAK]
                             / false["breaking_findings"])


def test_every_adjudication_entry_matches_a_finding_that_exists():
    """A verdict for a finding the differ no longer produces is dead weight.

    It is also the shape a flattering score would take: keep the verdicts,
    quietly lose the findings.
    """
    breaking = report().by_severity(BREAKING)
    adjudication = Adjudication.load(ADJUDICATION)
    used = {id(adjudication.verdict_for(f)) for f in breaking}
    orphans = [entry["match"] for entry in adjudication.verdicts
               if id(entry) not in used]
    assert orphans == []


def test_the_baseline_covers_every_endpoint_the_replay_called():
    index = BaselineIndex.load(BASELINE)
    called = {endpoint_key(p["method"], p["path_template"]) for p in pairs()}
    missing = sorted(key for key in called if key not in index.endpoints)
    assert missing == [], "the baseline was generated for a different corpus"


def test_the_baseline_was_generated_from_the_pinned_specs():
    meta = BaselineIndex.load(BASELINE).meta
    assert meta["specs"]["a"]["declared_version"] == "2022-11-15"
    assert meta["specs"]["b"]["declared_version"] == "2025-03-31.basil"
    assert "@sha256:" in meta["oasdiff"]["image"]


def test_the_written_report_still_leads_with_the_computed_headline():
    assert REPORT.exists(), "run `compatlab score --out`"
    assert headline(card()) in REPORT.read_text()


def test_the_findings_file_carries_no_fixture_value_or_secret():
    """A derived artifact outside `corpus/`, so it gets its own gate.

    The findings quote values out of the corpus, which means a redaction hole
    would be copied straight into them — the way the first leak got out was a
    file nobody thought to scan (ADR 0002 D3).
    """
    policy = seeded_policy()
    stored = FINDINGS.read_text()
    assert "sk_test" not in stored and "sk_live" not in stored
    leaks = [
        f"{record.get('key')}: {finding}"
        for line in stored.splitlines() if line
        for record in [json.loads(line)]
        for finding in policy.scan(record)
    ]
    assert leaks == []


def test_normalized_loci_are_what_the_adjudication_matches_on():
    # Guards the one coupling that would silently break every verdict: the
    # adjudication file is written against normalized loci.
    for entry in Adjudication.load(ADJUDICATION).verdicts:
        locus = entry["match"].get("locus")
        if locus:
            assert normalize(locus) == locus
