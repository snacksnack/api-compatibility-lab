# M7, read and probed (RC1-618 Stage 2)

Date: 2026-11-06. Same test-mode sandbox as the Phase 0 spike, both pinned
versions per request.

M7 (statement descriptor and prefix auto-populated, 2023-10-16) was the last
entry with an external blocker. Stage 2's job was to probe it live once the
blocker cleared, then capture it if it survived. **It survived, it narrowed,
and it is now the inventory's cleanest catch.**

## The blocker was not the one the ticket named

The ticket and three handoffs said M7 needed Connect enabled on the sandbox.
Connect was already enabled: `GET /v1/accounts` returned 200 on both versions
with a connected account already present. The actual blocker was newer than
the ticket. `POST /v1/accounts` now 400s on **both** versions:

> Stripe no longer recommends Accounts v1 for new Connect integrations. [...]
> If your integration requires v1 account creation for a supported
> compatibility scenario, enable Accounts v1 support in the Dashboard.

**This is worth more than M7 is.** The 400 is identical on `2022-11-15` and on
basil, which makes it an *account-policy* gate rather than a version gate —
the same shape that disqualified `total_count` in the Phase 0 spike. A pinned
`Stripe-Version` does not insulate a replay from a policy the provider changed
after that version shipped. The lab's whole premise is that pinning two
versions isolates the variable; this is a live counterexample, and it arrived
by accident. Recorded in ADR 0001.

Enabling Accounts v1 support in the dashboard restored creation on both sides,
which is what made the rest of this stage possible.

## The rule changed, not the defaulting

The changelog entry is titled *"Statement descriptor and prefix
auto-populated."* Read as written, it predicts null on A and populated on B.
That is true only in one of the four cases, and the real behavior is more
interesting. One account created per version per case, same request body:

| `business_profile` sent | A `2022-11-15` descriptor | B `basil` descriptor | B prefix |
|---|---|---|---|
| neither name nor url | `null` | `null` | `null` |
| name only | `null` | `NORTHWIND SUPPLY CO` | — |
| url only | `WWW.NORTHWINDSUPPLY.COM` | `NORTHWINDSUPPLY.COM` | `NORTHWINDS` |
| name + url | `WWW.NORTHWINDSUPPLY.COM` | `NORTHWIND SUPPLY CO` | `NORTHWIND` |

- **A** derives the descriptor from `business_profile[url]`, and returns null
  when there is no url.
- **basil** derives it from `business_profile[name]`, falling back to the url
  with the `WWW.` prefix stripped.

So what changed is the **derivation source**, not the fact of population.

**Kept, narrowed, and promoted.** Two observables:

1. **`$.body.settings.payments.statement_descriptor`** — a value change on a
   field present and documented on both sides.
2. **`$.body.settings.card_payments.statement_descriptor_prefix`** — null on
   A, populated on basil. The prefix half of the title does reproduce, but at
   the `card_payments` path rather than the `payments` path the title implies.

## Why this is the best break in the inventory

In the name+url case **both versions return a plausible, non-null descriptor
and disagree only about its content.** A null check passes on both sides. A
schema diff sees two strings. A status-code smoke test sees two 200s. The only
thing that differs is what a cardholder reads on their statement when they
try to remember what they bought — which is exactly the kind of difference
that gets discovered by a support ticket rather than by a test.

M6 is a changed default on a field nobody set. M8 is an aggregate that
disagrees with its own line items. M7 is both versions confidently answering
the same question differently, and it is the one a reader feels immediately.

## The fourth entry running where the title was not the break

M6 was the default flip, not the free order. M8 was the aggregate, not
partial-payment support. M5 was the failed attempt, not the completed one. M7
is the derivation source, not the auto-population. Four for four. **The
inventory's titles are leads, not findings**, and the probe-before-you-capture
step has now paid for itself four times.

## The observable survives sanitization

`business_profile[name]` is redacted at write time, so the corpus carries
`redacted-0de8e8b1` and the replay creates both accounts under that surrogate.
A derives from the url and still reports `WWW.NORTHWINDSUPPLY.COM`; basil
derives from the redacted name and reports `REDACTED-0DE8E8B1`. The *values*
are surrogates and the *difference* is intact, which is ADR 0003 D2's central
claim — a sanitized corpus is still a replayable one — demonstrating itself on
the one break whose observable is derived from a redacted input.

The url-only step needs no surrogate to make the point: `WWW.NORTHWINDSUPPLY.COM`
against `NORTHWINDSUPPLY.COM` is a real value difference with no redaction in it.

## Scored

Exercised by `scenarios/07-connected-account-onboarding.json`, mapped by
`workflows/08-connected-account-onboarding.json`, which comes out **CORRUPTED**:
the merchant approves one descriptor on the onboarding confirmation screen and
their buyers see a different one, with no error anywhere.

The schema diff is **fully green** on it: `statement_descriptor` is not named
once in the breaking entries for `POST /v1/accounts`, while the same baseline
reports 18,901 breaking changes on the twenty-nine endpoints this corpus calls.
