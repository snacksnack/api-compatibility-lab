"""Render this repository's committed reports as a static site (ADR 0008).

Separate from `compatlab` on purpose. The lab writes its reports; this is the
step that publishes the ones already committed. It is the only code here that
needs a markdown renderer, and keeping it out of the package keeps that
dependency out of every other command (the `site` dependency group).

Nothing in here computes a figure. The markdown it renders and the HTML it
copies are artifacts CI has already regenerated and diffed, so a published
page cannot disagree with the repository it came from.
"""
