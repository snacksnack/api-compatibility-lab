"""Canonicalize replayed responses so a diff means something.

Two runs of the same workflow against the *same* version produce responses
that differ everywhere: every object has a fresh id, every timestamp is a few
seconds later, every request has its own request id. None of that is a
behavioral difference. Canonicalization removes exactly that class and
nothing else, and the A/A control run is the proof that the line was drawn in
the right place: replay one version against itself, canonicalize both sides,
and anything still differing is noise this module failed to account for.

Ids are normalized by provenance, not by shape, wherever provenance is
known: the id the `create_customer` step returned becomes `<id:create_customer>`
on both sides, so a later response referring to that customer matches across
runs. Ids the corpus never saw created — a charge, a balance transaction, a
payment-method configuration the server made on its own — fall back to
`<id:prefix>`, which collapses two distinct charges into one token. That is a
real loss of signal, accepted deliberately: a diff between *which* charge id
appeared is never the behavioral break we are hunting.

Timestamps are bucketed by day relative to the run, not erased. Two runs
minutes apart agree on `<ts+0d>`, while a billing period that moved from 30
days out to a calendar month still reads as a different bucket.
"""

from __future__ import annotations

import re
from typing import Any

# A Stripe object id: short lowercase prefix, then a long random-looking tail.
# The prefix may itself be underscore-joined (`il_tmp_...` for a preview line),
# which an earlier version of this pattern missed — the A/A control caught it.
#
# The tail must carry a capital or a digit. Without that clause the pattern
# also matches an all-lowercase snake_case *word*: `charge_automatically`, the
# value of `collection_method`, was being rewritten to `<id:charge>` on both
# sides at once. A symmetric corruption is invisible to the A/A control
# (ADR 0003 D6) and it blinds the one axis that cares most about enum values,
# so RC1-608 tightened it — matching the rule `compatlab.capture` already
# applied to path segments, where the same trap was spotted in Phase 1.
OBJECT_ID_RE = re.compile(
    r"\b([a-z]{2,8}(?:_[a-z]{2,8})?)_((?=[A-Za-z0-9]*[A-Z0-9])[A-Za-z0-9]{10,})\b"
)
# Seconds-since-epoch, loosely: 2020-09-13 through 2033-05-18.
# A token this module already inserted; never re-match inside one.
TOKEN_RE = re.compile(r"<[^<>]*>")
EPOCH_MIN = 1_600_000_000
EPOCH_MAX = 2_000_000_000
DAY = 86_400

# Headers kept for provenance but meaningless to compare. `stripe-version`
# differs by construction on every pair of a version diff; replay asserts the
# served version matches the requested one instead, which is the property that
# header is actually there to prove (spike finding 1).
VOLATILE_HEADERS = {
    "request-id": "<request-id>",
    "stripe-version": "<version>",
}

# Values that are freshly random per run and cannot be traced to a step, so
# there is nothing to key them on but the field name. Each one is a deliberate
# blind spot: a version that changed how it scores risk, or stopped returning
# an authorization code, would not show up here. Neither is the kind of break
# this project is hunting, and leaving them in drowns the signal — every
# charge-bearing step would report a difference on every run.
VOLATILE_KEYS = {
    "risk_score": "<risk-score>",
    "authorization_code": "<auth-code>",
    "network_transaction_id": "<network-txn>",
    "authorization": "<authorization>",
    # Provenance first, key-name fallback second: a customer this run created
    # keeps its step name, while one left over from an earlier run — which a
    # list endpoint will happily return — collapses to the flat token.
    "invoice_prefix": "<invoice-prefix>",
}

# Per-object random strings that appear again inside other fields (an invoice
# number is its customer's `invoice_prefix` plus a sequence), so they are
# registered as run tokens and replaced by provenance rather than by key —
# which keeps the `-0001` sequence comparable.
RUN_TOKEN_KEYS = ("invoice_prefix",)
MIN_RUN_TOKEN_LENGTH = 6


def build_id_map(records: list[dict]) -> dict[str, str]:
    """Map each id a step created to a token naming the step that created it."""
    id_map: dict[str, str] = {}
    for rec in sorted(records, key=lambda r: r["seq"]):
        body = rec["response"].get("body")
        if not isinstance(body, dict):
            continue
        token = f"<id:{rec['step']}>"
        value = body.get("id")
        # Whatever its shape: a Coupon id is a bare 8-character string with no
        # prefix at all, and the A/A control found it by differing.
        if isinstance(value, str) and len(value) >= MIN_RUN_TOKEN_LENGTH:
            id_map.setdefault(value, token)
        for key in RUN_TOKEN_KEYS:
            extra = body.get(key)
            if isinstance(extra, str) and len(extra) >= MIN_RUN_TOKEN_LENGTH:
                id_map.setdefault(extra, f"<{key}:{rec['step']}>")
        # A list response creates nothing, but a create-then-expand step may
        # carry nested objects whose ids appear again later.
        for key in ("latest_invoice", "latest_charge", "payment_intent",
                    "charge", "customer", "subscription", "invoice"):
            nested = body.get(key)
            if isinstance(nested, str) and OBJECT_ID_RE.fullmatch(nested):
                id_map.setdefault(nested, f"{token}.{key}")
    return id_map


def run_start(records: list[dict]) -> int:
    """Earliest response timestamp in a run, as the timestamp origin."""
    stamps = [
        value
        for rec in records
        for value in _epochs(rec["response"].get("body"))
    ]
    return min(stamps) if stamps else 0


def _epochs(value: Any) -> list[int]:
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value] if EPOCH_MIN <= value <= EPOCH_MAX else []
    if isinstance(value, dict):
        return [s for v in value.values() for s in _epochs(v)]
    if isinstance(value, list):
        return [s for v in value for s in _epochs(v)]
    return []


def canonicalize(value: Any, id_map: dict[str, str], origin: int) -> Any:
    """Replace run-specific ids and timestamps with stable tokens."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if EPOCH_MIN <= value <= EPOCH_MAX:
            return f"<ts+{round((value - origin) / DAY)}d>"
        return value
    if isinstance(value, str):
        return _canonical_string(value, id_map)
    if isinstance(value, dict):
        return {key: _canonical_field(key, item, id_map, origin)
                for key, item in value.items()}
    if isinstance(value, list):
        return [canonicalize(v, id_map, origin) for v in value]
    return value


def _canonical_field(key: str, value: Any, id_map: dict[str, str],
                     origin: int) -> Any:
    if key not in VOLATILE_KEYS or value is None:
        return canonicalize(value, id_map, origin)
    if isinstance(value, str) and value in id_map:
        return id_map[value]
    return VOLATILE_KEYS[key]


def _canonical_string(text: str, id_map: dict[str, str]) -> str:
    out = text
    for raw in sorted(id_map, key=len, reverse=True):
        if raw in out:
            out = out.replace(raw, id_map[raw])
    return _shape_outside_tokens(out)


def _shape_outside_tokens(text: str) -> str:
    """Apply the prefix fallback to everything except tokens already inserted.

    A step name can itself look like an object id: `<id:create_subscriber>` is
    `create` plus a ten-character tail, so a naive second pass rewrites it to
    `<id:<id:create>>`. The A/A control cannot catch that — it corrupts both
    sides identically — which is worth remembering about what a control run
    does and does not prove.
    """
    parts = []
    cursor = 0
    for match in TOKEN_RE.finditer(text):
        parts.append(OBJECT_ID_RE.sub(_shape_token, text[cursor:match.start()]))
        parts.append(match.group(0))
        cursor = match.end()
    parts.append(OBJECT_ID_RE.sub(_shape_token, text[cursor:]))
    return "".join(parts)


def _shape_token(match: re.Match[str]) -> str:
    return f"<id:{match.group(1)}>"


def canonical_record(record: dict, id_map: dict[str, str], origin: int) -> dict:
    """The comparable projection of one record."""
    response = record["response"]
    headers = {
        key: VOLATILE_HEADERS.get(key.lower(), value)
        for key, value in response.get("headers", {}).items()
    }
    comparable = {
        "workflow": record["workflow"],
        "step": record["step"],
        "method": record["method"],
        "path": _canonical_string(record["path"], id_map),
        "query": canonicalize(record.get("query"), id_map, origin),
        "request_body": canonicalize(record.get("request_body"), id_map, origin),
        "status": response["status"],
        "headers": headers,
        "body": canonicalize(response.get("body"), id_map, origin),
    }
    # Carried through uncanonicalized: a duration is not a value to normalize,
    # and the differ reports it on its own axis. Absent from corpora captured
    # before RC1-608, which the differ treats as "no timing data".
    if "duration_ms" in record:
        comparable["duration_ms"] = record["duration_ms"]
    return comparable


def without_timing(record: dict) -> dict:
    """A canonical record with the wall-clock duration removed.

    The A/A control exists to measure infrastructure noise so a reader knows
    what the A/B run's findings are worth, and a duration is pure
    infrastructure noise: two runs of one version never agree on it. The
    differ keeps the key — it has a timing axis, benign by rule (ADR 0004 D7)
    — so it is dropped at the comparison rather than at canonicalization.

    Found in RC1-618 when the first corpus carrying `duration_ms` was run
    through the control: all 38 steps failed, every one on timing alone. The
    control had been passing because the committed corpus predated the field,
    which made "the differ handles timing on its own axis" quietly untrue of
    the one consumer that does not use the differ.
    """
    return {key: value for key, value in record.items() if key != "duration_ms"}


def canonical_side(records: list[dict]) -> dict[tuple[str, str], dict]:
    """Canonicalize a whole run, keyed by (workflow, step)."""
    id_map = build_id_map(records)
    origin = run_start(records)
    return {
        (rec["workflow"], rec["step"]): canonical_record(rec, id_map, origin)
        for rec in records
    }


def diff_paths(a: Any, b: Any, path: str = "$") -> list[str]:
    """Every leaf path at which two canonical structures disagree."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: only in B = {_short(b[key])}")
            elif key not in b:
                out.append(f"{path}.{key}: only in A = {_short(a[key])}")
            else:
                out += diff_paths(a[key], b[key], f"{path}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True))
                for d in diff_paths(x, y, f"{path}[{i}]")]
    if a != b:
        return [f"{path}: {_short(a)} != {_short(b)}"]
    return []


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 70 else text[:67] + "..."
