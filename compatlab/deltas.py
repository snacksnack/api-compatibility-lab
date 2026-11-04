"""Walk two canonical bodies and emit typed structural deltas.

This is deliberately separate from classification. The walk answers "what is
structurally different", with no opinion about whether it matters; the rule
table in `compatlab.classify` answers "what does that mean to a client". Two
things kept wanting to blur together while this was built, and both are bugs:
a walker that quietly suppresses differences it thinks are unimportant, and a
classifier that re-derives structure from a formatted diff string.

The walk also decides where to *stop*, which is the difference between a
report and a wall. Phase 2's `diff_paths` enumerated every leaf; on the one
pair where an endpoint was removed it produced 85 lines about the fields of an
error body, none of which was the finding. So:

- a list whose length changed yields **one** delta, and the elements are not
  compared — a shifted list makes every positional comparison meaningless
  anyway;
- a list reordered with the same members yields **one** delta;
- a subtree present on only one side yields **one** delta at its root, not one
  per leaf inside it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from compatlab.findings import MISSING

ONLY_IN_A = "only_in_a"
ONLY_IN_B = "only_in_b"
VALUE = "value"
LENGTH = "length"
ORDER = "order"


@dataclass(frozen=True)
class Delta:
    """One structural difference, at one locus."""

    kind: str
    locus: str
    a: Any = MISSING
    b: Any = MISSING

    @property
    def a_present(self) -> bool:
        return self.a is not MISSING

    @property
    def b_present(self) -> bool:
        return self.b is not MISSING


def _fingerprint(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=repr)


def deltas(a: Any, b: Any, locus: str = "") -> list[Delta]:
    """Every structural difference between two canonical structures."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[Delta] = []
        for key in sorted(set(a) | set(b)):
            child = f"{locus}.{key}"
            if key not in b:
                out.append(Delta(ONLY_IN_A, child, a=a[key]))
            elif key not in a:
                out.append(Delta(ONLY_IN_B, child, b=b[key]))
            else:
                out += deltas(a[key], b[key], child)
        return out
    if isinstance(a, list) and isinstance(b, list):
        return _list_deltas(a, b, locus)
    if _fingerprint(a) != _fingerprint(b):
        return [Delta(VALUE, locus, a=a, b=b)]
    return []


def _list_deltas(a: list, b: list, locus: str) -> list[Delta]:
    if len(a) != len(b):
        return [Delta(LENGTH, locus, a=a, b=b)]
    if a == b:
        return []
    if sorted(map(_fingerprint, a)) == sorted(map(_fingerprint, b)):
        return [Delta(ORDER, locus, a=a, b=b)]
    return [
        delta
        for index, (left, right) in enumerate(zip(a, b, strict=True))
        for delta in deltas(left, right, f"{locus}[{index}]")
    ]


def has_payload(value: Any) -> bool:
    """Does this value carry anything a client could read?

    An added field arriving as `null`, `{}`, `[]`, or an object whose every
    leaf is null is additive noise; the same field arriving with a value in it
    is something a strict parser can choke on and a careless one can
    misinterpret. The distinction decides a severity, so it is a named
    function with its own tests rather than an inline truthiness check.
    """
    if value is MISSING or value is None:
        return False
    if isinstance(value, dict):
        return any(has_payload(item) for item in value.values())
    if isinstance(value, list):
        return any(has_payload(item) for item in value)
    if isinstance(value, str):
        return value != ""
    return True


def leaf_values(value: Any) -> int:
    """How many leaves a subtree holds, for the `subsumed` count."""
    if isinstance(value, dict):
        return sum(leaf_values(item) for item in value.values()) or 1
    if isinstance(value, list):
        return sum(leaf_values(item) for item in value) or 1
    return 1
