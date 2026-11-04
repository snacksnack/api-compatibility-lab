"""The integration inventory and the gates that keep it honest.

Most of these tests are about validation failing. That is the point of the
module: a declaration is the one input to Phase 4 that a human writes by hand,
so every way it can be wrong has to be a build failure rather than a confident
sentence in a customer-facing report.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from compatlab.workflows import (
    CRITICALITIES,
    USE_SUMMARY,
    USES,
    DeclarationError,
    load,
    load_all,
    validate,
)

CANON = {
    ("checkout", "create_intent"): {
        "status": 200,
        "body": {"id": "pi_1", "capture_method": "automatic",
                 "amount": 1099, "nothing": None},
    },
    ("checkout", "confirm_intent"): {
        "status": 200,
        "body": {"id": "pi_1", "status": "succeeded",
                 "data": [{"amount": 1099}]},
    },
}
SEQS = {("checkout", "create_intent"): 0, ("checkout", "confirm_intent"): 1}

GOOD = {
    "workflow": "card_payment",
    "purpose": "Takes a payment.",
    "criticality": "high",
    "owner": "Payments",
    "sequence": [
        {"corpus": "checkout.create_intent", "reads": [
            {"locus": "$.body.id", "use": "request_input",
             "feeds": "checkout.confirm_intent", "note": "confirmed next"},
            {"locus": "$.body.capture_method", "use": "decision",
             "note": "routes to the ops queue"},
        ]},
        {"corpus": "checkout.confirm_intent", "reads": [
            {"locus": "$.body.status", "use": "decision", "note": "paid?"},
        ]},
    ],
}


def write(tmp_path: pathlib.Path, *declarations: dict) -> pathlib.Path:
    for index, declaration in enumerate(declarations):
        (tmp_path / f"{index:02d}.json").write_text(json.dumps(declaration))
    return tmp_path


def tweak(**changes) -> dict:
    return {**json.loads(json.dumps(GOOD)), **changes}


def test_a_well_formed_declaration_loads(tmp_path):
    workflow = load(write(tmp_path, GOOD) / "00.json")
    assert workflow.name == "card_payment"
    assert workflow.length == 2
    assert len(workflow.reads) == 3
    assert workflow.position(("checkout", "confirm_intent")) == 2
    assert workflow.position(("checkout", "nope")) is None


def test_the_round_trip_through_to_dict_is_lossless(tmp_path):
    workflow = load(write(tmp_path, GOOD) / "00.json")
    assert workflow.to_dict() == GOOD


def test_a_good_declaration_validates_against_the_traffic(tmp_path):
    result = validate(load_all(write(tmp_path, GOOD)), CANON, SEQS)
    assert result.ok, result.problems
    assert result.steps_checked == 2
    assert result.reads_checked == 3


@pytest.mark.parametrize("key", ["workflow", "purpose", "criticality",
                                 "owner", "sequence"])
def test_a_declaration_missing_a_required_field_is_refused(tmp_path, key):
    bad = tweak(**{key: ""})
    with pytest.raises(DeclarationError, match=key):
        load(write(tmp_path, bad) / "00.json")


def test_an_unknown_criticality_is_refused(tmp_path):
    with pytest.raises(DeclarationError, match="criticality"):
        load(write(tmp_path, tweak(criticality="urgent")) / "00.json")
    assert set(CRITICALITIES) == {"high", "medium", "low"}


def test_an_unknown_use_is_refused(tmp_path):
    bad = tweak()
    bad["sequence"][0]["reads"][0]["use"] = "vibes"
    with pytest.raises(DeclarationError, match="unknown use"):
        load(write(tmp_path, bad) / "00.json")


def test_a_read_with_no_note_is_refused(tmp_path):
    """The note is the integration knowledge; a read without one is noise."""
    bad = tweak()
    del bad["sequence"][0]["reads"][1]["note"]
    with pytest.raises(DeclarationError, match="note"):
        load(write(tmp_path, bad) / "00.json")


def test_a_corpus_reference_without_a_step_is_refused(tmp_path):
    bad = tweak()
    bad["sequence"][0]["corpus"] = "checkout"
    with pytest.raises(DeclarationError, match="corpus"):
        load(write(tmp_path, bad) / "00.json")


def test_two_declarations_cannot_claim_the_same_workflow_name(tmp_path):
    with pytest.raises(DeclarationError, match="already declared"):
        load_all(write(tmp_path, GOOD, GOOD))


def test_invalid_json_names_the_file(tmp_path):
    (tmp_path / "00.json").write_text("{not json")
    with pytest.raises(DeclarationError, match="not valid JSON"):
        load_all(tmp_path)


# --- the four gates that compare a declaration against the captured traffic


def test_a_step_the_corpus_never_captured_fails_validation(tmp_path):
    bad = tweak()
    bad["sequence"][1]["corpus"] = "checkout.never_happened"
    result = validate(load_all(write(tmp_path, bad)), CANON, SEQS)
    assert not result.ok
    assert any("no such step in the version-A corpus" in p
               for p in result.problems), result.problems


def test_a_sequence_that_runs_backwards_fails_validation(tmp_path):
    """A customer workflow has to be replayable from the captured order."""
    bad = tweak()
    bad["sequence"] = list(reversed(bad["sequence"]))
    bad["sequence"][1]["reads"][0]["feeds"] = "checkout.create_intent"
    result = validate(load_all(write(tmp_path, bad)), CANON, SEQS)
    assert not result.ok
    assert any("captured later" in p for p in result.problems)


def test_the_same_step_declared_twice_fails_validation(tmp_path):
    bad = tweak()
    bad["sequence"].append({"corpus": "checkout.confirm_intent", "reads": []})
    result = validate(load_all(write(tmp_path, bad)), CANON, SEQS)
    assert not result.ok
    assert any("declared twice" in p for p in result.problems)


def test_a_locus_absent_from_the_version_a_response_fails_validation(tmp_path):
    """A stale integration note, which is how this gate earns its keep."""
    bad = tweak()
    bad["sequence"][0]["reads"][1]["locus"] = "$.body.capture_mode"
    result = validate(load_all(write(tmp_path, bad)), CANON, SEQS)
    assert not result.ok
    assert any("stale" in p for p in result.problems)


def test_a_locus_that_is_present_but_null_passes_validation(tmp_path):
    """Null is a value a client can read; absent is not."""
    good = tweak()
    good["sequence"][0]["reads"][1]["locus"] = "$.body.nothing"
    assert validate(load_all(write(tmp_path, good)), CANON, SEQS).ok


def test_an_unparseable_or_unreadable_locus_fails_validation(tmp_path):
    for locus, expected in (("body.id", "must start"),
                            ("$.duration_ms", "must name")):
        bad = tweak()
        bad["sequence"][0]["reads"][1]["locus"] = locus
        result = validate(load_all(write(tmp_path, bad)), CANON, SEQS)
        assert not result.ok
        assert any(expected in p for p in result.problems), result.problems


def test_a_request_input_read_with_no_feeds_fails_validation(tmp_path):
    bad = tweak()
    del bad["sequence"][0]["reads"][0]["feeds"]
    result = validate(load_all(write(tmp_path, bad)), CANON, SEQS)
    assert not result.ok
    assert any("names no `feeds`" in p for p in result.problems)


def test_a_request_input_read_feeding_a_step_that_is_not_later_fails(tmp_path):
    bad = tweak()
    bad["sequence"][0]["reads"][0]["feeds"] = "checkout.create_intent"
    result = validate(load_all(write(tmp_path, bad)), CANON, SEQS)
    assert not result.ok
    assert any("not a later step" in p for p in result.problems)


def test_every_use_has_a_summary_for_the_report():
    assert set(USE_SUMMARY) == set(USES)
