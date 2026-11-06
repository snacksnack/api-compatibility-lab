"""Render the impact report. This module draws; it never computes.

Every number here comes from the `ImpactReport` and `Verification` that
`compatlab.impact` and `compatlab.verify` produced, the same way the Phase 3
report reads a scorecard. If a sentence in the output cannot be traced to a
field on one of those objects, it is a bug in this file.

Two sections exist for honesty rather than for the reader's convenience, and
neither is optional:

- **Reads nothing touched** and **differences no declared read covers**. The
  first says the inventory described fields this version change does not
  affect; the second says the version change affects fields the inventory does
  not describe. A report that printed only the hits would look identical
  whether the inventory was any good or not.
- **Severity against consequence.** Phase 3's severity is a property of the
  API change; the consequence here is a property of this customer's
  integration. They disagree on purpose, in both directions, and cross-tabbing
  them is the only way a reader can see that the mapping is doing work rather
  than relabeling.
"""

from __future__ import annotations

from compatlab.findings import SEVERITIES
from compatlab.impact import (
    BLOCKS,
    CONSEQUENCE_SUMMARY,
    CONSEQUENCE_TABLE,
    CONSEQUENCES,
    CORRUPTS,
    EFFECT_OF_RULE,
    EFFECT_SUMMARY,
    EFFECTS,
    UNBLOCKS,
    ImpactReport,
    WorkflowImpact,
    pins,
)
from compatlab.verify import Verification
from compatlab.workflows import USE_SUMMARY, USES, Workflow

VERDICT_LABEL = {
    BLOCKS: "BLOCKED",
    CORRUPTS: "CORRUPTED",
    UNBLOCKS: "UNBLOCKED",
    "degrades": "DEGRADED",
    "tolerates": "TOLERATED",
    "clear": "clear",
}


def _names(items: list[WorkflowImpact]) -> str:
    return ", ".join(w.workflow.name for w in items)


def headline(report: ImpactReport, verification: Verification) -> str:
    """The first paragraph: the answer to "will this upgrade break us"."""
    blocked = report.by_verdict(BLOCKS)
    corrupted = report.by_verdict(CORRUPTS)
    total = len(report.workflows)
    affected = len(report.affected)
    parts = [
        f"Upgrading from {report.version_a} to {report.version_b} affects "
        f"{affected} of the {total} workflows in the integration inventory."
    ]
    if blocked:
        one = len(blocked) == 1
        parts.append(
            f"{len(blocked)} {'stops' if one else 'stop'} outright "
            f"({_names(blocked)}): a call {'it depends' if one else 'they depend'} "
            f"on no longer works.")
    if corrupted:
        one = len(corrupted) == 1
        parts.append(
            f"{len(corrupted)} {'keeps' if one else 'keep'} running and "
            f"{'goes' if one else 'go'} silently wrong ({_names(corrupted)}): "
            f"every call still succeeds and a value "
            f"{'it decides' if one else 'they decide'} or "
            f"{'records' if one else 'record'} on has changed.")
    unblocked = report.by_verdict(UNBLOCKS)
    if unblocked:
        one = len(unblocked) == 1
        parts.append(
            f"{len(unblocked)} {'reaches' if one else 'reach'} a path "
            f"{'it' if one else 'they'} could not reach before "
            f"({_names(unblocked)}): a call the old version rejected now "
            f"succeeds.")
    clear = report.by_verdict("clear")
    if clear:
        parts.append(
            f"{len(clear)} {'is' if len(clear) == 1 else 'are'} unaffected "
            f"({_names(clear)}).")
    precision = verification.precision
    if precision is not None:
        parts.append(
            f"Workflow-mapping precision: {precision:.0%} "
            f"({len(verification.confirmed)} of {len(verification.checks)} "
            f"claims independently confirmed against the replay record).")
    return " ".join(parts)


def _sequence_lines(item: WorkflowImpact) -> list[str]:
    """The declared sequence, with what happens at each call."""
    lines = ["| # | Call | Reads | What happens |",
             "|---|------|-------|--------------|"]
    for position, call in enumerate(item.workflow.sequence, start=1):
        here = [i for i in item.impacts if i.position == position]
        if here:
            worst = min(here, key=lambda i: CONSEQUENCES.index(i.consequence))
            what = f"**{VERDICT_LABEL[worst.consequence]}** — {len(here)} impact(s)"
        else:
            what = "no declared read affected"
        lines.append(
            f"| {position} | `{call.corpus}` | {len(call.reads)} | {what} |")
    return lines


def _impact_lines(item: WorkflowImpact) -> list[str]:
    lines = ["| Call | Read | Use | Consequence | Old | New | Why |",
             "|------|------|-----|-------------|-----|-----|-----|"]
    order = sorted(item.impacts,
                   key=lambda i: (CONSEQUENCES.index(i.consequence), i.position))
    for impact in order:
        why = impact.reason
        if impact.caveat:
            why += f" _({impact.caveat})_"
        lines.append(
            f"| {impact.position}. `{impact.corpus.split('.', 1)[1]}` "
            f"| `{impact.locus}` | {impact.use} "
            f"| **{VERDICT_LABEL[impact.consequence]}** "
            f"| {impact.a or '-'} | {impact.b or '-'} | {why} |")
    return lines


def _workflow_section(item: WorkflowImpact) -> list[str]:
    workflow: Workflow = item.workflow
    verdict = VERDICT_LABEL[item.verdict]
    lines = [
        f"### {workflow.name} — {verdict}",
        "",
        workflow.purpose,
        "",
        f"- Owner: {workflow.owner}, criticality {workflow.criticality}",
        f"- {workflow.length} call(s), {len(workflow.reads)} declared read(s)",
    ]
    first = item.first_break
    if first:
        lines.append(
            f"- First goes wrong at call {first.position} of {first.length}, "
            f"`{first.corpus}`: {first.reason}")
    else:
        lines.append(
            "- No declared read is affected by any difference between the two "
            "versions")
    lines.append("")
    lines += _sequence_lines(item)
    if item.impacts:
        lines += ["", "**Impacts**", ""]
        lines += _impact_lines(item)
    if item.untouched_reads:
        lines += ["", f"<details><summary>{len(item.untouched_reads)} declared "
                      f"read(s) this version change does not touch</summary>",
                  "", "| Call | Read | Use |", "|------|------|-----|"]
        lines += [
            f"| `{call.corpus.split('.', 1)[1]}` | `{read.locus}` | {read.use} |"
            for call, read in item.untouched_reads
        ]
        lines += ["", "</details>"]
    if item.uncovered:
        lines += ["", f"<details><summary>{len(item.uncovered)} real "
                      f"difference(s) on these calls that no declared read "
                      f"covers</summary>", "",
                  "| Call | Locus | Rule | Severity |",
                  "|------|-------|------|----------|"]
        lines += [
            f"| `{f.step}` | `{f.locus}` | `{f.rule}` | {f.severity} |"
            for f in item.uncovered
        ]
        lines += ["", "</details>"]
    return lines


def _cross_tab(report: ImpactReport) -> list[str]:
    grid = {
        (severity, consequence): sum(
            1 for i in report.impacts
            if i.severity == severity and i.consequence == consequence)
        for severity in SEVERITIES for consequence in CONSEQUENCES
    }
    labels = [VERDICT_LABEL[c].lower() for c in CONSEQUENCES]
    header = "| Phase 3 severity | " + " | ".join(labels) + " |"
    lines = [header, "|---" * (len(CONSEQUENCES) + 1) + "|"]
    for severity in SEVERITIES:
        row = [str(grid[(severity, c)]) for c in CONSEQUENCES]
        lines.append(f"| {severity} | " + " | ".join(row) + " |")
    return lines


def render(report: ImpactReport, verification: Verification,
           pin_list: list[dict] | None = None) -> str:
    """The whole markdown report."""
    pin_list = pin_list if pin_list is not None else pins(report)
    summary = report.to_dict()
    lines = [
        "# API upgrade impact report",
        "",
        f"`{report.version_a}` to `{report.version_b}`. Generated by "
        f"`compatlab impact`; regenerate it rather than editing it. The "
        f"method — where the inventory comes from, how a consequence is "
        f"derived, and what the precision number does and does not mean — is "
        f"[ADR 0005](adr/0005-workflow-impact-mapping.md).",
        "",
        headline(report, verification),
        "",
        "## Workflows",
        "",
        "| Workflow | Criticality | Verdict | Calls | Reads | Impacts |",
        "|----------|-------------|---------|-------|-------|---------|",
    ]
    for item in report.ordered():
        lines.append(
            f"| {item.workflow.name} | {item.workflow.criticality} "
            f"| **{VERDICT_LABEL[item.verdict]}** | {item.workflow.length} "
            f"| {len(item.workflow.reads)} | {len(item.impacts)} |")
    lines += ["", "What each verdict means:", ""]
    lines += [f"- **{VERDICT_LABEL[c]}** — {CONSEQUENCE_SUMMARY[c]}"
              for c in CONSEQUENCES]
    lines += ["- **clear** — no difference between the two versions reaches "
              "anything this workflow declares that it reads"]

    for item in report.ordered():
        lines += ["", *_workflow_section(item)]

    lines += [
        "",
        "## What must be pinned",
        "",
        f"{len(pin_list)} regression test(s), one per place a declared read is "
        f"blocked or corrupted. This section states what must be pinned; the "
        f"tests themselves are generated from it and run both ways against "
        f"the API, each one passing on {report.version_a} and failing on "
        f"{report.version_b} — the suite is "
        f"[`pinned/test_pinned_behavior.py`](../pinned/test_pinned_behavior.py) "
        f"and the result is "
        f"[`docs/regression-tests.md`](regression-tests.md).",
        "",
        "| Call | Assert | Workflows |",
        "|------|--------|-----------|",
    ]
    for pin in pin_list:
        lines.append(
            f"| `{pin['corpus']}` | {pin['assertion']} "
            f"| {', '.join(pin['workflows'])} |")

    lines += [
        "",
        "## How a consequence is derived",
        "",
        "Nothing in `workflows/` names a break. A declaration says which "
        "fields the client reads and what it does with each value; the "
        "consequence is the cell those two facts pick out of one table.",
        "",
        "| Effect on the value | " + " | ".join(USES) + " |",
        "|---" * (len(USES) + 1) + "|",
    ]
    for effect in EFFECTS:
        row = [VERDICT_LABEL[CONSEQUENCE_TABLE[(effect, use)]].lower()
               for use in USES]
        lines.append(f"| {effect} | " + " | ".join(row) + " |")
    lines += ["", "- " + "\n- ".join(
        f"**{effect}** — {EFFECT_SUMMARY[effect]}" for effect in EFFECTS)]
    lines += ["", "- " + "\n- ".join(
        f"**{use}** — the value is {USE_SUMMARY[use]}" for use in USES)]
    lines += [
        "",
        "Two rules override the table and always block: `step-missing` and "
        "`status-class-changed`. When the call itself stops working the client "
        "never reaches the field, so what it would have done with the value "
        "does not enter into it.",
        "",
        "Which rule belongs to which effect:",
        "",
        "| Effect | Rules |",
        "|--------|-------|",
    ]
    for effect in EFFECTS:
        rules = sorted(r for r, e in EFFECT_OF_RULE.items() if e == effect)
        lines.append(f"| {effect} | " + ", ".join(f"`{r}`" for r in rules) + " |")
    inert = sorted(r for r, e in EFFECT_OF_RULE.items() if e is None)
    lines += [
        "",
        "Rules that can never produce an impact, because they describe the "
        "comparison rather than a value a client reads: "
        + ", ".join(f"`{r}`" for r in inert) + ".",
        "",
        "## Severity against consequence",
        "",
        "Phase 3's severity is a property of the API change; the consequence "
        "is a property of this customer's integration. They are allowed to "
        "disagree, and the point of the inventory is that they do. A `risky` "
        "finding is Phase 3 saying *it depends how the client was written* — "
        "the declaration is that missing fact, which is why risky findings "
        "appear in the blocked and corrupted columns below.",
        "",
    ]
    lines += _cross_tab(report)

    lines += [
        "",
        "## What this report does not cover",
        "",
        f"- {summary['reads_touched']} of {summary['reads_declared']} declared "
        f"reads are touched by this version change. The rest are listed per "
        f"workflow above. An inventory where every read turned out to be "
        f"affected would be a sign it had been written backwards from the "
        f"findings.",
        f"- {summary['findings_outside_inventory']} real difference(s) fall on "
        f"calls no declared workflow replays at all. They are listed below. "
        f"Each one is either a field this customer does not use or a gap in "
        f"the inventory, and nothing in the traffic can tell those apart — "
        f"which is the question to take back to the customer.",
    ]
    if report.outside:
        lines += ["", "| Call | Locus | Rule | Severity |",
                  "|------|-------|------|----------|"]
        lines += [
            f"| `{f.workflow}.{f.step}` | `{f.locus}` | `{f.rule}` "
            f"| {f.severity} |"
            for f in sorted(report.outside, key=lambda f: (f.seq, f.locus))
        ]

    lines += ["", "## Verification", "",
              "Every claim above is re-derived from `replay/pairs.jsonl` by "
              "`compatlab.verify`, which does not read the rule table and asks "
              "only questions with observable answers: was this step really "
              "replayed on both sides, does the declared read really return "
              "something different on the new version, and does a blocking "
              "claim really have nothing left to send. `compatlab impact` "
              "exits non-zero while any claim is unconfirmed, so the precision "
              "figure is never computed over whichever claims happened to "
              "verify.", ""]
    precision = verification.precision
    if precision is None:
        lines.append("- No claims to verify.")
    else:
        lines.append(
            f"- **Workflow-mapping precision: {precision:.0%}** "
            f"({len(verification.confirmed)} of {len(verification.checks)})")
    for check in verification.unconfirmed:
        lines.append(f"- UNCONFIRMED {check.claim}: {check.detail}")
    lines += [
        "",
        "What it does not verify is the judgment: whether a difference "
        "deserves to be called breaking, or whether a client's exhaustive "
        "switch really does fall through on a value it has not seen. Neither "
        "is mechanically checkable, which is why the number is named "
        "*mapping* precision. Severity has its own honesty mechanism, the "
        "hand adjudication in Phase 3.",
    ]
    if verification.coverage:
        lines += [
            "",
            "The mapping also has to keep reaching the breaks Phase 3 caught. "
            "This is a regression guard and not evidence: the inventory is "
            "authored in this repository, so a break landing on a declared "
            "read says as much about its author as about the tool. What it "
            "catches is the mapping quietly losing one.",
            "",
            "| Break | Findings | Mapped | Workflows |",
            "|-------|----------|--------|-----------|",
        ]
        for item in verification.coverage:
            lines.append(
                f"| {item['id']} {item['summary']} | {item['evidence_findings']} "
                f"| {item['mapped_findings']} "
                f"| {', '.join(item['workflows']) or '-'} |")
    return "\n".join(lines)
