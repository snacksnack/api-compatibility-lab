"""The six quality dimensions, scored from the committed artifacts.

CI already gates on four of these. The suite is not a second copy of those
gates: a gate answers *is this publishable right now*, and an eval answers
*is it getting better or worse, and attributably*. Run records carry the code
version, so a number that moves can be pinned to the commit that moved it —
which is the thing a passing gate cannot tell anyone.

Each dimension is one case with named characteristics, and the published
figures ride in `observations` so a report can aggregate them without
re-deriving anything.

One dimension is deliberately **advisory**: how badly the schema-diff baseline
does on these breaks is a property of Stripe's published specs, not of this
code. It belongs in every run and it must never fail a build, because a
dimension that can fail for reasons outside the subject gets muted, and a
muted check catches nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from agent_evals.case import Case
from agent_evals.record import CaseResult, CharacteristicResult, SubjectVersion, Usage

from compatlab import VERSION_A, VERSION_B
from compatlab.certify import gate
from compatlab.impact import BLOCKS, CORRUPTS
from compatlab.pinning import UNREACHED
from compatlab.telemetry import package_version
from evals import world

SUBJECT = "api-compatibility-lab"

CASES: tuple[Case, ...] = (
    Case(
        id="detection-recall",
        input={"artifact": "findings/findings.jsonl", "against": "docs/ground-truth.md"},
        expect=("every-exercised-break-caught",
                "no-unexercised-break-reported-as-caught"),
        tags=("ground-truth",),
    ),
    Case(
        id="false-breaks",
        input={"artifact": "scoring/adjudication.json"},
        expect=("every-breaking-finding-adjudicated", "no-false-breaks"),
        tags=("ground-truth", "honesty-gate"),
    ),
    Case(
        id="schema-diff-advantage",
        input={"artifact": "baseline/schema-diff-index.jsonl"},
        expect=("the-baseline-gave-no-usable-warning",),
        tags=("baseline", "advisory"),
    ),
    Case(
        id="workflow-mapping",
        input={"artifact": "workflows/", "against": "replay/pairs.jsonl"},
        expect=("the-inventory-matches-the-captured-traffic",
                "every-impact-claim-confirmed"),
        tags=("impact", "honesty-gate"),
    ),
    Case(
        id="pinned-tests",
        input={"artifact": "pins/certification.json"},
        expect=("the-suite-matches-what-the-pins-compile-to",
                "every-pin-certified",
                "no-pin-rests-on-an-unreached-step"),
        tags=("pins", "honesty-gate"),
    ),
    Case(
        id="corpus-sanitization",
        input={"artifact": "corpus/"},
        expect=("zero-pii-findings-in-the-committed-corpus",),
        tags=("sanitization", "scored-requirement"),
    ),
)


def version() -> SubjectVersion:
    """A deterministic subject: `model` is None because there is no model.

    Spelled out rather than omitted — a missing key would read as "we forgot
    to record it" instead of "there is nothing to record" (ADR 0007).
    """
    return SubjectVersion(subject=SUBJECT, code_version=package_version(),
                          model=None, prompt_version=None)


def _ok(name: str, passed: bool, detail: str, *, advisory: bool = False):
    return CharacteristicResult(name=name, passed=passed, detail=detail,
                                advisory=advisory)


def _detection_recall() -> tuple[list[CharacteristicResult], dict]:
    card = world.card()["ground_truth"]
    exercised = [b for b in card["breaks"] if b["exercised"]]
    missed = [b["id"] for b in exercised if not b["caught"]]
    phantom = [b["id"] for b in card["breaks"]
               if b["caught"] and not b["exercised"]]
    return [
        _ok("every-exercised-break-caught", not missed,
            f"{card['caught_of_exercised']} exercised ground-truth breaks "
            f"caught (inventory M={card['m']})"
            + (f"; missed {', '.join(missed)}" if missed else "")),
        _ok("no-unexercised-break-reported-as-caught", not phantom,
            "no break the corpus cannot exercise is reported as caught"
            if not phantom else
            f"reported as caught without being exercised: {', '.join(phantom)}"),
    ], {
        "caught": len(exercised) - len(missed),
        "exercised": len(exercised),
        "inventory_m": card["m"],
        "unexercised": [b["id"] for b in card["breaks"] if not b["exercised"]],
        "per_break": {b["id"]: {"exercised": b["exercised"],
                                "caught": b["caught"],
                                "baseline": b["baseline"]}
                      for b in card["breaks"]},
    }


def _false_breaks() -> tuple[list[CharacteristicResult], dict]:
    card = world.card()["false_breaks"]
    unadjudicated = card["unadjudicated"]
    rate = card["rate"]
    return [
        _ok("every-breaking-finding-adjudicated", not unadjudicated,
            f"{card['breaking_findings']} breaking finding(s), "
            f"{len(unadjudicated)} without a hand verdict"),
        # Scored against a published rate of exactly zero. The rate is None
        # while anything is unadjudicated, and None is a failure here rather
        # than a skip: no rate means the first characteristic already failed.
        _ok("no-false-breaks", rate == 0,
            f"false-break rate {rate} over {card['breaking_findings']} "
            f"breaking finding(s); read as no false breaks observed, not as a "
            f"rate measured at scale"),
    ], {
        "breaking_findings": card["breaking_findings"],
        "verdicts": card["verdicts"],
        "false_break_rate": rate,
        "unadjudicated": len(unadjudicated),
    }


def _schema_diff_advantage() -> tuple[list[CharacteristicResult], dict]:
    card = world.card()["baseline"]
    blind = card["green_on_caught"] + card["named_only_on_caught"]
    return [
        _ok("the-baseline-gave-no-usable-warning", blind > 0,
            f"of the caught breaks, {card['green_on_caught']} drew no baseline "
            f"entry at all and {card['named_only_on_caught']} named the field "
            f"without the behavior, while the same baseline reported "
            f"{card['entries_corpus_endpoints']} breaking changes on the "
            f"endpoints this corpus calls",
            advisory=True),
    ], {
        "green_on_caught": card["green_on_caught"],
        "named_only_on_caught": card["named_only_on_caught"],
        "reported_on_caught": card["reported_on_caught"],
        "baseline_entries_corpus_endpoints": card["entries_corpus_endpoints"],
        "baseline_entries_unscoped": card["entries_unscoped"],
        "missed_by_schema_diff": card["missed_by_schema_diff"],
    }


def _workflow_mapping() -> tuple[list[CharacteristicResult], dict]:
    report, verification, validation = world.impact()
    precision = verification.precision
    return [
        _ok("the-inventory-matches-the-captured-traffic", validation.ok,
            f"{validation.steps_checked} declared call(s) and "
            f"{validation.reads_checked} declared read(s) validated"
            + ("" if validation.ok
               else f"; {len(validation.problems)} problem(s)")),
        _ok("every-impact-claim-confirmed", verification.ok,
            f"{len(verification.confirmed)} of {len(verification.checks)} "
            f"claim(s) re-derived from the replay record by a checker that "
            f"does not read the rule table"),
    ], {
        "claims": len(verification.checks),
        "confirmed": len(verification.confirmed),
        "mapping_precision": None if precision is None else round(precision, 4),
        "workflows_declared": len(report.workflows),
        "workflows_affected": len(report.affected),
        "workflows_blocked": len(report.by_verdict(BLOCKS)),
        "workflows_corrupted": len(report.by_verdict(CORRUPTS)),
        "reads_declared": validation.reads_checked,
        "findings_outside_the_inventory": len(report.outside),
    }


def _pinned_tests() -> tuple[list[CharacteristicResult], dict]:
    tests = world.pins()
    certification = world.certification()
    source = world.suite_source()
    committed = world.SUITE.read_text() if world.SUITE.exists() else ""
    problems = gate(tests, certification, source, version_a=VERSION_A,
                    version_b=VERSION_B)
    unreached = [e.pin for e in certification.entries
                 if UNREACHED in (e.on_a, e.on_b)]
    return [
        _ok("the-suite-matches-what-the-pins-compile-to", committed == source,
            f"{len(tests)} pinned test(s) generated from {len(tests)} pin(s)"
            if committed == source else
            "the committed suite is not what the pins compile to"),
        _ok("every-pin-certified", not problems,
            f"{len(certification.certified)} of "
            f"{len(certification.claimable)} pin(s) pass on {VERSION_A} and "
            f"fail on {VERSION_B}, certified {certification.certified_at}"
            + ("" if not problems else f"; {len(problems)} problem(s)")),
        _ok("no-pin-rests-on-an-unreached-step", not unreached,
            "every certified outcome is a real assertion result"
            if not unreached else
            f"{len(unreached)} pin(s) never exercised: {', '.join(unreached)}"),
    ], {
        "pins": len(tests),
        "certified": len(certification.certified),
        "claimable": len(certification.claimable),
        "waived": len(certification.waived),
        "certified_at": certification.certified_at,
        "certification_mode": certification.mode,
        "gate_problems": len(problems),
    }


def _corpus_sanitization() -> tuple[list[CharacteristicResult], dict]:
    findings = world.corpus_scan()
    return [
        _ok("zero-pii-findings-in-the-committed-corpus", not findings,
            "an independent scan of the committed corpus found nothing"
            if not findings else f"{len(findings)} finding(s)"),
    ], {
        # The findings themselves are deliberately not recorded: a run record
        # that quotes what leaked is the leak, one store further on.
        "pii_findings": len(findings),
    }


SCORERS: dict[str, Callable[[], tuple[list[CharacteristicResult], dict]]] = {
    "detection-recall": _detection_recall,
    "false-breaks": _false_breaks,
    "schema-diff-advantage": _schema_diff_advantage,
    "workflow-mapping": _workflow_mapping,
    "pinned-tests": _pinned_tests,
    "corpus-sanitization": _corpus_sanitization,
}


def run(case: Case) -> CaseResult:
    """Score one dimension. Deterministic, offline, and free."""
    started = time.perf_counter()
    try:
        characteristics, observations = SCORERS[case.id]()
    except Exception as exc:  # noqa: BLE001 - an error is a distinct outcome
        return CaseResult(
            case_id=case.id, usage=_usage(started),
            error=f"{type(exc).__name__}: {exc}")
    declared = {c.name for c in characteristics}
    missing = set(case.expect) - declared
    if missing:
        # A case that scored fewer characteristics than it declared would
        # quietly pass on the ones it skipped.
        return CaseResult(
            case_id=case.id, usage=_usage(started),
            error=f"scored nothing for: {', '.join(sorted(missing))}")
    return CaseResult(case_id=case.id, characteristics=characteristics,
                      usage=_usage(started), observations=observations)


def _usage(started: float) -> Usage:
    """Zero spend, recorded rather than omitted: this suite costs nothing."""
    return Usage(latency_ms=(time.perf_counter() - started) * 1000)
