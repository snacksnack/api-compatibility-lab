"""Join findings to the integration inventory and derive what breaks.

This is the half of the project that is not a testing tool. Phase 3 answers
"what changed between these two API versions". Phase 4 answers the question a
customer actually asks — *will this upgrade break us, and where* — and it does
that by joining each finding to the reads the client declared
(`compatlab.workflows`) and deriving a consequence.

Nothing here is declared. The inventory says what the client does with a
value; the findings say what happened to it; the consequence is the cell those
two pick out of one table:

                 request_input   decision    record      display
    loss         blocks          corrupts    corrupts    degrades
    change       corrupts        corrupts    corrupts    degrades
    novel        corrupts        corrupts    degrades    degrades
    addition     tolerates       tolerates   degrades    tolerates

- **blocks** — the sequence stops. The customer sees an error.
- **corrupts** — the sequence finishes and is silently wrong: a decision made
  on changed data, or wrong data written down. This is the class the whole
  project exists to find, and the class a schema diff cannot reach.
- **degrades** — a person sees something different, or a new column arrives;
  nothing the client decides or stores is wrong.
- **tolerates** — additive material the client's declared use cannot notice.

Three things the table is careful about.

A `loss` on a `request_input` read **blocks** rather than corrupts, because
the next call in the sequence has nothing to send — that is the propagation
claim, and the one place the mapping reasons across steps rather than within
one.

`novel` on a `decision` read **corrupts**: a value the client has never seen
reaching an exhaustive switch or a comparison is the classic quiet failure.
This is also why `risky` findings are joined here rather than filtered out
first. A `risky` finding is Phase 3 saying *it depends how the client was
written*, and a declared read is exactly that missing fact — which means the
consequence derived here can be more severe than the finding's own severity,
or less. The report cross-tabs the two instead of implying they agree.

And two rules are about the **call** rather than about a value in it:
`step-missing` and `status-class-changed`. They override the table and always
block, they apply to every read declared on that call rather than only to the
ones whose locus they happen to match, and they produce an impact even on a
call with no declared reads at all. All three of those follow from the same
fact: when the request itself stops working the client never reaches any
field, so neither the locus nor the declared use enters into it. The first
version of this module matched them by locus like everything else, which read
a 404 on an endpoint as "nothing you declared was affected" — the whole
workflow had stopped and the report said it was fine.

Everything derived here is re-checked against the replay record by
`compatlab.verify`, which does not read the rule table.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from compatlab.findings import BENIGN, Finding
from compatlab.loci import touches
from compatlab.workflows import (
    DECISION,
    DISPLAY,
    RECORD,
    REQUEST_INPUT,
    Call,
    Read,
    Workflow,
)

BLOCKS = "blocks"
CORRUPTS = "corrupts"
DEGRADES = "degrades"
TOLERATES = "tolerates"
# Worst first: a workflow's verdict is the worst consequence over its impacts.
CONSEQUENCES = (BLOCKS, CORRUPTS, DEGRADES, TOLERATES)
CONSEQUENCE_ORDER = {name: i for i, name in enumerate(CONSEQUENCES)}
CONSEQUENCE_SUMMARY = {
    BLOCKS: "the sequence stops; the customer sees an error",
    CORRUPTS: "the sequence finishes and is silently wrong",
    DEGRADES: "visibly different, but nothing decided or stored is wrong",
    TOLERATES: "additive; the declared use cannot notice it",
}

# What the finding did to the value the client reads. Every rule in
# `compatlab.classify.RULES` belongs to exactly one effect, or to neither —
# the `benign` rules that describe the comparison rather than the data.
LOSS = "loss"
CHANGE = "change"
NOVEL = "novel"
ADDITION = "addition"
EFFECTS = (LOSS, CHANGE, NOVEL, ADDITION)
EFFECT_SUMMARY = {
    LOSS: "the value the client read is gone or unusable",
    CHANGE: "the value is still there and is different",
    NOVEL: "the client is handed something it has never seen",
    ADDITION: "new material arrives alongside what was read",
}

EFFECT_OF_RULE = {
    "step-missing": LOSS,
    "status-class-changed": LOSS,
    "status-changed": CHANGE,
    "error-identity-changed": CHANGE,
    "error-message-changed": CHANGE,
    "error-shape-changed": ADDITION,
    "populated-field-removed": LOSS,
    "null-field-removed": LOSS,
    "value-nulled": LOSS,
    "list-emptied": LOSS,
    "list-truncated": LOSS,
    "type-changed": LOSS,
    "value-changed": CHANGE,
    "enum-value-changed": NOVEL,
    "pagination-boundary-changed": CHANGE,
    "order-changed": CHANGE,
    "value-unnulled": NOVEL,
    "field-added-populated": NOVEL,
    "enum-set-grew": NOVEL,
    "list-grew": ADDITION,
    "field-added-empty": ADDITION,
    # Describe the comparison, not the data a client reads. A declared read
    # cannot be affected by either, so they never produce an impact.
    "status-body-subsumed": None,
    "timing-shifted": None,
}

CONSEQUENCE_TABLE: dict[tuple[str, str], str] = {
    (LOSS, REQUEST_INPUT): BLOCKS,
    (LOSS, DECISION): CORRUPTS,
    (LOSS, RECORD): CORRUPTS,
    (LOSS, DISPLAY): DEGRADES,
    (CHANGE, REQUEST_INPUT): CORRUPTS,
    (CHANGE, DECISION): CORRUPTS,
    (CHANGE, RECORD): CORRUPTS,
    (CHANGE, DISPLAY): DEGRADES,
    (NOVEL, REQUEST_INPUT): CORRUPTS,
    (NOVEL, DECISION): CORRUPTS,
    (NOVEL, RECORD): DEGRADES,
    (NOVEL, DISPLAY): DEGRADES,
    (ADDITION, REQUEST_INPUT): TOLERATES,
    (ADDITION, DECISION): TOLERATES,
    (ADDITION, RECORD): DEGRADES,
    (ADDITION, DISPLAY): TOLERATES,
}

# Rules about the call rather than about a value in it. The client never gets
# to the read, so the declared use cannot soften the consequence.
BLOCKING_RULES = ("step-missing", "status-class-changed")
# The pseudo-use on a call-level impact: the call stopped working and this
# workflow depends on it, whether or not it declared a read on the response.
# Not a value a declaration may name — `USES` is what a declaration may say.
CALL = "call"
BLOCKING_REASON = {
    "step-missing": (
        "this call could not be made at all against the new version, so the "
        "workflow stops here"),
    "status-class-changed": (
        "this call returned {a} on the old version and {b} on the new one; the "
        "workflow stops here"),
}

REASON = {
    (LOSS, REQUEST_INPUT): (
        "the client sends this value to `{feeds}`, and on the new version "
        "there is no value to send"),
    (LOSS, DECISION): (
        "the client decides on this value ({note}), and on the new version "
        "there is nothing to decide on"),
    (LOSS, RECORD): (
        "the client stores this value ({note}); on the new version the record "
        "it writes is missing it"),
    (LOSS, DISPLAY): "the client displays this value and now has nothing to show",
    (CHANGE, REQUEST_INPUT): (
        "the client sends this value to `{feeds}`, which now receives a "
        "different input than it did on the old version"),
    (CHANGE, DECISION): (
        "the client decides on this value ({note}); the same request now "
        "yields a different decision"),
    (CHANGE, RECORD): (
        "the client stores this value ({note}); the same request now writes a "
        "different record"),
    (CHANGE, DISPLAY): "the client displays this value and now shows something else",
    (NOVEL, REQUEST_INPUT): (
        "the client forwards this value to `{feeds}` and has never forwarded "
        "this one"),
    (NOVEL, DECISION): (
        "the client decides on this value ({note}) and has never been handed "
        "this one; an exhaustive branch has no case for it"),
    (NOVEL, RECORD): (
        "the client stores this value ({note}); the stored value is one its "
        "own consumers have not seen"),
    (NOVEL, DISPLAY): "the client shows a value it has never shown",
    (ADDITION, REQUEST_INPUT): "additive; nothing the client forwards changed",
    (ADDITION, DECISION): "additive; the value the client decides on is unchanged",
    (ADDITION, RECORD): (
        "the client stores this subtree ({note}); it gains material it did "
        "not have, which a strict writer will reject"),
    (ADDITION, DISPLAY): "additive; nothing the client shows changed",
}


def effect_of(finding: Finding) -> str | None:
    """Which effect class a finding's rule belongs to, or None.

    A rule absent from the table is a bug, not a default: a new rule must be
    placed deliberately or the mapping would quietly stop reporting it.
    """
    if finding.rule not in EFFECT_OF_RULE:
        raise KeyError(
            f"rule {finding.rule!r} has no effect class; add it to "
            f"EFFECT_OF_RULE so the mapping cannot silently ignore it")
    return EFFECT_OF_RULE[finding.rule]


@dataclass(frozen=True)
class Impact:
    """One finding meeting one declared read: the derived consequence."""

    workflow: str
    position: int
    length: int
    corpus: str
    locus: str
    use: str
    note: str
    feeds: str | None
    effect: str
    consequence: str
    reason: str
    finding_key: str
    finding_locus: str
    rule: str
    severity: str
    axis: str
    a: str | None
    b: str | None
    caveat: str | None

    @property
    def key(self) -> str:
        return f"{self.workflow}[{self.position}] {self.locus} <- {self.rule}"

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "position": self.position,
            "length": self.length,
            "corpus": self.corpus,
            "locus": self.locus,
            "use": self.use,
            "note": self.note,
            "feeds": self.feeds,
            "effect": self.effect,
            "consequence": self.consequence,
            "reason": self.reason,
            "finding_key": self.finding_key,
            "finding_locus": self.finding_locus,
            "rule": self.rule,
            "severity": self.severity,
            "axis": self.axis,
            "a": self.a,
            "b": self.b,
            "caveat": self.caveat,
            "key": self.key,
        }


@dataclass
class WorkflowImpact:
    """Everything the version change does to one declared workflow."""

    workflow: Workflow
    impacts: list[Impact] = field(default_factory=list)
    untouched_reads: list[tuple[Call, Read]] = field(default_factory=list)
    uncovered: list[Finding] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """The worst consequence over this workflow's impacts, or `clear`."""
        if not self.impacts:
            return "clear"
        return min((i.consequence for i in self.impacts),
                   key=lambda c: CONSEQUENCE_ORDER[c])

    @property
    def first_break(self) -> Impact | None:
        """The earliest impact at the verdict's severity: where it goes wrong."""
        worst = [i for i in self.impacts if i.consequence == self.verdict]
        return min(worst, key=lambda i: i.position) if worst else None

    def at(self, consequence: str) -> list[Impact]:
        return [i for i in self.impacts if i.consequence == consequence]

    def to_dict(self) -> dict:
        first = self.first_break
        return {
            "workflow": self.workflow.name,
            "purpose": self.workflow.purpose,
            "criticality": self.workflow.criticality,
            "owner": self.workflow.owner,
            "length": self.workflow.length,
            "verdict": self.verdict,
            "first_break": first.to_dict() if first else None,
            "counts": {c: len(self.at(c)) for c in CONSEQUENCES
                       if self.at(c)},
            "impacts": [i.to_dict() for i in self.impacts],
            "reads_declared": len(self.workflow.reads),
            "reads_untouched": [
                {"corpus": call.corpus, **read.to_dict()}
                for call, read in self.untouched_reads
            ],
            "uncovered_findings": [f.key for f in self.uncovered],
        }


@dataclass
class ImpactReport:
    """The whole inventory joined to the whole finding set."""

    workflows: list[WorkflowImpact] = field(default_factory=list)
    outside: list[Finding] = field(default_factory=list)
    version_a: str = ""
    version_b: str = ""

    @property
    def impacts(self) -> list[Impact]:
        return [i for w in self.workflows for i in w.impacts]

    def by_verdict(self, verdict: str) -> list[WorkflowImpact]:
        return [w for w in self.workflows if w.verdict == verdict]

    @property
    def affected(self) -> list[WorkflowImpact]:
        return [w for w in self.workflows if w.verdict != "clear"]

    def ordered(self) -> list[WorkflowImpact]:
        """Worst verdict first, then by declared criticality, then by name."""
        rank = {"clear": len(CONSEQUENCES)}
        crit = {"high": 0, "medium": 1, "low": 2}
        return sorted(self.workflows, key=lambda w: (
            rank.get(w.verdict, CONSEQUENCE_ORDER.get(w.verdict, 9)),
            crit.get(w.workflow.criticality, 9),
            w.workflow.name,
        ))

    def to_dict(self) -> dict:
        return {
            "version_a": self.version_a,
            "version_b": self.version_b,
            "workflows_declared": len(self.workflows),
            "workflows_affected": len(self.affected),
            "by_verdict": {
                verdict: [w.workflow.name for w in self.by_verdict(verdict)]
                for verdict in (*CONSEQUENCES, "clear")
                if self.by_verdict(verdict)
            },
            "impacts": len(self.impacts),
            "reads_declared": sum(len(w.workflow.reads) for w in self.workflows),
            # Call-level impacts are excluded: `$` is not a declared read, and
            # counting one would let `reads_touched` exceed `reads_declared`.
            "reads_touched": len({(i.workflow, i.corpus, i.locus)
                                  for i in self.impacts if i.use != CALL}),
            "findings_outside_inventory": len(self.outside),
            "detail": [w.to_dict() for w in self.ordered()],
        }


def consequence_of(finding: Finding, effect: str, read: Read) -> tuple[str, str]:
    """The derived consequence and the sentence that explains it."""
    if finding.rule in BLOCKING_RULES:
        return BLOCKS, BLOCKING_REASON[finding.rule].format(
            a=finding.a, b=finding.b)
    template = REASON[(effect, read.use)]
    return CONSEQUENCE_TABLE[(effect, read.use)], template.format(
        note=read.note.rstrip("."), feeds=read.feeds or "")


def map_workflow(workflow: Workflow, findings: list[Finding]) -> WorkflowImpact:
    """Join one declared workflow to the findings on the steps it replays."""
    out = WorkflowImpact(workflow=workflow)
    by_key: dict[tuple[str, str], list[Finding]] = {}
    for finding in findings:
        by_key.setdefault((finding.workflow, finding.step), []).append(finding)

    touched: set[tuple[str, str]] = set()
    covered: set[str] = set()
    reached: list[Finding] = []
    for position, call in enumerate(workflow.sequence, start=1):
        step_findings = by_key.get(call.key, [])
        reached += step_findings
        for finding in step_findings:
            effect = effect_of(finding)
            if effect is None:
                continue
            about_the_call = finding.rule in BLOCKING_RULES
            hits = [
                read for read in call.reads
                if about_the_call or touches(finding.locus, read.locus)
            ]
            if about_the_call and not hits:
                # The call stopped working and this workflow runs it. There is
                # no declared read to hang the impact on, and saying nothing
                # would report the workflow as unaffected.
                hits = [Read(locus="$", use=CALL,
                             note="this workflow makes this call")]
            for read in hits:
                consequence, reason = consequence_of(finding, effect, read)
                if read.use != CALL:
                    touched.add((call.corpus, read.locus))
                covered.add(finding.key)
                out.impacts.append(Impact(
                    workflow=workflow.name, position=position,
                    length=workflow.length, corpus=call.corpus,
                    locus=read.locus, use=read.use, note=read.note,
                    feeds=read.feeds, effect=effect, consequence=consequence,
                    reason=reason, finding_key=finding.key,
                    finding_locus=finding.locus, rule=finding.rule,
                    severity=finding.severity, axis=finding.axis,
                    a=finding.a, b=finding.b, caveat=finding.caveat,
                ))
    out.untouched_reads = [
        (call, read) for call in workflow.sequence for read in call.reads
        if (call.corpus, read.locus) not in touched
    ]
    # A real difference on a step this workflow replays that no declared read
    # covers. Reported, never dropped: it is either a field the client does
    # not use, or a gap in the inventory, and the report cannot tell which.
    out.uncovered = [
        f for f in reached if f.key not in covered and f.severity != BENIGN
    ]
    return out


def map_findings(workflows: list[Workflow], findings: list[Finding], *,
                 version_a: str = "", version_b: str = "") -> ImpactReport:
    """The whole join, plus the findings no declared workflow even reaches."""
    report = ImpactReport(version_a=version_a, version_b=version_b)
    report.workflows = [map_workflow(w, findings) for w in workflows]
    declared_steps = {
        call.key for w in workflows for call in w.sequence
    }
    report.outside = [
        f for f in findings
        if (f.workflow, f.step) not in declared_steps and f.severity != BENIGN
    ]
    return report


def pins(report: ImpactReport) -> list[dict]:
    """The regression-test specification Phase 5 compiles.

    One pin per place a declared read is blocked or corrupted: the step to
    replay, the locus to assert on, what version A returned there, and what
    version B returned instead. Phase 4 states what must be pinned; RC1-610
    turns each of these into an executable test and verifies the defining
    property — fails on B, passes on A.
    """
    worst: dict[str, Impact] = {}
    seen: dict[str, list[str]] = {}
    for workflow in report.ordered():
        for impact in workflow.impacts:
            if impact.consequence not in (BLOCKS, CORRUPTS):
                continue
            key = f"{impact.corpus} {impact.finding_locus}"
            names = seen.setdefault(key, [])
            if impact.workflow not in names:
                names.append(impact.workflow)
            held = worst.get(key)
            if held is None or CONSEQUENCE_ORDER[impact.consequence] < \
                    CONSEQUENCE_ORDER[held.consequence]:
                worst[key] = impact
    out = [
        {
            "pin": key,
            "corpus": impact.corpus,
            "locus": impact.finding_locus,
            "declared_read": impact.locus,
            "rule": impact.rule,
            "axis": impact.axis,
            "consequence": impact.consequence,
            "expect_on_a": impact.a,
            "observed_on_b": impact.b,
            "assertion": _assertion(impact),
            "workflows": seen[key],
            "caveat": impact.caveat,
        }
        for key, impact in worst.items()
    ]
    return sorted(out, key=lambda p: p["pin"])


def _assertion(impact: Impact) -> str:
    """What the generated test has to assert, in one sentence.

    A finding's recorded values are truncated for readability (`short`), so a
    pin cannot always quote the old value back: an assertion built from a
    clipped JSON blob would be a test nobody can write. Where the value does
    not fit, the pin names the property instead of the literal, and the full
    old and new values stay on the record as `expect_on_a` / `observed_on_b`.
    """
    if impact.rule == "step-missing":
        return f"replaying `{impact.corpus}` succeeds"
    if impact.axis == "status":
        return f"`{impact.corpus}` returns status {impact.a} and not {impact.b}"
    if impact.rule == "list-emptied":
        return f"`{impact.finding_locus}` comes back as a non-empty collection"
    if impact.rule == "list-truncated":
        return (f"`{impact.finding_locus}` comes back with as many elements as "
                f"it did on the old version")
    clipped = impact.a is not None and impact.a.endswith("...")
    if clipped:
        return (f"`{impact.finding_locus}` is present and unchanged from the "
                f"old version")
    if impact.effect == LOSS:
        return f"`{impact.finding_locus}` is present and equals {impact.a}"
    return f"`{impact.finding_locus}` equals {impact.a}"
