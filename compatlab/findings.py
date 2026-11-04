"""What the differ emits: one finding per behavioral difference.

A finding is deliberately not "a line of diff output". The unit is a
*difference a client could notice*, carrying the axis it was found on, the
rule that classified it, and the one-sentence reason that rule fired. Phase 4
turns these into a customer-facing impact report, so every field here has to
survive being read by somebody who did not run the tool.

The severity vocabulary is three words and they are defined once, here,
because the whole project's credibility rests on the definitions holding:

- **breaking**: a client that worked against A can observably malfunction
  against B without changing a line of its own code. Data it read is gone,
  nulled, or different in a way that changes a decision it makes.
- **risky**: a client *may* malfunction, depending on how it was written — a
  strict deserializer, a regex over an error message, an exhaustive switch on
  an enum, a dependence on list position.
- **benign**: no correctly written client can be affected. An additive field
  that arrives null, a timing shift.

Anything that cannot be argued into one of those three is a bug in the rule
table, not a fourth severity.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

BREAKING = "breaking"
RISKY = "risky"
BENIGN = "benign"
SEVERITIES = (BREAKING, RISKY, BENIGN)
SEVERITY_ORDER = {name: i for i, name in enumerate(SEVERITIES)}

# The axes the epic names, plus `availability` for a step that could not be
# sent at all. `timing` is implemented and never scored — see ADR 0004 D7.
AXES = (
    "availability",
    "status",
    "error_semantics",
    "shape",
    "value",
    "nullability",
    "ordering",
    "pagination",
    "truncation",
    "enum",
    "timing",
)

MAX_VALUE_CHARS = 120
# A locus is a JSON path into a canonical record: `$.body.data[0].lines[1].type`.
# Two operations on one are needed everywhere, so they live here with the type
# they describe rather than in the classifier that happens to use them most.
LIST_INDEX_RE = re.compile(r"\[\d+\]")
LIST_SUFFIX_RE = re.compile(r"(?:\[\d*\])+$")
# How an absent field prints, as against the string "null".
ABSENT = "<absent>"


def short(value: Any) -> str | None:
    """A value as it appears in a finding: JSON, truncated, never a surprise."""
    if value is MISSING:
        return None
    text = json.dumps(value, sort_keys=True, default=repr)
    if len(text) <= MAX_VALUE_CHARS:
        return text
    return text[: MAX_VALUE_CHARS - 3] + "..."


class _Missing:
    """Distinct from None, which is a value a field can really have.

    Half of this project is the difference between "the field is absent" and
    "the field is null", so the sentinel is not optional sugar.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<missing>"


MISSING = _Missing()


def normalize(locus: str) -> str:
    """Collapse list indices: `$.body.data[2].status` -> `$.body.data[].status`.

    Two findings at the same place in different list elements are the same
    finding as far as ground truth and adjudication are concerned.
    """
    return LIST_INDEX_RE.sub("[]", locus)


def leaf(locus: str) -> str:
    """The field name a locus ends in: `$.body.data[0].lines.data[1].type` -> `type`."""
    last = locus.split(".")[-1]
    return LIST_SUFFIX_RE.sub("", last) or last


@dataclass(frozen=True)
class Finding:
    """One behavioral difference, classified."""

    workflow: str
    step: str
    seq: int
    method: str
    path_template: str
    axis: str
    locus: str
    rule: str
    severity: str
    rationale: str
    a: str | None = None
    b: str | None = None
    caveat: str | None = None
    targets: tuple[str, ...] = ()
    subsumed: int = 0

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity!r}")
        if self.axis not in AXES:
            raise ValueError(f"unknown axis: {self.axis!r}")

    @property
    def key(self) -> str:
        """Stable identity: the step and the place inside it."""
        return f"{self.workflow}.{self.step} {self.locus}"

    @property
    def endpoint(self) -> str:
        return f"{self.method} {self.path_template}"

    @property
    def field_name(self) -> str:
        """The leaf field name, for cross-checking against a schema diff."""
        return leaf(self.locus)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["targets"] = list(self.targets)
        out["key"] = self.key
        return out

    def line(self) -> str:
        """One printable line, for the CLI."""
        arrow = ""
        if self.a is not None or self.b is not None:
            # `None` here means the field was not there at all. Printing it as
            # `None` next to a JSON `null` would erase the distinction this
            # whole module is built around.
            arrow = f": {self.a or ABSENT} -> {self.b or ABSENT}"
        extra = f" [{self.caveat}]" if self.caveat else ""
        return (f"{self.severity:8} {self.axis:15} {self.rule:28} "
                f"{self.locus}{arrow}{extra}")


@dataclass
class DiffReport:
    """Every finding from one A/B comparison, plus what was compared."""

    findings: list[Finding] = field(default_factory=list)
    steps_compared: int = 0
    steps_skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def steps_with_findings(self) -> int:
        return len({(f.workflow, f.step) for f in self.findings})

    def by_severity(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    def counts(self, attribute: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[getattr(finding, attribute)] = (
                counts.get(getattr(finding, attribute), 0) + 1
            )
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))

    def sorted_findings(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (SEVERITY_ORDER[f.severity], f.seq, f.locus),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps_compared": self.steps_compared,
            "steps_with_findings": self.steps_with_findings,
            "steps_skipped": [list(s) for s in self.steps_skipped],
            "findings": len(self.findings),
            "by_severity": self.counts("severity"),
            "by_axis": self.counts("axis"),
        }
