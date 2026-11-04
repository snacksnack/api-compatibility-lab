# ADR 0002: redaction and corpus decisions (RC1-606)

Status: accepted
Date: 2026-11-04

## Context

Phase 1 captures real traffic against version A and stores it as the corpus
every later phase reads. Two constraints shape it. The epic makes
sanitization load-bearing rather than hygienic: redaction on captured traffic
is what would make this tool installable against a customer's production
calls instead of only against synthetic ones, and "zero PII findings on a scan
of the stored corpus" is a scored requirement. And RC1-594's diagnostic bundle
needs the same redaction, which is why RC1-603 was sequenced ahead of it.

Phase 0 supplied the motivating incident: the spike wrote raw response bodies
to a committed corpus and shipped a test-mode `client_secret` and
account-bearing log URLs to a public repo, caught in review on PR #1
(docs/spike-findings.md, finding 5).

## D1. Redaction is a standalone component, not a capture detail

`compatlab/redaction/` depends on nothing but the standard library: no HTTP,
no Stripe, no corpus format. A `Policy` is data — key rules, value detectors,
a salt — so a second consumer ships a different policy over the same engine
rather than a second implementation. `BASE_POLICY` carries detectors only;
`STRIPE_POLICY` adds the key rules for Stripe's field names.

## D2. Two actions: drop credentials, surrogate everything else

Dropping every sensitive value would be simpler and would make the corpus
useless for its actual purpose: a corpus full of `[redacted]` cannot be
replayed, and replay is Phase 2. So:

- **DROP** replaces the value with a marker. Credentials only. A secret has no
  legitimate use downstream, replay included.
- **SURROGATE** replaces the value with a deterministic, type-preserving
  stand-in from a reserved range: `example.invalid` for email, the 555-01xx
  fictional block for phone, TEST-NET-1 for IP, ZIPs beginning `000`, Stripe's
  published test card. A redacted email is still a syntactically valid email,
  so the sanitized request is still a sendable request.

Determinism is what keeps the corpus diffable: the same input value yields the
same surrogate everywhere it appears, so an error message still names the same
customer the rest of the record talks about, and a diff between two versions
does not light up with redaction noise.

Surrogates are derived with HMAC-SHA256 over a salt. The default salt is
public, which is correct for this repo (the corpus is synthetic sandbox
traffic and reproducibility is worth more here), and wrong for a customer
install: with a known salt, a surrogate for a low-entropy value like an email
address can be recovered by hashing a candidate list. `COMPATLAB_REDACTION_SALT`
sets a private one.

## D3. The scanner does not trust the writer

`Policy.redact` runs before anything is stored. `Policy.scan` runs against
what *is* stored and re-detects sensitive shapes from scratch, accepting only
a recognized surrogate, the drop marker, or an explicitly allowed public test
fixture (`tok_visa` and friends, which are meaningless outside a sandbox).
That is why surrogates come from recognizable reserved ranges: recognition is
what lets an audit of a redacted corpus come back empty without the audit
simply agreeing with the code that wrote it. `scan(redact(x))` being empty is
evidence, not a tautology.

It earned this on its first live run, in the same session it was written: the
capture path redacted request *bodies* and response bodies but stored the
scenario's `request_template` raw, so every literal email, name, street
address and postal code in the fixtures went to disk in the clear. 20
findings, from a corpus the process had just declared written. The writer was
wrong and the auditor was right, which is the entire argument for having two.

## D4. Value detectors run on strings only; numbers are matched by key

The first capture also flagged a digit substring of a hex record id as a phone
number. A phone pattern now requires a formatting signal (a leading `+` or
separators), and numeric fields are matched by key (`phone`) rather than by
shape. The alternative — pattern-matching integers — reads every Unix
timestamp as a phone number and trains the reader to ignore findings, which is
worse than a narrower detector.

Over-redaction is otherwise the chosen direction: `name` is surrogated
everywhere, costing the readability of a product name and buying never having
to decide whether a given `name` is a person's. Coarse fields (`city`,
`state`, `country`) are left alone; `country` in particular changes Stripe's
behavior, and redacting it would corrupt the comparison the corpus exists for.

## D5. Known values, because a name has no shape

Neither key rules nor detectors cover the case the first captured corpus
actually failed on. Stripe composes an invoice line item's `description` from
the product name: `"1 x Reconciliation Pro (at $25.00 / month)"`. The name was
redacted at its own key, and the server echoed it back into prose under
`description`, where nothing marks it as sensitive and no pattern can
recognize it. A person's name has no detectable shape — that is not a gap in
the detectors, it is the nature of names.

So a policy also carries `known`: literal values it has been told are
sensitive, replaced wherever they appear, with the same surrogate their keyed
occurrence receives. The capture path seeds it automatically from the
scenarios about to run — every literal a key rule covers — because a caller
who forgets to seed it is exactly the failure this is meant to prevent.
`compatlab scan` seeds identically, or auditing stored data would miss what
the writer caught. For a customer install the seed list is their own customer
records, which is how commercial redaction handles names too: you cannot
detect them, you can only be told.

The gate for this class cannot be the scanner, for the same reason. It is
`test_no_known_fixture_value_appears_anywhere_in_the_corpus`: the test knows
what the scenarios sent, so it can check what was stored. That test is what
caught `customer_name` surviving, after `scan` had already called the same
corpus clean.

## D6. Workflows are data, and the corpus is captured workflow-shaped

Scenarios live in `scenarios/*.json` as named call sequences with
`{{step.field}}` references between steps. Phase 4 has to say "this change
breaks checkout at step 5", so the workflow boundary has to exist in the
corpus from the start rather than be inferred later from a flat pile of
endpoints. Data rather than code because the real use of this tool is a
customer describing their own call sequences.

References resolve against the raw response and never against the stored one:
a surrogate is not a usable object id. The unresolved template survives into
the record as `request_template` / `path_reference` so Phase 2 can re-resolve
it against version B's own ids instead of replaying stale ones.

A step whose references cannot be resolved is skipped and reported. A non-2xx
response is captured like any other: error semantics are one of the behavioral
axes the differ compares, and three of the 29 captured calls are deliberate
errors.

## D7. Coverage states the denominator

`compatlab coverage` reports calls per endpoint and per workflow with status
counts, and how many of the ground-truth behavioral breaks the corpus can
exercise: **4 of 8** today (M1, M2, M3, M4). A break no captured call touches
cannot be caught, so leaving that number out of the coverage table would
quietly flatter the Phase 3 score. The remaining four need a completed
Checkout Session, a Connect test account, or detail pages still unread from
Phase 0.
