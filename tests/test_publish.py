"""The published site: links, chrome, and the report it must not re-render.

The failure this file exists to prevent is a page that looks fine and links
nowhere. Every relative link in `docs/` is written to work on disk and on
GitHub, and neither convention survives being published: `.md` targets are
not pages here, and half the link targets are not on this site at all. So the
rewriting is asserted per case rather than spot-checked on one document.

The other failure is subtler. The impact report is the artifact an FDE sends
a customer, and CI already regenerates and diffs it; if the site rendered its
own copy, a published report could disagree with the delivered one. The test
for that asserts the published bytes still contain the committed ones.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from publish.render import (
    DECISIONS,
    REPO,
    RESULTS,
    build,
    nav,
    pages,
    resolve,
    routes,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
TABLE = routes(pages())


def test_every_declared_page_has_a_source_on_disk():
    for page in pages():
        assert (ROOT / page.source).exists(), page.source


def test_the_engagement_writeup_is_the_index():
    index = [p for p in pages() if p.out == "index.html"]
    assert [p.source for p in index] == ["docs/engagement.md"]


def test_the_markdown_impact_report_is_not_published_but_still_links():
    """Five documents link to `impact-report.md`; they mean the report.

    Publishing both renders would leave a reader guessing which is current,
    so the markdown twin is aliased onto the HTML page rather than emitted.
    """
    assert "docs/impact-report.md" not in {p.source for p in pages()}
    assert TABLE["docs/impact-report.md"] == "impact-report.html"


def test_a_link_to_another_page_becomes_a_relative_page_link():
    assert resolve("regression-tests.md", source="docs/engagement.md",
                   out="index.html", table=TABLE) == "regression-tests.html"


def test_a_link_from_a_subdirectory_climbs_out():
    assert resolve("../engagement.md",
                   source="docs/adr/0003-replay-and-canonicalization.md",
                   out="adr/0003-replay-and-canonicalization.html",
                   table=TABLE) == "../index.html"


def test_a_sibling_adr_link_stays_in_the_subdirectory():
    assert resolve("0006-regression-test-generation.md",
                   source="docs/adr/0005-workflow-impact-mapping.md",
                   out="adr/0005-workflow-impact-mapping.html",
                   table=TABLE) == "0006-regression-test-generation.html"


def test_a_target_that_is_not_published_goes_to_the_source_on_github():
    """A file the site does not carry is still a real file in the repo."""
    assert resolve("../pinned/test_pinned_behavior.py",
                   source="docs/regression-tests.md",
                   out="regression-tests.html", table=TABLE) == (
        f"{REPO}/blob/main/pinned/test_pinned_behavior.py")


def test_a_directory_target_uses_a_tree_url_not_a_blob_url():
    assert resolve("../workflows", source="docs/engagement.md",
                   out="index.html", table=TABLE) == (
        f"{REPO}/tree/main/workflows")


def test_a_fragment_survives_the_rewrite():
    assert resolve("ground-truth.md#m5", source="docs/engagement.md",
                   out="index.html", table=TABLE) == "ground-truth.html#m5"


@pytest.mark.parametrize("href", ["https://stripe.com", "#later", "mailto:a@b.c"])
def test_an_absolute_or_in_page_link_is_left_alone(href):
    assert resolve(href, source="docs/engagement.md", out="index.html",
                   table=TABLE) == href


def test_a_link_to_nothing_fails_the_build_rather_than_the_reader():
    with pytest.raises(ValueError, match="resolves to nothing"):
        resolve("no-such-document.md", source="docs/engagement.md",
                out="index.html", table=TABLE)


def test_a_link_out_of_the_repository_fails_the_build():
    with pytest.raises(ValueError, match="outside the repository"):
        resolve("../../../etc/hosts", source="docs/engagement.md",
                out="index.html", table=TABLE)


def test_the_navigation_marks_the_current_page_for_a_screen_reader():
    page_list = pages()
    current = next(p for p in page_list if p.out == "impact-report.html")
    markup = nav(page_list, current)
    assert markup.count('aria-current="page"') == 1
    assert '<a href="impact-report.html" aria-current="page">' in markup


def test_the_navigation_is_grouped_and_every_page_appears_once():
    page_list = pages()
    markup = nav(page_list, page_list[0])
    for section in (RESULTS, DECISIONS):
        assert f"<h2>{section}</h2>" in markup
    for page in page_list:
        assert markup.count(f">{page.nav}</a>") == 1, page.nav


def test_an_adr_is_labelled_from_its_filename():
    labels = {p.nav for p in pages() if p.section == DECISIONS}
    assert "0003 Replay and canonicalization" in labels


# --- the built site ---------------------------------------------------------

@pytest.fixture(scope="module")
def site(tmp_path_factory) -> pathlib.Path:
    out = tmp_path_factory.mktemp("site")
    build(out, commit="0123456789abcdef")
    return out


def test_the_build_writes_every_page_and_a_nojekyll_marker(site):
    for page in pages():
        assert (site / page.out).exists(), page.out
    # Pages runs Jekyll unless this file is present, and Jekyll silently drops
    # anything underscore-prefixed.
    assert (site / ".nojekyll").exists()


def test_no_published_link_points_at_a_markdown_file(site):
    for path in site.rglob("*.html"):
        for href in re.findall(r'href="([^"]+)"', path.read_text()):
            assert not href.endswith(".md"), f"{path.name} -> {href}"


def test_every_internal_link_resolves_to_a_file_that_was_built(site):
    for path in site.rglob("*.html"):
        for href in re.findall(r'href="([^"]+)"', path.read_text()):
            if href.startswith(("http", "#", "mailto:")):
                continue
            target = (path.parent / href.partition("#")[0]).resolve()
            assert target.exists(), f"{path.name} -> {href}"


def test_the_published_impact_report_is_the_committed_one(site):
    """The site wraps the delivered artifact; it does not re-render it.

    Asserted on the report's own body rather than on a marker, so re-rendering
    it with so much as a different number would fail here.
    """
    committed = (ROOT / "docs" / "impact-report.html").read_text()
    published = (site / "impact-report.html").read_text()
    body = committed[committed.index("<main>"):committed.index("</main>")]
    assert body in published
    assert 'header class="site"' in published


def test_a_markdown_page_renders_its_tables(site):
    # The scorecard is mostly tables; markdown-it drops them unless the rule
    # is enabled, and the failure looks like pipes in a paragraph.
    assert "<table>" in (site / "behavioral-diff-report.html").read_text()


def test_every_page_carries_the_navigation_and_the_footer(site):
    for page in pages():
        text = (site / page.out).read_text()
        assert 'nav class="site"' in text, page.out
        assert "<footer" in text, page.out


def test_the_footer_credits_the_commit_it_was_built_from(site):
    assert "<code>0123456</code>" in (site / "index.html").read_text()


def test_the_title_comes_from_the_document_not_the_nav_label(site):
    text = (site / "index.html").read_text()
    assert "<title>Engagement writeup:" in text


def test_a_canonicalization_token_renders_as_text_not_a_link(site):
    """`<id:pi>` is a token, not a URI.

    CommonMark reads it as an autolink with scheme `id`, which published a
    link to nowhere on the regression-test page. The prose carrying it is
    generated and feeds the pin fingerprint, so the renderer gives way, not
    the token.
    """
    text = (site / "regression-tests.html").read_text()
    assert "&lt;id:pi&gt;" in text
    assert 'href="id:pi"' not in text
