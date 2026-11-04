# ADR 0004: behavioral differ, classification, and scoring (RC1-608)

Status: accepted
Date: 2026-11-04

## Context

Phase 2 left `replay/pairs.jsonl`: 29 paired responses, A/A and B/B controls
both silent, 16 steps differing on the real A/B run. Phase 3 has to turn those
pairs into findings a customer could act on, classify each one, and score the
result against two things that can argue back — the live-verified ground-truth
inventory in `docs/ground-truth.md`, and a schema diff nobody can accuse of
having been built to lose.

The output is `findings/findings.jsonl` (Phase 4's input),
`baseline/schema-diff-index.jsonl`, and the generated
`docs/behavioral-diff-report.md`.

Result: **4 of the 4 documented behavioral breaks the corpus exercises are
caught** (M = 8; four entries need scenarios the corpus does not have). The
schema-diff baseline gave no usable warning on three of them, while reporting
12,313 breaking changes on the same twenty endpoints. 25 findings classified
`breaking`, every one adjudicated against the changelog, 0 false breaks.

## D1. The unit is a finding, not a line of diff

Phase 2's `diff_paths` enumerated leaves. That is the right primitive and the
wrong product: on the one step where an endpoint was removed it emitted 85
lines about the fields of an error body. A finding is instead *a difference a
client could notice*, and it carries the axis it was found on, the rule that
classified it, the values on both sides, and a one-sentence reason.

Three severities, defined once in `compatlab/findings.py` and nowhere else:

- **breaking** — a client that worked against A can observably malfunction
  against B with no change of its own. Data it read is gone, nulled, or
  different in a way that changes a decision.
- **risky** — a client *may* malfunction depending on how it was written: a
  strict deserializer, a regex over an error message, an exhaustive switch, a
  dependence on list position.
- **benign** — no correctly written client can be affected.

Anything that cannot be argued into one of those three is a missing rule, not
a fourth severity. The vocabulary is enforced in the constructor.

## D2. Structure and meaning are separate modules

`compatlab/deltas.py` answers "what is structurally different" with no
opinion. `compatlab/classify.py` answers "what does that mean to a client" as
an ordered rule table. Two failure modes wanted them merged, and both are
bugs: a walker that silently suppresses differences it thinks are unimportant,
and a classifier that re-derives structure by parsing a formatted diff string.

Every finding names its rule, which is the only real answer to the obvious
objection to a tool like this — that "breaking" means whatever the author
needed it to mean that afternoon. A reader who disagrees can point at a rule,
and the rule is one sentence long. The generated report prints the table,
including which rules did not fire.

## D3. A changed status subsumes the body

When a step returns 200 on A and 404 on B, the two bodies are different kinds
of document and comparing their fields describes the consequence instead of
the cause. The status change is one finding; the body differences are counted
and reported as a second, benign finding carrying the count. Two lines instead
of 85, with nothing hidden: the count is right there.

Under the *same* status, error bodies are compared by identity rather than by
prose. A different `type`/`code`/`param` is a different error (breaking); the
same error reworded is `error-message-changed` (risky) — not because rewording
should break a client, but because clients really do match on message text,
and the live corpus contains exactly that case (the `total_count` 400 carries
a deprecation hint on A and not on basil). Saying so is more useful than
pretending otherwise.

## D4. A changed value outranks a new enum member

`capture_method` going `automatic` -> `automatic_async` is both "the value
changed" and "a member never seen on A". Classified as the second it would
read as "the set of possible values grew" — risky, additive, ignorable. It is
the project's own headline finding (M2), so precedence puts the changed value
first and uses the enum axis to say *which kind* of changed value it is.

The rule also reads the request: `capture_method` was not in the request body,
so the rationale says "the request did not specify `capture_method`, so this
is a changed server default". A changed default is exactly what a schema
cannot express, and the sentence makes that visible without the reader
needing to know the project's thesis.

## D5. The baseline is oasdiff over Stripe's own spec, pinned twice over

Not a schema differ written here. `oasdiff` in `breaking` mode, container
pinned by digest (`tufin/oasdiff@sha256:6f3b5b16…`, build `dbf670e`), over
`stripe/openapi@c3ae0d4c07` and `@31b29ff897` from ADR 0001 D3, with each
spec's self-declared `info.version` checked against the version it is supposed
to be before anything is diffed. A spec that fails the check is not diffed at
all. Anyone can re-run it.

Two findings about that run matter as much as the score:

**It is not quiet.** 254,576 breaking entries over the whole spec pair. 19,349
within the paths the corpus touches; 12,313 on the exact twenty operations the
corpus calls. 11,270 of those 12,313 are one rule,
`response-property-enum-value-added`, mostly a new country or currency
surfacing at every nested `anyOf` path that can reach it. The rule mix is
stored in the index so the report cites a number rather than an impression. Diffing these two specs does not
produce a green light a reader can trust — it produces a haystack. That is
part of the baseline's performance, not a snipe at the tool.

**It is given every benefit of the doubt.** Matching a finding to the baseline
is done on field name within endpoint, over every backticked token in an
entry's text with `anyOf[...]` noise stripped — so an entry about
`error/payment_intent/capture_method` counts as the baseline having said
something about `capture_method` there. The claim is that the baseline missed
things; a generous match makes that claim harder to make, not easier.

The verdict per break is therefore three-valued, and only two of the three are
misses:

- `reported` — an entry about that field's own contract, or the path's
  removal. A reader would have been warned. M4 lands here: the spec does
  record that `GET /v1/invoices/upcoming` is gone.
- `named` — entries mention the field, but only to say the value set or the
  polymorphic branches grew. M2 lands here: the baseline announces that
  `automatic_async` is now a possible value, which cannot tell anyone it
  became the default for requests that do not ask.
- `green` — nothing at all. M1 and M3 land here. `automatic_payment_methods`
  is not named once on `POST /v1/payment_intents`, and `amount_refunded` is
  not named once on `GET /v1/charges`.

The index is committed so scoring needs neither network nor container;
`compatlab baseline` regenerates it by hand. It is JSONL with rule ids stored
as indices into a table — pure encoding, and the difference between a 334 KB
artifact a reviewer will open and a 743 KB one nobody checks.

## D6. The account-state caveat is scoped, and it is never a discount

ADR 0003 D7 left Phase 3 to decide what to do about the sandbox accumulating
objects between runs, which can make a list endpoint differ for reasons that
have nothing to do with the version. The decision: keep one sandbox, and
attach the caveat to exactly the findings it can explain.

Leftover objects can change *which* objects a list returns, so a value, a
length, or an order under `data` may be about the objects. They cannot change
whether a key exists on the object the server serializes — that is the
version's doing either way. So value, length, order, and pagination-key
findings on a list body carry the caveat; shape findings under `data` do not.
Attaching it to all of them would train a reader to discount the clearest
findings in the report.

Severity is never reduced by a caveat. A caveat that silently downgrades is
the same mistake as not mentioning it.

The cleaner fixes — a fresh sandbox per side, or `created[gte]` filters scoped
to the run — stay deferred, and now for a stated reason rather than by
omission: the current corpus has no finding that the caveat was needed to
explain, so the fix would be untested machinery. It belongs with the first
scenario whose list results the account can pollute.

## D7. Timing is implemented and never scored

The story names timing among the axes. Replay now records `duration_ms` per
call and the differ reports a shift above 50% on its own axis — always
`benign`, by rule, with the reason in the rationale. Both sides run
sequentially against one shared sandbox, so a duration difference measures the
queue a request landed in at least as much as the version that served it, and
there is one sample and no control. That is the honest ceiling: report it,
never score it. A corpus captured under better conditions makes the axis real
without changing a line of the differ.

The currently committed corpus predates the field, so the real run reports no
timing findings at all. That is visible in the report's rule table, under the
rules that did not fire.

## D8. The false-break rate requires hand adjudication, and scoring fails without it

"False-break rate" has no mechanical definition: whether a flagged difference
is a real break is a judgment about client behavior. So every finding
classified `breaking` gets a verdict by hand in `scoring/adjudication.json`,
against the published changelog for the span: `documented`, `undocumented`
(real, and Stripe did not write it down — a finding in its own right), or
`false-break`.

`compatlab score` **exits non-zero while any breaking finding is
unadjudicated**, and publishes no rate. A rate computed over whichever
findings happened to have verdicts is the single most likely way this number
becomes flattering by accident. A test asserts the complement too: an
adjudication entry that no longer matches any finding is an error, because
"keep the verdicts, quietly lose the findings" is the other shape of the same
dishonesty.

On this corpus: 25 breaking findings, all `documented`, 0 false breaks. Eight
evidence the behavioral breaks (M2 at three steps, M3 at three loci, M4 at
two); the other seventeen are basil's invoice and subscription restructuring, which the baseline largely reports too — the check
that the lab is not missing what a schema diff does catch. Where the changelog
announces a restructuring without enumerating the fields it displaces, the
adjudication note says the mapping is inference, not a quotation.

The report states the number as *no false breaks observed*, with the
denominator in the same sentence. Four workflows is not a scale at which a 0%
rate means much, and the report says so rather than leaving the reader to
work it out.

## D9. An enum value was being read as an object id, symmetrically

Found while reading the real A/B output: `collection_method:
"charge_automatically"` appeared on both sides as `<id:charge>`. The
canonicalizer's object-id pattern — lowercase prefix, underscore, long tail —
matches any sufficiently long snake_case word, and `charge` + `automatically`
qualifies.

Both sides, same corruption, so the A/A control was green (ADR 0003 D6 again,
and this is the second time that limit has cost something). The cost was
specific: the enum axis cannot see a changed enum value whose name happens to
look like an id, and the enum axis is where two of the eight ground-truth
breaks live.

Fixed by requiring the random half to carry a capital or a digit — the rule
`compatlab/capture.py` already applied to path segments, where the same trap
was spotted in Phase 1 and the lesson did not travel. `prod_abcdefghij` would
now be missed; real Stripe ids are mixed-case, and the provenance map catches
created ids regardless of shape. Regression tests in
`tests/test_canonical.py`.

## D10. What this score does not claim

- **M is 8, not 4.** Four entries (M5–M8) need a completed Checkout Session, a
  Connect test account, a billing-boundary crossing, or an unread changelog
  detail page. They are reported as *not exercised*, never dropped from the
  denominator, and a test asserts none of them is ever reported as caught.
- **The headline is 4 of 4 exercised**, which is the number the corpus can
  honestly support. Raising it is corpus work (RC1-606's scenarios), not
  differ work.
- **One of the four was not missed by the baseline.** M4's schema-visible half
  is in the spec. Reporting it as a miss would be the easiest available lie
  and the quickest to be caught.
- **`total_count` and the `amount_off` coupon restriction remain out**:
  account-gated and reversed upstream respectively (docs/spike-findings.md).
  The differ does report the `total_count` error-message difference, as a
  risky finding, correctly labeled as not the documented break.
