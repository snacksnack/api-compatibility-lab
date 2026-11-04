# API Compatibility Lab

Replays sanitized API traffic across two API versions to find the behavioral
breaks a schema diff misses.

An OpenAPI diff catches removed fields and changed types. It is blind to a
field that became nullable in practice, a changed default, a pagination
boundary shift, a changed sort order, a different error code under the same
HTTP status, silent truncation, and undocumented enum values. Every one of
those breaks real integration code while the schema diff reports green.
Behavior, not schema, is the contract customers actually depend on.

**Status: Phase 0 spike (RC1-605).** Nothing here is a finished tool yet.

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

## Spike

```
cp .env.example .env   # add a test-mode sandbox key
uv run python scripts/spike_dual_call.py
```

Sends the same three requests under both version headers — each chosen to
surface a documented behavioral break — records the paired responses to
`corpus/spike-pair.jsonl`, and prints the top-level differences.
