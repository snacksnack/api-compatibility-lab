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
before final scoring (open Phase 0 work).

## 2023-08-16

| # | Change | Objects | Class |
|---|--------|---------|-------|
| 1 | Automatic payment methods enabled by default | PaymentIntent, SetupIntent | BEHAVIORAL |
| 2 | One-time payments in Checkout support no-cost orders *(title-only)* | Checkout Session | BEHAVIORAL |
| 3 | Platform-scoped rendering for select PaymentMethod fingerprints | PaymentMethod | BEHAVIORAL |
| 4 | Specific error codes for failed Klarna payments | PaymentIntent, Checkout | BOTH |
| 5 | New director verification error codes | Account | BOTH |

## 2023-10-16

| # | Change | Objects | Class |
|---|--------|---------|-------|
| 1 | New account requirement error codes | Account | BOTH |
| 2 | Statement descriptor and prefix auto-populated | Account | BEHAVIORAL |

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
| 4 | Checkout Sessions: subscriptions created only after completed payment; no invoice until `complete`; sessions editable after failed attempt. No schema change | Checkout Session, Subscription, Invoice | BEHAVIORAL |
| 5 | `amount_off` coupons with `duration: forever` rejected at creation and application (`percent_off` unaffected). Reversed upstream in 2026-01-28.clover; live API accepts again | Coupon | BEHAVIORAL (reversed) |
| 6 | Singular `coupon`/`promotion_code` params removed for stackable `discounts` *(title-only)* | Billing | SCHEMA |
| 7 | `GET /v1/invoices/upcoming` removed; preview now requires subscription context (previews across all subscriptions no longer possible) | Invoice | BOTH |
| 8 | Legacy usage-based billing removed *(title-only)* | Billing | SCHEMA (provisional) |
| 9 | InvoiceItem/InvoiceLineItem top-level price fields replaced by `pricing` | Invoice | SCHEMA |
| 10 | Top-level tax properties replaced by `total_taxes`/`taxes` | Invoice, CreditNote | SCHEMA |
| 11 | Multiple (partial) payments on invoices *(title-only)* | Invoice | BOTH |
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
| 3 | Partial capture/cancel creates no Refund | basil | pending *(title-only)* |
| 4 | Invoice preview requires subscription context (behavioral half of basil #7) | basil | pending |
| 5 | Checkout Session create/complete semantics (observable: no invoice until `complete`) | basil | pending (full flow needs a completed session) |
| 6 | Checkout no-cost orders | 2023-08-16 | pending *(title-only)* |
| 7 | Statement descriptor auto-population | 2023-10-16 | pending (needs Connect test account) |
| 8 | Partial invoice payment semantics | basil | pending *(title-only)* |

**Provisional M = 8 (2 confirmed live, 6 pending exercise).**

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
