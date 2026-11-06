# Engagement writeup: assessing a Stripe API version upgrade before it ships

Written the way the work would be papered for a customer: the statement of
work up front, the findings in the middle, and the artifacts they keep at the
end. The customer here is the reference integration this repository ships as
its fixture: eight declared integration workflows in
[`workflows/`](../workflows), exercised by the seven capture scenarios in
[`scenarios/`](../scenarios), running against Stripe's dated API versions
`2022-11-15` and `2025-03-31.basil`. Every figure below traces to a committed
artifact; nothing is an estimate.

The lab is not finished: the inventory of workflows is declared by the
customer rather than discovered from their code, and every figure here
describes one version pair of one API. What is finished is the argument, and
this document is that argument against that pair.

## Statement of work

**Objective.** Tell the customer, before they change their version pin, which
of their integration's workflows the upgrade breaks, which ones keep running
and go silently wrong, and which are safe, with each claim traceable to a pair
of real responses. Leave them a regression suite that fails on the day someone
tries the upgrade again.

**In scope.** A workflow-shaped capture of their traffic against the current
version, sanitized for storage; a replay of the same requests against the
target version; classification of every difference; a mapping from each
difference onto the workflows and the specific field reads it affects; and an
executable test per affected read.

**Out of scope.** Changing their code. The lab says what breaks and proves it;
the remediation is theirs. Also out of scope: endpoints their traffic does not
call, since the whole method is replay, and a behavior nobody exercises cannot
be observed.

**Approach and gates.** Four gates hold regardless of how good the numbers
look, and each refuses to publish rather than caveat:

- `score` will not publish a false-break rate while any `breaking` finding
  lacks a hand verdict against Stripe's changelog.
- `impact` will not publish a mapping precision while any impact claim is
  unconfirmed against the replay record by a checker that cannot see the
  classifier's rule table.
- `pin check` will not publish a pass-on-A / fail-on-B count while the suite
  differs from what the pins compile to, or any pin's certification is
  missing, stale, or names a pin that no longer exists.
- `capture` and `scan` will not leave the corpus with a credential or a
  personal detail in it, and the scanner does not trust the writer.

Nothing in the pipeline calls a model. The differ, the mapper and the test
compiler are deterministic Python, which is why the quality record for this
subject carries `model: null` and zero spend, written down rather than left
out.

## What the schema diff said

The customer's own first instinct, and the industry default: diff the two
OpenAPI specs. `oasdiff` in breaking mode over Stripe's published snapshots at
the two pinned commits reports **254,576 breaking entries** across the pair,
**29,584** inside the paths this integration touches, and **18,901** on the
twenty-nine endpoints its traffic actually calls.

17,204 of those 18,901 are one rule, `response-property-enum-value-added` —
largely a new country or currency surfacing at every nested `anyOf` path that
can reach it.

On the seven documented behavioral breaks this corpus exercises, the same
baseline was:

| Break | Baseline verdict |
|---|---|
| Automatic payment methods enabled by default | no entry at all |
| `capture_method` defaults to `automatic_async` | named the field, not the behavior |
| Partial capture no longer creates a Refund | no entry at all |
| `GET /v1/invoices/upcoming` removed outright | reported |
| Checkout `payment_method_collection` defaults to `if_required` | no entry at all |
| Checkout statement descriptor derives from the business name | no entry at all |
| Invoice `amount_paid` reflects out-of-band payments | no entry at all |

So the baseline does not hand a reader a green light to trust. It hands them a
haystack, and six of the seven needles are not usefully in it. That is the project's
whole premise, and it is a property of the specs rather than of this code —
which is why the lab scores that comparison as **advisory** and never gates on
it.

## What the replay found

Capture runs the seven scenarios in order against `2022-11-15`, resolving each
step's references from the previous responses: 41 calls over 29 endpoints,
four of them deliberate errors. Replay re-executes the identical requests against
`2025-03-31.basil`. The differ compares canonical forms — ids normalized by
provenance, timestamps day-bucketed, volatile keys tokenized — so the only
differences that survive are the ones a client could see.

- **Caught 7 of the 7 documented behavioral breaks the corpus exercises** (8
  in the inventory; the last one is not reachable by this traffic and is
  reported as *unexercised*, never as *passed*).
- **201 findings** over 28 of the 41 steps: 65 breaking, 109 risky, 27 benign,
  each naming the rule that classified it.
- **0 false breaks.** All 65 breaking findings are adjudicated by hand against
  the changelog for the span: 65 documented, 0 undocumented, 0 false-break.
  Read that as *no false breaks observed* rather than a rate measured at
  scale — the denominator is 62 findings over 38 steps.
- **A/A on `2022-11-15` and B/B on `2025-03-31.basil` both report zero
  mismatches** across all 38 records. Without that control a non-empty diff
  proves nothing about the version pair — though the control only proves the
  absence of *asymmetric* noise, and one bug that corrupted both sides
  identically got past it ([ADR 0003](adr/0003-replay-and-canonicalization.md)).

Full scorecard: [`behavioral-diff-report.md`](behavioral-diff-report.md).
Method and caveats: [ADR 0004](adr/0004-differ-classification-and-scoring.md).

## What it means for this integration

A finding is a fact about the API. A customer wants a fact about their own
code, so each workflow declares the calls it makes and the fields it reads,
and the mapper joins the two.

Upgrading affects **7 of the 8 workflows**:

| Workflow | Criticality | Verdict | What the customer sees |
|---|---|---|---|
| `subscription_renewal_billing` | high | **BLOCKED** | the sequence stops; a call it depends on no longer works |
| `guest_checkout_capture` | high | **CORRUPTED** | every call succeeds and a value it decides on has changed |
| `nightly_refund_reconciliation` | high | **CORRUPTED** | every call succeeds and a value it records has changed |
| `free_sample_fulfillment` | high | **CORRUPTED** | it branches on a value it has never been handed, and a promo call the old version rejected now succeeds |
| `offline_invoice_settlement` | high | **CORRUPTED** | it posts money to the ledger as settled through Stripe that never moved through Stripe |
| `connected_account_onboarding` | high | **CORRUPTED** | the merchant approves one statement descriptor at onboarding and their buyers see a different one |
| `api_error_alerting` | medium | **DEGRADED** | still works; something it depends on reads differently |
| `customer_sync_export` | medium | clear | unaffected |

The five CORRUPTED workflows are the point of the engagement. Nothing errors,
no alert fires, and the numbers they write down are wrong — which is the class
of break a status-code smoke test and a schema diff both miss.

**Workflow-mapping precision: 100% (25 of 25 claims).** Each claim is
re-derived from the replay record by a checker that does not read the rule
table, so a wrong rule and a wrong claim cannot agree with each other.
Precision here means *the claims made are right*, not *every impact was
found*: recall over claims is bounded by what the inventory declares, which is
the customer's own description of their code
([ADR 0005](adr/0005-workflow-impact-mapping.md)).

Deliverable: [`impact-report.md`](impact-report.md), and the self-contained
page a customer would actually be sent,
[`impact-report.html`](impact-report.html).

## What the customer keeps

Phase 4 ended with 11 places where a difference reaches a field one of their
workflows reads. Each is compiled into a test that states the dependency as a
sentence their CI can fail on:

```python
def test_partial_capture_reconcile_retrieve_charge_after_partial__data_0_amount_refunded(canonical):
    """$.body.data[0].amount_refunded equals 3000.

    nightly_refund_reconciliation: corrupts. Rule `value-changed`, axis `value`.
    Pinned from 2022-11-15. On 2025-03-31.basil the read at `$.body.data[0].amount_refunded`
    returned 0.
    The client reads `$.body.data[].amount_refunded`.
    """
    response = canonical("partial_capture_reconcile.retrieve_charge_after_partial")
    assert value_at(response, "$.body.data[0].amount_refunded") == 3000
```

**21 of 21 pass on `2022-11-15` and fail on `2025-03-31.basil`**, certified by
a live double run. Three things make that number mean something:

- A pinned test has **three outcomes, not two**: it can hold, it can break, or
  the replay can never have reached its step. Only the middle one is a pinned
  break, and the certification gate refuses a count that rests on an
  unreached step — otherwise one workflow dying at its third call turns every
  test behind it red and reads as 21 of 21 off a run that proved nothing.
- **Fail-on-B is cheap; pass-on-A is the evidence.** Version A's traffic is
  fetched after the pins were written, so a pin holding there is a statement
  about the API rather than about the file it came from. The offline run
  against the committed replay is circular by construction and is labelled a
  compilation check, not evidence.
- Two assertions are deliberately **relative**: `current_period_end` is pinned
  as *about thirty days out*, not as a date that would be wrong tomorrow.

Deliverable: [`regression-tests.md`](regression-tests.md), with each test's
real failure message on the new version.
Method: [ADR 0006](adr/0006-regression-test-generation.md).

## The corpus a customer would be handing over

Redaction is not hygiene here, it is what makes the method installable. A tool
that can only be pointed at synthetic traffic is a demo; this one stores the
customer's real calls and still replays them.

Credentials are dropped. Personal data is replaced with a deterministic,
type-preserving surrogate from a reserved range, so a redacted email is still
a sendable email and the same value always maps to the same surrogate — an
error message still names the same object the rest of the record talks about.
Names have no detectable shape, so the policy is also *told the literals* it
must remove everywhere, including prose the server composed from them. And
`scan` re-detects sensitive shapes in stored data rather than trusting the
writer, which is how the capture path got caught storing an unredacted request
template, and how a customer's name was later found inside an invoice line
description in a corpus the scanner had already called clean
([ADR 0002](adr/0002-redaction-and-corpus.md)).

Zero findings on the committed corpus is a CI gate, not a footnote.

## What the engagement cost to run

Nothing, in the sense that matters: no model calls, so no inference spend, and
the capture and replay run against a Stripe sandbox in test mode. The quality
record for every run carries zero spend — recorded rather than omitted,
because "this costs nothing" is a claim worth being able to check.

The offline chain — classify, score, map, check the pinned suite — runs in
about one second on a laptop over the committed corpus, so the whole analysis
is re-runnable on every commit, and four of its five published numbers are CI
gates. The parts that touch Stripe are capture, replay and the live
certification, which is why those happen by hand and their records are what CI
gates against.

## What this does not say

- **One of the eight documented breaks in the inventory is unexercised.**
  It is listed, reported as unexercised, and excluded from the recall
  denominator. Widening the corpus was tracked as RC1-618,
  which took the exercised count from four to seven and is the honest answer
  to "is 7 of 7 a good score" — it is 7 of 7 of what this traffic can reach.
  The one that remains, M5, was read and probed, confirmed live, and left
  unexercised **by decision rather than by blocker**: its observable needs a
  hosted Checkout page driven to a *failed* payment attempt, and replaying
  that would put a browser inside the A/A control, whose determinism is the
  property this project refuses to trade (ADR 0003 D2, docs/m5-probe.md).
  Every entry in the inventory is now confirmed live; the gap is reach, not
  knowledge.
- **The inventory is declared, not discovered.** The customer describes the
  calls they make and the fields they read. A read they forgot to declare is a
  break this report will not mention, and no amount of precision changes that.
  Deriving the inventory from a customer's code is the obvious next phase.
- **One version pair, one integration.** The method generalizes; this
  measurement does not. The numbers above describe `2022-11-15` to
  `2025-03-31.basil` for eight workflows, and the value of any of them on
  another pair is unknown until it is run.
