# Ground truth: documented Stripe changes, 2022-11-15 -> 2025-03-31.basil

Source: the Stripe developer changelog (https://docs.stripe.com/changelog).
A version's changes land when upgrading TO it, so the span (A, B] covers
2023-08-16 through 2025-03-31.basil; changes at 2022-11-15 itself are already
in version A and excluded.

Classification:

- **SCHEMA**: a field, parameter, endpoint, or type was added/removed/renamed;
  an OpenAPI spec diff catches it.
- **BEHAVIORAL**: same schema shape, different runtime behavior (changed
  default, field no longer populated, different error code under the same
  status, changed ordering/pagination, requests that now error). The schema
  diff reports green on these; they are the project's target.
- **BOTH**: components of each.

Exercisable = replayable from a bare test-mode sandbox (no Issuing, Terminal,
Vault & Forward, or client-side surface). Entries marked *(title-only)* were
inventoried from changelog titles; their detail pages still need reading
before final scoring (open Phase 0 work). The two that carried an M number —
2023-08-16 #2 and basil #11 — were read and probed in RC1-618 Stage 1 and no
longer carry the marker; see docs/m6-m8-probe.md.

## 2023-08-16

| # | Change | Objects | Class |
|---|--------|---------|-------|
| 1 | Automatic payment methods enabled by default | PaymentIntent, SetupIntent | BEHAVIORAL |
| 2 | One-time payments in Checkout support no-cost orders: `payment_method_collection` default moves `always` -> `if_required`. **Live-verified in RC1-618:** the default flip is readable on a `mode=payment` session create, and a zero-total session goes 400 -> 200 | Checkout Session | BEHAVIORAL |
| 3 | Platform-scoped rendering for select PaymentMethod fingerprints | PaymentMethod | BEHAVIORAL |
| 4 | Specific error codes for failed Klarna payments | PaymentIntent, Checkout | BOTH |
| 5 | New director verification error codes | Account | BOTH |

## 2023-10-16

| # | Change | Objects | Class |
|---|--------|---------|-------|
| 1 | New account requirement error codes | Account | BOTH |
| 2 | Statement descriptor and prefix auto-populated. **Live-verified in RC1-618:** the derivation SOURCE changed, not the fact of population — `2022-11-15` derives the descriptor from `business_profile[url]`, basil from `business_profile[name]` with a url fallback that strips `WWW.`; with both sent, both versions return a plausible non-null value and disagree only about its content | Account | BEHAVIORAL |

## 2024-04-10

| # | Change | Objects | Class |
|---|--------|---------|-------|
| 1 | `automatic_async` becomes the default capture method when unspecified | PaymentIntent | BEHAVIORAL |
| 2 | `rendering_options` renamed to `rendering` | Invoice | SCHEMA |
| 3 | `features` attribute renamed | Product | SCHEMA |

## 2024-06-20

Nine changes, all Issuing/Connect schema-level (renames, removed undocumented
fields, new enum values, two deprecations marked BOTH pending detail pages).
No exercisable behavioral entries.

## 2024-09-30.acacia (4 breaking)

| # | Change | Objects | Class |
|---|--------|---------|-------|
| 1 | Contextual filters on billing alerts *(title-only)* | Billing Alerts | SCHEMA (provisional) |
| 2 | Terminal saved-card consent model updated *(title-only)* | Terminal | BOTH (provisional) |
| 3 | Default for shipping address validation changed *(title-only)* | Issuing Card | BEHAVIORAL |
| 4 | Risk verification details for connected accounts *(title-only)* | Account | SCHEMA (provisional) |

## 2025-03-31.basil (22 breaking)

| # | Change | Objects | Class |
|---|--------|---------|-------|
| 1 | Item-level billing periods; subscription-level periods removed *(title-only)* | Subscription | SCHEMA |
| 2 | Invoicing objects gain `parent` provenance field *(title-only)* | Invoice | SCHEMA |
| 3 | `shipping_details` moved to `collected_information.shipping_details` | Checkout Session | SCHEMA |
| 4 | Checkout Sessions: subscriptions created only after completed payment; no invoice until `complete`; sessions editable after failed attempt. No schema change. **Live-verified in RC1-618:** a session create is identical across the pair, and so is a SUCCESSFUL completion; the difference appears only after a FAILED payment attempt, where A leaves an `incomplete` subscription and an `open` invoice and basil leaves nothing | Checkout Session, Subscription, Invoice | BEHAVIORAL |
| 5 | `amount_off` coupons with `duration: forever` rejected at creation and application (`percent_off` unaffected). Reversed upstream in 2026-01-28.clover; live API accepts again | Coupon | BEHAVIORAL (reversed) |
| 6 | Singular `coupon`/`promotion_code` params removed for stackable `discounts` *(title-only)* | Billing | SCHEMA |
| 7 | `GET /v1/invoices/upcoming` removed outright — 404 `invalid_request_error` pointing at `POST /v1/invoices/create_preview`. **Live-verified in RC1-607:** the subscription-context form 404s too, so the changelog's "previews across all subscriptions no longer possible" understates it | Invoice | BOTH |
| 8 | Legacy usage-based billing removed *(title-only)* | Billing | SCHEMA (provisional) |
| 9 | InvoiceItem/InvoiceLineItem top-level price fields replaced by `pricing` | Invoice | SCHEMA |
| 10 | Top-level tax properties replaced by `total_taxes`/`taxes` | Invoice, CreditNote | SCHEMA |
| 11 | Multiple (partial) payments on invoices. Removed pointers (`payment_intent`, `charge`, `paid`, `paid_out_of_band`, `application_fee_amount`, `transfer_data`) and the new `payments`/`amount_overpaid`/`confirmation_secret` fields are all schema-visible; the behavioral half is one line, `amount_paid` now counting an out-of-band payment. **Live-verified in RC1-618** | Invoice | BOTH |
| 12 | Reason code for authorizations while Stripe unavailable *(title-only)* | Issuing | SCHEMA |
| 13 | Webhook Accept headers specify JSON for Issuing authorizations *(title-only)* | Issuing webhooks | BEHAVIORAL |
| 14 | `expired` status added for Issuing Authorizations *(title-only)* | Issuing | BOTH |
| 15 | Vault & Forward returns 402 for upstream timeouts *(title-only)* | Vault & Forward | BEHAVIORAL |
| 16 | Manual capture removed for Interac *(title-only)* | Terminal | BOTH |
| 17 | Naver Pay fields immutable after creation *(title-only)* | PaymentMethod | BEHAVIORAL |
| 18 | Partial capture/cancel no longer creates a Refund *(title-only)* | PaymentIntent, Refund | BEHAVIORAL |
| 19 | `total_count` expansion removed; 400 `property_forbidden`. Docs: "New users can't expand `total_count` on earlier Stripe versions" — account-gated for new accounts | All list APIs | BEHAVIORAL (account-gated) |
| 20 | New error codes for required verifications *(title-only)* | Account | BEHAVIORAL |
| 21 | Default Payment Element layout changed *(title-only)* | Payment Element (client-side) | BEHAVIORAL |
| 22 | Person `political_exposure` string -> enum *(title-only)* | Person | SCHEMA |

## M: behavioral breaks in scope (provisional, spike-rescored)

Exercisable from a bare test-mode sandbox, schema diff reports green. The
spike (docs/spike-findings.md) live-verified entries where noted.

| M# | Break | Version | Status |
|----|-------|---------|--------|
| 1 | Automatic payment methods default on PaymentIntent/SetupIntent | 2023-08-16 | **confirmed live** |
| 2 | `capture_method` default `automatic_async` | 2024-04-10 | **confirmed live** |
| 3 | Partial capture/cancel creates no Refund | basil | **confirmed live** |
| 4 | `GET /v1/invoices/upcoming` removed outright (both call shapes 404) | basil | **confirmed live** |
| 5 | Checkout Session defers subscription and invoice to completion (observables: `$.body.subscription`, `$.body.invoice`, read after a failed payment attempt) | basil | **confirmed live**, unexercised by decision (ADR 0003 D2) |
| 6 | Checkout `payment_method_collection` defaults to `if_required` (observables: `$.body.payment_method_collection`, and `$.status` on a zero-total session) | 2023-08-16 | **confirmed live, exercised, caught** |
| 7 | Checkout statement descriptor derives from the business name (observables: `$.body.settings.payments.statement_descriptor`, `$.body.settings.card_payments.statement_descriptor_prefix`) | 2023-10-16 | **confirmed live, exercised, caught** |
| 8 | Invoice `amount_paid` reflects out-of-band payments (observables: `$.body.amount_paid`, `$.body.amount_remaining`) | basil | **confirmed live, exercised, caught** |

**M = 8 (8 confirmed live, 7 exercised and caught, 1 unexercised).**

Every entry in the inventory is now confirmed live. The remaining gap is
reach, not knowledge: M5 has a named observable and no scenario that can
reach it within the replay contract.

RC1-618 Stage 1 read the two title-only M entries' detail pages and probed
them on both versions. Both survived and both narrowed, so M did not move:
M6's break is the `payment_method_collection` default flip rather than the
no-cost order itself, and M8's is the `amount_paid` aggregate rather than
partial-payment support, whose whole removed-and-added-field surface is
schema-visible. Full probe record, including the two Stage 4 assumptions it
retired, in docs/m6-m8-probe.md.

The corpus was then widened to reach both: `scenarios/05-checkout-session-no-cost.json`
and `scenarios/06-invoice-out-of-band-payment.json`, which took the exercised
count from four to six and the corpus from 20 endpoint templates to 27.

**RC1-618 Stage 3 then read and probed M5**, and it survived and narrowed
twice (docs/m5-probe.md). A `mode=subscription` session create is identical
across the pair on every observable, and so is a session driven to a
*successful* completion — both end with an active subscription and a paid
invoice. The break appears only after a *failed* payment attempt: A leaves an
`incomplete` subscription and an `open` invoice behind, basil leaves nothing,
and both sessions still report `status: open` and `payment_status: unpaid`.

**RC1-618 Stage 2 then read and probed M7**, the last entry with an external
blocker, and it survived and narrowed like the three before it
(docs/m7-probe.md). The title says "auto-populated"; what changed is the
derivation source. It is now the inventory's cleanest catch, because in the
name-and-url case **both versions return a plausible non-null descriptor and
disagree only about its content** — a null check passes on both sides, and the
only thing that differs is what a cardholder reads on their statement.

Stage 2 also turned up something larger than M7. `POST /v1/accounts` now 400s
on **both** versions pending an account-level Accounts v1 policy toggle, which
makes it account-gated rather than version-gated — the `total_count` shape from
the Phase 0 spike. **A pinned `Stripe-Version` does not insulate a replay from
a provider policy changed after that version shipped.** Recorded in ADR 0001.

**M5 is the one entry left, and it waits on a tradeoff this project has
already refused**: its observable needs a hosted page driven with a declining
card, and ADR 0003 D2 replays by re-execution, so a scenario reaching it would
put a browser inside `replay` and `pin certify` and make the lab's own A/A
control non-deterministic. It stays reported as *unexercised*, and the test
asserting a break with no declared workflow cannot be reported as caught still
holds for it.

**Phase 3 (RC1-608) scored this inventory mechanically.** All four
live-confirmed breaks are caught by the differ; the four pending entries are
reported as *not exercised* rather than dropped from the denominator, and a
test asserts none of them is ever reported as caught. What the schema-diff
baseline said about each one, from `baseline/schema-diff-index.jsonl`:

| M# | Caught | Schema diff | What the baseline said |
|----|--------|-------------|------------------------|
| M1 | yes (risky) | **green** | `automatic_payment_methods` is not named once on `POST /v1/payment_intents` |
| M2 | yes (breaking) | **named only** | `automatic_async` is now a possible value of `capture_method` — not that it became the default |
| M3 | yes (breaking) | **green** | `amount_refunded` is not named once on `GET /v1/charges` |
| M4 | yes (breaking) | reported | `api-path-removed-without-deprecation` on `GET /v1/invoices/upcoming` |
| M6 | yes (breaking) | **green** | `payment_method_collection` is not named once on `POST /v1/checkout/sessions` |
| M7 | yes (breaking) | **green** | `statement_descriptor` is not named once on `POST /v1/accounts` |
| M8 | yes (breaking) | **green** | neither `amount_paid` nor `amount_remaining` is named once on `GET /v1/invoices/{id}` |

So six of the seven caught breaks had no usable warning in a schema diff that
reported 18,901 breaking changes on the same twenty-nine endpoints. M4 is the
one with a schema-visible half, and is counted as caught by both. Scorecard in
docs/behavioral-diff-report.md; methodology in ADR 0004.

For an unexercised entry the scorecard prints a fourth verdict,
`not-covered`, rather than `green`. The baseline's path scope is derived from
the endpoints the corpus calls, so an endpoint no captured call reaches was
never diffed at all, and reporting it as green credits the schema diff with a
silence it was never asked for. **No row is in that state now.** Widening the
corpus brought Checkout Sessions and `POST /v1/accounts` into scope, which
turned M6's and M7's rows into real **green** verdicts and M5's into
**reported** — the baseline does have `response-required-property-removed` on
the `subscription` field M5 depends on, so the one unexercised break is also
the one with a schema-visible half.

M7's baseline endpoint moved as part of this: it was `GET /v1/account`, the
platform's own account, which is not where the break surfaces and is not a
call the corpus makes. It is now `POST /v1/accounts`.

M6, M7 and M8 are the third, fourth and fifth fully green catches. For M7,
`statement_descriptor` is not named once in the breaking entries for
`POST /v1/accounts`, on a break where **both versions return a plausible
non-null value and disagree only about its content** — a null check passes on
both sides. For the other two: `payment_method_collection`
is not named once in the breaking entries for `POST /v1/checkout/sessions`,
and `amount_paid` and `amount_remaining` are not named once in the 702
`oasdiff` produces for the Invoice object — which does carry `paid` and
`payment_intent` entries. In both cases the schema diff reports the half that
moved a field and says nothing about the half that moved a number.

M3 and M4 were confirmed by the RC1-607 dual replay: partial capture produced
a 3,000-cent Refund on A and none on basil (`count: 1 -> 0`,
`amount_refunded: 3000 -> 0`), and both invoice-preview call shapes went
200 -> 404. M4's description was corrected in the process — see basil #7.

Disqualified by the spike (documented behavioral, but not scoreable here):

- `total_count` expansion removal — account-gated: a fresh sandbox fails on
  both versions, so there is no A/B diff to detect.
- `amount_off` + `forever` coupon restriction — reversed upstream in
  2026-01-28.clover; the live API no longer exhibits the break.

Excluded from M (documented behavioral, not exercisable here): Issuing
shipping-validation default, Issuing `expired` status, Issuing webhook Accept
header, Terminal consent model, Vault & Forward 402, Naver Pay immutability,
Payment Element layout (client-side), error-code families with
nondeterministic triggers (Klarna, director/requirement/verification codes),
PaymentMethod fingerprint platform-scoping (needs a Connect platform context).
