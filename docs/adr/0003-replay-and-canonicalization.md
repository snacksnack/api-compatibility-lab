# ADR 0003: dual replay and canonicalization (RC1-607)

Status: accepted
Date: 2026-11-04

## Context

Phase 2 replays the sanitized corpus against both dated versions and produces
paired responses for the Phase 3 differ. The exit criterion is not "a replay
ran" but "an A/A control run shows zero infrastructure-caused mismatches":
until replaying one version against itself is silent, no A/B difference can be
attributed to the version.

## D1. Replay drives from the corpus, not from the scenario files

What a customer hands over is captured traffic. If replay needed the scenario
definitions, the tool would only work on integrations somebody had already
described by hand, which is the opposite of the point. Phase 1 stored
`path_reference` and `request_template` — the unresolved `{{step.field}}`
forms — so a stored record carries enough to be re-executed.

## D2. Re-execute, do not re-send

`POST /v1/payment_intents/pi_OLD/capture` cannot be replayed verbatim:
`pi_OLD` belongs to the run that recorded it. Each side therefore re-runs the
workflow against its own version, builds its own object graph, and resolves
references against its own responses. Two sides, two sets of ids, the same
sequence of intent.

This is also the step where Phase 1's central claim is either true or empty:
what gets replayed is the *sanitized* corpus, carrying the surrogates, not the
original values. A corpus that could not be replayed after redaction would
make "installable against production traffic" a slogan. It replays.

**Amended by RC1-618 Stage 3.** The decision stands, and it is now the reason
one inventory entry stays unexercised, so it is worth naming what it costs.
M5's observable (basil #4) needs a Checkout Session driven to a *failed*
payment attempt on a hosted page. Capture could do that once; re-execution
means `replay` would do it twice per run, once per version, and `pin certify`
runs the pinned suite live on both versions on top of that. A browser in that
path makes the A/A control non-deterministic, which is the one property this
project refuses to trade, so M5 is recorded as confirmed-live and unexercised
with the reason written down rather than captured.

The probe also collapsed an option the RC1-618 Stage 3 handoff had ranked
above driving a browser inside replay: declaring completion as an out-of-band
step performed through a non-HTTP hook. The only out-of-band step such a hook
could perform *is* driving a hosted page, so it buys containment — one
declared step rather than the whole engine — and not determinism. Worth having
if M5 is ever built; not a separate answer to the question. Record in
docs/m5-probe.md.

## D3. Ids are normalized by provenance, with a shape fallback

The id that `create_customer` returned becomes `<id:create_customer>` on both
sides, so every later response that refers to that customer matches across
runs. Ids the corpus never saw created — a charge, a balance transaction, a
payment-method configuration the server made on its own — fall back to
`<id:prefix>`, collapsing two distinct charges into one token. That is a real
loss of signal, accepted: which charge id appeared is never the break we are
hunting.

Three id shapes had to be learned from the control rather than guessed:
underscore-joined prefixes (`il_tmp_...` on a preview line), prefixless ids (a
Coupon id is a bare eight characters), and `invoice_prefix`, which reappears
inside the invoice `number` and so is registered as a run token rather than
normalized by key — that keeps the `-0001` sequence comparable.

## D4. Timestamps are bucketed by day, not erased

Replacing every timestamp with a constant is the easy way to make a control
pass and it throws away real signal: a billing period that moved from thirty
days to a calendar month would become invisible. Epoch integers are rewritten
relative to the run's own start and rounded to days, so two runs minutes apart
agree on `<ts+0d>` while a period boundary a month out still reads as a
different bucket.

## D5. Volatile keys are named, and each one is a stated blind spot

`risk_score`, `authorization_code`, `network_transaction_id` are freshly
random per run with nothing to key them on but the field name, so each is
replaced by a token. The cost is explicit: a version that changed how it
scores risk, or stopped returning an authorization code, would not show up.
Neither is the class of break this project is for, and leaving them in means
every charge-bearing step reports a difference on every run — the fastest way
to train a reader to ignore the output.

`stripe-version` is tokenized too, because it differs on every pair of a
version diff by construction. The property that header exists to prove —
pinning actually worked — moves into replay itself, which warns when the
served version is not the requested one. Without that, a typo in one side's
version would produce a beautifully quiet A/B run that compared a version
against itself.

## D6. What the A/A control proves, and what it does not

It proves the absence of *asymmetric* noise. It cannot catch a
canonicalization bug that corrupts both sides identically, and one did: the
shape fallback re-matched tokens this module had already inserted, rewriting
`<id:create_subscriber>` to `<id:<id:create>>` because `create` plus
`subscriber` has the shape of an object id. Both sides, same corruption, green
control. It was caught by a unit test. The control is a necessary gate, not a
sufficient one.

Result: **A/A on 2022-11-15 and B/B on 2025-03-31.basil both report zero
mismatches** across all 38 records, and the real A/B run yields differences on
24 of 38 steps, including all six live-confirmed ground-truth breaks the
corpus reaches.

**Amended by RC1-618.** The control had a second blind spot, and it was in the
sentence above rather than in the method. `canonical_record` carries
`duration_ms` through uncanonicalized for the differ's timing axis, and the
control diffs canonical records directly — so a corpus carrying the field
mismatches on every step, every run. It had never happened, because the
committed corpus predated the field. The first capture that included it failed
all 38 steps on timing alone. Fixed by `canonical.without_timing`, applied at
the control's comparison and not at canonicalization, so the differ keeps the
axis it reports as benign-forever (ADR 0004 D7).

The generalizable part: "the differ handles timing on its own axis" was true
of the differ and quietly false of the only other consumer of the same
records. A guarantee that lives in one reader is not a property of the data.

## D7. Account-wide state outlives a run

The control's last two mismatches were not canonicalization gaps. The list
endpoints return objects created by *earlier* runs — the sandbox accumulates —
so page two of a customer list differs between two runs of the same version
because the account grew in between. Handled by letting unknown-provenance
values collapse to a flat token, which keeps the pagination boundary and the
page size comparable while making the identity of leftover objects opaque.

Phase 3 has to know this: **a difference on a list call can come from
accumulated account state rather than from the version.** The cleaner answers
are a fresh sandbox per side or `created[gte]` filters scoped to the run, and
both are Phase 3's call, since it is the consumer that has to trust the diff.

## D8. Test clocks are deferred, deliberately

The story names test clocks among the non-determinism to handle. No scenario
in the corpus currently depends on wall-clock progression: the subscription
workflow creates and cancels within one run and never crosses a billing
boundary. Both controls pass without clocks, so building the plumbing now
would be untested machinery justifying itself. It belongs with the first
scenario that needs a renewal to occur — which is also what would raise
ground-truth coverage past M5 and M8, and is therefore a corpus-coverage task
rather than a replay task.

**Amended by RC1-618 Stage 1.** The decision stands; one of its two cited
triggers does not. M8 was a title-only inventory entry when this was written,
and reading its detail page showed it is about partial and out-of-band
invoice payments, not a billing boundary: the live observable is
`invoice.amount_paid` after `POST /v1/invoices/{id}/pay`, six synchronous
calls and no clock (docs/m6-m8-probe.md). Exercising M8 therefore does not
reach the replay engine at all. Test clocks keep waiting for a scenario that
genuinely needs wall-clock progression, and no longer have a coverage story
pointing at them.

## D9. An encoded leak, found by replay

Canonicalization flagged `receipt_url` as noise, and reading why exposed a
redaction hole instead: Stripe embeds the account id in that URL
base64-encoded, so the plain `acct_...` detector saw nothing while the same
value sat in the corpus in encoded form. `hosted_invoice_url` and
`invoice_pdf` carried it too.

Fixed in both directions. The three fields are now dropped by key — named
explicitly rather than by a `_url` suffix, so `return_url`, whose value is
behavioral signal, survives. And the redaction component gained a general
pass: candidate base64 runs are decoded at each of the three byte alignments,
standard and url-safe, and the decoded text is re-run through the existing
detectors. Encoded personal data is still personal data, and the next field
like this will have a different name.

The leaked value was a test-mode account identifier, not a credential:
nothing to rotate, nothing usable without an API key. It is fixed forward,
since `refs/pull/*/head` keeps old blobs regardless.
