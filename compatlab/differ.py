"""The behavioral differ: paired A/B responses in, classified findings out.

Phase 2 produced `replay/pairs.jsonl`, one entry per (workflow, step) with
both sides' records. This module is what finally answers the question the
project was built to ask: of the differences between those two responses,
which ones can hurt somebody.

Three things here are judgment, not mechanism, and each is a decision the
report has to be able to defend:

1. **A changed status subsumes the body.** When an endpoint goes 200 -> 404 the
   two bodies have nothing in common, and enumerating the 85 fields of the
   error object buries the finding under its own consequences. The status
   change is reported, the body differences are counted, and the count is the
   second finding.
2. **An error body is compared by identity, not by prose.** Under the same
   status, a different `type`/`code`/`param` is a different error; the same
   error with reworded text is a separate, lesser finding — because clients
   really do match on message text, and saying so is more useful than
   pretending they do not.
3. **A list endpoint carries a caveat, not a discount.** The sandbox
   accumulates objects between runs (ADR 0003 D7), so a difference under
   `data` can come from account state rather than from the version. The
   finding still gets reported at full severity with the caveat attached.
   Silently downgrading it would be the same mistake as not mentioning it.
"""

from __future__ import annotations

from typing import Any

from compatlab.canonical import canonical_side
from compatlab.classify import PAGINATION_KEYS, StepContext, Verdict, classify
from compatlab.deltas import ONLY_IN_A, ONLY_IN_B, Delta, deltas, leaf_values
from compatlab.findings import BENIGN, DiffReport, Finding, leaf, normalize, short

# Fields that identify *which* error this is. Everything else in the envelope
# is description.
ERROR_IDENTITY = ("type", "code", "param", "decline_code", "advice_code")
ERROR_MESSAGE = ("message", "doc_url", "user_message")
TIMING_TOLERANCE = 0.5
ACCOUNT_STATE_CAVEAT = (
    "list endpoint: may reflect account state accumulated between runs "
    "(ADR 0003 D7)"
)
REQUEST_MISMATCH_CAVEAT = (
    "the two sides did not send an identical request; the comparison for this "
    "step is not sound"
)


def sides(pairs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split paired entries back into the two runs they came from."""
    return (
        [p["a"] for p in pairs if p.get("a")],
        [p["b"] for p in pairs if p.get("b")],
    )


def observed(canon: dict[tuple[str, str], dict]) -> dict[str, frozenset[str]]:
    """Every scalar value seen at every locus on one side.

    This is what makes "a value that never appears on A" answerable. It is
    collected across the whole run rather than per step, because an enum
    member a client has handled since forever may well have been observed on a
    different endpoint.
    """
    seen: dict[str, set[str]] = {}

    def walk(value: Any, locus: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{locus}.{key}")
        elif isinstance(value, list):
            for item in value:
                walk(item, f"{locus}[]")
        else:
            seen.setdefault(normalize(locus), set()).add(short(value))

    for record in canon.values():
        walk(record.get("body"), "$.body")
    return {locus: frozenset(values) for locus, values in seen.items()}


def _request_keys(record: dict) -> frozenset[str]:
    """The base names of the parameters the request actually sent.

    `address[city]` counts as `address`: Stripe's form encoding nests with
    brackets, and the question a rule asks is whether the client said anything
    about that field at all.
    """
    body = record.get("request_body") or {}
    return frozenset(key.split("[")[0] for key in body)


def _is_list(record: dict) -> bool:
    body = record.get("body")
    return isinstance(body, dict) and body.get("object") == "list"


def _requests_agree(a: dict, b: dict) -> bool:
    return (a.get("path") == b.get("path")
            and a.get("query") == b.get("query")
            and a.get("request_body") == b.get("request_body"))


def _error_verdict(delta: Delta) -> Verdict | None:
    """Route a delta inside an error envelope to the error-semantics rules."""
    name = leaf(delta.locus)
    if name in ERROR_IDENTITY:
        return Verdict("error-identity-changed", (
            f"the error's `{name}` changed; a client branching on it no longer "
            f"recognizes this failure"))
    if name in ERROR_MESSAGE:
        return Verdict("error-message-changed", (
            f"the error's `{name}` was reworded under an unchanged error "
            f"identity; a client matching on message text breaks, and some do"))
    if delta.kind in ("only_in_a", "only_in_b"):
        return Verdict("error-shape-changed", (
            f"the error envelope {'lost' if delta.kind == 'only_in_a' else 'gained'} "
            f"`{name}`"))
    return None


def _caveat(delta: Delta, ctx: StepContext, sound: bool) -> str | None:
    """The account-state caveat, scoped to the findings it can actually explain.

    Leftover objects in the sandbox can change *which* objects a list returns,
    so a value, a length, or an order under `data` may be about the objects
    rather than the version. They cannot change whether a *key exists* on the
    object the server serializes: that is the version's doing either way. So
    shape findings under `data` carry no caveat, and attaching one to them
    would train the reader to discount the clearest findings in the report.
    """
    if not sound:
        return REQUEST_MISMATCH_CAVEAT
    if not ctx.list_body or delta.kind in (ONLY_IN_A, ONLY_IN_B):
        return None
    if delta.locus.startswith("$.body.data") or leaf(delta.locus) in PAGINATION_KEYS:
        return ACCOUNT_STATE_CAVEAT
    return None


def diff_pair(pair: dict, canon_a: dict, canon_b: dict,
              observed_a: dict[str, frozenset[str]]) -> list[Finding]:
    """Every finding for one (workflow, step)."""
    common = {
        "workflow": pair["workflow"],
        "step": pair["step"],
        "seq": pair["seq"],
        "method": pair["method"],
        "path_template": pair["path_template"],
        "targets": tuple(pair.get("targets") or ()),
    }
    if canon_a is None or canon_b is None:
        side = "A" if canon_a is not None else "B"
        return [Finding(
            **common, axis="availability", locus="$", rule="step-missing",
            severity="breaking",
            rationale=(f"the step ran on {side} only; on the other version the "
                       f"request could not be made or was never recorded, "
                       f"which is as hard a break as there is"),
        )]

    sound = _requests_agree(canon_a, canon_b)
    ctx = StepContext(
        method=pair["method"],
        path_template=pair["path_template"],
        status=canon_a["status"],
        request_keys=_request_keys(canon_a),
        list_body=_is_list(canon_a) or _is_list(canon_b),
        observed_a=observed_a,
    )
    findings: list[Finding] = []

    if canon_a["status"] != canon_b["status"]:
        findings += _status_findings(common, canon_a, canon_b)
        return findings

    for delta in deltas(canon_a.get("body"), canon_b.get("body"), "$.body"):
        verdict = None
        if ctx.status >= 400 and delta.locus.startswith("$.body.error"):
            verdict = _error_verdict(delta)
        verdict = verdict or classify(delta, ctx)
        findings.append(Finding(
            **common, axis=verdict.axis, locus=delta.locus,
            rule=verdict.rule, severity=verdict.severity,
            rationale=verdict.rationale,
            a=short(delta.a), b=short(delta.b),
            caveat=_caveat(delta, ctx, sound),
        ))

    findings += _timing_findings(common, canon_a, canon_b)
    return findings


def _status_findings(common: dict, canon_a: dict, canon_b: dict) -> list[Finding]:
    status_a, status_b = canon_a["status"], canon_b["status"]
    changed_class = status_a // 100 != status_b // 100
    rule = "status-class-changed" if changed_class else "status-changed"
    rationale = (
        f"the same request returned {status_a} on A and {status_b} on B"
        + (", moving between success and failure" if changed_class else
           ", within the same status class")
    )
    out = [Finding(
        **common, axis="status", locus="$.status", rule=rule,
        severity="breaking" if changed_class else "risky",
        rationale=rationale, a=short(status_a), b=short(status_b),
    )]
    body_deltas = deltas(canon_a.get("body"), canon_b.get("body"), "$.body")
    subsumed = sum(
        leaf_values(d.a if d.a is not None else d.b) if d.kind.startswith("only")
        else 1
        for d in body_deltas
    )
    if subsumed:
        out.append(Finding(
            **common, axis="shape", locus="$.body", rule="status-body-subsumed",
            severity=BENIGN,
            rationale=(f"{subsumed} field-level difference(s) in the body, not "
                       f"enumerated: under a changed status the two bodies are "
                       f"different kinds of document, and listing their fields "
                       f"describes the consequence instead of the cause"),
            subsumed=subsumed,
        ))
    return out


def _timing_findings(common: dict, canon_a: dict, canon_b: dict) -> list[Finding]:
    """Reported when the corpus carries durations; never scored.

    Replay runs the two sides sequentially against one shared sandbox, so a
    duration difference measures the queue it landed in as much as the version
    that served it. The axis is implemented because the story names it and
    because a corpus captured under better conditions would make it real; its
    findings are benign by rule, which is the honest ceiling for a measurement
    with one sample and no control.
    """
    ms_a, ms_b = canon_a.get("duration_ms"), canon_b.get("duration_ms")
    if not isinstance(ms_a, int | float) or not isinstance(ms_b, int | float):
        return []
    if ms_a <= 0:
        return []
    shift = abs(ms_b - ms_a) / ms_a
    if shift < TIMING_TOLERANCE:
        return []
    return [Finding(
        **common, axis="timing", locus="$.duration_ms", rule="timing-shifted",
        severity=BENIGN,
        rationale=(f"response time moved {ms_a:.0f}ms -> {ms_b:.0f}ms "
                   f"({shift:+.0%}); one sample, one shared sandbox, sequential "
                   f"runs — reported, never scored"),
        a=short(round(ms_a)), b=short(round(ms_b)),
    )]


def diff_pairs(pairs: list[dict]) -> DiffReport:
    """Compare every pair in a replay, in captured order."""
    side_a, side_b = sides(pairs)
    canon_a = canonical_side(side_a) if side_a else {}
    canon_b = canonical_side(side_b) if side_b else {}
    observed_a = observed(canon_a)

    report = DiffReport()
    for pair in sorted(pairs, key=lambda p: p["seq"]):
        key = (pair["workflow"], pair["step"])
        report.steps_compared += 1
        report.findings += diff_pair(
            pair, canon_a.get(key), canon_b.get(key), observed_a,
        )
    return report
