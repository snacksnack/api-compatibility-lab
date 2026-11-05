"""Render the regression-test deliverable: what was pinned, and what ran.

Generated from the committed inputs — `pins/pins.jsonl`, the generated suite,
and `pins/certification.json` — so the published numbers cite a record rather
than asserting a result. The report's job is to say what the two runs prove
and, more importantly, what the offline one does not.
"""

from __future__ import annotations

from compatlab.certify import Certification, Outcome, headline
from compatlab.pinning import BROKE, HELD, PinnedTest

VERDICT_WORD = {
    HELD: "holds",
    BROKE: "breaks",
    "unreached": "not exercised",
    "errored": "errored",
}


def _row(test: PinnedTest, certification: Certification,
         recorded: dict[str, dict[str, Outcome]]) -> str:
    entry = _entry(test, certification)
    live = (f"{_word(entry.on_a)} / {_word(entry.on_b)}" if entry
            else "not certified")
    rec_a = recorded.get("a", {}).get(test.name)
    rec_b = recorded.get("b", {}).get(test.name)
    rec = (f"{_word(rec_a.verdict)} / {_word(rec_b.verdict)}"
           if rec_a and rec_b else "not run")
    return (f"| `{test.name}` | {', '.join(test.pin.workflows)} | "
            f"{test.pin.consequence} | {live} | {rec} |")


def _word(verdict: str) -> str:
    return VERDICT_WORD.get(verdict, verdict)


def _entry(test: PinnedTest, certification: Certification):
    return next((e for e in certification.entries if e.pin == test.pin.pin), None)


def _assertion_row(test: PinnedTest, certification: Certification) -> str:
    entry = _entry(test, certification)
    detail = (entry.detail_b or "no failure recorded") if entry else "not certified"
    waived = " **(waived)**" if entry and entry.waived else ""
    return (f"| `{test.name.removeprefix('test_')}` | "
            f"{test.pin.assertion}{waived} | `{detail}` |")


def render(tests: list[PinnedTest], certification: Certification,
           recorded: dict[str, dict[str, Outcome]], *, version_a: str,
           version_b: str) -> str:
    """The whole `docs/regression-tests.md`."""
    good = certification.certified
    lines = [
        "# Pinned-behavior regression tests",
        "",
        f"**{headline(certification, version_a, version_b)}.**",
        "",
        f"Phase 4 ended with {len(tests)} places where a difference between "
        f"`{version_a}` and `{version_b}` reaches a field a declared customer "
        f"workflow actually reads. This phase compiles each one into a test "
        f"that passes on the old version and fails on the new one, and then "
        f"runs them both ways to show that it does.",
        "",
        "A pinned test is not a test of the API. It is the sentence *this "
        "customer's integration depends on this behavior*, written so that a "
        "version bump has to argue with it. It goes in the customer's own CI, "
        "where it fails the day someone changes the version pin.",
        "",
        "## What was pinned",
        "",
        "| test | workflow(s) | consequence | live A / B | recorded A / B |",
        "|---|---|---|---|---|",
    ]
    lines += [_row(test, certification, recorded) for test in tests]
    lines += [
        "",
        "## What each test asserts, and how the new version fails it",
        "",
        "The right-hand column is the assertion message from the live run on "
        f"`{version_b}`, quoted out of the certification record. It is the "
        "clearest short statement of the break there is: a refund count that "
        "went to zero, a billing period that stopped being returned, a "
        "preview endpoint that answers 404.",
        "",
        "| test | pins | fails on the new version with |",
        "|---|---|---|",
    ]
    lines += [_assertion_row(test, certification) for test in tests]
    lines += [
        "",
        f"Certified live on {certification.certified_at} against "
        f"`{version_a}` and `{version_b}`; the record is "
        f"[`pins/certification.json`](../pins/certification.json), and the "
        f"suite is [`pinned/test_pinned_behavior.py`]"
        f"(../pinned/test_pinned_behavior.py), generated from the pins.",
        "",
        "## The expected values are canonical, not literal",
        "",
        "The suite asserts over the same canonicalized responses the differ "
        "compares, so the tokens come with it: `<ts+30d>` is a timestamp in "
        "the 30-day bucket from the start of the run, and `<id:pi>` is *some* "
        "payment-intent id rather than one particular one. That is what makes "
        "a pinned timestamp a relative assertion: `current_period_end` is "
        "pinned as about thirty days out, which is the behavior, rather than "
        "as a date that would be wrong tomorrow. Ids are pinned by provenance "
        "for the same reason (ADR 0003).",
        "",
        "## The two runs are not equally good evidence",
        "",
        "The suite runs either against the live API or against a committed "
        "replay, with the same assertions. Only one of those is evidence.",
        "",
        f"The **live** run replays the corpus against each version now and "
        f"asserts against what comes back. Version A's traffic is fetched "
        f"after the pins were written, so a pin passing on `{version_a}` is a "
        f"statement about the API: {len(good)} of "
        f"{len(certification.claimable)} held there and broke on "
        f"`{version_b}`.",
        "",
        "The **recorded** run is a compilation check and is labelled one. The "
        "pins were derived from exactly those records, so a pin failing on "
        "the recorded B side is true by construction and says nothing about "
        "the API. What it does say is worth having in CI: that the generated "
        "code still compiles, still runs, and still evaluates the way the "
        "certification says it did, with no key and no network.",
        "",
        "## Three outcomes, because two would be generous",
        "",
        "A test can hold, it can break, or the replay can never have reached "
        "its step. Only the middle one is a pinned break. A workflow that "
        "falls over at call two turns every test behind it red, and counting "
        "those as *fails on the new version* would certify a suite that "
        "proves nothing — so an unreached step fails with `[unreached]` in "
        "the message, and the gate rejects a certification that rests on one.",
        "",
        "## The gate",
        "",
        "`compatlab pin check` runs offline in CI and fails when: the "
        "generated suite does not match what the pins compile to; any pin has "
        "no live certification; a certification was made against a different "
        "assertion than the one in the file now; a certified pin did not hold "
        "on the old version or did not break on the new one; or a "
        "certification entry refers to a pin that no longer exists. The last "
        "one matters as much as the rest: keeping a verdict while quietly "
        "losing the test it was about is the same dishonesty as never "
        "verifying.",
        "",
        "A behavioral break the upstream later reverses is real and can be "
        "waived, with a reason, in the certification. A waived pin is named "
        "in the headline rather than dropped from the denominator.",
        "",
        "## Running them",
        "",
        "```",
        f"uv run pytest pinned/ --api-version {version_a}    # all pass",
        f"uv run pytest pinned/ --api-version {version_b}  # all fail",
        "uv run python -m compatlab pin check              # offline gate",
        "```",
        "",
        "Design decisions behind all of this: "
        "[`docs/adr/0006-regression-test-generation.md`]"
        "(adr/0006-regression-test-generation.md).",
    ]
    return "\n".join(lines)
