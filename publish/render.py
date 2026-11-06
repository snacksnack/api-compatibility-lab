"""The page set, the navigation, and the link rewriting.

Two kinds of page. Most are markdown files under `docs/`, rendered into the
shared document shell. One - the impact report - is already HTML, because
`compatlab impact --html` writes it as the self-contained artifact an FDE
sends a customer; that file is copied and the site's chrome is injected into
it, so the published report is byte-for-byte the delivered one.

Links are the part that needs care. Every relative link in `docs/` is written
to resolve on disk and on GitHub, and `tests/test_engagement.py` enforces
that. On the web neither holds: `regression-tests.md` is not a page here, and
`pinned/test_pinned_behavior.py` is not on this site at all. So each link is
resolved against its own file, then either pointed at the page that renders
that document or sent to the source on GitHub. A link that resolves to
nothing is a build failure rather than a 404 somebody finds later.
"""

from __future__ import annotations

import dataclasses
import pathlib
import posixpath
import re
from html import escape

from markdown_it import MarkdownIt

from compatlab.theme import CSS, SITE_CSS, document

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
REPO = "https://github.com/snacksnack/api-compatibility-lab"

RESULTS = "Results"
METHOD = "Method"
DECISIONS = "Decisions"
SECTIONS = (RESULTS, METHOD, DECISIONS)

# The report is copied, not re-rendered, so these are the seams the copy is
# spliced at. They are asserted rather than assumed: if the generator's shell
# ever changes, this build fails loudly instead of publishing a page with no
# navigation and no stylesheet.
STYLE_CLOSE = "</style>"
BODY_OPEN = "<body>\n"
BODY_CLOSE = "\n</body>"


@dataclasses.dataclass(frozen=True)
class Page:
    """One published page."""

    source: str        # path relative to the repository root
    out: str           # path relative to the site root
    nav: str           # label in the navigation
    section: str
    title: str = ""    # falls back to the source's own first heading

    @property
    def is_markdown(self) -> bool:
        return self.source.endswith(".md")


def _adr_pages() -> list[Page]:
    """Every ADR, labelled from its filename rather than a second list."""
    pages = []
    for path in sorted(DOCS.glob("adr/*.md")):
        number, _, rest = path.stem.partition("-")
        words = rest.replace("-", " ")
        pages.append(Page(
            source=f"docs/adr/{path.name}",
            out=f"adr/{path.stem}.html",
            nav=f"{number} {words[:1].upper()}{words[1:]}",
            section=DECISIONS,
        ))
    return pages


def pages() -> list[Page]:
    """The site, in reading order.

    The engagement writeup is the index because it is the one document that
    states the question, the numbers and the limits in that order; everything
    else is something it links to. `docs/impact-report.md` is deliberately
    absent: it is the same content as the HTML report, and publishing both
    would invite a reader to wonder which one is current.
    """
    return [
        Page("docs/engagement.md", "index.html", "Engagement writeup", RESULTS),
        Page("docs/impact-report.html", "impact-report.html",
             "Impact report", RESULTS),
        Page("docs/behavioral-diff-report.md", "behavioral-diff-report.html",
             "Scorecard", RESULTS),
        Page("docs/regression-tests.md", "regression-tests.html",
             "Regression tests", RESULTS),
        Page("docs/ground-truth.md", "ground-truth.html", "Ground truth",
             METHOD),
        Page("docs/corpus-coverage.md", "corpus-coverage.html",
             "Corpus coverage", METHOD),
        Page("docs/spike-findings.md", "spike-findings.html", "Spike findings",
             METHOD),
        Page("docs/m5-probe.md", "m5-probe.html", "M5 probe", METHOD),
        Page("docs/m6-m8-probe.md", "m6-m8-probe.html", "M6-M8 probe", METHOD),
        Page("docs/m7-probe.md", "m7-probe.html", "M7 probe", METHOD),
        *_adr_pages(),
    ]


def routes(page_list: list[Page]) -> dict[str, str]:
    """Source path -> published path, including the aliases links need.

    `impact-report.md` is not published, but five documents link to it, and
    they mean the impact report rather than the file. The alias sends them to
    the page that renders it instead of off to GitHub.
    """
    table = {p.source: p.out for p in page_list}
    if "docs/impact-report.html" in table:
        table["docs/impact-report.md"] = table["docs/impact-report.html"]
    return table


def _github(rel: str) -> str:
    kind = "tree" if (ROOT / rel).is_dir() else "blob"
    return f"{REPO}/{kind}/main/{rel}"


def resolve(href: str, *, source: str, out: str, table: dict[str, str]) -> str:
    """Rewrite one link for the site.

    `source` and `out` are the containing page's paths, because a relative
    link means different things from `docs/engagement.md` and from
    `docs/adr/0003-...md`, and the answer has to be relative to where the
    page is published rather than to where it was written.
    """
    if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", href):
        return href
    path, sep, fragment = href.partition("#")
    if not path:
        return href
    target = ((ROOT / source).parent / path).resolve()
    try:
        rel = target.relative_to(ROOT).as_posix()
    except ValueError:
        raise ValueError(
            f"{source}: link {href!r} points outside the repository") from None
    if not target.exists():
        raise ValueError(f"{source}: link {href!r} resolves to nothing")
    if rel in table:
        here = posixpath.dirname(out)
        return posixpath.relpath(table[rel], here or ".") + sep + fragment
    return _github(rel) + sep + fragment


def _markdown(table: dict[str, str]) -> MarkdownIt:
    """CommonMark plus tables, with every link rewritten on the way out."""
    # Tables on, autolinks off. This repo's canonicalization tokens are
    # angle-bracketed and look like URIs with a scheme - `<id:pi>`, `<ts+30d>`
    # - so CommonMark turns them into links to nowhere. The assertion prose
    # that carries them is generated and feeds the pin fingerprint, so the
    # token cannot be rewritten without invalidating 21 live certifications
    # that need a Stripe key to rebuild. No document here uses a bare
    # autolink, and `tests/test_publish.py` keeps it that way.
    md = MarkdownIt("commonmark").enable(["table"]).disable(["autolink"])

    def link_open(self, tokens, idx, options, env):
        token = tokens[idx]
        href = token.attrGet("href")
        if href is not None:
            token.attrSet("href", resolve(
                href, source=env["source"], out=env["out"], table=table))
        return self.renderToken(tokens, idx, options, env)

    md.add_render_rule("link_open", link_open)
    return md


_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_TITLE = re.compile(r"<title>(.*?)</title>", re.DOTALL)


def _title_of(page: Page, text: str) -> str:
    if page.title:
        return page.title
    if page.is_markdown:
        found = _H1.search(text)
        return found.group(1).strip() if found else page.nav
    found = _TITLE.search(text)
    return found.group(1).strip() if found else page.nav


def nav(page_list: list[Page], current: Page) -> str:
    """The grouped navigation, with the current page marked for a screen
    reader as well as visually."""
    blocks = []
    for section in SECTIONS:
        members = [p for p in page_list if p.section == section]
        if not members:
            continue
        links = []
        for item in members:
            href = posixpath.relpath(
                item.out, posixpath.dirname(current.out) or ".")
            mark = ' aria-current="page"' if item.out == current.out else ""
            links.append(f'<a href="{escape(href)}"{mark}>'
                         f'{escape(item.nav)}</a>')
        blocks.append(f"<section><h2>{escape(section)}</h2>"
                      f"{''.join(links)}</section>")
    return "".join(blocks)


def header(page_list: list[Page], current: Page, *, home: str) -> str:
    return (
        '<header class="site"><div class="inner">'
        f'<a class="home" href="{escape(home)}">API Compatibility Lab</a>'
        '<span class="tag">Stripe <code>2022-11-15</code> to '
        '<code>2025-03-31.basil</code></span>'
        f'<nav class="site" aria-label="Reports">{nav(page_list, current)}</nav>'
        '</div></header>'
    )


def footer(*, commit: str = "") -> str:
    built = f" Built from <code>{escape(commit[:7])}</code>." if commit else ""
    return (
        '<footer class="site"><div class="inner">'
        f'Generated from the committed reports in <a href="{REPO}">'
        'snacksnack/api-compatibility-lab</a>; no figure on these pages was '
        f'entered by hand.{built}'
        '</div></footer>'
    )


def _markdown_page(page: Page, text: str, md: MarkdownIt, chrome: str,
                   tail: str) -> str:
    body = md.render(text, {"source": page.source, "out": page.out})
    return document(
        escape(_title_of(page, text)),
        f'{chrome}<main><article>{body}</article></main>{tail}',
        css=CSS + SITE_CSS,
    )


def _copied_page(page: Page, text: str, chrome: str, tail: str) -> str:
    """Splice the site's chrome into an already-rendered report.

    Deliberately a splice and not a re-render: the bytes between the seams
    are the ones CI regenerated and diffed, so the published report cannot
    drift from the delivered one.
    """
    for seam in (STYLE_CLOSE, BODY_OPEN, BODY_CLOSE):
        if seam not in text:
            raise ValueError(
                f"{page.source}: no {seam!r} to splice at; the report "
                f"generator's shell changed and this build needs updating")
    text = text.replace(STYLE_CLOSE, SITE_CSS + STYLE_CLOSE, 1)
    text = text.replace(BODY_OPEN, BODY_OPEN + chrome + "\n", 1)
    return text.replace(BODY_CLOSE, "\n" + tail + BODY_CLOSE, 1)


def build(out_dir: pathlib.Path, *, commit: str = "") -> list[pathlib.Path]:
    """Render every page into `out_dir`. Returns what it wrote."""
    page_list = pages()
    table = routes(page_list)
    md = _markdown(table)
    tail = footer(commit=commit)
    written = []
    for page in page_list:
        source = ROOT / page.source
        if not source.exists():
            raise ValueError(f"{page.source}: no such document")
        text = source.read_text()
        home = posixpath.relpath("index.html",
                                 posixpath.dirname(page.out) or ".")
        chrome = header(page_list, page, home=home)
        if page.is_markdown:
            rendered = _markdown_page(page, text, md, chrome, tail)
        else:
            rendered = _copied_page(page, text, chrome, tail)
        target = out_dir / page.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
        written.append(target)
    # Pages runs Jekyll over an artifact unless told not to, and Jekyll
    # ignores directories beginning with an underscore. Nothing here starts
    # with one today, which is exactly why this is cheap insurance.
    (out_dir / ".nojekyll").write_text("")
    return written
