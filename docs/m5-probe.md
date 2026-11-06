# M5, read and probed (RC1-618 Stage 3)

Date: 2026-11-06. Same test-mode sandbox as the Phase 0 spike, both pinned
versions per request, via `uv run python scripts/probe_m5.py` and
`uv run python scripts/probe_m5_hosted.py`.

M5 is basil's Checkout Session entry, and Stage 3 existed to answer one
question the ticket framed as the stage's real decision: scope to the half of
the break that needs no completed session, or complete one with browser
automation. The Stage 3 handoff argued the first option was probably bigger
than it looked, because two of the entry's three clauses read like they should
be visible from a `mode=subscription` create plus a list.

**Neither framing survived.** The cheap option exercises nothing, and so does
the expensive one as it was imagined. The break is real, it is now confirmed
live, and it sits in a third place neither option named.

## What the detail page actually says

The [detail page](https://docs.stripe.com/changelog/basil/2025-03-31/checkout-legacy-subscription-upgrade)
is titled *"Checkout Sessions have lower latency and new update semantics"* —
not the subscription-timing phrasing the inventory carried. Its Impact list is
three bullets:

- Subscriptions are now created after the user completes payment.
- Failed payment attempts no longer result in an incomplete subscription with
  a finalized invoice.
- An invoice isn't present until the Checkout Session is in the `complete`
  state.

Every one is phrased around the customer's payment *attempt*, and the What's
new section puts the latency win *"including when your customer confirms the
Session."* Read closely, nothing there promises a difference at session
create. That is a question for the API rather than for a close reading, so
both readings were probed.

## Probe 1: the create-only option exercises nothing

`POST /v1/prices` (recurring) -> `POST /v1/checkout/sessions` `mode=subscription`
-> read it back, expand `subscription` and `invoice`, list the customer's
subscriptions and invoices. Repeated with a trial-mode session
(`subscription_data[trial_period_days]`, `payment_method_collection=if_required`)
on the theory that if any subscription-mode shape creates its subscription
eagerly on A, that is the one.

| Observable | A `2022-11-15` | B `2025-03-31.basil` |
|---|---|---|
| `session.status` | `open` | `open` |
| `session.subscription` | `null` | `null` |
| `session.invoice` | `null` | `null` |
| subscriptions for the customer | 0 | 0 |
| invoices for the customer | 0 | 0 |
| trial session `subscription` | `null` | `null` |

Every status 200 on both sides, no observable differs. **The cheap option is
not partial, it is empty.** A scenario scoped to session create would have
produced no finding, and — this is the part worth keeping — it would have
looked exactly like a disqualified break while actually being a scenario that
never reached the behavior. That is the Stage 1 lesson arriving from the
other direction: there, a broken scenario looked like a disqualification; here,
a correctly-built scenario aimed at the wrong moment would have too.

One incidental result, recorded because it contradicts a reasonable guess:
`POST /v1/checkout/sessions/{id}` returns 200 on **both** versions, so the
"sessions editable after a failed attempt" clause is not a new endpoint.

## Probe 2: a successful completion exercises nothing either

This is the finding that reframes the stage. A hosted test-mode page *can* be
driven to completion — the Stage 3 handoff asked that first, and the answer is
yes, with the published test card, and the page honors the version the session
was created under. So both sessions were driven to a successful subscribe and
read back:

| Observable | A `2022-11-15` | B `2025-03-31.basil` |
|---|---|---|
| `session.status` | `complete` | `complete` |
| `session.payment_status` | `paid` | `paid` |
| subscriptions / `status` | 1 / `active` | 1 / `active` |
| invoices / `status` | 1 / `paid` | 1 / `paid` |
| `invoice.amount_paid` | `1500` | `1500` |
| `invoice.billing_reason` | `subscription_create` | `subscription_create` |

Identical, down to the billing reason. The only differences are object ids,
which canonicalization surrogates away by design.

So the expensive option, built the obvious way, catches nothing. A browser in
the replay path driving the happy-path card would have bought a scenario that
proves the two versions agree. The entry's headline clause — *subscriptions
are created only after completed payment* — describes a change in **when**,
and once the payment has completed, both versions have arrived at the same
place.

## Probe 3: the break lives in the failed attempt

Same two sessions, driven with the published always-declines card. Both pages
reported the decline and stayed open, which is itself the third clause working.

| Observable | A `2022-11-15` | B `2025-03-31.basil` |
|---|---|---|
| `session.status` | `open` | `open` |
| `session.payment_status` | `unpaid` | `unpaid` |
| **`session.subscription`** | **an id** | **`null`** |
| **`session.invoice`** | **an id** | **`null`** |
| subscriptions for the customer | **1**, `status: incomplete` | **0** |
| invoices for the customer | **1**, `status: open`, `amount_paid: 0` | **0** |

**Confirmed live, and narrowed twice.** The named observables are
`$.body.subscription` and `$.body.invoice` on the Checkout Session, read after
a failed payment attempt. Both sessions report the same `status` and
`payment_status`; the integration-visible difference is two objects that exist
on one version and not the other.

It is a good break on the merits — an integration that reconciles open
invoices or sweeps `incomplete` subscriptions sees phantom rows on A that
basil simply never creates — and it is the clearest "same status, different
world" shape in the inventory.

## Why it stays unexercised, and why that is a decision

The observable needs a hosted page driven with a declining card. Capture could
do that once. Replay cannot: ADR 0003 D2 is *re-execute, do not re-send*, so
each side re-runs the workflow against its own version, and `pin certify` runs
the pinned suite live on both versions on top of that. A scenario reaching M5
therefore puts a browser inside `replay` and inside `certify`, where the first
flaky hosted page makes the lab's own A/A control non-deterministic. That
control is the project's load-bearing claim, and trading it for one inventory
row is a bad trade.

The Stage 3 handoff ranked an out-of-band replay hook above driving the
browser inside replay. **The probe collapses that preference**: the only
out-of-band step a hook could perform *is* driving a hosted page, so the hook
buys containment — one declared step rather than the whole engine — and not
determinism. It is the same dependency with a better name. Worth having if M5
is ever built; not a reason to call it a different option.

So M5 moves from *pending, needs a completed session* to **confirmed live,
unexercised by decision**, with the reason written down and a named observable
recorded for whoever revisits it. M stays 8, exercised stays 6, and the
published headline does not move — which is the outcome the ticket asked for:
an exercised denominator that is real, whatever it turns out to be.

## What this cost and what it bought

No published number moved. What moved is that the last entry anyone could have
called "probably easy" has been read, probed three ways, and priced. Two of
the eight inventory entries remain unexercised and they are now unexercised
for two different kinds of reason: M7 waits on a Connect account somebody can
enable, and M5 waits on a tradeoff this project has already refused.
