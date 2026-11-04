"""Capture live API traffic into the sanitized corpus.

Three invariants, all set here and all worth stating because each one is a
mistake this project already made or nearly made:

1. **Bodies are redacted before a record exists.** Not on read, not on commit
   — at write time. PR #1 shipped a client_secret to a public repo by scrubbing
   only what it printed (docs/spike-findings.md, finding 5).
2. **Response headers are a whitelist**, and the Authorization header is never
   written anywhere.
3. **References resolve against the raw response, never the stored one.** A
   surrogate is not a usable object id, so the raw payload stays in memory for
   the length of the run and is never handed to `compatlab.corpus`.

A step whose references cannot be resolved — because an earlier step failed,
or returned a different shape — is skipped and reported, not guessed at. A
non-2xx response is captured like any other: error semantics are one of the
behavioral axes the differ compares.
"""

from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from compatlab.redaction import STRIPE_POLICY, Policy
from compatlab.scenarios import Scenario

HEADER_WHITELIST = ("request-id", "stripe-version")
# Below this length a literal is too generic to redact by value ("US", "usd").
MIN_KNOWN_LENGTH = 3
REFERENCE_RE = re.compile(r"\{\{([^}]+)\}\}")
# A Stripe object id in a literal path (`/v1/customers/cus_VZEjqrw2Z5KNnn`), so
# coverage groups by endpoint whether the id came from a reference or was
# written out. The random half has to carry a digit or a capital, or resource
# names would qualify: `balance_transactions` is prefix-underscore-suffix too.
OBJECT_ID_RE = re.compile(r"^[a-z]{2,8}_[A-Za-z0-9]{10,}$")
SCHEMA = 1


class CaptureError(RuntimeError):
    """A capture call failed at the transport level."""


class UnresolvedReference(LookupError):
    """A step referenced a value an earlier response did not provide."""


@dataclass(frozen=True)
class RawCall:
    """One live interaction, unredacted. Never stored, never serialized."""

    method: str
    path: str
    query: dict[str, str]
    body: dict[str, str] | None
    version: str
    status: int
    headers: dict[str, str]
    payload: Any


@dataclass
class CaptureReport:
    records: list[dict] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)

    @property
    def failures(self) -> list[dict]:
        return [r for r in self.records if r["response"]["status"] >= 400]


def dig(payload: Any, dotted: str) -> Any:
    """`data.0.id` over a decoded JSON payload."""
    cursor = payload
    for part in dotted.split("."):
        if isinstance(cursor, list):
            try:
                cursor = cursor[int(part)]
            except (ValueError, IndexError) as exc:
                raise UnresolvedReference(f"{dotted}: no element {part}") from exc
        elif isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            raise UnresolvedReference(f"{dotted}: no key {part!r}")
    if cursor is None:
        raise UnresolvedReference(f"{dotted}: null")
    return cursor


def resolve(text: str, outputs: dict[str, Any]) -> str:
    """Substitute every `{{step.field}}` reference in one string."""
    def substitute(match: re.Match[str]) -> str:
        step, _, dotted = match.group(1).strip().partition(".")
        if step not in outputs:
            raise UnresolvedReference(f"{match.group(1)}: no step {step!r}")
        return str(dig(outputs[step], dotted) if dotted else outputs[step])

    return REFERENCE_RE.sub(substitute, text)


def resolve_body(body: dict[str, str] | None,
                 outputs: dict[str, Any]) -> dict[str, str] | None:
    if body is None:
        return None
    return {k: resolve(str(v), outputs) for k, v in body.items()}


def split_query(path: str) -> tuple[str, dict[str, str]]:
    """`/v1/customers?limit=2` -> (`/v1/customers`, {'limit': '2'}).

    Repeated keys (Stripe's `expand[]`) keep the bracketed name, so the query
    map stays a flat dict and still round-trips into a replayable request.
    """
    base, _, raw = path.partition("?")
    query: dict[str, str] = {}
    for pair in filter(None, raw.split("&")):
        key, _, value = pair.partition("=")
        query[key] = value
    return base, query


def looks_like_object_id(segment: str) -> bool:
    return bool(OBJECT_ID_RE.match(segment)) and any(
        c.isupper() or c.isdigit() for c in segment.partition("_")[2]
    )


def template_of(path: str) -> str:
    """Collapse references and object ids to `{id}` for coverage grouping."""
    base, _ = split_query(path)
    segments = [
        "{id}" if looks_like_object_id(seg) else seg
        for seg in REFERENCE_RE.sub("{id}", base).split("/")
    ]
    return "/".join(segments)


def seed_known(policy: Policy, scenarios: list[Scenario]) -> Policy:
    """Tell the policy the literal values the scenarios are about to send.

    Everything a key rule covers, registered as a known value too, so it is
    also redacted where the server echoes it into free text under an innocuous
    key — the invoice `description` case in ADR 0002 D7. Seeded automatically
    rather than by the caller, because the caller forgetting is the whole
    failure mode.
    """
    known: dict[str, str | None] = {}
    for scenario in scenarios:
        for step in scenario.steps:
            for key, value in (step.body or {}).items():
                text = str(value)
                rule = policy.key_rule_for(key)
                if rule is None or "{{" in text or len(text) < MIN_KNOWN_LENGTH:
                    continue
                known[text] = rule.shape
    return policy.with_known(known)


def call(client: httpx.Client, version: str, method: str, path: str,
         body: dict[str, str] | None) -> RawCall:
    base, query = split_query(path)
    try:
        response = client.request(method, path, data=body,
                                  headers={"Stripe-Version": version})
    except httpx.HTTPError as exc:
        raise CaptureError(f"{method} {path} ({version}): {exc}") from exc
    try:
        payload = response.json()
    except ValueError:
        payload = {"_non_json_body": response.text[:500]}
    return RawCall(
        method=method,
        path=base,
        query=query,
        body=body,
        version=version,
        status=response.status_code,
        headers={k: v for k, v in response.headers.items()
                 if k.lower() in HEADER_WHITELIST},
        payload=payload,
    )


def to_record(raw: RawCall, *, seq: int, workflow: str, step: str,
              path_template: str, request_template: dict[str, str] | None,
              path_reference: str, targets: tuple[str, ...] = (),
              policy: Policy = STRIPE_POLICY) -> dict:
    """Build the stored record. Everything written here is redacted."""
    return {
        "schema": SCHEMA,
        "id": uuid.uuid4().hex[:12],
        "seq": seq,
        "workflow": workflow,
        "step": step,
        "targets": list(targets),
        "method": raw.method,
        "path": policy.redact(raw.path),
        "path_template": path_template,
        "path_reference": path_reference,
        "query": policy.redact(raw.query),
        "request_body": policy.redact(raw.body),
        # Redacted too, and for a reason the first live capture found the hard
        # way: the template is where a scenario's literal field values live, so
        # storing it raw leaks everything the response path redacted. Surrogates
        # are deterministic, so template and resolved body still agree.
        "request_template": policy.redact(request_template),
        "stripe_version": raw.version,
        "captured_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "redaction": {"policy": policy.name},
        "response": {
            "status": raw.status,
            "headers": raw.headers,
            "body": policy.redact(raw.payload),
        },
    }


def record(client: httpx.Client, version: str, step: str, method: str,
           path: str, body: dict[str, str] | None, seq: int, *,
           workflow: str = "ad_hoc", policy: Policy = STRIPE_POLICY) -> dict:
    """Capture a single call with no scenario around it."""
    raw = call(client, version, method, path, body)
    return to_record(raw, seq=seq, workflow=workflow, step=step,
                     path_template=template_of(path), path_reference=path,
                     request_template=body, policy=policy)


def capture_scenario(client: httpx.Client, scenario: Scenario, version: str, *,
                     seq_start: int = 0, policy: Policy = STRIPE_POLICY,
                     report: CaptureReport | None = None) -> CaptureReport:
    """Run one workflow end to end, in order, recording every interaction."""
    report = report or CaptureReport()
    policy = seed_known(policy, [scenario])
    outputs: dict[str, Any] = {}
    seq = seq_start
    for item in scenario.steps:
        try:
            path = resolve(item.path, outputs)
            body = resolve_body(item.body, outputs)
        except UnresolvedReference as exc:
            report.skipped.append((f"{scenario.workflow}.{item.step}", str(exc)))
            continue
        raw = call(client, version, item.method, path, body)
        outputs[item.step] = raw.payload
        report.records.append(to_record(
            raw, seq=seq, workflow=scenario.workflow, step=item.step,
            path_template=template_of(item.path), path_reference=item.path,
            request_template=item.body, targets=scenario.targets, policy=policy,
        ))
        seq += 1
    return report


def capture_all(client: httpx.Client, scenarios: list[Scenario], version: str, *,
                policy: Policy = STRIPE_POLICY) -> CaptureReport:
    report = CaptureReport()
    policy = seed_known(policy, scenarios)
    for scenario in scenarios:
        capture_scenario(client, scenario, version, seq_start=len(report.records),
                         policy=policy, report=report)
    return report
