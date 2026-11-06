# ADR 0006: regression-test generation and certification (RC1-610)

Status: accepted
Date: 2026-11-04

## Context

Phase 4 ended with `pins/pins.jsonl`: eleven places where a difference
between `2022-11-15` and `2025-03-31.basil` lands on a response field that a
declared customer workflow actually reads, each naming the step, the locus,
and what the two versions returned there. That is a specification, not a test.

The epic puts "here is the regression test that pins it" in the customer
deliverable and gives generation its own phase, with the property to prove
stated in the ticket: **each generated test fails against version B and passes
against version A**, verified by running them both ways. The ticket also sets
the scope line — pinned-behavior tests attached to the impact report, not a
test framework — because "generate regression tests" is the output in this
project that comes closest to the Agent Evals row on the portfolio.

Output: `compatlab/{pinning,codegen,certify,pin_report}.py`, the generated
suite `pinned/test_pinned_behavior.py` with its hand-written
`pinned/conftest.py`, `pins/certification.json`, `compatlab pin
generate|certify|check`, and `docs/regression-tests.md`.

Result: **11 of 11 pinned tests pass on `2022-11-15` and fail on
`2025-03-31.basil`**, certified by a live double run, with the failure
messages the report quotes — `assert 0 == 3000`, `assert <missing> ==
'<ts+30d>'`, `assert 404 == 200`.

## D1. There is one evaluator of a pin, and it is pytest

The claim is that a generated test passes on one version and fails on the
other. Nothing in this repository can assert that from the pin record; it has
to be run. So `compatlab pin certify` shells out to pytest over the generated
file, once per version, and reads per-test outcomes out of the JUnit report.

The faster design — ask the harness "would this assertion hold against this
record" — is a second evaluator. It would agree with the suite until the day
it did not, and on that day it would certify a file that does not actually
pass. The slow version is also the honest one: the artifact that gets
certified is the artifact a customer runs.

## D2. Three outcomes, because two would be generous

A pinned test can hold, it can break, or **the replay can never have reached
its step**. Only the middle one is a pinned break.

This is the mechanism that keeps the headline from being easy. Workflows are
sequences; `subscription_renewal_billing` dies at its third call on the new
version. If the replay falls over early, every test behind it goes red, and a
count of "tests that failed on B" would read 11 of 11 off a run that exercised
two pins. So `canonical("workflow.step")` raises `PinUnreached` with
`[unreached]` in the message, the certification records that verdict
separately, and the gate rejects a certification resting on one. A test
asserts the published record contains no unreached outcome on either side.

Same family as the A/A control and the unit tests that missed three
canonicalization bugs (ADR 0003 D6, ADR 0004): a check only sees the failure
mode it was built to distinguish, so the distinctions have to be in the
vocabulary rather than in the reader's head.

## D3. The expected value comes from the record, not from the pin

ADR 0005 D7 noted that a finding truncates its recorded values, so a pin
cannot always quote the old value back, and had the pin name a property
instead (`comes back as a non-empty collection`). The compiler does not have
to accept that: it holds the version-A replay record the pin was derived
from, so it resolves the locus there and gets the whole, typed value. An
assertion is never built from clipped JSON, and the pin file stays readable.

## D4. An assertion is the narrowest property the difference violates

A pin on a 40-key object by deep equality would be a test that fails whenever
anything in that subtree changes — which is precisely the failure this phase
exists to rule out: a test going red on the new version for a reason other
than the behavior it was written to pin. So:

| what version A returned | assertion |
|---|---|
| a scalar | equality on that value |
| a flat, short list or object | equality — for an enum, the value set growing *is* the behavior |
| a nested structure, or a wildcard locus | it still arrives, and still carries content |
| a list the new version emptied | it still comes back non-empty |
| a list the new version shortened | it still has as many elements |
| a call whose status class moved | the status code |
| a call that stopped working at all | the step runs |

Booleans and nulls are rendered with `is`, not `==`: `assert value` would pass
on any truthy value, which is not what was pinned, and `== True` does not
pass the project's linter.

## D5. The assertions are over canonical responses, which makes two of them relative

The suite canonicalizes with the same code the differ uses, so the expected
values carry the project's tokens. `<ts+30d>` is a timestamp in the 30-day
bucket from the start of the run and `<id:pi>` is *some* payment-intent id.
That is a feature on the two pins where it shows up: `current_period_end` is
pinned as *about thirty days out*, which is the behavior, rather than as a
date that would be wrong tomorrow.

It also means the generated file depends on `compatlab`. The alternative
considered and rejected was a portable file carrying its own request prefix,
which reads more like a handoff but would duplicate reference resolution and
canonicalization into untested generated code — and the ticket scopes this
phase away from shipping a framework.

## D6. The recorded run is a compilation check, and is labelled one

The suite runs against the live API or against a committed replay, with the
same assertions either way. They are not equally good evidence and the report
says so in its own section.

The **recorded** run is circular: the pins were derived from exactly those
records, so a pin failing on the recorded B side is true by construction and
says nothing about the API. What it is good for is CI — it proves the
generated code still compiles, runs, and evaluates the way the certification
says it did, with no key and no network. That is the gate `compatlab pin
check` runs on every push.

The **live** run is the evidence, and the non-circular half is the one that
looks redundant: *pass on A*. Version A's traffic is fetched now, after the
pins were written, so a pin holding there is a statement about the API rather
than about the file it came from. A canonicalization bug, an account-state
drift, a changed sandbox — each shows up as a pin that no longer holds on the
old version, and the gate goes red.

Both modes refuse to be vague about which version they ran: recorded mode
checks the records' own `stripe_version` against `--api-version`, and live
mode treats a served-version warning as fatal. Without that, a suite that ran
one version twice would pass every pin and prove nothing (ADR 0003, spike
finding 1).

## D7. The gate is strict in both directions

`compatlab pin check` is offline and fails when: the committed suite is not
what the pins compile to; the recorded double run disagrees with the
certification; any pin has no live certification; a certification was made
against a different assertion than the file now holds (the fingerprint covers
the pin *and* the compiled assertion); a certified pin did not hold on the old
version or did not break on the new one; or **a certification entry names a
pin that no longer exists**.

That last one is the same shape as Phase 3's adjudication test. Keeping a
verdict while quietly losing the test it was about is the same dishonesty as
never verifying, inverted, and it is the direction nobody notices.

No count is published while any problem stands, which is the third appearance
of the pattern this project uses for every number it prints: `score` refuses a
false-break rate with an unadjudicated finding, `impact` refuses a precision
with an unconfirmed claim, and `pin check` refuses a pass-on-A / fail-on-B
count with an uncertified pin.

## D8. A reversed upstream change is waived, not deleted

Phase 0 already found one documented break that a later Stripe version undid
(the `amount_off` coupon restriction, reversed in `2026-01-28.clover`). A pin
on a behavior the upstream restores is not wrong — it stopped applying. So a
certification entry can carry `waived` with a reason; the gate accepts it and
**the headline names it** rather than dropping it from the denominator. A
waiver with no reason fails the gate. There are no waivers today.

## D9. What is deferred, with the reason

**The generated tests are not run against the live API in CI.** CI has no
Stripe key by design (ADR 0001), and two live replays per push would write to
a shared sandbox on every commit. The live run is a command Reid runs, and
its output is committed as the record CI gates against — the same arrangement
as `baseline`, for the same reason.

**A pin cannot be generated for a break the corpus does not exercise.** Four
of the eight documented breaks are still unexercised (M5-M8), so they have no
pins, and the ground-truth coverage table in the impact report is the place
that says so. Pins follow the corpus; widening the corpus is Phase 1 work.

**Amended by RC1-618.** The rule stands; the roster shrank. M6 and M8 were
captured in the cascade and now carry pins, taking the suite from 11 to 19.
M5 and M7 remain pinless, and Stage 3 established that they are pinless for
different reasons: M7 waits on a Connect test account, while M5's observable
is confirmed live but needs a hosted page driven to a failed payment attempt,
which `pin certify` would have to re-drive on both versions every run (ADR
0003 D2, docs/m5-probe.md). For M5 "widening the corpus" is not Phase 1 work
that nobody has done yet — it is work this project has declined.

**Nothing is generated for a `risky` finding that no declared read touches.**
The pins come from impacts, so a difference nobody declared a read on produces
no test even where it is real — the impact report counts those separately (8
of them). Pinning them would mean inventing a client that reads them.

**One suite, not one per workflow.** A per-workflow file would let a customer
take only the tests for the integration they own, which is a real
convenience; nothing in the design prevents it, and no current reader needs
it.
