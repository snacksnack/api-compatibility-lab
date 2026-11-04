"""Scenario parsing, plus a static check over the shipped workflows."""

from __future__ import annotations

import pytest

from compatlab.capture import REFERENCE_RE
from compatlab.scenarios import SCENARIO_DIR, ScenarioError, load_all, parse

MINIMAL = {"workflow": "w", "description": "d",
           "steps": [{"step": "a", "method": "post", "path": "/v1/x"}]}


def test_parse_normalizes_the_method_and_defaults_the_rest():
    scenario = parse(MINIMAL)
    assert scenario.steps[0].method == "POST"
    assert scenario.steps[0].body is None
    assert scenario.targets == ()


def test_a_missing_field_names_the_source():
    with pytest.raises(ScenarioError, match="x.json: missing field 'description'"):
        parse({"workflow": "w", "steps": []}, source="x.json")


def test_no_steps_is_an_error():
    with pytest.raises(ScenarioError, match="no steps"):
        parse({"workflow": "w", "description": "d", "steps": []})


def test_a_duplicate_step_id_is_an_error():
    data = {**MINIMAL, "steps": MINIMAL["steps"] * 2}
    with pytest.raises(ScenarioError, match="duplicate step id 'a'"):
        parse(data)


def test_the_shipped_scenarios_parse_and_have_unique_names():
    scenarios = load_all(SCENARIO_DIR)
    assert len(scenarios) >= 4
    names = [s.workflow for s in scenarios]
    assert len(names) == len(set(names))


def test_every_shipped_reference_points_at_an_earlier_step():
    # A forward or misspelled reference would only surface as a skipped step
    # during a live capture, which is an expensive place to find a typo.
    for scenario in load_all(SCENARIO_DIR):
        seen: set[str] = set()
        for step in scenario.steps:
            targets = [step.path, *(step.body or {}).values()]
            for text in targets:
                for ref in REFERENCE_RE.findall(str(text)):
                    name = ref.strip().partition(".")[0]
                    assert name in seen, (
                        f"{scenario.workflow}.{step.step} references {name!r}, "
                        f"which is not an earlier step"
                    )
            seen.add(step.step)
