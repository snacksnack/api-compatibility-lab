"""Recursive scrubbing of sensitive values in captured API payloads.

Seed of the Phase 1 (RC1-606) redaction component, pulled forward after the
spike committed a test-mode client_secret and account-bearing request log
URLs into the public corpus (caught by the PR review agent on PR #1).
Scrubbing happens at write time, never downstream of storage.
"""

from __future__ import annotations

from typing import Any

REDACTED = "[redacted]"
SENSITIVE_KEYS = {"client_secret", "secret", "request_log_url"}


def _sensitive(key: str) -> bool:
    return key in SENSITIVE_KEYS or key.endswith("_secret") or key.endswith("_key")


def scrub(value: Any) -> Any:
    """Replace the value under any sensitive key, at any depth."""
    if isinstance(value, dict):
        return {k: REDACTED if _sensitive(k) else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value
