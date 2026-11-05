"""`python -m evals` — the lab's quality suite (RC1-611).

Six dimensions scored from the committed artifacts: detection recall against
ground truth, the false-break rate, the schema-diff baseline comparison,
workflow-mapping precision, pinned-test validity, and corpus sanitization.

Unlike the estate's other eval suites this one is free and offline — no model,
no API key, no spend — so it can run anywhere. What it needs to be *useful* is
the shared store: `EVAL_DATABASE_URL` makes a run comparable to every earlier
run, which is the whole difference between this suite and the CI gates it
reads from. Without it `agent_evals` forks history into local JSONL, so the
run still records, and says where.

    uv run --group evals python -m evals
    uv run --group evals python -m evals --post-datadog

`--post-datadog` publishes the quality gauges the dashboard, monitors and
SLOs in `tpm-automation-platform/datadog/` read. It declines without
DD_API_KEY, and the run is unaffected either way: telemetry is decoration.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime

from agent_evals.runner import UnknownCase, exit_code, print_result, record_run, select_cases

from compatlab import telemetry
from evals import subject

# One gauge per published figure, read out of the case observations. Named
# after what they measure rather than after the case, because a dashboard
# outlives a case id.
GAUGES: dict[str, tuple[str, str]] = {
    "detection.caught": ("detection-recall", "caught"),
    "detection.exercised": ("detection-recall", "exercised"),
    "detection.inventory_m": ("detection-recall", "inventory_m"),
    "false_breaks.rate": ("false-breaks", "false_break_rate"),
    "false_breaks.breaking_findings": ("false-breaks", "breaking_findings"),
    "impact.mapping_precision": ("workflow-mapping", "mapping_precision"),
    "impact.claims": ("workflow-mapping", "claims"),
    "impact.workflows_affected": ("workflow-mapping", "workflows_affected"),
    "impact.workflows_blocked": ("workflow-mapping", "workflows_blocked"),
    "pins.certified": ("pinned-tests", "certified"),
    "pins.claimable": ("pinned-tests", "claimable"),
    "corpus.pii_findings": ("corpus-sanitization", "pii_findings"),
}


def gauges(results) -> dict[str, float]:
    """The publishable figures, from whichever cases actually ran.

    A `None` observation is left out rather than sent as zero: an unpublished
    rate and a rate of zero are different facts, and this project spends a lot
    of effort keeping them apart.
    """
    by_case = {r.case_id: r for r in results}
    points: dict[str, float] = {}
    for metric, (case_id, key) in GAUGES.items():
        result = by_case.get(case_id)
        if result is None or result.error:
            continue
        value = result.observations.get(key)
        if value is None:
            continue
        points[metric] = float(value)
    points["evals.cases_passed"] = sum(1 for r in results if r.passed)
    points["evals.cases_failed"] = sum(1 for r in results if not r.passed)
    # Derived here rather than in the monitor. A monitor doing arithmetic
    # across two series depends on them interpolating onto the same
    # timestamps; the suite already knows the answer, so it publishes it.
    if {"detection.caught", "detection.exercised"} <= set(points):
        points["detection.missed"] = (points["detection.exercised"]
                                      - points["detection.caught"])
    return points


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals", description=__doc__)
    parser.add_argument("--case", help="run a single dimension by id")
    parser.add_argument("--post-datadog", action="store_true",
                        help="publish the quality gauges to Datadog")
    args = parser.parse_args(argv)

    try:
        cases = select_cases(subject.CASES, args.case)
    except UnknownCase as exc:
        print(exc, file=sys.stderr)
        return 2

    version = subject.version()
    print(f"{len(cases)} dimension(s) against {version.subject} "
          f"{version.code_version} — deterministic, offline, no spend.\n")
    started = datetime.now(UTC)
    results = [subject.run(case) for case in cases]
    for result in results:
        print_result(result)

    record_run(version, started, results)
    if not os.environ.get("EVAL_DATABASE_URL"):
        print("\nEVAL_DATABASE_URL is not set: this run recorded to local "
              "JSONL and is not comparable to the shared history.")

    if args.post_datadog:
        points = gauges(results)
        if telemetry.submit(points):
            print(f"\ndatadog: {len(points)} gauge(s) submitted")
        else:
            print(f"\ndatadog: {len(points)} gauge(s) not submitted "
                  f"(no DD_API_KEY, or the POST failed above)")

    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
