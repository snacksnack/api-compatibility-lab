"""The published pinned suite, as tests.

Phase 5's claim comes out of three committed artifacts — the generated suite,
`pins/certification.json`, and `docs/regression-tests.md` — each derived from
`pins/pins.jsonl` and the version-A replay record. These tests re-derive all
of it and fail if any of it has drifted.

The gate has the same shape as Phase 3's adjudication and Phase 4's
verification: the pass-on-A / fail-on-B count is not publishable while any pin
is uncertified or stale, so the suite goes red rather than printing a number
nobody ran.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from compatlab import VERSION_A, VERSION_B
from compatlab.canonical import canonical_side
from compatlab.certify import gate, load_certification
from compatlab.codegen import render_module
from compatlab.differ import sides
from compatlab.pin_report import render as render_report
from compatlab.pinning import BROKE, HELD, compile_all, load_pins

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAIRS = ROOT / "replay" / "pairs.jsonl"
PINS = ROOT / "pins" / "pins.jsonl"
CERTIFICATION = ROOT / "pins" / "certification.json"
SUITE = ROOT / "pinned" / "test_pinned_behavior.py"
REPORT = ROOT / "docs" / "regression-tests.md"

pytestmark = pytest.mark.skipif(
    not PINS.exists(), reason="no pins committed")


def suite() -> tuple[list, str]:
    pairs = [json.loads(line) for line in PAIRS.read_text().splitlines() if line]
    side_a, _ = sides(pairs)
    tests = compile_all(load_pins(PINS), canonical_side(side_a))
    return tests, render_module(tests, VERSION_A, VERSION_B)


def test_every_committed_pin_compiles():
    tests, _ = suite()
    assert len(tests) == len([
        line for line in PINS.read_text().splitlines() if line.strip()])


def test_the_committed_suite_is_what_the_pins_compile_to():
    """A hand-edited assertion inside a generated file is the failure here."""
    _, source = suite()
    assert SUITE.read_text() == source, (
        "pinned/test_pinned_behavior.py is stale; re-run "
        "`compatlab pin generate`")


def test_every_pin_is_certified_against_the_committed_suite():
    tests, source = suite()
    certification = load_certification(CERTIFICATION)
    assert gate(tests, certification, source, version_a=VERSION_A,
                version_b=VERSION_B) == []


def test_the_certification_is_a_live_double_run():
    """A recorded run is a compilation check; only a live one is evidence."""
    certification = load_certification(CERTIFICATION)
    assert certification.mode == "live"
    assert (certification.version_a, certification.version_b) == (
        VERSION_A, VERSION_B)


def test_every_pin_held_on_the_old_version_and_broke_on_the_new_one():
    certification = load_certification(CERTIFICATION)
    for entry in certification.claimable:
        assert (entry.on_a, entry.on_b) == (HELD, BROKE), entry.pin


def test_no_pin_is_counted_on_a_step_the_replay_never_reached():
    """The third outcome is what keeps the count honest, so assert on it."""
    certification = load_certification(CERTIFICATION)
    assert [e.pin for e in certification.entries
            if "unreached" in (e.on_a, e.on_b)] == []


def test_the_published_report_matches_the_committed_record():
    tests, _ = suite()
    certification = load_certification(CERTIFICATION)
    # Rendered without the recorded run, which is what `pin check` adds live;
    # the columns it fills are asserted by the command's own gate in CI.
    produced = render_report(tests, certification, {}, version_a=VERSION_A,
                             version_b=VERSION_B)
    committed = REPORT.read_text()
    for line in produced.splitlines():
        if "not run" in line:
            continue
        assert line in committed, f"docs/regression-tests.md is stale: {line!r}"


def test_the_report_publishes_the_denominator_with_the_number():
    """A count without its denominator is the shape of a flattering one."""
    certification = load_certification(CERTIFICATION)
    head = REPORT.read_text().splitlines()[2]
    assert f"of {len(certification.claimable)}" in head
