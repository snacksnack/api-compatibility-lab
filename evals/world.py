"""Load the committed artifacts once, so six dimensions can score them.

Every number this suite reports is derived from files in the repository:
`replay/pairs.jsonl`, `findings/findings.jsonl`, the baseline index, the hand
adjudication, the integration inventory, the pins, and the pinned suite's
certification. Nothing here calls Stripe and nothing here calls a model.

That is the whole shape of this subject. The estate's other eval suites score
a model's output and cost money to run; this one scores a deterministic
pipeline against ground truth its author did not write, which is why the
record carries `model=None` and zero spend — and recording the zero is the
point, not an omission (`agent_evals.record.Usage`).
"""

from __future__ import annotations

import functools
import json
import pathlib

from compatlab import VERSION_A, VERSION_B, baseline, scoring
from compatlab.canonical import canonical_side
from compatlab.capture import seed_known
from compatlab.certify import Certification, load_certification
from compatlab.codegen import render_module
from compatlab.corpus import files, read
from compatlab.differ import DiffReport, diff_pairs, sides
from compatlab.findings import Finding
from compatlab.findings import load as load_findings
from compatlab.impact import ImpactReport, map_findings
from compatlab.pinning import PinnedTest, compile_all, load_pins
from compatlab.redaction import STRIPE_POLICY
from compatlab.scenarios import SCENARIO_DIR
from compatlab.scenarios import load_all as load_scenarios
from compatlab.verify import Verification, verify
from compatlab.workflows import Validation, validate
from compatlab.workflows import load_all as load_workflows

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAIRS = ROOT / "replay" / "pairs.jsonl"
FINDINGS = ROOT / "findings" / "findings.jsonl"
BASELINE = ROOT / "baseline" / "schema-diff-index.jsonl"
ADJUDICATION = ROOT / "scoring" / "adjudication.json"
WORKFLOWS = ROOT / "workflows"
PINS = ROOT / "pins" / "pins.jsonl"
CERTIFICATION = ROOT / "pins" / "certification.json"
SUITE = ROOT / "pinned" / "test_pinned_behavior.py"
CORPUS = ROOT / "corpus"


@functools.cache
def pairs() -> list[dict]:
    with PAIRS.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


@functools.cache
def findings() -> list[Finding]:
    return load_findings(FINDINGS)


@functools.cache
def diff() -> DiffReport:
    return diff_pairs(pairs())


@functools.cache
def canonical() -> tuple[dict, dict]:
    side_a, side_b = sides(pairs())
    return canonical_side(side_a), canonical_side(side_b)


@functools.cache
def card() -> dict:
    """The Phase 3 scorecard: recall, the baseline comparison, false breaks."""
    index = baseline.BaselineIndex.load(BASELINE)
    adjudication = scoring.Adjudication.load(ADJUDICATION)
    return scoring.score(diff(), index, adjudication, pairs())


@functools.cache
def impact() -> tuple[ImpactReport, Verification, Validation]:
    declared = load_workflows(WORKFLOWS)
    canon_a, canon_b = canonical()
    seqs = {(p["workflow"], p["step"]): p["seq"] for p in pairs()}
    validation = validate(declared, canon_a, seqs)
    report = map_findings(declared, findings(), version_a=VERSION_A,
                          version_b=VERSION_B)
    return report, verify(report, pairs(), canon_a, canon_b), validation


@functools.cache
def pins() -> list[PinnedTest]:
    canon_a, _ = canonical()
    return compile_all(load_pins(PINS), canon_a)


@functools.cache
def certification() -> Certification:
    return load_certification(CERTIFICATION)


@functools.cache
def suite_source() -> str:
    """What the committed pins compile to now, for the drift comparison."""
    return render_module(pins(), VERSION_A, VERSION_B)


@functools.cache
def corpus_scan() -> list[str]:
    """An independent PII audit of every committed corpus file.

    Seeded with the literal values the scenarios send, exactly as
    `compatlab scan` is: shape detection alone cannot gate a name, so the
    scanner has to be told what was sent (ADR 0002 D7).
    """
    policy = seed_known(STRIPE_POLICY, load_scenarios(SCENARIO_DIR))
    out = []
    for path in files(CORPUS):
        for record in read(path):
            for finding in policy.scan(record):
                out.append(f"{path.name}: {finding}")
    return out
