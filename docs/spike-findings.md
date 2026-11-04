# Spike findings (RC1-605)

Date: 2026-11-04. Fresh test-mode sandbox (created same day), three request
shapes sent under both pinned versions via `scripts/spike_dual_call.py`;
paired responses in `corpus/spike-pair.jsonl`.

## 1. Per-request version pinning works, including a 3-year-old version

A sandbox created in 2026 served both `Stripe-Version: 2022-11-15` and
`2025-03-31.basil`, confirmed by the `stripe-version` response header on every
call. The ADR 0001 D1 risk is retired; no fallback pair needed.

## 2. Two documented behavioral breaks observed live (M1, M2)

`POST /v1/payment_intents` with only `amount` + `currency`:

- `automatic_payment_methods`: `null` on A -> `{enabled: true, ...}` on B,
  with `payment_method_types` going `["card"]` -> `["card", "klarna", "link",
  "cashapp", "amazon_pay"]` (2023-08-16 change).
- `capture_method`: `"automatic"` -> `"automatic_async"` (2024-04-10 change).

Bonus diffs the same call surfaced: the `invoice` field exists only on A
(schema-visible basil removal) and `payment_method_options` gained keys.

## 3. `total_count` removal is account-gated, not version-gated

`expand[]=total_count` returned 400 on BOTH versions. The A-side error adds
"Hint: The feature you are trying to use is deprecated." The changelog detail
page confirms: "New users can't expand `total_count` on earlier Stripe
versions." A fresh sandbox therefore cannot exercise this break — both sides
fail identically, so there is no A/B diff to detect. Moved out of M.

Two residuals worth keeping:

- The error *bodies* differ between versions (hint text, extra fields), which
  the differ will flag — a real behavioral diff, but not the documented break.
- This establishes a break taxonomy the lab must carry: **version-gated**
  (header-exercisable), **account-gated** (bound to account creation epoch),
  and **reversed** (see finding 4).

## 4. The coupon restriction was reversed upstream

The basil break is specifically `amount_off` + `duration: forever` (creation
and application; `percent_off` was never affected — the first spike run used
`percent_off` and proved only that). Stripe reversed the deprecation in
`2026-01-28.clover`, and the live API now accepts `amount_off` + `forever`
even on basil-pinned requests (200/200, no diff). The documented break no
longer exists on the live API and cannot be scored. Moved out of M.

## 5. Consequences for the build

- **Ground truth must be live-verified.** The changelog alone overstates M:
  of the 10 provisional entries, live testing has already confirmed 2 and
  disqualified 2 (one account-gated, one reversed). Scoring N against a
  changelog-only M would be dishonest in both directions.
- **M is now 8 provisional (2 live-confirmed, 6 pending exercise).** See
  docs/ground-truth.md.
- **The differ must compare error bodies, not just status codes** — the
  total_count case produced same-status, different-body pairs.
