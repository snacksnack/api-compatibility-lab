# API Compatibility Lab

Replays sanitized API traffic across two API versions to find the behavioral
breaks a schema diff misses.

An OpenAPI diff catches removed fields and changed types. It is blind to a
field that became nullable in practice, a changed default, a pagination
boundary shift, a changed sort order, a different error code under the same
HTTP status, silent truncation, and undocumented enum values. Every one of
those breaks real integration code while the schema diff reports green.
Behavior, not schema, is the contract customers actually depend on.

**Status: Phase 1 (RC1-606) — capture and redaction.** Traffic is captured and
sanitized; replaying it against version B and diffing the results are Phase 2
and Phase 3. Nothing here is a finished tool yet.

## Ground truth

The detector is scored against Stripe's dated API versions: traffic is
replayed across `2022-11-15` and `2025-03-31.basil` (pinned per request via
the `Stripe-Version` header), and every behavioral difference it finds is
checked against Stripe's published upgrade changelog — ground truth this
project's author did not write. The schema-diff baseline is `oasdiff` over
Stripe's own published OpenAPI snapshots at pinned commits.

- [`docs/ground-truth.md`](docs/ground-truth.md) — the documented changes in
  the span, classified schema-visible vs behavioral, and the provisional M.
- [`docs/adr/0001-phase-0-decisions.md`](docs/adr/0001-phase-0-decisions.md) —
  version pair, baseline, stack, and corpus-format decisions.
- [`docs/adr/0002-redaction-and-corpus.md`](docs/adr/0002-redaction-and-corpus.md) —
  redaction actions, the independent scanner, and workflow-shaped capture.
- [`docs/corpus-coverage.md`](docs/corpus-coverage.md) — what the captured
  corpus reaches, including how many of the eight documented breaks it can
  exercise.

## Usage

```
cp .env.example .env            # add a test-mode sandbox key
uv run compatlab capture        # live traffic -> corpus/version-a.jsonl
uv run compatlab coverage       # per-endpoint and per-workflow stats
uv run compatlab scan           # independent PII audit of the stored corpus
```

`capture` runs the workflows in [`scenarios/`](scenarios) against version A,
in order, resolving each step's `{{step.field}}` references from the previous
responses. 29 calls across four workflows today, three of them deliberate
errors. It refuses to finish quietly: it scans what it just wrote and exits
non-zero if anything survived.

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

## Spike

```
uv run python scripts/spike_dual_call.py
```

The Phase 0 artifact: sends three requests under both version headers, records
the paired responses to `corpus/spike-pair.jsonl`, and prints the top-level
differences. Superseded by the capture path above for everything except
version-pinning verification.
