"""Check every impact claim against the replay record, without the rule table.

The mapping in `compatlab.impact` reads findings. The findings came from the
classifier. So a mapping scored against the findings would be scoring the
mapper against its own input, and a mapping bug — a claim attributed to the
wrong step, a read whose locus does not actually differ, a `blocks` on a step
that completed fine on the new version — would score a clean 100%.

So the check here goes back to `replay/pairs.jsonl` and re-derives each claim
from the two canonical responses directly. It never imports the rule table,
never looks at a severity, and asks only questions with observable answers:

- the step the claim is about was really replayed on both sides (or really
  was not, for an availability claim);
- the **declared read** the claim is about really returns something different
  on the new version. This is the backbone: a claim that the client's read
  changed, where the read resolves identically on both sides, is false no
  matter what rule produced it;
- a `blocks` claim from a lost `request_input` really has nothing left to
  send — the value on the new version is absent, null, or empty;
- a `blocks` claim from a changed status class really crossed between success
  and failure, read off the two recorded status codes and nothing else.

What this does *not* verify is the judgment: whether a difference deserves to
be called breaking, and whether a `decision` read really blows up on a value
it has not seen. That is not mechanically checkable, which is why Phase 3
adjudicates severity by hand and why the report says `workflow-mapping
precision` rather than `impact accuracy`. The number means: of the claims this
report makes about the customer's integration, how many are borne out by the
traffic.

`compatlab impact` exits non-zero while any claim is unconfirmed, for the same
reason `score` refuses to publish a false-break rate with an unadjudicated
finding: a precision number computed over the claims that happened to verify
is the likeliest way this figure would get flattering by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from compatlab.findings import MISSING
from compatlab.impact import BLOCKS, Impact, ImpactReport
from compatlab.loci import value_at
from compatlab.workflows import REQUEST_INPUT

CONFIRMED = "confirmed"
UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class Check:
    """One claim, re-derived from the replay record."""

    claim: str
    workflow: str
    corpus: str
    locus: str
    consequence: str
    verdict: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim, "workflow": self.workflow,
            "corpus": self.corpus, "locus": self.locus,
            "consequence": self.consequence, "verdict": self.verdict,
            "detail": self.detail,
        }


@dataclass
class Verification:
    """Every claim checked, plus the precision that falls out of it."""

    checks: list[Check] = field(default_factory=list)
    coverage: list[dict[str, Any]] = field(default_factory=list)

    @property
    def confirmed(self) -> list[Check]:
        return [c for c in self.checks if c.verdict == CONFIRMED]

    @property
    def unconfirmed(self) -> list[Check]:
        return [c for c in self.checks if c.verdict == UNCONFIRMED]

    @property
    def precision(self) -> float | None:
        """Confirmed claims over all claims, or None when there are none."""
        if not self.checks:
            return None
        return len(self.confirmed) / len(self.checks)

    @property
    def ok(self) -> bool:
        return not self.unconfirmed

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": len(self.checks),
            "confirmed": len(self.confirmed),
            "unconfirmed": [c.to_dict() for c in self.unconfirmed],
            "precision": (None if self.precision is None
                          else round(self.precision, 4)),
            "ground_truth_coverage": self.coverage,
        }


def _usable(value: Any) -> bool:
    """Is there still something here for a client to send on?"""
    if value is MISSING or value is None:
        return False
    if isinstance(value, list | dict | str):
        return len(value) > 0
    return True


def check(impact: Impact, pair: dict | None, canon_a: dict | None,
          canon_b: dict | None) -> Check:
    """Re-derive one claim from the two canonical responses."""
    common = {
        "claim": impact.key, "workflow": impact.workflow,
        "corpus": impact.corpus, "locus": impact.locus,
        "consequence": impact.consequence,
    }
    if pair is None:
        return Check(**common, verdict=UNCONFIRMED,
                     detail="no replay pair for this step")

    if canon_a is None or canon_b is None:
        side = "A" if canon_a is not None else "B"
        if impact.rule == "step-missing":
            return Check(**common, verdict=CONFIRMED,
                         detail=f"the step was replayed on {side} only")
        return Check(**common, verdict=UNCONFIRMED,
                     detail=(f"the step ran on {side} only, which no rule but "
                             f"step-missing can be about"))
    if impact.rule == "step-missing":
        return Check(**common, verdict=UNCONFIRMED,
                     detail="both sides replayed this step")

    # Checked before the value comparison, because the claim is about the call
    # and not about a field in the response.
    if impact.rule == "status-class-changed":
        status_a, status_b = canon_a.get("status"), canon_b.get("status")
        if status_a is None or status_b is None or \
                status_a // 100 == status_b // 100:
            return Check(**common, verdict=UNCONFIRMED,
                         detail=(f"claimed to block on a changed status class, "
                                 f"but the recorded statuses are {status_a} and "
                                 f"{status_b}"))
        return Check(**common, verdict=CONFIRMED,
                     detail=(f"the call returned {status_a} on A and {status_b} "
                             f"on B, so the workflow stops here"))

    on_a = value_at(canon_a, impact.locus)
    on_b = value_at(canon_b, impact.locus)
    if on_a == on_b:
        return Check(**common, verdict=UNCONFIRMED,
                     detail=(f"the declared read resolves identically on both "
                             f"versions ({_show(on_a)}), so nothing the client "
                             f"reads here changed"))

    if impact.consequence == BLOCKS and impact.use == REQUEST_INPUT:
        if _usable(on_b):
            return Check(**common, verdict=UNCONFIRMED,
                         detail=(f"claimed to block because there is nothing "
                                 f"to send to `{impact.feeds}`, but the new "
                                 f"version still returns {_show(on_b)}"))
        return Check(**common, verdict=CONFIRMED,
                     detail=(f"{_show(on_a)} on A, nothing usable on B, and "
                             f"`{impact.feeds}` needs it"))

    return Check(**common, verdict=CONFIRMED,
                 detail=f"the read returns {_show(on_a)} on A and {_show(on_b)} on B")


def _show(value: Any) -> str:
    if value is MISSING:
        return "<absent>"
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def verify(report: ImpactReport, pairs: list[dict],
           canon_a: dict[tuple[str, str], dict],
           canon_b: dict[tuple[str, str], dict]) -> Verification:
    """Check every claim in an impact report against the replay record."""
    by_key = {(p["workflow"], p["step"]): p for p in pairs}
    out = Verification()
    for workflow in report.ordered():
        for impact in workflow.impacts:
            workflow_name, step = impact.corpus.split(".", 1)
            key = (workflow_name, step)
            out.checks.append(check(
                impact, by_key.get(key), canon_a.get(key), canon_b.get(key),
            ))
    return out


def ground_truth_coverage(report: ImpactReport, caught: list[dict],
                          evidence_keys: dict[str, set[str]]) -> list[dict[str, Any]]:
    """Does the mapping still reach every break the differ caught?

    A regression guard, not evidence. The inventory is authored here, so a
    break landing on a declared read says as much about the author as about
    the tool; what it does catch is the mapping quietly dropping a break that
    Phase 3 found — a step left out of every declaration, a locus a read no
    longer covers. Stated that way in the report, not as a score.
    """
    mapped = {i.finding_key for i in report.impacts}
    out = []
    for item in caught:
        keys = evidence_keys.get(item["id"], set())
        hit = keys & mapped
        workflows = sorted({
            i.workflow for i in report.impacts if i.finding_key in hit
        })
        out.append({
            "id": item["id"],
            "summary": item["summary"],
            "evidence_findings": len(keys),
            "mapped_findings": len(hit),
            "workflows": workflows,
        })
    return out
