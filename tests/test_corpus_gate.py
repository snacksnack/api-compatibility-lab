"""The epic's scored requirement, as a test: zero PII findings on the corpus.

This runs against the committed corpus on every push. It is the one test that
fails for a reason outside the code — somebody captured traffic the policy
does not cover — which is the point. The scan deliberately does not reuse the
writer's judgment: it re-detects sensitive shapes in stored data and accepts
only a recognized surrogate, the drop marker, or a public test fixture.
"""

from __future__ import annotations

import pathlib

import pytest

from compatlab.cli import seeded_policy
from compatlab.corpus import files, read, validate
from compatlab.redaction import STRIPE_POLICY
from compatlab.scenarios import SCENARIO_DIR, load_all

CORPUS_DIR = pathlib.Path(__file__).resolve().parent.parent / "corpus"
CORPUS_FILES = sorted(files(CORPUS_DIR))


def test_the_corpus_is_not_empty():
    assert CORPUS_FILES, f"no corpus files under {CORPUS_DIR}"


@pytest.mark.parametrize("path", CORPUS_FILES, ids=lambda p: p.name)
def test_every_stored_record_is_valid(path: pathlib.Path):
    problems = [f"{i}: {p}" for i, rec in enumerate(read(path))
                for p in validate(rec)]
    assert problems == []


@pytest.mark.parametrize("path", CORPUS_FILES, ids=lambda p: p.name)
def test_zero_pii_findings_in_the_stored_corpus(path: pathlib.Path):
    findings = [
        f"{rec.get('workflow')}.{rec.get('step')} {finding}"
        for rec in read(path)
        for finding in seeded_policy().scan(rec)
    ]
    assert findings == []


@pytest.mark.parametrize("path", CORPUS_FILES, ids=lambda p: p.name)
def test_no_authorization_header_was_ever_stored(path: pathlib.Path):
    for rec in read(path):
        headers = {k.lower() for k in rec["response"]["headers"]}
        assert not headers - {"request-id", "stripe-version"}
        assert "sk_test" not in str(rec) and "sk_live" not in str(rec)


def fixture_values() -> list[tuple[str, str, str]]:
    """Literal scenario values the policy claims to redact: (file, key, value)."""
    out = []
    for scenario in load_all(SCENARIO_DIR):
        for step in scenario.steps:
            for key, value in (step.body or {}).items():
                if "{{" in str(value):
                    continue
                if STRIPE_POLICY.redact({key: value})[key] != value:
                    out.append((f"{scenario.workflow}.{step.step}", key, value))
    return out


def test_the_scenarios_contain_values_worth_redacting():
    assert fixture_values(), "nothing in the corpus exercises redaction"


@pytest.mark.parametrize("path", CORPUS_FILES, ids=lambda p: p.name)
def test_no_known_fixture_value_appears_anywhere_in_the_corpus(path: pathlib.Path):
    """The only gate that can catch an unredacted person's name.

    A name has no detectable shape, so `scan` cannot find one: names are
    covered by key rules, and a key rule that misses a field name fails
    silently. This test knows what was sent, so it can check what was stored.
    It is how `customer_name` — Stripe's snapshot of the customer onto the
    Invoice object — was caught surviving into the first captured corpus.
    """
    stored = path.read_text()
    survivors = [
        f"{where}: {key}={value!r}"
        for where, key, value in fixture_values()
        if value in stored
    ]
    assert survivors == []


PAIRS = pathlib.Path(__file__).resolve().parent.parent / "replay" / "pairs.jsonl"


def test_the_paired_replay_output_carries_no_fixture_value():
    """Pairs embed the side records, so this follows from the corpus gates.

    Asserted anyway: `replay/pairs.jsonl` is a committed file outside
    `corpus/`, and a derived artifact nobody checks is how the first leak got
    out (ADR 0002 D3).
    """
    if not PAIRS.exists():
        pytest.skip("no replay output committed")
    stored = PAIRS.read_text()
    survivors = [f"{where}: {key}" for where, key, value in fixture_values()
                 if value in stored]
    assert survivors == []
