"""Shallow response diffing, extracted from the RC1-605 spike.

The real behavioral differ (RC1-608) replaces this; the spike and its tests
use it to compare paired A/B response bodies at the top level.
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
