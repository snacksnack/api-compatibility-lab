"""The corpus file format: one captured interaction per JSONL line.

Decided in ADR 0001 D5 and extended in ADR 0002 for Phase 1. Two fields exist
only to serve later phases and are worth naming here:

- `request_template` keeps the unresolved `{{step.field}}` references, so
  Phase 2 can replay the sequence against a second version and resolve them
  against *that* version's object ids instead of replaying stale ones.
- `path_template` collapses resolved ids back to `{id}`, so coverage counts
  group by endpoint rather than by object.

Request and response bodies are always already redacted when they arrive here:
this module never sees a raw payload, which is what keeps the write path from
having a bypass.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable, Iterator
from typing import Any

SCHEMA = 1

REQUIRED_FIELDS = (
    "schema", "id", "workflow", "step", "seq", "method", "path",
    "path_template", "stripe_version", "captured_at", "redaction", "response",
)
REQUIRED_RESPONSE_FIELDS = ("status", "headers", "body")


def validate(record: Any) -> list[str]:
    """Return a list of problems with one record; empty means valid."""
    if not isinstance(record, dict):
        return ["record is not an object"]
    problems = [f"missing field: {f}" for f in REQUIRED_FIELDS if f not in record]
    if record.get("schema") != SCHEMA:
        problems.append(f"unsupported schema: {record.get('schema')!r}")
    response = record.get("response")
    if not isinstance(response, dict):
        problems.append("response is not an object")
    else:
        problems += [
            f"missing response field: {f}"
            for f in REQUIRED_RESPONSE_FIELDS
            if f not in response
        ]
    return problems


def write(path: pathlib.Path, records: Iterable[dict]) -> int:
    """Write records as JSONL with stable key order. Returns the count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w") as handle:
        for rec in records:
            problems = validate(rec)
            if problems:
                raise ValueError(f"refusing to write invalid record: {problems}")
            handle.write(json.dumps(rec, sort_keys=True) + "\n")
            count += 1
    return count


def read(path: pathlib.Path) -> list[dict]:
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def files(root: pathlib.Path) -> Iterator[pathlib.Path]:
    """Every corpus file under a directory, or the file itself."""
    if root.is_file():
        yield root
        return
    yield from sorted(root.glob("*.jsonl"))
