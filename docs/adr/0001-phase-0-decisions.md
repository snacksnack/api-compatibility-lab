# ADR 0001: Phase 0 decisions (RC1-605)

Status: accepted (sandbox verification pending, see D1 risk)
Date: 2026-11-04

## Context

RC1-603 (API Compatibility Lab) replays sanitized API traffic against two API
versions to find the behavioral breaks a schema diff misses. The epic locks two
scope decisions: Stripe's dated API versions are the ground-truth anchor, and
affected-workflow mapping is required scope. Phase 0 fixes everything else:
the version pair, the ground-truth inventory (M in the caught-N-of-M headline),
the schema-diff baseline, the stack, and the corpus format.

## D1. Version pair: A = 2022-11-15, B = 2025-03-31.basil

Both are real Stripe dated versions, pinned per request via the
`Stripe-Version` header against a single sandbox.

The span (A, B] covers versions 2023-08-16, 2023-10-16, 2024-04-10,
2024-06-20, 2024-09-30.acacia (plus additive monthly acacia releases), and
2025-03-31.basil. A version's documented changes land when upgrading TO it, so
A must predate 2023-08-16: that version and 2024-04-10 carry the two
cheapest-to-exercise behavioral breaks in the whole changelog, both changed
defaults on `POST /v1/payment_intents` (automatic payment methods enabled by
default; `capture_method` defaulting to `automatic_async`). B = basil carries
the richest single-release behavioral set (~9 purely behavioral breaking
changes plus 4 with a behavioral component).

Alternatives considered:

- A = 2024-09-30.acacia, B = basil: cleanest (one major release's changelog as
  ground truth) but roughly halves M and loses both PaymentIntent defaults.
  This is the fallback pair.
- A = 2022-11-15, B = 2024-06-20: loses basil, the richest release. Rejected.

Risk and required verification: a fresh sandbox must accept
`Stripe-Version: 2022-11-15` per request. **Verified 2026-11-04** by
`scripts/spike_dual_call.py`: a sandbox created the same day served both
versions, confirmed via the `stripe-version` response header. The acacia ->
basil fallback is retired. The spike surfaced a subtler risk instead: some
documented breaks are account-gated or were reversed upstream, so ground
truth must be live-verified per break (docs/spike-findings.md).

## D2. Ground truth and M

`docs/ground-truth.md` enumerates every documented change in the span with a
SCHEMA-VISIBLE / BEHAVIORAL / BOTH classification and an exercisability call.
M counts documented behavioral breaks exercisable from a bare test-mode
sandbox: Issuing, Terminal, Vault & Forward, and client-side (Payment Element)
changes are excluded and listed as such, so the denominator is honest.
Provisional M = 8 after spike rescoring: 2 confirmed live, 6 pending
exercise; 2 former entries disqualified (one account-gated, one reversed
upstream — see docs/spike-findings.md). Open Phase 0 work: remaining
title-only entries need their detail pages read before scoring.

## D3. Schema-diff baseline: oasdiff over pinned stripe/openapi snapshots

The baseline the headline is scored against is `oasdiff` (`breaking` and
`changelog` modes) run over Stripe's own published OpenAPI spec
(`openapi/spec3.json` in github.com/stripe/openapi) at pinned commits:

- Version A: `stripe/openapi@c3ae0d4c07` (2022-11-16, the snapshot current at
  2022-11-15)
- Version B: `stripe/openapi@31b29ff897` (2025-04-02, the first post-basil
  snapshot)

Specs are fetched by SHA at build time, not vendored (~7 MB each); the fetch
validates the spec's declared version. Pinning SHAs makes "the schema diff
reported green on these breaks" reproducible by anyone, not asserted.

## D4. Stack: Python 3.12+, uv, httpx, pytest

Raw REST via httpx rather than stripe-python: per-request version pinning
stays explicit in the wire format, and capture/replay operate on raw HTTP
anyway. An SDK would reshape responses and hide exactly the transport-level
details (error bodies, pagination envelopes, header semantics) the differ
exists to compare.

## D5. Corpus format: JSONL

One interaction per line:
`{id, seq, method, path, query, request_body, response: {status, headers,
body}, stripe_version, captured_at}`. Response headers are a whitelist
(`request-id`, `stripe-version`); the Authorization header is never written
anywhere. The full redaction component is Phase 1 (RC1-606) and is built as a
standalone library because RC1-594 consumes it too.

## D6. Repo bootstrap and branching

Repo `api-compatibility-lab`, README-only initial commit on main (the
esp-migration-agent precedent), all work on `rc1-NNN-slug` story branches via
PRs. GitHub repo public, matching esp-migration-agent.
