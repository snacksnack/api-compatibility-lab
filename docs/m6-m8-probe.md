# M6 and M8, read and probed (RC1-618 Stage 1)

Date: 2026-11-05. Same test-mode sandbox as the Phase 0 spike, both pinned
versions per request, via `uv run python scripts/probe_m6_m8.py`.

M6 (Checkout no-cost orders) and M8 (multiple/partial invoice payments) were
inventoried from changelog *titles* in Phase 0 and had sat in M as "pending
*(title-only)*" ever since. Stage 1's job was to read their detail pages and
probe them live, with three honest outcomes available per entry: scoreable
with a named observable, narrowed to a smaller behavioral claim, or
disqualified with a reason. **Both survived, both narrowed, M stays 8.**

The probe prints named observables only, redacted through `STRIPE_POLICY`, and
writes nothing to `corpus/`. A probe is not capture: deciding what is worth
capturing is this stage's output, and capturing it is the next stage's work.

## M6: the default flip, not the free order

The [detail page](https://docs.stripe.com/changelog/2023-08-16/no-cost-orders-checkout-session)
is two sentences, and the breaking half is in a subordinate clause: no-cost
orders are enabled for one-time payments in Checkout Sessions, *"changing the
value of `payment_method_collection` from `always` to `if_required`."* That is
a changed server-side default on a field that exists in both versions — the
same shape as M1 and M2, and the project's cleanest kind of catch.

`POST /v1/checkout/sessions`, `mode=payment`, one `price_data` line item, no
`payment_method_collection` sent:

| Observable | A `2022-11-15` | B `2025-03-31.basil` |
|---|---|---|
| `payment_method_collection` (1099¢ item) | `always` | `if_required` |
| HTTP status (0¢ item) | **400** | **200** |
| `error.message` (0¢ item) | "The Checkout Session's total amount due cannot be zero in `payment` mode." | *absent* |
| `amount_total` (0¢ item) | *absent* | `0` |
| `payment_intent` (0¢ item) | *absent* | `null` |

Two observables, both readable on create:

1. **`$.body.payment_method_collection`** — `always` -> `if_required`, a value
   change on a field present and documented on both sides.
2. **`$.status`** — a zero-total payment-mode session is rejected on A and
   created on B, which the differ already classifies as
   `status-class-changed` (breaking).

**Kept, narrowed.** The summary moves from "Checkout supports no-cost orders"
to the default flip, because the no-cost order is the *feature* and the default
flip is the *break*. The consequence the guide warns about — a completed free
session has no PaymentIntent, so a fulfillment integration listening for
PaymentIntent events silently never fulfills — still needs a completed
session, and that blocker belongs to M5. M6 does not inherit it: the 400 -> 200
pair and the default flip are both visible at create, and B already shows
`payment_intent: null` on the created free session.

## M8: the aggregate disagrees, not the ledger

The [detail page](https://docs.stripe.com/changelog/basil/2025-03-31/add-support-for-multiple-partial-payments-on-invoices)
is mostly schema. Its "Why is this a breaking change?" list is five bullets of
removed and added fields — `payment_intent`, `charge`, `paid`,
`paid_out_of_band`, `application_fee_amount` and `transfer_data` off the
Invoice; `invoice` off PaymentIntent and Charge; `payments`, `amount_overpaid`
and `confirmation_secret` added; CreditNote `refund` -> `refunds` — every one
of which an OpenAPI diff reports. One bullet is behavioral: *"The `amount_paid`
field on the `Invoice` object now reflects out of band payments."*

Create customer -> create invoice -> attach a 2000¢ item -> finalize ->
`POST /v1/invoices/{id}/pay` with `paid_out_of_band=true` -> read it back:

| Observable | A `2022-11-15` | B `2025-03-31.basil` |
|---|---|---|
| `amount_due` after finalize | `2000` | `2000` |
| `/pay` status | 200 | 200 |
| **`amount_paid`** | **`0`** | **`2000`** |
| **`amount_remaining`** | **`2000`** | **`0`** |
| `status` | `paid` | `paid` |
| `paid` / `paid_out_of_band` | `true` / `true` | *absent* / *absent* |
| `payment_intent` / `charge` | `null` / `null` | *absent* / *absent* |
| `payments.data[0].amount_paid` (expanded) | `2000` | `2000` |
| `amount_overpaid` | `0` | `0` |

The last two rows are what make this worth scoring. **The underlying ledger
agrees across versions** — both sides record an `invoice_payment` of 2000¢,
and the expanded `payments` array is served on an A-pinned request too, so the
"new" InvoicePayment surface is not version-gated at all. What disagrees is
the aggregate an integration actually reads: `invoice.amount_paid` is `0` on A
and `2000` on B for the identical payment, and `amount_remaining` inverts with
it. A reconciliation job that sums `amount_paid` to decide what was collected,
or treats `amount_remaining > 0` as still owed, flips verdict on every
out-of-band paid invoice while every field keeps its name and type.

The schema diff is green on exactly those two fields. Over the 702 breaking
entries `oasdiff` produces for `GET /v1/invoices`, `amount_paid` and
`amount_remaining` are not named once — while `paid`
(`response-required-property-removed`) and `payment_intent` (seven rules) are
both reported. The
baseline names the schema half of this entry and says nothing about the half
that changes a number.

**Kept, narrowed, and one blocker retired.** The summary moves from "partial
invoice payment semantics" to the `amount_paid` claim. The groomed Stage 4 —
"M8 billing-boundary crossing, needs test clocks, touches the replay engine"
— was built on the title alone and does not survive the detail page: nothing
in this entry involves a billing boundary, and the observable needs six
synchronous REST calls and no clock. ADR 0003 D8's deferral of test clocks
stands, and loses the one piece of coverage work that was cited as its
trigger.

## A near-miss worth recording

The first M8 run showed `amount_due: 0`, `status: paid`, `amount_paid: 0` on
**both** versions, with no diff anywhere — which reads exactly like a
disqualification. It was a probe bug: a pending invoice item is not pulled
into a draft invoice on either version, so the invoice was empty, and an empty
finalized invoice goes straight to `paid` with nothing owed. Creating the
invoice first and attaching the item to it by id produced the 0 -> 2000 pair on
the next run.

A corpus-widening story is the one place where a broken scenario and a
disqualified break look identical from the outside, and the broken scenario is
the cheaper, more flattering answer: it shrinks the work. The guard is the one
this project already uses on its own numbers — require a positive control. An
unexercisable break and an unexercised one have to be told apart by something
that went right, here `finalize.amount_due == 2000` on both sides before the
payment, not by the absence of a diff.

## What Stage 1 changed

- **M stays 8.** M6 and M8 move from "pending *(title-only)*" to
  live-confirmed with named loci. Nothing moved into or out of the
  denominator, and neither is *exercised*: `workflows=()` on both, so the
  score still reports 4 of 4 exercised, 8 in the inventory. A test asserts
  that a confirmed break with no workflow cannot be caught, so the loci added
  here cannot quietly become a numerator.
- **`not-covered` is now a fourth baseline verdict.** The published scorecard
  printed `green` for M5, M6 and M7 — crediting the schema diff with silence
  on `POST /v1/checkout/sessions` and `GET /v1/account`, two endpoints the
  baseline was never generated over, because its path scope is built from the
  endpoints the corpus calls. Absence of entries was being read as evidence.
  The four caught breaks are all on covered endpoints, so the headline is
  unchanged.
- **The cascade is now priced in endpoints, not sessions.** Capturing these
  two takes the corpus from 20 endpoint templates to 26 —
  `POST /v1/checkout/sessions` for M6, and `POST /v1/invoices`,
  `POST /v1/invoiceitems`, `POST /v1/invoices/{id}/finalize`,
  `POST /v1/invoices/{id}/pay`, `GET /v1/invoices/{id}` for M8. The baseline's
  path regex is derived from that set, so it has to be regenerated, and the
  published "12,313 breaking changes on the same endpoints" moves. That figure
  is a measurement of the scope, not a constant; when it changes, it changes
  because the corpus got wider, and the report says so because it is generated.

## What it does not promise

Two entries went from title-only to live-confirmed. Neither is caught, and
`caught 4 of 4 exercised (M=8)` is still the published number — raising the
exercised count is the capture-and-cascade work this stage was meant to scope,
not do. M5 (hosted-page completion) and M7 (Connect enablement) keep their
external blockers and were not probed.
