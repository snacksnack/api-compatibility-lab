"""The schema-diff baseline: parsing oasdiff, indexing it, querying it.

Nothing here touches the network or a container. The generated index is a
committed artifact; these tests cover the machinery that reads and writes it,
and `test_committed_artifacts.py` covers the artifact itself.
"""

from __future__ import annotations

import json
import re
import shutil

import pytest

from compatlab.baseline import (
    OASDIFF_IMAGE,
    SPEC_PINS,
    BaselineError,
    BaselineIndex,
    _oasdiff_command,
    build_index,
    endpoint_key,
    fetch_spec,
    fields_named,
    match_path_regex,
    normalize_path,
    spec_url,
    write_index,
)

ENTRIES = [
    {"id": "response-property-enum-value-added", "operation": "POST",
     "path": "/v1/payment_intents",
     "text": "added the new `automatic_async` enum value to the "
             "`capture_method` response property for the response status `200`"},
    {"id": "response-property-enum-value-added", "operation": "POST",
     "path": "/v1/payment_intents",
     "text": "added the new `automatic_async` enum value to the "
             "`error/payment_intent/capture_method` response property"},
    {"id": "response-required-property-removed", "operation": "DELETE",
     "path": "/v1/subscriptions/{subscription_exposed_id}",
     "text": "removed the required property `current_period_end` from the "
             "response with the `200` status"},
    {"id": "api-path-removed-without-deprecation", "operation": "GET",
     "path": "/v1/invoices/upcoming",
     "text": "api path removed without deprecation"},
]


def index() -> BaselineIndex:
    return BaselineIndex.from_index(build_index(
        ENTRIES, scope=["POST /v1/payment_intents"], match="^x$", unscoped=99))


def test_the_pins_are_the_pair_the_adr_fixed():
    assert SPEC_PINS["a"][1] == "2022-11-15"
    assert SPEC_PINS["b"][1] == "2025-03-31.basil"
    assert "stripe/openapi" in spec_url(SPEC_PINS["a"][0])


def test_the_oasdiff_image_is_pinned_by_digest_not_by_tag():
    assert "@sha256:" in OASDIFF_IMAGE
    assert ":latest" not in OASDIFF_IMAGE


@pytest.mark.parametrize("path,expected", [
    ("/v1/customers/{customer}", "/v1/customers/{}"),
    ("/v1/customers/{id}", "/v1/customers/{}"),
    ("/v1/payment_intents", "/v1/payment_intents"),
])
def test_path_parameter_names_do_not_make_two_endpoints(path, expected):
    assert normalize_path(path) == expected


def test_endpoint_keys_are_method_and_normalized_path():
    assert endpoint_key("get", "/v1/customers/{customer}") == \
        "GET /v1/customers/{}"


def test_the_match_regex_covers_the_corpus_paths_and_nothing_else():
    pattern = re.compile(match_path_regex(
        ["/v1/customers", "/v1/customers/{id}", "/v1/invoices/upcoming"]))
    assert pattern.match("/v1/customers")
    assert pattern.match("/v1/customers/{customer}")
    assert pattern.match("/v1/invoices/upcoming")
    assert not pattern.match("/v1/invoices")
    assert not pattern.match("/v1/customers/{customer}/sources")


def test_field_names_are_read_generously_out_of_an_entry_text():
    # Deliberately generous: the claim is that the baseline missed things, so
    # a loose match makes the claim harder to make, not easier.
    named = fields_named(ENTRIES[1]["text"])
    assert {"capture_method", "payment_intent", "error"} <= named


def test_anyof_noise_is_stripped_before_segments_are_read():
    named = fields_named(
        "added `#/components/schemas/x` to the "
        "`charge/anyOf[subschema #2: Charge]/balance_transaction` response "
        "property `anyOf` list")
    assert "balance_transaction" in named
    assert not any("anyOf" in name for name in named)


def test_an_entry_naming_no_field_is_recorded_at_the_path_level():
    assert index().path_level("GET", "/v1/invoices/upcoming") == {
        "api-path-removed-without-deprecation": 1}


def test_rules_are_stored_as_indices_and_read_back_as_names():
    card = index()
    assert card.rules_for("POST", "/v1/payment_intents", "capture_method") == {
        "response-property-enum-value-added": 2}
    raw = card.endpoints["POST /v1/payment_intents"]["fields"]["capture_method"]
    assert list(raw) == ["0"] or all(key.isdigit() for key in raw)


def test_the_three_entry_counts_are_all_recorded_separately():
    card = index()
    assert card.entries_unscoped == 99
    assert card.entries_matched_paths == len(ENTRIES)
    assert card.entries_corpus_endpoints == 2


def test_an_unknown_endpoint_or_field_answers_empty_rather_than_raising():
    card = index()
    assert card.rules_for("GET", "/v1/nope", "field") == {}
    assert card.entry_count("GET", "/v1/nope") == 0
    assert not card.covers_endpoint("GET", "/v1/nope")


def test_the_index_round_trips_through_jsonl(tmp_path):
    built = build_index(ENTRIES, scope=[], match="^x$")
    path = tmp_path / "index.jsonl"
    assert write_index(path, built) == len(built["endpoints"])
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines[0]["record"] == "meta"
    assert all(line["record"] == "endpoint" for line in lines[1:])
    reloaded = BaselineIndex.load(path)
    assert reloaded.rules_for("DELETE", "/v1/subscriptions/{id}",
                              "current_period_end") == {
        "response-required-property-removed": 1}


def test_a_spec_that_declares_the_wrong_version_is_refused(tmp_path, monkeypatch):
    """The SHA is the contract; the version string is the check on the SHA."""
    cache = tmp_path / "specs"
    cache.mkdir()
    sha = SPEC_PINS["a"][0]
    (cache / f"spec3-{sha}.json").write_text(
        json.dumps({"info": {"version": "2099-01-01"}}))
    with pytest.raises(BaselineError, match="ADR 0001 D3"):
        fetch_spec("a", cache)


def test_a_cached_spec_with_the_right_version_is_not_refetched(tmp_path):
    cache = tmp_path / "specs"
    cache.mkdir()
    sha, version = SPEC_PINS["b"]
    path = cache / f"spec3-{sha}.json"
    path.write_text(json.dumps({"info": {"version": version}}))
    assert fetch_spec("b", cache) == path


def test_the_command_prefers_a_local_binary_and_falls_back_to_docker(tmp_path,
                                                                    monkeypatch):
    spec_a, spec_b = tmp_path / "a.json", tmp_path / "b.json"
    monkeypatch.setattr(shutil, "which",
                        lambda name: "/usr/bin/oasdiff" if name == "oasdiff" else None)
    local = _oasdiff_command(spec_a, spec_b, "^x$")
    assert local[0] == "/usr/bin/oasdiff"
    assert local[-2:] == ["-p", "^x$"]

    monkeypatch.setattr(shutil, "which",
                        lambda name: "/usr/bin/docker" if name == "docker" else None)
    containerized = _oasdiff_command(spec_a, spec_b, None)
    assert containerized[:2] == ["docker", "run"]
    assert OASDIFF_IMAGE in containerized
    assert "/specs/a.json" in containerized


def test_with_no_runtime_at_all_the_baseline_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(BaselineError, match="neither"):
        _oasdiff_command(tmp_path / "a.json", tmp_path / "b.json", None)
