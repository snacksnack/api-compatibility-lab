# API Compatibility Lab

Replays sanitized API traffic across two API versions to find the behavioral
breaks a schema diff misses.

An OpenAPI diff catches removed fields and changed types. It is blind to a
field that became nullable in practice, a changed default, a pagination
boundary shift, a changed sort order, a different error code under the same
HTTP status, silent truncation, and undocumented enum values. Every one of
those breaks real integration code while the schema diff reports green.
Behavior, not schema, is the contract customers actually depend on.

**Status: Phase 7 (RC1-612) — every groomed phase built.** Traffic is
captured, sanitized, replayed against both versions, classified, scored,
mapped onto the customer workflows it affects, and each affected read is
pinned by a generated test that passes on the old version and fails on the
new one. Those six results are scored as an eval suite on every run and
published as Datadog gauges behind a dashboard and three monitors, and the
whole thing is papered as an engagement in
[`docs/engagement.md`](docs/engagement.md). It is still not a finished tool:
the corpus exercises six of the eight documented breaks in the inventory, and
the two that remain are unexercised for two different reasons (M7 needs a
Connect test account; M5 was probed and confirmed live, then left unexercised
by decision, because replaying its observable would put a browser inside the
A/A control); the integration inventory is declared by the customer rather
than discovered from their code.

> **Caught 6 of the 6 documented behavioral breaks the corpus exercises** (8
> in the inventory). The schema-diff baseline gave no usable warning on five
> of them — four with no entry at all, one naming the field but not the
> behavior — while reporting 17,495 breaking changes on the same twenty-seven
> endpoints. 62 findings classified breaking, every one adjudicated against
> Stripe's changelog, 0 false breaks.
>
> **Of seven declared customer workflows, one stops outright, four keep
> running and go silently wrong, one is visibly degraded, and one is
> unaffected.** 21 impact claims, all 21 confirmed against the replay record
> by a checker that does not read the classifier's rule table.
>
> **19 of 19 generated regression tests pass on `2022-11-15` and fail on
> `2025-03-31.basil`**, certified by a live double run — one test per place a
> declared customer read is blocked, corrupted or newly reachable, each
> failing on its own assertion rather than on a step the replay never
> reached.
>
> Scorecard: [`docs/behavioral-diff-report.md`](docs/behavioral-diff-report.md).
> Impact report: [`docs/impact-report.md`](docs/impact-report.md), and the
> self-contained page a customer would be sent,
> [`docs/impact-report.html`](docs/impact-report.html). Pinned tests:
> [`docs/regression-tests.md`](docs/regression-tests.md).

## Ground truth

The detector is scored against Stripe's dated API versions: traffic is
replayed across `2022-11-15` and `2025-03-31.basil` (pinned per request via
the `Stripe-Version` header), and every behavioral difference it finds is
checked against Stripe's published upgrade changelog — ground truth this
project's author did not write. The schema-diff baseline is `oasdiff` over
Stripe's own published OpenAPI snapshots at pinned commits.

- [`docs/ground-truth.md`](docs/ground-truth.md) — the documented changes in
  the span, classified schema-visible vs behavioral, and the provisional M.
- [`docs/engagement.md`](docs/engagement.md) — the same work papered as a
  customer engagement: statement of work, what the schema diff said, what the
  replay found, what the customer keeps, and what none of it claims.
- [`docs/adr/0001-phase-0-decisions.md`](docs/adr/0001-phase-0-decisions.md) —
  version pair, baseline, stack, and corpus-format decisions.
- [`docs/adr/0002-redaction-and-corpus.md`](docs/adr/0002-redaction-and-corpus.md) —
  redaction actions, the independent scanner, and workflow-shaped capture.
- [`docs/adr/0003-replay-and-canonicalization.md`](docs/adr/0003-replay-and-canonicalization.md) —
  re-execution, id and timestamp normalization, and the A/A control.
- [`docs/adr/0004-differ-classification-and-scoring.md`](docs/adr/0004-differ-classification-and-scoring.md) —
  the severity vocabulary, the rule table, the baseline's two caveats, and
  what the score does not claim.
- [`docs/adr/0005-workflow-impact-mapping.md`](docs/adr/0005-workflow-impact-mapping.md) —
  why the integration inventory is declared, the consequence table, and what
  the mapping-precision number does and does not mean.
- [`docs/adr/0006-regression-test-generation.md`](docs/adr/0006-regression-test-generation.md) —
  the three outcomes of a pinned test, why the offline run is not evidence,
  and what the certification gate refuses.
- [`docs/adr/0007-evals-and-instrumentation.md`](docs/adr/0007-evals-and-instrumentation.md) —
  the six scored dimensions, why a deterministic subject records `model: null`
  and zero spend, and why there is no new SLO.
- [`docs/m6-m8-probe.md`](docs/m6-m8-probe.md) — the two title-only
  inventory entries read and probed live, then captured: what each break
  actually is, the A/B tables, and the two assumptions the reading retired.
- [`docs/corpus-coverage.md`](docs/corpus-coverage.md) — what the captured
  corpus reaches, including how many of the eight documented breaks it can
  exercise.

## Usage

```
cp .env.example .env            # add a test-mode sandbox key
uv run compatlab capture        # live traffic -> corpus/version-a.jsonl
uv run compatlab coverage       # per-endpoint and per-workflow stats
uv run compatlab scan           # independent PII audit of the stored corpus
uv run compatlab control        # A/A control: same version twice, must be silent
uv run compatlab replay         # A/B replay -> paired responses for the differ
uv run compatlab diff --why     # classify the pairs -> findings/findings.jsonl
uv run compatlab baseline       # regenerate the oasdiff baseline (network + docker)
uv run compatlab score --out    # caught N of M, false-break rate, the report
uv run compatlab impact --out --html   # map findings onto customer workflows
uv run compatlab pin generate   # compile the pins into pinned/
uv run compatlab pin certify    # run the pinned suite live on both versions
uv run compatlab pin check --out  # offline gate + the regression-test report

uv run --group evals python -m evals   # score the six quality dimensions
```

`capture` runs the workflows in [`scenarios/`](scenarios) against version A,
in order, resolving each step's `{{step.field}}` references from the previous
responses. 38 calls across six workflows today, four of them deliberate
errors. It refuses to finish quietly: it scans what it just wrote and exits
non-zero if anything survived.

## Replay

Replay drives from the corpus, not from the scenario files: what a customer
hands over is captured traffic, not a hand-written description of their
integration. And it re-executes rather than re-sends — `POST
/v1/payment_intents/pi_OLD/capture` cannot be replayed verbatim, because
`pi_OLD` belongs to the run that recorded it. Each side re-runs the workflow
against its own version and resolves `{{step.field}}` references against its
own responses.

Two runs of the same workflow differ everywhere: fresh ids, later timestamps,
a new request id each call. Canonicalization removes that class and nothing
else — ids by the step that created them, timestamps bucketed by day relative
to the run, named volatile fields tokenized. The gate on having drawn that
line correctly is the **A/A control run**: replay one version against itself
and anything still differing is noise the canonicalizer missed.

```
A/A control on 2022-11-15: 29 record(s)
PASS: zero infrastructure-caused mismatches
```

Both `2022-11-15` and `2025-03-31.basil` controls are silent. The real A/B
replay then differs on 24 of 38 steps, and all six ground-truth breaks this
corpus reaches are visible in it — including `capture_method` going
`automatic` to `automatic_async`, a partial capture that produced a
3,000-cent refund on the old version and none on the new one while the schema
stayed identical, and an invoice settled by wire whose `amount_paid` reads 0
on the old version and 2,000 on the new one. Details in
[ADR 0003](docs/adr/0003-replay-and-canonicalization.md), including what a
control run does *not* prove.

## The differ

A finding is not a line of diff output. It is a difference a client could
notice, carrying the axis it was found on, the rule that classified it, both
values, and one sentence of reasoning. Three severities, defined once:

- **breaking** — a client that worked against A can malfunction against B
  with no change of its own: data it read is gone, nulled, or different in a
  way that changes a decision.
- **risky** — it depends how the client was written: a strict deserializer, a
  regex over an error message, an exhaustive switch, a dependence on list
  position.
- **benign** — no correctly written client can be affected.

```
breaking enum            enum-value-changed    $.body.capture_method: "automatic" -> "automatic_async"
  why: `capture_method` now returns `automatic_async`, a value that never appears
       anywhere on A; the request did not specify `capture_method`, so this is a
       changed server default
```

Every finding names its rule, and the generated report prints the whole rule
table, including the rules that did not fire. That is the only real answer to
the objection that "breaking" means whatever the author needed it to mean: a
reader who disagrees can point at a rule, and the rule is one sentence long.

Two design calls are worth stating out of the dozen in
[ADR 0004](docs/adr/0004-differ-classification-and-scoring.md). A **changed
status subsumes the body**: when a step went 200 to 404, Phase 2's leaf-level
diff emitted 85 lines about the fields of an error document, none of which was
the finding — so the status change is one finding and the body differences are
counted into a second. And a **changed value outranks a new enum member**:
`capture_method` going `automatic` to `automatic_async` is both, and
classifying it as "the set of possible values grew" would turn the project's
headline finding into a footnote.

## Scoring, and the baseline that can argue back

The baseline is not a schema differ written here. It is `oasdiff` in
`breaking` mode over Stripe's *own* published spec at the two commits pinned
in ADR 0001, with the container pinned by digest and each spec's declared
version checked before anything is diffed. Matching a finding to it is done
generously, on field name within endpoint: the claim is that the baseline
missed things, and a loose match makes that harder to claim, not easier.

Two things about that run matter as much as the score. It reported **254,576
breaking changes** over the whole spec pair, 15,916 of the 17,495 on the
corpus's endpoints from a single rule — a new country or currency surfacing at
every nested `anyOf` path that can reach it. Diffing these two specs does not
hand a reader a green light they can trust; it hands them a haystack. And on
the breaks it *did* have something to say about, what it said was sometimes
beside the point: for M2 the baseline announces that `automatic_async` is now
a possible value, which cannot tell anyone it became the default for requests
that do not ask.

The false-break rate is a judgment, not a measurement, so every finding
classified `breaking` is adjudicated by hand in `scoring/adjudication.json`
against the published changelog. `compatlab score` **exits non-zero while any
breaking finding has no verdict** and publishes no rate — a rate computed over
whichever findings happened to be adjudicated is the likeliest way this number
would get flattering by accident. CI runs that gate, and a test fails on the
other direction too: an adjudication entry matching no current finding.

## The impact report

A grouped finding list is not an answer to "will this upgrade break us". The
corpus was captured workflow-shaped, so every finding already names a workflow
and a step; grouping by that is one line of code. The fact the findings cannot
carry is the one that decides whether a difference matters: **which of these
fields does the client read, and what does it do with the value.**

Nothing in captured traffic says that. The `{{step.field}}` references prove a
handful of reads, every one of them an `id`, and nothing about what happens to
a value after the response is parsed. So it is declared, in
[`workflows/`](workflows), and on a real engagement it is declared by the
customer — this is the artifact an FDE fills in during discovery, and the
conversation it forces is itself the deliverable.

```json
{
  "corpus": "partial_capture_reconcile.list_refunds_for_intent",
  "reads": [
    {"locus": "$.body.count", "use": "decision",
     "note": "the loop bound for reversal rows; zero means the job writes
              none and reports the night as balanced"}
  ]
}
```

A declaration states facts and never conclusions — a locus, what the client
does with the value, a note — and the consequence is derived from that joined
to the finding. `blocks` means the sequence stops; `corrupts` means it
finishes and is silently wrong; `degrades` means a person sees something
different. Three things keep the inventory from being a hand-written answer
key:

- **It is validated against the captured traffic.** A declared step the corpus
  never captured, a sequence that runs backwards through the captured order, a
  locus absent from that step's version-A response, a `request_input` read
  feeding a step that is not later — each one fails the build and publishes
  nothing. The locus gate is the one that earns its keep: a stale integration
  note is the normal way this input goes wrong.
- **Every claim is re-derived from the replay record** by a checker that does
  not import the rule table and asks only questions with observable answers.
  `compatlab impact` exits non-zero while any claim is unconfirmed, so a
  precision figure is never computed over whichever claims happened to verify.
- **The report publishes the numbers that would expose a rigged inventory**:
  13 of 36 declared reads are touched, 8 real differences fall on calls the
  inventory does not describe at all, and one workflow came out clear. An
  inventory written backwards from the findings would touch every read and
  leave nothing clear.

The inventory is also what resolves a `risky` finding. Phase 3 calls a
difference risky when it depends on how the client was written — a strict
deserializer, an exhaustive switch, a dependence on list position — and a
declared read is exactly that missing fact. 106 of the 194 findings are risky,
and a handful become concrete here: `payment_method_types` gaining four
members corrupts a storefront that renders a tile per method, and no finding
on its own could say so.

```
subscription_renewal_billing — BLOCKED
  3. preview_upcoming_by_subscription  $.body.amount_due  decision  BLOCKED
     this call returned 200 on the old version and 404 on the new one;
     the workflow stops here
```

Each blocked or corrupted read becomes a pin in
[`pins/pins.jsonl`](pins/pins.jsonl): the step to replay, the locus, the
assertion, and both versions' values. Details, including what the precision
number does not mean, in
[ADR 0005](docs/adr/0005-workflow-impact-mapping.md).

## The pinned tests

A pin is a specification; `compatlab pin generate` compiles it into
[`pinned/test_pinned_behavior.py`](pinned/test_pinned_behavior.py), which is
written to be read rather than to be clever:

```python
def test_partial_capture_reconcile_retrieve_charge_after_partial__data_0_amount_refunded(canonical):
    """$.body.data[0].amount_refunded equals 3000.

    nightly_refund_reconciliation: corrupts. Rule `value-changed`, axis `value`.
    Pinned from 2022-11-15. On 2025-03-31.basil the read at `$.body.data[0].amount_refunded`
    returned 0.
    The client reads `$.body.data[].amount_refunded`.
    Assertion: a value small enough to read, pinned exactly.
    Caveat: list endpoint: may reflect account state accumulated between runs (ADR 0003 D7).
    """
    response = canonical("partial_capture_reconcile.retrieve_charge_after_partial")
    assert value_at(response, "$.body.data[0].amount_refunded") == 3000
```

The defining property is not assertable from the repository, so it is run.
`compatlab pin certify` replays the corpus against each version and runs the
generated suite over the result, twice, and records what every test did:

```
19 of 19 pinned regression tests pass on 2022-11-15 and fail on 2025-03-31.basil
```

Three things keep that number from being easy.

- **A pinned test has three outcomes, not two.** It can hold, it can break, or
  the replay can never have reached its step — and only the middle one is a
  pinned break. Workflows are sequences, and one that dies at its third call
  turns every test behind it red without exercising a single pin, which is how
  a count of "tests that failed on B" would read 19 of 19 off a run that
  proved nothing.
- **Fail-on-B is cheap; pass-on-A is the evidence.** Version A's traffic is
  fetched after the pins were written, so a pin holding there is a statement
  about the API rather than about the file it came from. The offline run
  against the committed replay is circular by construction — the pins came
  from those records — so it is labelled a compilation check and gates CI on
  nothing more than that.
- **The gate is strict in both directions.** `compatlab pin check` fails on a
  suite that is not what the pins compile to, on a pin with no live
  certification, on a certification made against a different assertion than
  the file now holds, and on a certification entry naming a pin that no longer
  exists. No count is published while any of that stands.

The assertions run over canonical responses, which makes two of them
deliberately relative: `current_period_end` is pinned as *about thirty days
out*, not as a date that would be wrong tomorrow. Full reasoning in
[ADR 0006](docs/adr/0006-regression-test-generation.md); the certified result,
with each test's failure message on the new version, is
[`docs/regression-tests.md`](docs/regression-tests.md).

## Sanitization

Redaction is not hygiene here, it is the feature. A tool that can only be
pointed at synthetic traffic is a demo; what makes this installable against a
customer's real calls is that the corpus it stores carries no customer data
and is still replayable.

`compatlab/redaction/` is a standalone component — standard library only, no
HTTP, no Stripe, no corpus format — because RC1-594 consumes the same thing
later. A policy is data: key rules, value detectors, a salt.

- Credentials are **dropped**. A secret has no downstream use.
- Personal data is replaced with a **deterministic, type-preserving
  surrogate** from a reserved range (`example.invalid`, the 555-01xx block,
  TEST-NET-1). A redacted email is still a valid email, so a sanitized
  request is still a sendable request; and because the same value always maps
  to the same surrogate, an error message still names the same object the
  rest of the record talks about.
- A name has no shape, so the policy is also **told the literals** it must
  redact everywhere, including free text the server composed. Stripe builds
  an invoice line's description from the product name; the keyed value was
  redacted and the prose copy was not.
- The **scanner does not trust the writer.** `compatlab scan` re-detects
  sensitive shapes in stored data and accepts only a recognized surrogate,
  the drop marker, or a public test fixture. It runs on the committed corpus
  in CI, which is the epic's scored requirement — zero findings — expressed
  as a gate.

Both of those came from being wrong once. The scanner's first run on a real
corpus found the capture path storing the scenario's request *template*
unredacted — 20 findings in a file the writer had just declared clean. And
then a check against the known fixture values found a customer's name inside
an invoice description, in a corpus the scanner had called clean, because
nothing about a name is detectable. See
[ADR 0002](docs/adr/0002-redaction-and-corpus.md).

## What is measured, and where it lands

Four of the numbers above are CI gates, and a gate only ever answers *is this
publishable right now*. `evals/` answers the other question — *is it getting
better or worse, and attributably* — by scoring six dimensions over the
committed artifacts and recording the run in the estate's shared eval store
(RC1-548), where every figure is tagged with the code version that produced
it.

```
uv run --group evals python -m evals --post-datadog
```

```
6 dimension(s) against api-compatibility-lab 0.1.0 - deterministic, offline, no spend.

  pass detection-recall  (0s)
  pass false-breaks  (0s)
  pass schema-diff-advantage  (0s)
    ~ the-baseline-gave-no-usable-warning [advisory]: of the caught breaks, 2 drew
      no baseline entry at all and 1 named the field without the behavior, while
      the same baseline reported 12313 breaking changes on the endpoints this
      corpus calls
  pass workflow-mapping  (0s)
  pass pinned-tests  (0s)
  pass corpus-sanitization  (0s)
```

The dimensions are detection recall against the ground truth, the false-break
rate, the schema-diff comparison, workflow-mapping validity and precision, the
pinned suite's certification, and the PII count on the committed corpus. Each
publishes its figures as `compatlab.*` gauges that the dashboard and three
monitors in `tpm-automation-platform/datadog/` read.

Four decisions are worth knowing before reading the output, all of them in
[ADR 0007](docs/adr/0007-evals-and-instrumentation.md):

- **This subject is deterministic, and the record says so.** Nothing in the
  pipeline calls a model, so the run record carries `model: null` and zero
  spend — written down rather than left out, because a missing field reads as
  "we forgot" and the zero is worth being able to prove. No LLM Observability
  pane, for the same reason: there is no model call to trace.
- **The baseline comparison is advisory and nothing else is.** How badly
  `oasdiff` does on these breaks is a property of Stripe's published specs,
  not of this code, and a dimension that can fail for reasons outside the
  subject gets muted. The other five fail the run.
- **A missing number is not zero.** The false-break rate is `None` while any
  finding lacks a hand verdict, and a `None` observation is left out of the
  Datadog payload rather than sent as 0.0 — publishing it would turn "we have
  not looked" into "we looked and found none".
- **It does not run in CI.** `EVAL_DATABASE_URL` has one home, a developer
  machine, so the suite runs by hand after a change and weekly from the shared
  sweep. A trend with a hole in it is worse than a trend with a slower
  cadence. The gates keep running on every push; the scorers themselves are
  unit-tested there.

## Spike

```
uv run python scripts/spike_dual_call.py
```

The Phase 0 artifact: sends three requests under both version headers, records
the paired responses to `corpus/spike-pair.jsonl`, and prints the top-level
differences. Superseded by the capture path above for everything except
version-pinning verification.
