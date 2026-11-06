"""One stylesheet and one document shell, shared by every page this repo
renders (ADR 0008).

The impact report is the artifact an FDE sends a customer and the published
site is the same work seen by whoever follows a link, so they are deliberately
not two designs. Keeping the rules here means a change to a hairline or a
status color cannot land on one and miss the other.

`CSS` is the stylesheet the impact report has always carried, moved verbatim.
`SITE_CSS` is appended only by the site build, for the elements markdown
produces that a generated report never contains - nav, links, block quotes,
preformatted blocks - so the committed report stays byte-for-byte what it was.
"""

from __future__ import annotations

CSS = """
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

# Markdown yields elements the report generator never emits. These rules are
# additive and site-only; nothing here restyles anything in CSS above.
SITE_CSS = """
/* Declared here rather than in CSS so the committed impact report, which has
   no links in it, does not change a byte. The hue is the chart bar's. */
:root { --link: #2a78d6; }
@media (prefers-color-scheme: dark) { :root { --link: #6aa9ec; } }
a { color: var(--link); text-decoration-thickness: 1px;
  text-underline-offset: 2px; }
a:hover { text-decoration-thickness: 2px; }
header.site { border-bottom: 1px solid var(--hairline); background: var(--surface); }
header.site .inner { max-width: 920px; margin: 0 auto; padding: 14px 16px; }
header.site .home { font-weight: 600; color: var(--ink); text-decoration: none; }
header.site .tag { color: var(--ink-2); font-size: 0.85rem; margin-left: 8px; }
nav.site { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px 18px; }
nav.site section { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 10px; }
nav.site h2 { font-size: 0.72rem; margin: 0; color: var(--ink-muted);
  text-transform: uppercase; letter-spacing: 0.04em; }
nav.site a { font-size: 0.82rem; color: var(--ink-2); }
nav.site a[aria-current="page"] { color: var(--ink); font-weight: 600;
  text-decoration: none; }
article h1 { font-size: 1.5rem; margin: 0 0 16px; }
article h2 { margin-top: 36px; }
article h3 { font-size: 0.95rem; margin: 24px 0 6px; }
article p, article li { overflow-wrap: break-word; }
article > table, article .tw > table { margin: 16px 0; }
article table th, article table td { padding: 6px 12px 6px 0; }
blockquote { margin: 16px 0; padding: 2px 0 2px 14px;
  border-left: 2px solid var(--baseline); color: var(--ink-2); }
blockquote p { margin: 6px 0; }
pre { background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 14px; overflow-x: auto; font-size: 0.82rem; }
pre code { font-size: 1em; }
hr { border: none; border-top: 1px solid var(--hairline); margin: 32px 0; }
footer.site { border-top: 1px solid var(--hairline); color: var(--ink-2);
  font-size: 0.82rem; }
footer.site .inner { max-width: 920px; margin: 0 auto;
  padding: 16px 16px 48px; }
"""


def document(title: str, body: str, *, css: str = CSS) -> str:
    """The page shell every rendered artifact shares."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
{body.rstrip()}
</body>
</html>
"""
