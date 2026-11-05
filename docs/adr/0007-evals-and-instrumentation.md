# ADR 0007: the eval suite and what is instrumented (RC1-611)

Status: accepted
Date: 2026-11-05

## Context

Five phases produced four numbers and four CI gates: detection recall against
Stripe's changelog, a false-break rate, workflow-mapping precision, and a
pass-on-A / fail-on-B count for the pinned tests. Each is published in a
generated report and each is refused outright when its honesty gate is unmet.

The ticket asks for estate-standard instrumentation on the RC1-548 pattern:
quality evals in the shared harness, LLM Obs tracing on model-backed steps,
cost per run, and monitors, SLOs and a dashboard managed as code. RC1-613
already wired CI Test Optimization, the catalog entity and delivery-monitor
coverage, so what is left is the quality half.

Output: `evals/` (six dimensions over the committed artifacts),
`compatlab/telemetry.py` (quality gauges), the `evals` dependency group
pinning `agent-evals` by tag, a dashboard and three monitors in
`tpm-automation-platform/datadog/`, and a line in the weekly sweep.

## D1. The subject is deterministic, and the record says so out loud

Every other eval subject on the estate scores a model's output and costs money
to run. This one scores a pipeline that makes no model calls, against ground
truth its author did not write.

`SubjectVersion.model` is therefore `null` and the run's spend is zero — both
**recorded rather than omitted**, which is what the shared record schema asks
for: a missing field reads as "we forgot", and "this costs nothing" is a
finding worth being able to prove. For the same reason the dependency group
takes `agent-evals[sql]` and **not** the `llmobs` extra. Installing tracing
for a subject with nothing to trace would imply there is a model call
somewhere in here.

## D2. An eval is not a second copy of a CI gate

Four of the six dimensions are already gated on every push, so the obvious
objection is that this suite re-runs CI with extra steps.

A gate and an eval answer different questions. **A gate answers *is this
publishable right now*** — `score` refuses a false-break rate while a finding
is unadjudicated, `impact` refuses a precision while a claim is unconfirmed,
`pin check` refuses a count while a pin is uncertified. **An eval answers *is
this getting better or worse, and attributably***: the run record carries the
code version, lands in the shared store beside every earlier run, and makes
the quality trend page a query rather than a memory. A gate that passes cannot
tell anyone that recall fell from 6 of 6 to 4 of 4 when the corpus grew.

The suite is also the only place the six numbers are stated together, in one
vocabulary, with the characteristic that decides each one named.

## D3. The baseline comparison is advisory, and nothing else is

`schema-diff-advantage` reports how badly `oasdiff` does on these breaks: two
of the caught breaks drew no baseline entry at all, one named the field
without the behavior, against 12,313 breaking changes reported on the same
twenty endpoints.

That is the project's headline and it is **advisory**, because it is a property
of Stripe's published specs rather than of this code. A future spec pair could
describe its own behavior better without anything here regressing, and a
dimension that can fail for reasons outside the subject gets muted — a muted
check catches nothing. Everything else gates: those are facts about this
pipeline.

## D4. Gauges, not counts, and a missing number is not zero

The quality series are gauges (`type: 3`). A rate is a level, not a tally:
four runs in an hour that each caught four breaks must not read as sixteen.

A `None` observation is **left out of the payload** rather than sent as zero.
The false-break rate is `None` while any finding is unadjudicated — that is
the Phase 3 honesty gate — and publishing it as 0.0 would turn "we have not
looked" into "we looked and found none", which is the exact confusion three
phases of this project have been built to avoid.

Two derived figures — `detection.missed` and the per-run pass and fail counts
— are computed **in the suite**, not in the monitor. A monitor subtracting one
series from another depends on the two interpolating onto the same timestamps;
the suite already knows the answer, so it publishes it.

Submission is decoration, like tracing elsewhere: no `DD_API_KEY`, no
submission, run unaffected. But a rejected payload prints in full, because a
swallowed 400 on the v2 series endpoint is indistinguishable from no traffic
(RC1-440, and RC1-613's afternoon spent on a query bug that looked like
missing data).

## D5. The suite does not run in CI

It could — it needs no key and no network. It should not. `EVAL_DATABASE_URL`
has one home, a developer machine, and a CI run without it forks history into
a local JSONL file inside a container that is then thrown away. A trend with a
hole in it is worse than a trend with a slower cadence.

So: the four gates keep running on every push, the eval scorers are covered by
unit tests in CI, and the suite itself runs by hand after a change and weekly
from `agent-evals/scripts/scheduled_eval.sh`. The dashboard's cadence is that
sweep, and the dashboard says so.

## D6. The monitors watch what CI cannot see

Three monitors, chosen by subtraction rather than by listing every metric:

- `compatlab.detection.missed > 0` — a documented break the corpus exercises
  stopped being caught. CI gates on every breaking finding carrying a hand
  verdict, **never on recall**, so this failure leaves the build green.
- `compatlab.false_breaks.rate > 0` — a finding was adjudicated a false break.
  CI gates on a verdict existing, never on what the verdict says.
- `compatlab.evals.cases_failed > 0` — the catch-all, so the four dimensions
  CI does gate keep a monitor if a gate is ever removed, and a dimension added
  later is covered before anyone writes it a monitor.

Corpus sanitization, inventory validity, claim confirmation and pin
certification get no monitor of their own: each is already a red X on the
commit that broke it, which is both faster and more specific than an alert.

All three have `notify_no_data: false`. No data means the weekly sweep did not
run, and `agent_evals.scheduled_run.*` already watches exactly that — a second
alert on one cause is how an alert set stops being read.

## D7. No new SLO, because the useful one already exists

The lab is **already inside the fleet test-health SLO**: the RC1-467 collector
groups every default-branch test service with no allowlist, and
`delivery.tests.{attempted,passed}{test_service:api-compatibility-lab}` reads
260 of 260 over the last seven days. Nothing to add.

A quality SLO over these gauges would be computed from about four points in a
30-day window. An error budget over four points is a number with a percent
sign on it and no meaning, and this project has spent five phases refusing
exactly that kind of figure. Stated here instead of shipped as a thin object.

## D8. What is deferred, with the reason

**No LLM Observability pane.** Nothing in the pipeline calls a model: the
differ, the mapper and the test compiler are deterministic Python. The ticket
asked for tracing "on any model-backed classification or mapping step" and the
honest answer is that there is no such step. If a later phase adds one — a
model-assisted integration inventory is the obvious candidate — it arrives with
its own `ml_app`, its own cost, and its own place on the fleet pane.

**No cost-per-run pane.** Replay runs against a Stripe sandbox for free and the
suite spends nothing. The zero is in every run record, which is where a reader
can check it; a dashboard tile reading `$0.00` forever is furniture.

**The dimensions are not weighted into a single score.** Six numbers that
measure six different things do not add up, and a composite would hide which
one moved. The run record keeps them separate and so does the dashboard.
