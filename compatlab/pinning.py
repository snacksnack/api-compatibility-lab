"""Compile a pin specification into the assertion a generated test makes.

Phase 4 emitted `pins/pins.jsonl`: one entry per place a declared customer
read is blocked or corrupted, naming the step to replay, the locus to look at,
and what each version returned there. This module turns one of those into a
`PinnedTest` — a name, an assertion kind, and the expected value — which
`compatlab.codegen` renders as Python and `compatlab.certify` runs.

Two decisions here carry most of the phase.

**The expected value is read back out of the replay record, not out of the
pin.** A finding truncates its recorded values for readability (`short`), so
`expect_on_a` can arrive clipped — ADR 0005 D7 handled that by having the pin
name the property instead of quoting a half-JSON blob. The compiler does not
have to settle for that: it has the A-side record the pin was derived from, so
it resolves the locus there and gets the whole, typed value.

**The assertion is the narrowest property the pinned difference violates.**
Pinning a 40-key object by deep equality would produce a test that fails when
anything in that subtree changes, which is the exact failure this phase is
trying to rule out: a test that goes red on the new version for a reason other
than the behavior it was written to pin. So a scalar is pinned exactly, a flat
list of scalars is pinned exactly (the value set growing *is* the behavior),
and a nested structure is pinned on the property the finding is about.

The verdict of a pin is not computed here. There is one evaluator and it is
pytest running the generated file — see `compatlab.certify`. A second
evaluator in this module would be the thing that drifts from the suite and
then certifies it anyway.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from dataclasses import dataclass
from typing import Any

from compatlab.findings import MISSING
from compatlab.loci import value_at, wildcarded

PINS_PATH = pathlib.Path("pins/pins.jsonl")
CERTIFICATION_PATH = pathlib.Path("pins/certification.json")

# Assertion kinds. Each one is a shape of generated code and a shape of claim.
REACHABLE = "reachable"
STATUS = "status"
EQUALS = "equals"
PRESENT = "present"
NON_EMPTY = "non-empty"
LENGTH = "length"

# What running a pinned test says about one version. `unreached` is the third
# value this phase exists to keep: a test whose workflow died before the
# pinned step also comes out red, and counting that as "fails on the new
# version" would let a broken replay certify the suite.
HELD = "held"
BROKE = "broke"
UNREACHED = "unreached"
ERRORED = "errored"

# A failure message carrying this marker is an unreached step, not a broken
# pin. The generated test raises it from the fixture call inside the test
# body, so pytest records it as a failure of that test and the token survives
# into the JUnit report.
UNREACHED_MARKER = "[unreached]"

# Above this, a literal in generated source stops being readable, and a
# reader cannot tell which part of it the test is really about.
MAX_LITERAL_CHARS = 160
SCALARS = (str, int, float, bool)


class CompileError(ValueError):
    """A pin that cannot be turned into an assertion."""


class PinUnreached(AssertionError):
    """The replay never reached the step this pin is about."""


@dataclass(frozen=True)
class Pin:
    """One entry of `pins/pins.jsonl`, as written by Phase 4."""

    pin: str
    corpus: str
    locus: str
    declared_read: str
    rule: str
    axis: str
    consequence: str
    assertion: str
    workflows: tuple[str, ...]
    caveat: str | None
    expect_on_a: str | None
    observed_on_b: str | None

    @property
    def workflow(self) -> str:
        return self.corpus.split(".", 1)[0]

    @property
    def step(self) -> str:
        return self.corpus.split(".", 1)[1]

    @property
    def key(self) -> tuple[str, str]:
        return (self.workflow, self.step)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin": self.pin, "corpus": self.corpus, "locus": self.locus,
            "declared_read": self.declared_read, "rule": self.rule,
            "axis": self.axis, "consequence": self.consequence,
            "assertion": self.assertion, "workflows": list(self.workflows),
            "caveat": self.caveat, "expect_on_a": self.expect_on_a,
            "observed_on_b": self.observed_on_b,
        }


def pin_from(entry: dict[str, Any]) -> Pin:
    if "." not in entry.get("corpus", ""):
        raise CompileError(f"a pin's corpus must be `workflow.step`: {entry!r}")
    return Pin(
        pin=entry["pin"], corpus=entry["corpus"], locus=entry["locus"],
        declared_read=entry["declared_read"], rule=entry["rule"],
        axis=entry["axis"], consequence=entry["consequence"],
        assertion=entry["assertion"],
        workflows=tuple(entry.get("workflows", ())),
        caveat=entry.get("caveat"),
        expect_on_a=entry.get("expect_on_a"),
        observed_on_b=entry.get("observed_on_b"),
    )


def load_pins(path: pathlib.Path) -> list[Pin]:
    with path.open() as handle:
        return [pin_from(json.loads(line)) for line in handle if line.strip()]


@dataclass(frozen=True)
class PinnedTest:
    """One pin, compiled: what to call it, what to assert, and why that."""

    pin: Pin
    name: str
    kind: str
    expected: Any
    reason: str

    @property
    def fingerprint(self) -> str:
        """Identifies the pin *and* the assertion compiled from it.

        A certification is only evidence about the test that was run, so the
        fingerprint has to move when either the specification or the compiled
        assertion moves. Certifying a pin and then changing what it asserts is
        the quiet way this number would stop meaning anything.
        """
        payload = json.dumps({
            "pin": self.pin.to_dict(), "name": self.name, "kind": self.kind,
            "expected": self.expected,
        }, sort_keys=True, default=repr)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pin": self.pin.pin, "name": self.name, "kind": self.kind,
            "expected": self.expected, "reason": self.reason,
            "fingerprint": self.fingerprint,
            "workflows": list(self.pin.workflows),
            "consequence": self.pin.consequence,
            "caveat": self.pin.caveat,
        }


def _slug(text: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", text.lower())).strip("_")


# `def ` + the name + `(`, against the line length `compatlab.codegen` holds
# generated files to. Named here rather than imported to keep the name builder
# free of a dependency on the renderer.
DEF_PREFIX = "def "
NAME_WIDTH = 100


def name_for(pin: Pin) -> str:
    """A stable, legible test name: the step and the locus it pins.

    Derived rather than numbered on purpose. A generated suite whose test
    names are `test_pin_07` reorders itself the moment a pin is added, and
    every certification entry for it becomes a claim about a different test.
    """
    tail = _slug(pin.locus.removeprefix("$.body.").removeprefix("$."))
    name = f"test_{_slug(pin.corpus)}__{tail}"
    if len(DEF_PREFIX) + len(name) + 1 <= NAME_WIDTH:
        return name
    # An identifier cannot be folded, so a name that would push `def NAME(`
    # past the project's line length drops the workflow half of the corpus
    # reference and keeps the step and the locus. `codegen` wraps signatures
    # and (since RC1-618 Stage 2) body statements, but neither can help here,
    # and a generated file the repository's own linter rejects is a generated
    # file somebody hand-edits.
    #
    # The full corpus reference stays in the body and the docstring, which is
    # where the test's identity actually lives. Shortening only the names that
    # need it keeps every existing pin — and so every certification entry
    # naming one — unchanged.
    _, _, step = pin.corpus.partition(".")
    shortened = f"test_{_slug(step)}__{tail}" if step else name
    return shortened if len(shortened) < len(name) else name


def _flat(value: Any) -> bool:
    """Is this small and shallow enough to pin by exact equality?"""
    if value is None or isinstance(value, SCALARS):
        return True
    if not isinstance(value, list | dict):
        return False
    items = value.values() if isinstance(value, dict) else value
    if not all(item is None or isinstance(item, SCALARS) for item in items):
        return False
    return len(repr(value)) <= MAX_LITERAL_CHARS


def compile_pin(pin: Pin, record: dict[str, Any] | None) -> PinnedTest:
    """Compile one pin against the version-A record it was derived from."""
    name = name_for(pin)

    if pin.rule == "step-missing":
        return PinnedTest(pin=pin, name=name, kind=REACHABLE, expected=None,
                          reason="the pinned behavior is that the call runs at all")
    if record is None:
        raise CompileError(
            f"{pin.pin}: no version-A record for `{pin.corpus}`, so there is "
            f"no old behavior to pin")

    if pin.axis == "status" or pin.locus == "$.status":
        status = record.get("status")
        if not isinstance(status, int):
            raise CompileError(f"{pin.pin}: version A recorded no status code")
        return PinnedTest(pin=pin, name=name, kind=STATUS, expected=status,
                          reason="the pinned behavior is the status class of the call")

    value = value_at(record, pin.locus)
    if value is MISSING:
        raise CompileError(
            f"{pin.pin}: `{pin.locus}` is absent from the version-A response, "
            f"so there is nothing there to pin")

    if pin.rule == "list-emptied":
        return PinnedTest(pin=pin, name=name, kind=NON_EMPTY, expected=None,
                          reason="pinned on the property the finding is about: the "
                                 "collection still comes back with elements in it")
    if pin.rule == "list-truncated":
        if not isinstance(value, list):
            raise CompileError(f"{pin.pin}: `{pin.locus}` is not a list on version A")
        return PinnedTest(pin=pin, name=name, kind=LENGTH, expected=len(value),
                          reason="pinned on length: the collection still comes back "
                                 "with as many elements as it did")
    if wildcarded(pin.locus) or not _flat(value):
        return PinnedTest(pin=pin, name=name, kind=PRESENT, expected=None,
                          reason="a nested structure; pinning it by deep equality "
                                 "would fail on any unrelated change inside it, so "
                                 "the assertion is that it still arrives with content")
    return PinnedTest(pin=pin, name=name, kind=EQUALS, expected=value,
                      reason="a value small enough to read, pinned exactly")


def compile_all(pins: list[Pin],
                side: dict[tuple[str, str], dict]) -> list[PinnedTest]:
    """Compile every pin, refusing a name collision rather than renaming."""
    tests = [compile_pin(pin, side.get(pin.key)) for pin in pins]
    seen: dict[str, str] = {}
    for test in tests:
        if test.name in seen:
            raise CompileError(
                f"two pins compile to the test name {test.name!r} "
                f"({seen[test.name]} and {test.pin.pin}); one of them would "
                f"shadow the other in the generated module")
        seen[test.name] = test.pin.pin
    return sorted(tests, key=lambda t: t.name)


def reached(side: dict[tuple[str, str], dict], corpus: str) -> bool:
    """Did the replay get as far as this step on this version?"""
    workflow, _, step = corpus.partition(".")
    return (workflow, step) in side


def canonical_of(side: dict[tuple[str, str], dict], corpus: str) -> dict[str, Any]:
    """The canonical response for one step, or an unreached failure.

    The runtime half of the three-valued outcome: a test whose step never ran
    fails with `[unreached]` in the message, so the certification can tell a
    pinned break apart from a replay that fell over earlier in the workflow.
    """
    workflow, _, step = corpus.partition(".")
    record = side.get((workflow, step))
    if record is None:
        raise PinUnreached(
            f"{UNREACHED_MARKER} the replay never reached `{corpus}` on this "
            f"version, so this pin was not exercised")
    return record
