"""Read a locus out of a response, and decide when two loci are the same place.

A locus is the address a finding and a declared read both speak: `$.status`,
`$.body.count`, `$.body.data[].lines.data[].amount`. Phase 3 produced them by
walking a body; Phase 4 has to go the other way — take a locus a human wrote
down and find what is actually there — which is what makes a declared read
checkable rather than merely asserted.

Two operations, both small and both load-bearing:

- `resolve` expands `[]` over every element of a list and returns what it
  found, distinguishing *absent* from *present and null*. Half this project
  rests on that distinction, so it is in the return type and not in a
  truthiness test.
- `touches` decides whether a finding at one locus is about the same place as
  a read at another. It is a prefix test at segment boundaries in both
  directions, because the two interesting cases point opposite ways: a removed
  subtree at `$.body.lines` covers a declared read of
  `$.body.lines.data[].amount` (finding above read), and a changed element at
  `$.body.data[0].amount` is a change to a declared read of `$.body.data`
  (finding below read).
"""

from __future__ import annotations

import re
from typing import Any

from compatlab.findings import MISSING, normalize

# One locus segment: `.name` or `[7]` or `[]`.
SEGMENT_RE = re.compile(r"\.([A-Za-z0-9_-]+)|\[(\d*)\]")
ROOT = "$"
# Where a locus may start. A read of `$.duration_ms` is refused on purpose:
# the timing axis is benign by rule forever (ADR 0004 D7), so a declared read
# of it could only ever produce an impact the project has promised not to
# claim.
READABLE_ROOTS = ("$.status", "$.body")


class LocusError(ValueError):
    """A locus that is not a locus."""


def parse(locus: str) -> tuple[tuple[str, int | None], ...]:
    """`$.body.data[].amount` -> (('key','body'), ('index',None), ('key','amount')).

    An index segment carries its position, or `None` for the `[]` wildcard.
    """
    if not locus.startswith(ROOT):
        raise LocusError(f"a locus must start with `$`: {locus!r}")
    rest = locus[len(ROOT):]
    out: list[tuple[str, int | None]] = []
    cursor = 0
    while cursor < len(rest):
        match = SEGMENT_RE.match(rest, cursor)
        if match is None:
            raise LocusError(f"cannot parse {locus!r} at offset {cursor + 1}")
        name, index = match.group(1), match.group(2)
        if name is not None:
            out.append(("key", name))
        else:
            out.append(("index", int(index) if index else None))
        cursor = match.end()
    return tuple(out)


def _render(prefix: str, segment: tuple[str, int | None]) -> str:
    kind, value = segment
    return f"{prefix}.{value}" if kind == "key" else f"{prefix}[{value}]"


def resolve(record: dict, locus: str) -> list[tuple[str, Any]]:
    """Every concrete (locus, value) a locus addresses in one canonical record.

    `$.body.data[].amount` over a three-element list returns three entries.
    A locus that addresses nothing returns an empty list — which is the
    answer to "was this field there", and is why the caller gets a list
    rather than a value.
    """
    segments = parse(locus)
    found: list[tuple[str, Any]] = [(ROOT, record)]
    for segment in segments:
        nxt: list[tuple[str, Any]] = []
        for prefix, value in found:
            kind, name = segment
            if kind == "key":
                if isinstance(value, dict) and name in value:
                    nxt.append((_render(prefix, segment), value[name]))
            elif not isinstance(value, list):
                continue
            elif name is None:
                nxt += [(f"{prefix}[{i}]", item) for i, item in enumerate(value)]
            elif -len(value) <= name < len(value):
                nxt.append((_render(prefix, segment), value[name]))
        found = nxt
    return found


def wildcarded(locus: str) -> bool:
    """Does this locus contain a `[]`, addressing every element of a list?"""
    return any(kind == "index" and index is None for kind, index in parse(locus))


def value_at(record: dict, locus: str) -> Any:
    """What a locus reads, for comparing one side against the other.

    A wildcard locus collapses to the list of everything it matched, so the
    two sides stay comparable on one expression even when the list length
    changed. That conflates *the list was empty* with *the list was not there*
    — both read as `[]` — which is deliberate: a client reading
    `$.body.data[].amount` cannot tell those apart either, and the comparison
    this feeds asks what the client's read returned, not what the server
    serialized.

    A locus without a wildcard returns the value or `MISSING`, which does keep
    absent and null apart.
    """
    matches = resolve(record, locus)
    if wildcarded(locus):
        return [value for _, value in matches]
    if not matches:
        return MISSING
    return matches[0][1]


def touches(one: str, other: str) -> bool:
    """Are these two loci about the same place?

    True when the normalized loci are equal or one is a prefix of the other at
    a segment boundary. Both directions matter: a finding above a read (a
    removed subtree) and a finding below one (a changed element of a list the
    client stores whole) are each a hit, and only one of the two comparisons
    catches each.
    """
    left, right = normalize(one), normalize(other)
    if left == right:
        return True
    shorter, longer = sorted((left, right), key=len)
    return longer.startswith(shorter) and longer[len(shorter)] in ".["


def readable(locus: str) -> bool:
    """May a declared read name this locus? See `READABLE_ROOTS`."""
    return any(locus == root or locus.startswith(root + ".")
               or locus.startswith(root + "[") for root in READABLE_ROOTS)
