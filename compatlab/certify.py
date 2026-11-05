"""Run the generated suite against both versions, and gate on the result.

The defining property of a pinned-behavior test is that it **passes on the
old version and fails on the new one**. Nothing in this repository can assert
that; it has to be run. So this module runs the generated file with pytest —
twice, once per version — reads the per-test outcomes out of the JUnit report,
and writes `pins/certification.json`.

There is exactly one evaluator of a pin, and it is pytest running the
generated code. A faster in-process check of "would this assertion hold" would
be a second evaluator, and the first thing it would do on the day the two
disagree is certify a suite that does not actually pass.

Three outcomes, not two. A test can hold, it can break, or the replay can
never have reached its step — and only the middle one is a pinned break.
Counting an unreached step as "fails on the new version" is how a replay that
fell over in step two would certify every pin behind it, which is the most
likely way this number gets flattering by accident.

The gate (`compatlab pin check`) is deliberately strict in both directions: a
pin with no current certification blocks, and a certification entry matching
no current pin blocks too. Keeping a stale verdict while quietly losing the
test it was about is the same dishonesty as never verifying — it is the
lesson Phase 3 wrote into `scoring/adjudication.json`, applied here.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from compatlab.pinning import (
    BROKE,
    ERRORED,
    HELD,
    UNREACHED,
    UNREACHED_MARKER,
    PinnedTest,
)

SCHEMA = 1
MAX_DETAIL_CHARS = 200
# pytest's assertion rewriting appends the values it introspected, which runs
# to several hundred characters of mangled response repr. The claim is in the
# first clause; the values are already on the pin record, and a committed
# artifact is a bad place to keep more response content than it needs.
DETAIL_CUT = " + where"


class RunError(RuntimeError):
    """The suite could not be run, so there is nothing to certify."""


@dataclass(frozen=True)
class Outcome:
    """What one test did on one version."""

    name: str
    verdict: str
    detail: str


def _detail(text: str) -> str:
    """One readable line out of a pytest failure message."""
    return " ".join(text.split()).split(DETAIL_CUT)[0][:MAX_DETAIL_CHARS]


def parse_junit(path: pathlib.Path) -> dict[str, Outcome]:
    """Per-test outcomes from a JUnit report, keyed by test name."""
    root = ET.parse(path).getroot()
    out: dict[str, Outcome] = {}
    for case in root.iter("testcase"):
        name = case.get("name", "")
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        if failure is not None:
            detail = failure.get("message", "") or (failure.text or "")
            verdict = UNREACHED if UNREACHED_MARKER in (
                detail + (failure.text or "")) else BROKE
        elif error is not None:
            detail = error.get("message", "") or (error.text or "")
            verdict = ERRORED
        elif skipped is not None:
            detail = skipped.get("message", "") or "skipped"
            verdict = ERRORED
        else:
            detail, verdict = "", HELD
        out[name] = Outcome(name=name, verdict=verdict,
                            detail=_detail(detail))
    return out


def run_suite(root: pathlib.Path, api_version: str, *,
              tests: pathlib.Path | str = "pinned",
              records: pathlib.Path | None = None,
              timeout: int = 900) -> dict[str, Outcome]:
    """Run the generated suite once, against one version."""
    with tempfile.TemporaryDirectory() as workdir:
        report = pathlib.Path(workdir) / "report.xml"
        argv = [sys.executable, "-m", "pytest", str(tests), "-q",
                "-p", "no:cacheprovider", "-p", "no:ddtrace",
                "--api-version", api_version, "--junit-xml", str(report)]
        if records is not None:
            argv += ["--records", str(records)]
        proc = subprocess.run(argv, cwd=root, capture_output=True, text=True,
                              timeout=timeout, check=False)
        if not report.exists():
            raise RunError(f"pytest produced no report ({argv[2:]}):\n"
                           f"{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
        outcomes = parse_junit(report)
    if not outcomes:
        raise RunError(f"the suite collected no tests ({argv[2:]}):\n"
                       f"{proc.stdout[-2000:]}")
    return outcomes


@dataclass(frozen=True)
class Entry:
    """One pin's certification: what it did on each version."""

    pin: str
    test: str
    fingerprint: str
    on_a: str
    on_b: str
    detail_a: str
    detail_b: str
    waived: dict[str, Any] | None = None

    @property
    def certified(self) -> bool:
        return self.on_a == HELD and self.on_b == BROKE

    def to_dict(self) -> dict[str, Any]:
        out = {
            "pin": self.pin, "test": self.test,
            "fingerprint": self.fingerprint,
            "on_a": self.on_a, "on_b": self.on_b,
            "detail_a": self.detail_a, "detail_b": self.detail_b,
        }
        if self.waived is not None:
            out["waived"] = self.waived
        return out


@dataclass
class Certification:
    """The record of one live double run of the generated suite."""

    version_a: str
    version_b: str
    suite_fingerprint: str
    certified_at: str
    mode: str = "live"
    entries: list[Entry] = field(default_factory=list)

    @property
    def waived(self) -> list[Entry]:
        return [e for e in self.entries if e.waived is not None]

    @property
    def certified(self) -> list[Entry]:
        return [e for e in self.entries if e.certified and e.waived is None]

    @property
    def claimable(self) -> list[Entry]:
        """The entries the published number is over: everything unwaived."""
        return [e for e in self.entries if e.waived is None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "certified_at": self.certified_at,
            "mode": self.mode,
            "version_a": self.version_a,
            "version_b": self.version_b,
            "suite_fingerprint": self.suite_fingerprint,
            "pins": [e.to_dict() for e in sorted(self.entries,
                                                 key=lambda e: e.test)],
        }


def fingerprint_source(source: str) -> str:
    """The suite's own fingerprint: the generated bytes, hashed."""
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def certify(tests: list[PinnedTest], source: str, *, version_a: str,
            version_b: str, on_a: dict[str, Outcome],
            on_b: dict[str, Outcome], mode: str = "live",
            waivers: dict[str, dict[str, Any]] | None = None) -> Certification:
    """Build the certification from the two runs that were just done."""
    waivers = waivers or {}
    now = datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat()
    out = Certification(version_a=version_a, version_b=version_b,
                        suite_fingerprint=fingerprint_source(source),
                        certified_at=now, mode=mode)
    for test in tests:
        missing = Outcome(name=test.name, verdict=ERRORED,
                          detail="the run reported nothing for this test")
        a = on_a.get(test.name, missing)
        b = on_b.get(test.name, missing)
        out.entries.append(Entry(
            pin=test.pin.pin, test=test.name, fingerprint=test.fingerprint,
            on_a=a.verdict, on_b=b.verdict,
            detail_a=a.detail, detail_b=b.detail,
            waived=waivers.get(test.pin.pin),
        ))
    return out


def load_certification(path: pathlib.Path) -> Certification:
    data = json.loads(path.read_text())
    out = Certification(
        version_a=data["version_a"], version_b=data["version_b"],
        suite_fingerprint=data["suite_fingerprint"],
        certified_at=data["certified_at"], mode=data.get("mode", "live"),
    )
    out.entries = [
        Entry(pin=e["pin"], test=e["test"], fingerprint=e["fingerprint"],
              on_a=e["on_a"], on_b=e["on_b"],
              detail_a=e.get("detail_a", ""), detail_b=e.get("detail_b", ""),
              waived=e.get("waived"))
        for e in data["pins"]
    ]
    return out


def write_certification(path: pathlib.Path, certification: Certification) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(certification.to_dict(), indent=2,
                               sort_keys=False) + "\n")


def gate(tests: list[PinnedTest], certification: Certification, source: str, *,
         version_a: str, version_b: str) -> list[str]:
    """Every reason this certification is not evidence about this suite."""
    problems: list[str] = []
    if certification.mode != "live":
        problems.append(
            f"the certification was recorded in {certification.mode!r} mode; "
            f"only a live double run is evidence about the API")
    if (certification.version_a, certification.version_b) != (version_a, version_b):
        problems.append(
            f"the certification is about "
            f"{certification.version_a} -> {certification.version_b}, not "
            f"{version_a} -> {version_b}")
    if certification.suite_fingerprint != fingerprint_source(source):
        problems.append(
            "the certification is about a different version of the generated "
            "suite; regenerate, then re-certify with `compatlab pin certify`")

    by_pin = {e.pin: e for e in certification.entries}
    for test in tests:
        entry = by_pin.pop(test.pin.pin, None)
        if entry is None:
            problems.append(f"{test.pin.pin}: never certified")
            continue
        if entry.fingerprint != test.fingerprint:
            problems.append(
                f"{test.pin.pin}: certified against a different assertion "
                f"(the pin or what it asserts has changed since)")
            continue
        if entry.waived is not None:
            # A waiver is the escape hatch for a break the upstream reversed
            # (ADR 0001 found one already). It has to say why, and the waived
            # pin is named in the published line rather than dropped from it.
            if not entry.waived.get("reason"):
                problems.append(f"{test.pin.pin}: waived with no reason")
            continue
        if entry.on_a != HELD:
            problems.append(
                f"{test.pin.pin}: did not hold on {version_a} "
                f"({entry.on_a}: {entry.detail_a or 'no detail'})")
        if entry.on_b == UNREACHED:
            problems.append(
                f"{test.pin.pin}: the replay never reached its step on "
                f"{version_b}, so the pin was not exercised there")
        elif entry.on_b != BROKE:
            problems.append(
                f"{test.pin.pin}: still holds on {version_b} "
                f"({entry.on_b}), so it pins nothing")
    for orphan in sorted(by_pin):
        problems.append(
            f"{orphan}: certified, but no such pin exists now — keep the "
            f"verdict and lose the test and the number stops meaning anything")
    return problems


def headline(certification: Certification, version_a: str,
             version_b: str) -> str:
    """The one sentence this phase is allowed to publish."""
    claimable = certification.claimable
    good = certification.certified
    noun = "test" if len(claimable) == 1 else "tests"
    line = (f"{len(good)} of {len(claimable)} pinned regression {noun} pass "
            f"on {version_a} and fail on {version_b}")
    if certification.waived:
        line += (f"; {len(certification.waived)} waived "
                 f"({', '.join(e.pin for e in certification.waived)})")
    return line
