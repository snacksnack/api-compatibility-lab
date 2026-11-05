"""Running the suite, reading the outcomes, and refusing a stale verdict."""

from __future__ import annotations

import json
import pathlib

from compatlab.certify import (
    Entry,
    Outcome,
    certify,
    fingerprint_source,
    gate,
    headline,
    load_certification,
    parse_junit,
    run_suite,
    write_certification,
)
from compatlab.pinning import BROKE, ERRORED, HELD, UNREACHED, UNREACHED_MARKER
from tests.test_codegen import compiled

A, B = "2022-11-15", "2025-03-31.basil"
SOURCE = "# the suite\n"


def junit(tmp_path: pathlib.Path, cases: str) -> pathlib.Path:
    path = tmp_path / "report.xml"
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{cases}'
                    f'</testsuite></testsuites>')
    return path


def test_a_passing_test_held(tmp_path):
    report = junit(tmp_path, '<testcase name="test_one"/>')
    assert parse_junit(report)["test_one"].verdict == HELD


def test_an_assertion_failure_is_a_break(tmp_path):
    report = junit(tmp_path, '<testcase name="test_one">'
                             '<failure message="assert 0 == 1"/></testcase>')
    outcome = parse_junit(report)["test_one"]
    assert (outcome.verdict, outcome.detail) == (BROKE, "assert 0 == 1")


def test_an_unreached_step_is_not_a_break(tmp_path):
    """The whole point of the third outcome.

    A workflow that fell over before the pinned step turns the test red
    without exercising the pin, and counting that as "fails on the new
    version" would certify a suite that proves nothing.
    """
    report = junit(tmp_path, f'<testcase name="test_one"><failure '
                             f'message="PinUnreached: {UNREACHED_MARKER} nope"/>'
                             f'</testcase>')
    assert parse_junit(report)["test_one"].verdict == UNREACHED


def test_an_error_or_a_skip_is_neither(tmp_path):
    report = junit(tmp_path,
                   '<testcase name="test_one"><error message="boom"/></testcase>'
                   '<testcase name="test_two"><skipped message="nope"/></testcase>')
    outcomes = parse_junit(report)
    assert outcomes["test_one"].verdict == ERRORED
    assert outcomes["test_two"].verdict == ERRORED


def test_the_detail_keeps_the_claim_and_drops_the_introspection(tmp_path):
    report = junit(tmp_path, '<testcase name="test_one"><failure message="assert '
                             "0 == 3000 + where 0 = len([]) + where [] = "
                             'value_at({big: blob})"/></testcase>')
    assert parse_junit(report)["test_one"].detail == "assert 0 == 3000"


def certification(**over):
    tests = [compiled()]
    entries = {
        "on_a": HELD, "on_b": BROKE, "detail_a": "", "detail_b": "assert 0 == 1",
        **over,
    }
    cert = certify(tests, SOURCE, version_a=A, version_b=B,
                   on_a={tests[0].name: Outcome(tests[0].name, entries["on_a"],
                                                entries["detail_a"])},
                   on_b={tests[0].name: Outcome(tests[0].name, entries["on_b"],
                                                entries["detail_b"])})
    return tests, cert


def test_a_clean_certification_passes_the_gate():
    tests, cert = certification()
    assert gate(tests, cert, SOURCE, version_a=A, version_b=B) == []
    assert headline(cert, A, B).startswith("1 of 1 pinned regression test pass")


def test_a_pin_that_does_not_hold_on_the_old_version_blocks():
    tests, cert = certification(on_a=BROKE, detail_a="assert 2 == 1")
    problems = gate(tests, cert, SOURCE, version_a=A, version_b=B)
    assert any("did not hold" in p for p in problems)


def test_a_pin_that_still_holds_on_the_new_version_pins_nothing():
    tests, cert = certification(on_b=HELD)
    problems = gate(tests, cert, SOURCE, version_a=A, version_b=B)
    assert any("pins nothing" in p for p in problems)


def test_an_unreached_step_on_the_new_version_blocks():
    tests, cert = certification(on_b=UNREACHED)
    problems = gate(tests, cert, SOURCE, version_a=A, version_b=B)
    assert any("never reached its step" in p for p in problems)


def test_an_uncertified_pin_blocks():
    tests, cert = certification()
    cert.entries = []
    problems = gate(tests, cert, SOURCE, version_a=A, version_b=B)
    assert any("never certified" in p for p in problems)


def test_a_certification_of_a_different_assertion_blocks():
    """Certify a pin, then change what it asserts: the verdict is stale."""
    tests, cert = certification()
    cert.entries[0] = Entry(pin=cert.entries[0].pin, test=cert.entries[0].test,
                            fingerprint="deadbeef", on_a=HELD, on_b=BROKE,
                            detail_a="", detail_b="")
    problems = gate(tests, cert, SOURCE, version_a=A, version_b=B)
    assert any("different assertion" in p for p in problems)


def test_a_certification_of_a_different_suite_blocks():
    tests, cert = certification()
    problems = gate(tests, cert, "# edited\n", version_a=A, version_b=B)
    assert any("different version of the generated suite" in p for p in problems)


def test_a_verdict_for_a_pin_that_no_longer_exists_blocks():
    """The inverse direction, and it matters as much.

    Keeping a verdict while quietly losing the test it was about is the same
    dishonesty as never verifying — Phase 3's adjudication lesson, applied.
    """
    tests, cert = certification()
    problems = gate([], cert, SOURCE, version_a=A, version_b=B)
    assert any("no such pin exists now" in p for p in problems)


def test_a_recorded_certification_is_not_evidence():
    tests, cert = certification()
    cert.mode = "recorded"
    problems = gate(tests, cert, SOURCE, version_a=A, version_b=B)
    assert any("only a live double run" in p for p in problems)


def test_a_certification_about_another_version_pair_blocks():
    tests, cert = certification()
    cert.version_b = "2099-01-01"
    problems = gate(tests, cert, SOURCE, version_a=A, version_b=B)
    assert any("not" in p and "2099-01-01" in p for p in problems)


def test_a_waiver_needs_a_reason_and_is_named_in_the_headline():
    tests, cert = certification(on_b=HELD)
    cert.entries[0] = Entry(
        pin=cert.entries[0].pin, test=cert.entries[0].test,
        fingerprint=tests[0].fingerprint, on_a=HELD, on_b=HELD,
        detail_a="", detail_b="", waived={"reason": "reversed in a later version"})
    assert gate(tests, cert, SOURCE, version_a=A, version_b=B) == []
    assert "waived" in headline(cert, A, B)
    assert cert.entries[0].pin in headline(cert, A, B)

    cert.entries[0] = Entry(
        pin=cert.entries[0].pin, test=cert.entries[0].test,
        fingerprint=tests[0].fingerprint, on_a=HELD, on_b=HELD,
        detail_a="", detail_b="", waived={})
    problems = gate(tests, cert, SOURCE, version_a=A, version_b=B)
    assert any("waived with no reason" in p for p in problems)


def test_a_run_that_reports_nothing_for_a_test_is_an_error_not_a_pass():
    tests = [compiled()]
    cert = certify(tests, SOURCE, version_a=A, version_b=B, on_a={}, on_b={})
    assert cert.entries[0].on_a == ERRORED
    assert gate(tests, cert, SOURCE, version_a=A, version_b=B)


def test_a_certification_round_trips_through_disk(tmp_path):
    tests, cert = certification()
    path = tmp_path / "certification.json"
    write_certification(path, cert)
    again = load_certification(path)
    assert again.to_dict() == cert.to_dict()
    assert json.loads(path.read_text())["mode"] == "live"
    assert gate(tests, again, SOURCE, version_a=A, version_b=B) == []


def test_run_suite_runs_a_real_suite_and_reads_its_outcomes(tmp_path):
    """The one evaluator of a pin is pytest running the generated file."""
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "conftest.py").write_text(
        "def pytest_addoption(parser):\n"
        "    parser.addoption('--api-version', default='x')\n"
        "    parser.addoption('--records', default=None)\n")
    (suite / "test_generated.py").write_text(
        "def test_holds():\n    assert True\n\n"
        "def test_breaks():\n    assert 0 == 1\n")
    outcomes = run_suite(tmp_path, A, tests=suite)
    assert outcomes["test_holds"].verdict == HELD
    assert outcomes["test_breaks"].verdict == BROKE


def test_the_suite_fingerprint_is_over_the_generated_bytes():
    assert fingerprint_source(SOURCE) != fingerprint_source(SOURCE + " ")
