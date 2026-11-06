"""Self-contained HTML render of the impact report (RC1-609).

One file, no server, no external assets: the artifact an FDE sends the
customer who asked whether the upgrade will break them. Conventions are the
ESP discovery report's (RC1-559) — tiles, single-hue bars with values at the
tips, a collapsible table of the same numbers under every chart, and status
color carried by a glyph and a text label rather than by hue alone, so a
verdict survives being printed or read by somebody who cannot see the color.

This module draws. Every number comes from the same `ImpactReport` and
`Verification` the markdown render reads, and the two must never be able to
disagree — including on the parts that are unflattering. The sections for
reads nothing touched, differences no declared read covers, and unconfirmed
claims are rendered here too.
"""

from __future__ import annotations

import re
from html import escape

from compatlab.findings import SEVERITIES
from compatlab.impact import (
    BLOCKS,
    CONSEQUENCE_SUMMARY,
    CONSEQUENCE_TABLE,
    CONSEQUENCES,
    CORRUPTS,
    DEGRADES,
    EFFECT_SUMMARY,
    EFFECTS,
    TOLERATES,
    UNBLOCKS,
    ImpactReport,
    WorkflowImpact,
)
from compatlab.impact_report import VERDICT_LABEL, headline
from compatlab.verify import Verification
from compatlab.workflows import USE_SUMMARY, USES

# Verdict -> (status color, glyph). The reserved status palette from the ESP
# report, mode-invariant; the glyph and the label carry the meaning.
_VERDICT_BADGE = {
    BLOCKS: ("#d03b3b", "▲"),
    CORRUPTS: ("#ec835a", "◆"),
    # Informational rather than a failure tone, and a hollow version of the
    # corruption glyph: same call-level family, not a wrong value.
    UNBLOCKS: ("#3f7fb3", "◇"),
    DEGRADES: ("#fab219", "●"),
    TOLERATES: ("#898781", "○"),
    "clear": ("#3d8f5a", "✓"),
}

_CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
  --hairline: #e1e0d9; --baseline: #c3c2b7;
  --bar: #2a78d6;
  --border: rgba(11, 11, 11, 0.1);
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19;
    --ink: #f0efec; --ink-2: #c3c2b7; --ink-muted: #898781;
    --hairline: #2c2c2a; --baseline: #383835;
    --bar: #3987e5;
    --border: rgba(255, 255, 255, 0.1);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 920px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h2 { font-size: 1.05rem; margin: 40px 0 12px; }
h3 { font-size: 0.95rem; margin: 0 0 6px; }
.subtitle, figcaption, .note { color: var(--ink-2); font-size: 0.85rem; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px; margin-top: 24px; }
.tile { background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; }
.tile .label { color: var(--ink-2); font-size: 0.78rem; }
.tile .value { font-size: 1.5rem; font-weight: 600; }
figure { margin: 16px 0 0; background: var(--surface);
  border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
figure h3 { font-size: 0.9rem; margin: 0 0 12px; }
.row { display: grid; grid-template-columns: 210px 1fr; align-items: center;
  column-gap: 10px; margin: 6px 0; }
.row .cat { color: var(--ink-2); font-size: 0.8rem; text-align: right;
  overflow-wrap: anywhere; }
.row .track { display: flex; align-items: center; gap: 8px; min-width: 0; }
.row .fill { height: 18px; background: var(--bar);
  border-radius: 0 4px 4px 0; flex: none; max-width: calc(100% - 46px); }
.row .val { color: var(--ink-2); font-size: 0.8rem; white-space: nowrap;
  font-variant-numeric: tabular-nums; }
details { margin-top: 10px; }
details summary { color: var(--ink-muted); font-size: 0.78rem; cursor: pointer; }
/* Tables carry long identifiers and a prose column, so they are allowed to
   be wider than the card and scroll inside it rather than spill out of it. */
.tw { overflow-x: auto; margin-top: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
th { text-align: left; color: var(--ink-2); font-weight: 600; }
th, td { padding: 6px 10px 6px 0; border-bottom: 1px solid var(--hairline);
  vertical-align: top; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.sev { white-space: nowrap; font-weight: 600; }
.sev .glyph { font-size: 0.7rem; margin-right: 4px; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85em; overflow-wrap: break-word; }
/* The call column holds long unbroken identifiers; without a floor the auto
   layout squeezes it and breaks `preview_upcoming_by_subscription` mid-word
   across four lines. */
.wf table { font-size: 0.8rem; }
.wf table td:first-child, .wf table th:first-child { min-width: 175px; }
table.impacts tr.impact td { border-bottom: none; padding-bottom: 2px; }
table.impacts tr.why td { color: var(--ink-2); padding: 0 0 10px; }
.prose { background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px; margin-top: 16px; }
.wf { background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px; margin-top: 16px; }
.wf .meta { color: var(--ink-2); font-size: 0.8rem; margin: 4px 0 0; }
.seq { list-style: none; margin: 14px 0 0; padding: 0; }
.seq li { display: grid; grid-template-columns: 24px 1fr; gap: 10px;
  padding: 7px 0; border-top: 1px solid var(--hairline); }
.seq li .n { color: var(--ink-muted); font-size: 0.8rem;
  font-variant-numeric: tabular-nums; text-align: right; }
.seq li .what { color: var(--ink-2); font-size: 0.8rem; }
ul { margin: 8px 0; padding-left: 20px; }
@media (max-width: 620px) { .row { grid-template-columns: 120px 1fr; } }
"""


# Reasons and assertions are written once, in the mapper, and rendered by both
# the markdown and the HTML report. They carry markdown inline code, so the
# HTML render has to turn `foo` into <code>foo</code> or the backticks show up
# verbatim on the customer's page.
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def _prose(text: str) -> str:
    """Escape, then promote markdown inline code to real <code> spans."""
    return _INLINE_CODE_RE.sub(r"<code>\1</code>", escape(text))


def _fmt(n: int | float) -> str:
    if isinstance(n, float) and not n.is_integer():
        return f"{n:,.1f}"
    return f"{int(n):,}"


def _bars(rows: list[tuple[str, int]], aria: str) -> str:
    peak = max((v for _, v in rows), default=0)
    out = [f'<div role="img" aria-label="{escape(aria)}">']
    for label, value in rows:
        pct = 0.0 if peak == 0 else (value / peak) * 100
        tip = f"{escape(label)}: {_fmt(value)}"
        out.append(
            '<div class="row">'
            f'<span class="cat">{escape(label)}</span>'
            '<span class="track">'
            f'<span class="fill" style="width:{pct:.1f}%" title="{tip}"></span>'
            f'<span class="val">{_fmt(value)}</span>'
            "</span></div>"
        )
    out.append("</div>")
    return "".join(out)


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<div class="tw"><table><tr>{head}</tr>{body}</table></div>'


def _collapsed(headers: tuple[str, ...], rows: list[tuple[str, ...]],
               summary: str) -> str:
    if not rows:
        return ""
    return (f"<details><summary>{escape(summary)}</summary>"
            f"{_table(headers, rows)}</details>")


def _chart(title: str, rows: list[tuple[str, int]],
           headers: tuple[str, str]) -> str:
    table_rows = [(escape(k), _fmt(v)) for k, v in rows]
    return (
        f"<figure><h3>{escape(title)}</h3>{_bars(rows, title)}"
        f"{_collapsed(headers, table_rows, 'Table view')}</figure>"
    )


def _badge(verdict: str) -> str:
    color, glyph = _VERDICT_BADGE[verdict]
    return (f'<span class="sev"><span class="glyph" style="color:{color}">'
            f"{glyph}</span>{escape(VERDICT_LABEL[verdict])}</span>")


def _tile(label: str, value: str) -> str:
    return (f'<div class="tile"><div class="label">{escape(label)}</div>'
            f'<div class="value">{escape(value)}</div></div>')


def _sequence(item: WorkflowImpact) -> str:
    out = ['<ol class="seq">']
    for position, call in enumerate(item.workflow.sequence, start=1):
        here = [i for i in item.impacts if i.position == position]
        step = call.corpus.split(".", 1)[1]
        if here:
            worst = min(here, key=lambda i: CONSEQUENCES.index(i.consequence))
            what = (f"{_badge(worst.consequence)} &mdash; "
                    f"{_prose(worst.reason)}")
        else:
            what = ('<span class="what">no declared read affected</span>')
        out.append(
            f'<li><span class="n">{position}</span><span>'
            f"<code>{escape(step)}</code> "
            f'<span class="what">({len(call.reads)} declared read'
            f'{"" if len(call.reads) == 1 else "s"})</span><br>{what}'
            "</span></li>"
        )
    out.append("</ol>")
    return "".join(out)


_IMPACT_COLUMNS = ("Call", "Declared read", "Use", "Consequence",
                   "Old version", "New version")


def _impacts_table(item: WorkflowImpact) -> str:
    """One row per impact, with the reason on its own full-width row beneath.

    The reason is a sentence, and a sentence in a seventh column either forces
    the table wider than the page or gets clipped behind a horizontal scroll —
    where the one thing the reader most needs is the thing they cannot see. So
    it spans instead.
    """
    order = sorted(item.impacts,
                   key=lambda i: (CONSEQUENCES.index(i.consequence), i.position))
    if not order:
        return ""
    head = "".join(f"<th>{escape(h)}</th>" for h in _IMPACT_COLUMNS)
    body = []
    for impact in order:
        cells = (
            f"{impact.position}. "
            f"<code>{escape(impact.corpus.split('.', 1)[1])}</code>",
            f"<code>{escape(impact.locus)}</code>",
            escape(impact.use),
            _badge(impact.consequence),
            f"<code>{escape(impact.a or '-')}</code>",
            f"<code>{escape(impact.b or '-')}</code>",
        )
        caveat = (f' <span class="note">({escape(impact.caveat)})</span>'
                  if impact.caveat else "")
        body.append(
            '<tr class="impact">'
            + "".join(f"<td>{cell}</td>" for cell in cells)
            + "</tr>"
            f'<tr class="why"><td colspan="{len(_IMPACT_COLUMNS)}">'
            f"{_prose(impact.reason)}{caveat}</td></tr>"
        )
    return (f'<div class="tw"><table class="impacts"><tr>{head}</tr>'
            f'{"".join(body)}</table></div>')


def _workflow_block(item: WorkflowImpact) -> str:
    workflow = item.workflow
    first = item.first_break
    where = (
        f"First goes wrong at call {first.position} of {first.length}, "
        f"<code>{escape(first.corpus)}</code>."
        if first else
        "No declared read is affected by any difference between the two "
        "versions."
    )
    untouched = [
        (f"<code>{escape(call.corpus.split('.', 1)[1])}</code>",
         f"<code>{escape(read.locus)}</code>", escape(read.use))
        for call, read in item.untouched_reads
    ]
    uncovered = [
        (f"<code>{escape(f.step)}</code>", f"<code>{escape(f.locus)}</code>",
         f"<code>{escape(f.rule)}</code>", escape(f.severity))
        for f in item.uncovered
    ]
    untouched_block = _collapsed(
        ("Call", "Declared read", "Use"), untouched,
        f"{len(untouched)} declared read(s) this version change does not touch")
    uncovered_block = _collapsed(
        ("Call", "Locus", "Rule", "Severity"), uncovered,
        f"{len(uncovered)} real difference(s) on these calls that no declared "
        f"read covers")
    return (
        f'<div class="wf"><h3>{escape(workflow.name)} &nbsp; '
        f"{_badge(item.verdict)}</h3>"
        f'<p class="meta">{escape(workflow.purpose)}</p>'
        f'<p class="meta">Owner {escape(workflow.owner)} &middot; criticality '
        f"{escape(workflow.criticality)} &middot; {workflow.length} calls "
        f"&middot; {len(workflow.reads)} declared reads</p>"
        f'<p class="meta">{where}</p>'
        f"{_sequence(item)}{_impacts_table(item)}"
        f"{untouched_block}{uncovered_block}</div>"
    )


def _derivation(report: ImpactReport) -> str:
    rows = [
        (escape(effect),
         *[escape(VERDICT_LABEL[CONSEQUENCE_TABLE[(effect, use)]].lower())
           for use in USES])
        for effect in EFFECTS
    ]
    effects = "".join(
        f"<li><strong>{escape(e)}</strong> &mdash; {escape(EFFECT_SUMMARY[e])}</li>"
        for e in EFFECTS)
    uses = "".join(
        f"<li><strong>{escape(u)}</strong> &mdash; the value is "
        f"{escape(USE_SUMMARY[u])}</li>" for u in USES)
    grid = {
        (severity, consequence): sum(
            1 for i in report.impacts
            if i.severity == severity and i.consequence == consequence)
        for severity in SEVERITIES for consequence in CONSEQUENCES
    }
    cross = [
        (escape(severity),
         *[_fmt(grid[(severity, c)]) for c in CONSEQUENCES])
        for severity in SEVERITIES
    ]
    return (
        "<figure><h3>How a consequence is derived</h3>"
        '<p class="note">Nothing in the inventory names a break. A declaration '
        "says which fields the client reads and what it does with each value; "
        "the consequence is the cell those two facts pick out of this table. "
        "Two rules override it and always block, <code>step-missing</code> and "
        "<code>status-class-changed</code>: when the call itself stops "
        "working, the client never reaches the field.</p>"
        + _table(("Effect on the value", *USES), rows)
        + f"<ul>{effects}</ul><ul>{uses}</ul></figure>"
        "<figure><h3>Severity against consequence</h3>"
        '<p class="note">Severity is a property of the API change; the '
        "consequence is a property of this integration. They are allowed to "
        "disagree, and the point of the inventory is that they do: a "
        "<em>risky</em> finding is the differ saying <em>it depends how the "
        "client was written</em>, and the declaration is that missing "
        "fact.</p>"
        + _table(("Severity", *[VERDICT_LABEL[c].lower()
                                 for c in CONSEQUENCES]), cross)
        + "</figure>"
    )


def render_html(report: ImpactReport, verification: Verification,
                pin_list: list[dict]) -> str:
    """The whole self-contained page."""
    summary = report.to_dict()
    precision = verification.precision
    tiles = "".join([
        _tile("Workflows in inventory", _fmt(len(report.workflows))),
        _tile("Affected", _fmt(len(report.affected))),
        _tile("Stop outright", _fmt(len(report.by_verdict(BLOCKS)))),
        _tile("Silently wrong", _fmt(len(report.by_verdict(CORRUPTS)))),
        _tile("Regression tests to pin", _fmt(len(pin_list))),
        _tile("Mapping precision",
              "n/a" if precision is None else f"{precision:.0%}"),
    ])
    verdict_rows = [
        (VERDICT_LABEL[c], len(report.by_verdict(c)))
        for c in (*CONSEQUENCES, "clear")
    ]
    read_rows = [
        ("touched by this change", summary["reads_touched"]),
        ("not touched",
         summary["reads_declared"] - summary["reads_touched"]),
    ]
    charts = (
        _chart("Workflows by verdict", verdict_rows, ("Verdict", "Workflows"))
        + _chart("Declared reads", read_rows, ("Reads", "Count"))
    )
    legend = "".join(
        f"<li>{_badge(c)} &mdash; {escape(CONSEQUENCE_SUMMARY[c])}</li>"
        for c in CONSEQUENCES
    ) + (f"<li>{_badge('clear')} &mdash; no difference between the two "
         "versions reaches anything this workflow declares that it reads</li>")
    blocks = "".join(_workflow_block(w) for w in report.ordered())
    pin_rows = [
        (f"<code>{escape(p['corpus'])}</code>", _prose(p["assertion"]),
         escape(", ".join(p["workflows"])))
        for p in pin_list
    ]
    outside_rows = [
        (f"<code>{escape(f.workflow)}.{escape(f.step)}</code>",
         f"<code>{escape(f.locus)}</code>", f"<code>{escape(f.rule)}</code>",
         escape(f.severity))
        for f in sorted(report.outside, key=lambda f: (f.seq, f.locus))
    ]
    unconfirmed = "".join(
        f"<li><code>{escape(c.claim)}</code>: {_prose(c.detail)}</li>"
        for c in verification.unconfirmed
    )
    coverage_rows = [
        (f"{escape(item['id'])} {_prose(item['summary'])}",
         _fmt(item["evidence_findings"]), _fmt(item["mapped_findings"]),
         escape(", ".join(item["workflows"]) or "-"))
        for item in verification.coverage
    ]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>API upgrade impact report: {escape(report.version_a)} to {escape(report.version_b)}</title>
<style>{_CSS}</style>
</head>
<body>
<main>
<h1>API upgrade impact report</h1>
<p class="subtitle">Stripe <code>{escape(report.version_a)}</code> to
<code>{escape(report.version_b)}</code>. Every statement on this page is
derived from sanitized captured traffic replayed against both versions; no
customer data appears in it, and no number was entered by hand.</p>
<div class="tiles">{tiles}</div>
<div class="prose">{_prose(headline(report, verification))}</div>
<h2>Where it lands</h2>
{charts}
<figure><h3>What each verdict means</h3><ul>{legend}</ul></figure>
<h2>Workflow by workflow</h2>
{blocks}
<h2>What must be pinned</h2>
<figure>
<p class="note">{len(pin_list)} regression test(s), one per place a declared
read is blocked or corrupted. Each names the call to replay and the assertion
that has to hold. The tests themselves are generated from this table and run
both ways against the API: each one passes on the old version and fails on
the new one. The certified result is <code>docs/regression-tests.md</code>.</p>
{_table(("Call", "Assert", "Workflows"), pin_rows)}
</figure>
<h2>Method</h2>
{_derivation(report)}
<h2>What this report does not cover</h2>
<figure>
<ul>
<li>{summary['reads_touched']} of {summary['reads_declared']} declared reads
are touched by this version change. The rest are listed under each workflow
above. An inventory where every read turned out to be affected would be a
sign it had been written backwards from the findings.</li>
<li>{summary['findings_outside_inventory']} real difference(s) fall on calls
no declared workflow replays at all. Each is either a field this integration
does not use or a gap in the inventory, and nothing in the traffic can tell
those apart &mdash; which is the question to take back to the team that owns
the integration.</li>
</ul>
{_collapsed(("Call", "Locus", "Rule", "Severity"), outside_rows,
            f"{len(outside_rows)} difference(s) outside the inventory")}
</figure>
<h2>Verification</h2>
<figure>
<p class="note">Every claim on this page is re-derived from the replay record
by a checker that does not read the classifier's rule table and asks only
questions with observable answers: was this call really replayed on both
sides, does the declared read really return something different on the new
version, and does a blocking claim really have nothing left to send. The
generator exits non-zero while any claim is unconfirmed, so this figure is
never computed over whichever claims happened to verify.</p>
<p>{"No claims to verify." if precision is None else
   f"<strong>Workflow-mapping precision: {precision:.0%}</strong> "
   f"({len(verification.confirmed)} of {len(verification.checks)} claims "
   f"confirmed)."}</p>
{f"<ul>{unconfirmed}</ul>" if unconfirmed else ""}
<p class="note">What it does not verify is the judgment: whether a difference
deserves to be called breaking, or whether a client's exhaustive switch really
falls through on a value it has not seen. Neither is mechanically checkable,
which is why the number is named <em>mapping</em> precision.</p>
{_collapsed(("Break", "Findings", "Mapped", "Workflows"), coverage_rows,
            "Breaks the mapping still reaches (regression guard, not evidence)")}
</figure>
</main>
</body>
</html>
"""
