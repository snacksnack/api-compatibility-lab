"""Replay a stored corpus against two API versions.

Replay drives from the corpus, not from the scenario files. That is the whole
point of the tool: what a customer hands over is captured traffic, not a
hand-written description of their integration. Phase 1 stored
`path_reference` and `request_template` — the unresolved `{{step.field}}`
forms — so a stored record carries enough to be *re-executed* rather than
merely re-sent.

Re-sending is not an option on a stateful API. `POST
/v1/payment_intents/pi_OLD/capture` cannot be replayed verbatim: `pi_OLD`
belongs to the run that recorded it. So each side of a replay re-runs the
workflow against its own version, building its own object graph, and
references resolve against that side's responses. Two sides, two sets of ids,
the same sequence of intent — which is what makes the responses comparable
once the ids are canonicalized away (`compatlab.canonical`).

The sanitized corpus is what gets replayed: the requests carry the surrogates
Phase 1 wrote, not the original values. A corpus that could not be replayed
after redaction would make the installability claim empty, so this is the
step where that claim is either true or it is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from compatlab.capture import (
    CaptureReport,
    UnresolvedReference,
    call,
    resolve,
    resolve_body,
    template_of,
    to_record,
)
from compatlab.redaction import STRIPE_POLICY, Policy


@dataclass(frozen=True)
class ReplayStep:
    """One replayable unit, read back out of a stored record."""

    workflow: str
    step: str
    seq: int
    method: str
    path_reference: str
    request_template: dict[str, str] | None
    targets: tuple[str, ...]


def plan(records: list[dict]) -> list[tuple[str, list[ReplayStep]]]:
    """Group corpus records into workflows, each in captured order."""
    workflows: dict[str, list[ReplayStep]] = {}
    for rec in sorted(records, key=lambda r: r["seq"]):
        workflows.setdefault(rec["workflow"], []).append(ReplayStep(
            workflow=rec["workflow"],
            step=rec["step"],
            seq=rec["seq"],
            method=rec["method"],
            path_reference=rec.get("path_reference") or rec["path"],
            request_template=rec.get("request_template"),
            targets=tuple(rec.get("targets", ())),
        ))
    return list(workflows.items())


def replay_workflow(client: httpx.Client, steps: list[ReplayStep], version: str, *,
                    policy: Policy = STRIPE_POLICY,
                    report: CaptureReport | None = None) -> CaptureReport:
    report = report or CaptureReport()
    outputs: dict[str, Any] = {}
    for item in steps:
        try:
            path = resolve(item.path_reference, outputs)
            body = resolve_body(item.request_template, outputs)
        except UnresolvedReference as exc:
            report.skipped.append((f"{item.workflow}.{item.step}", str(exc)))
            continue
        raw = call(client, version, item.method, path, body)
        served = raw.headers.get("stripe-version")
        if served != version:
            # The one thing the version header is for. Canonicalization drops
            # it from the comparison, so the check has to live here or the
            # whole replay could silently run both sides on one version.
            report.warnings.append((
                f"{item.workflow}.{item.step}",
                f"requested {version}, served {served}",
            ))
        outputs[item.step] = raw.payload
        report.records.append(to_record(
            raw, seq=item.seq, workflow=item.workflow, step=item.step,
            path_template=template_of(item.path_reference),
            path_reference=item.path_reference,
            request_template=item.request_template, targets=item.targets,
            policy=policy,
        ))
    return report


def replay_corpus(client: httpx.Client, records: list[dict], version: str, *,
                  policy: Policy = STRIPE_POLICY) -> CaptureReport:
    """Replay every workflow in a corpus against one version."""
    report = CaptureReport()
    for _, steps in plan(records):
        replay_workflow(client, steps, version, policy=policy, report=report)
    return report


def pair(side_a: list[dict], side_b: list[dict]) -> list[dict]:
    """Match the two sides on (workflow, step).

    A step present on one side only is still a pair, with the other half
    missing: a step that could not even be sent against the new version is
    among the most severe findings there is, and dropping it here would hide
    it from Phase 3.
    """
    index_b = {(r["workflow"], r["step"]): r for r in side_b}
    pairs = []
    for rec in sorted(side_a, key=lambda r: r["seq"]):
        key = (rec["workflow"], rec["step"])
        pairs.append({
            "workflow": rec["workflow"],
            "step": rec["step"],
            "seq": rec["seq"],
            "targets": rec.get("targets", []),
            "path_template": rec["path_template"],
            "method": rec["method"],
            "a": rec,
            "b": index_b.pop(key, None),
        })
    for key, rec in index_b.items():
        pairs.append({
            "workflow": key[0], "step": key[1], "seq": rec["seq"],
            "targets": rec.get("targets", []),
            "path_template": rec["path_template"], "method": rec["method"],
            "a": None, "b": rec,
        })
    return sorted(pairs, key=lambda p: p["seq"])
