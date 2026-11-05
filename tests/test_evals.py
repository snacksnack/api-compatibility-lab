"""The eval suite: that it scores what it declares, and publishes what it scores.

These run against the committed artifacts, like the published-report tests do,
because the suite's whole job is to report on those artifacts. A dimension that
silently stopped scoring would otherwise read as a pass.
"""

from __future__ import annotations

import pytest

pytest.importorskip("agent_evals", reason="the evals dependency group")

from agent_evals.record import CaseResult, CharacteristicResult, Usage  # noqa: E402

from evals.__main__ import GAUGES, gauges  # noqa: E402
from evals.subject import CASES, SCORERS, run, version  # noqa: E402

RESULTS = [run(case) for case in CASES]
BY_CASE = {r.case_id: r for r in RESULTS}


def test_every_case_has_a_scorer_and_every_scorer_has_a_case():
    assert {c.id for c in CASES} == set(SCORERS)


def test_the_subject_records_that_there_is_no_model():
    """Spelled out, not omitted: a missing key reads as a forgotten one."""
    subject_version = version()
    assert subject_version.model is None
    assert subject_version.prompt_version is None
    assert subject_version.code_version


def test_no_case_errored_against_the_committed_artifacts():
    assert [r.case_id for r in RESULTS if r.error] == []


def test_every_dimension_passes_on_the_committed_artifacts():
    failed = [(r.case_id, [c.name for c in r.characteristics if not c.passed])
              for r in RESULTS if not r.passed]
    assert failed == []


def test_every_declared_characteristic_is_actually_scored():
    for case in CASES:
        scored = {c.name for c in BY_CASE[case.id].characteristics}
        assert set(case.expect) <= scored, case.id


def test_a_case_that_scores_nothing_it_declared_is_an_error_not_a_pass(monkeypatch):
    case = CASES[0]
    monkeypatch.setitem(SCORERS, case.id, lambda: ([], {}))
    result = run(case)
    assert result.error and "scored nothing for" in result.error


def test_a_scorer_that_raises_is_an_error_not_a_failure(monkeypatch):
    """An artifact that would not load is a different problem from a bad score."""
    def boom():
        raise RuntimeError("no artifact")

    monkeypatch.setitem(SCORERS, CASES[0].id, boom)
    result = run(CASES[0])
    assert result.error == "RuntimeError: no artifact"
    assert result.characteristics == []


def test_the_baseline_comparison_is_advisory_and_cannot_gate():
    """It is a property of Stripe's specs, not of this code."""
    result = BY_CASE["schema-diff-advantage"]
    assert [c.advisory for c in result.characteristics] == [True]


def test_the_honesty_gates_are_not_advisory():
    for case_id in ("detection-recall", "false-breaks", "workflow-mapping",
                    "pinned-tests", "corpus-sanitization"):
        assert not any(c.advisory for c in BY_CASE[case_id].characteristics), case_id


def test_the_scan_result_does_not_record_what_leaked():
    """A run record quoting the leak is the leak, one store further on."""
    assert set(BY_CASE["corpus-sanitization"].observations) == {"pii_findings"}


def test_every_mapped_gauge_resolves_on_a_real_run():
    """A metric pointed at a misspelled observation key publishes nothing.

    It would do so silently, and a dashboard with a missing series looks the
    same as a project with nothing to report.
    """
    points = gauges(RESULTS)
    assert set(GAUGES) <= set(points), set(GAUGES) - set(points)


def test_the_missed_count_is_derived_by_the_suite_not_by_a_monitor():
    """A monitor subtracting two series depends on them interpolating."""
    points = gauges(RESULTS)
    assert points["detection.missed"] == 0
    assert points["detection.missed"] == (points["detection.exercised"]
                                          - points["detection.caught"])


def test_the_gauges_carry_the_headline_numbers():
    points = gauges(RESULTS)
    assert points["detection.caught"] == points["detection.exercised"]
    assert points["false_breaks.rate"] == 0
    assert points["impact.mapping_precision"] == 1
    assert points["pins.certified"] == points["pins.claimable"]
    assert points["corpus.pii_findings"] == 0
    assert points["evals.cases_failed"] == 0


def test_a_none_observation_is_left_out_rather_than_published_as_zero():
    """An unpublished rate and a rate of zero are different facts."""
    result = CaseResult(
        case_id="false-breaks",
        characteristics=[CharacteristicResult(name="x", passed=True, detail="")],
        usage=Usage(latency_ms=0),
        observations={"false_break_rate": None, "breaking_findings": 3})
    points = gauges([result])
    assert "false_breaks.rate" not in points
    assert points["false_breaks.breaking_findings"] == 3


def test_an_errored_case_publishes_no_gauges():
    result = CaseResult(case_id="detection-recall", usage=Usage(latency_ms=0),
                        error="boom", observations={"caught": 99})
    assert "detection.caught" not in gauges([result])
