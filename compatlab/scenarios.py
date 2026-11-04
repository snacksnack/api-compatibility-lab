"""Workflows as named call sequences, loaded from `scenarios/*.json`.

A workflow is the unit Phase 4 maps breaking diffs onto ("this change breaks
checkout at step 5"), so the corpus is captured workflow-shaped from the
start rather than as a flat pile of endpoints. Scenarios are data, not code,
because the real use of this tool is a customer describing their own call
sequences.

A step's `path` and `body` may reference an earlier step's response with
`{{step_id.dotted.path}}`; `0` indexes into a list. The reference survives
into the corpus unresolved so Phase 2 can re-resolve it on replay.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

SCENARIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "scenarios"


class ScenarioError(ValueError):
    """A scenario file is malformed."""


@dataclass(frozen=True)
class Step:
    step: str
    method: str
    path: str
    body: dict[str, str] | None = None
    note: str = ""


@dataclass(frozen=True)
class Scenario:
    workflow: str
    description: str
    steps: tuple[Step, ...]
    targets: tuple[str, ...] = ()
    note: str = ""


def parse(data: dict, source: str = "<dict>") -> Scenario:
    for field in ("workflow", "description", "steps"):
        if field not in data:
            raise ScenarioError(f"{source}: missing field {field!r}")
    if not data["steps"]:
        raise ScenarioError(f"{source}: no steps")
    steps = []
    seen = set()
    for raw in data["steps"]:
        for field in ("step", "method", "path"):
            if field not in raw:
                raise ScenarioError(f"{source}: step missing field {field!r}")
        if raw["step"] in seen:
            raise ScenarioError(f"{source}: duplicate step id {raw['step']!r}")
        seen.add(raw["step"])
        steps.append(Step(
            step=raw["step"],
            method=raw["method"].upper(),
            path=raw["path"],
            body=raw.get("body"),
            note=raw.get("note", ""),
        ))
    return Scenario(
        workflow=data["workflow"],
        description=data["description"],
        steps=tuple(steps),
        targets=tuple(data.get("targets", ())),
        note=data.get("note", ""),
    )


def load(path: pathlib.Path) -> Scenario:
    return parse(json.loads(path.read_text()), source=path.name)


def load_all(directory: pathlib.Path = SCENARIO_DIR) -> list[Scenario]:
    return [load(p) for p in sorted(directory.glob("*.json"))]
