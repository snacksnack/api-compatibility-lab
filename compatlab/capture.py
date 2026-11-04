"""Capture one API interaction into the corpus record shape.

Spike-grade: the Phase 1 capture path replaces this, but the invariants are
set here — response headers are a whitelist, bodies are scrubbed before the
record exists, and the Authorization header is never part of the record.
"""

from __future__ import annotations

import datetime
import uuid

import httpx

from compatlab.redact import scrub

HEADER_WHITELIST = ("request-id", "stripe-version")


class CaptureError(RuntimeError):
    """A capture call failed at the transport level."""


def record(client: httpx.Client, version: str, name: str, method: str,
           path: str, body: dict | None, seq: int) -> dict:
    try:
        resp = client.request(method, path, data=body,
                              headers={"Stripe-Version": version})
    except httpx.HTTPError as exc:
        raise CaptureError(f"{method} {path} ({version}): {exc}") from exc
    try:
        payload = resp.json()
    except ValueError:
        payload = {"_non_json_body": resp.text[:500]}
    return {
        "id": uuid.uuid4().hex[:12],
        "seq": seq,
        "call": name,
        "method": method,
        "path": path,
        "request_body": body,
        "stripe_version": version,
        "captured_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "response": {
            "status": resp.status_code,
            "headers": {k: v for k, v in resp.headers.items()
                        if k.lower() in HEADER_WHITELIST},
            "body": scrub(payload),
        },
    }
