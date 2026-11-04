"""Shallow response diffing, extracted from the RC1-605 spike.

Superseded. The real behavioral differ is `compatlab.differ` plus
`compatlab.deltas` and `compatlab.classify` (RC1-608): typed deltas, a rule
table, severities, and loci that reach past the top level. This stays because
`scripts/spike_dual_call.py` is the Phase 0 artifact and still runs — it
verifies version pinning against a fresh sandbox, which is worth being able
to re-run on its own — and nothing in the pipeline imports it.
"""

from __future__ import annotations

import json

# Expected to differ between any two calls; excluded from the value diff.
NOISE_KEYS = {"id", "created", "client_secret", "livemode"}


def shallow_diff(a: dict, b: dict) -> list[str]:
    lines = []
    for key in sorted(set(a) | set(b)):
        if key in NOISE_KEYS:
            continue
        if key not in a:
            lines.append(f"  only in B: {key}")
        elif key not in b:
            lines.append(f"  only in A: {key}")
        elif a[key] != b[key]:
            lines.append(f"  value differs: {key}: "
                         f"{json.dumps(a[key])[:80]} -> {json.dumps(b[key])[:80]}")
    return lines
