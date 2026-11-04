"""The rule table: a structural delta in, a severity and a reason out.

Every finding the lab reports names the rule that produced it. That is not
bookkeeping — it is the only defense against the obvious objection to a tool
like this, which is that "breaking" means whatever the author needed it to
mean that afternoon. A reader who disagrees with a classification can point at
a rule, and the rule is one sentence long.

Precedence is the order of `RULES` and the order of the checks in
`classify`, and it matters in one place in particular: a *changed value* is
decided before a *new enum member*. `capture_method` going `automatic` ->
`automatic_async` is both, and reporting it as "the set of possible values
grew" (risky) rather than "the value you receive changed" (breaking) would
turn the project's own headline finding into a footnote. The enum axis exists
to say *which kind* of changed value it is, not to soften it.

The severity definitions live in `compatlab.findings`. Nothing here is allowed
to invent a fourth one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from compatlab.deltas import (
    LENGTH,
    ONLY_IN_A,
    ONLY_IN_B,
    ORDER,
    VALUE,
    Delta,
    has_payload,
)
from compatlab.findings import BENIGN, BREAKING, RISKY, leaf, normalize, short

# A value that reads as a member of a closed set rather than as free text or
# an identifier: lowercase, underscore-joined, no spaces. Stripe's enums all
# look like this (`automatic_async`, `requires_capture`, `charge_automatically`).
ENUM_VALUE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

# Keys that describe the page rather than the data on it. A change here moves
# the boundary a client pages against, which is the pagination axis.
PAGINATION_KEYS = ("has_more", "total_count", "next_page")
# The relative timing threshold below which a shift is not even reported.
TIMING_TOLERANCE = 0.5


@dataclass(frozen=True)
class Rule:
    """One classification rule, as it appears in the report's rule table."""

    id: str
    axis: str
    severity: str
    summary: str


RULES: tuple[Rule, ...] = (
    Rule("step-missing", "availability", BREAKING,
         "The step ran on one version and could not be run on the other."),
    Rule("status-class-changed", "status", BREAKING,
         "The response moved between success and failure."),
    Rule("status-changed", "status", RISKY,
         "The status code changed within the same class."),
    Rule("status-body-subsumed", "shape", BENIGN,
         "Body differences under a changed status, counted but not enumerated."),
    Rule("error-identity-changed", "error_semantics", BREAKING,
         "Same HTTP status, different error type, code, or param."),
    Rule("error-message-changed", "error_semantics", RISKY,
         "Same error identity, different human-readable message."),
    Rule("error-shape-changed", "error_semantics", RISKY,
         "The error envelope gained or lost a field."),
    Rule("populated-field-removed", "shape", BREAKING,
         "A field that carried a value on A is absent on B."),
    Rule("null-field-removed", "shape", RISKY,
         "A field that was always null on A is absent on B."),
    Rule("field-added-populated", "shape", RISKY,
         "B returns a new field carrying a value."),
    Rule("field-added-empty", "shape", BENIGN,
         "B returns a new field that is null or empty."),
    Rule("value-nulled", "nullability", BREAKING,
         "A field that held a value on A is null on B."),
    Rule("value-unnulled", "nullability", RISKY,
         "A field that was null on A holds a value on B."),
    Rule("enum-value-changed", "enum", BREAKING,
         "The value changed to a member never seen on A."),
    Rule("value-changed", "value", BREAKING,
         "The value a client reads from this field changed."),
    Rule("type-changed", "value", BREAKING,
         "The JSON type of the value changed."),
    Rule("pagination-boundary-changed", "pagination", BREAKING,
         "A field describing the page, not the data, changed."),
    Rule("list-emptied", "truncation", BREAKING,
         "A non-empty collection came back empty."),
    Rule("list-truncated", "truncation", BREAKING,
         "A collection came back shorter."),
    Rule("enum-set-grew", "enum", RISKY,
         "A list of enum members gained values."),
    Rule("list-grew", "pagination", RISKY,
         "A collection came back longer."),
    Rule("order-changed", "ordering", RISKY,
         "The same members came back in a different order."),
    Rule("timing-shifted", "timing", BENIGN,
         "Response time differed materially; never scored (ADR 0004 D7)."),
)

BY_ID = {rule.id: rule for rule in RULES}


@dataclass(frozen=True)
class Verdict:
    """The outcome of classifying one delta."""

    rule: str
    rationale: str

    @property
    def axis(self) -> str:
        return BY_ID[self.rule].axis

    @property
    def severity(self) -> str:
        return BY_ID[self.rule].severity


@dataclass(frozen=True)
class StepContext:
    """What the classifier needs to know beyond the delta itself."""

    method: str
    path_template: str
    status: int
    request_keys: frozenset[str] = frozenset()
    list_body: bool = False
    observed_a: dict[str, frozenset[str]] | None = None

    def saw_on_a(self, locus: str, value: Any) -> bool:
        """Was this exact value ever observed at this locus on side A?"""
        if self.observed_a is None:
            return False
        return short(value) in self.observed_a.get(normalize(locus), frozenset())


def looks_enum(value: Any) -> bool:
    return isinstance(value, str) and bool(ENUM_VALUE_RE.match(value))


def classify(delta: Delta, ctx: StepContext) -> Verdict:
    """The rule table, in precedence order."""
    name = leaf(delta.locus)

    if _is_pagination_key(delta, ctx, name):
        return Verdict("pagination-boundary-changed", (
            f"`{name}` describes the page rather than its contents; a client "
            f"paging on it stops or continues at a different point"))

    if delta.kind == LENGTH:
        return _classify_length(delta, name)

    if delta.kind == ORDER:
        return Verdict("order-changed", (
            f"`{name}` holds the same {len(delta.a)} members in a different "
            f"order; a client reading by position reads something else"))

    if delta.kind == ONLY_IN_A:
        if has_payload(delta.a):
            return Verdict("populated-field-removed", (
                f"`{name}` carried a value on A and is absent on B; a client "
                f"that reads it gets nothing, or raises"))
        return Verdict("null-field-removed", (
            f"`{name}` was always null on A and is absent on B; nothing was "
            f"lost, but a client that indexes the key rather than defaulting "
            f"it will raise"))

    if delta.kind == ONLY_IN_B:
        if has_payload(delta.b):
            return Verdict("field-added-populated", (
                f"B returns `{name}` with a value in it; additive for a "
                f"tolerant client, fatal for a strict deserializer"))
        return Verdict("field-added-empty", (
            f"B returns `{name}` null or empty; additive, and there is nothing "
            f"in it to misread"))

    return _classify_value(delta, ctx, name)


def _is_pagination_key(delta: Delta, ctx: StepContext, name: str) -> bool:
    return ctx.list_body and name in PAGINATION_KEYS and delta.kind == VALUE


def _classify_length(delta: Delta, name: str) -> Verdict:
    before, after = len(delta.a), len(delta.b)
    if after == 0:
        return Verdict("list-emptied", (
            f"`{name}` held {before} member(s) on A and none on B; a client "
            f"that counts, sums, or reconciles over it gets a different answer "
            f"with no error to notice"))
    if after < before:
        return Verdict("list-truncated", (
            f"`{name}` shrank from {before} to {after} member(s); whatever is "
            f"missing is missing silently"))
    if all(looks_enum(v) for v in delta.b):
        return Verdict("enum-set-grew", (
            f"`{name}` grew from {before} to {after} member(s), all of them "
            f"enum-shaped; a client switching exhaustively over it now has "
            f"unhandled cases"))
    return Verdict("list-grew", (
        f"`{name}` grew from {before} to {after} member(s)"))


def _classify_value(delta: Delta, ctx: StepContext, name: str) -> Verdict:
    a, b = delta.a, delta.b
    if a is not None and b is None:
        return Verdict("value-nulled", (
            f"`{name}` held a value on A and is null on B; this is the "
            f"nullability a schema describes as optional and a client learned "
            f"from traffic"))
    if a is None and b is not None:
        return Verdict("value-unnulled", (
            f"`{name}` was null on A and holds a value on B; a client that "
            f"treated null as 'absent' now has a branch it never took"))
    if _json_type(a) != _json_type(b):
        return Verdict("type-changed", (
            f"`{name}` changed from {_json_type(a)} to {_json_type(b)}"))
    if name in ctx.request_keys:
        origin = (f"the request specified `{name}` and the server returned "
                  f"something else")
    else:
        origin = (f"the request did not specify `{name}`, so this is a changed "
                  f"server default")
    if looks_enum(b) and not ctx.saw_on_a(delta.locus, b):
        return Verdict("enum-value-changed", (
            f"`{name}` now returns `{b}`, a value that never appears anywhere "
            f"on A; {origin}"))
    return Verdict("value-changed", f"`{name}` changed; {origin}")


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__
