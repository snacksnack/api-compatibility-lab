"""Replay: corpus-driven, per-side reference resolution, pairing."""

from __future__ import annotations

import httpx

from compatlab.redaction import STRIPE_POLICY
from compatlab.replay import pair, plan, replay_corpus, replay_workflow

POLICY = STRIPE_POLICY.with_salt(b"test-salt")


def stored(step: str, seq: int, method: str = "POST",
           path_reference: str = "/v1/customers",
           request_template: dict | None = None,
           workflow: str = "checkout", targets: list[str] | None = None) -> dict:
    return {
        "schema": 1, "id": f"r{seq}", "workflow": workflow, "step": step,
        "seq": seq, "method": method, "path": path_reference,
        "path_template": path_reference, "path_reference": path_reference,
        "query": {}, "request_body": request_template,
        "request_template": request_template, "targets": targets or [],
        "stripe_version": "2022-11-15", "captured_at": "2026-11-04T00:00:00Z",
        "redaction": {"policy": "stripe"},
        "response": {"status": 200, "headers": {}, "body": {}},
    }


CORPUS = [
    stored("create", 0, request_template={"email": "redacted-1@example.invalid"}),
    stored("fetch", 1, method="GET", path_reference="/v1/customers/{{create.id}}"),
    stored("other", 2, workflow="errors", method="GET",
           path_reference="/v1/charges?limit=1"),
]


def make_client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://api.example.test",
                        transport=httpx.MockTransport(handler))


def test_plan_groups_workflows_and_preserves_captured_order():
    grouped = dict(plan(list(reversed(CORPUS))))
    assert [s.step for s in grouped["checkout"]] == ["create", "fetch"]
    assert [s.step for s in grouped["errors"]] == ["other"]


def test_plan_falls_back_to_path_when_no_reference_was_stored():
    record = stored("x", 0)
    del record["path_reference"]
    assert plan([record])[0][1][0].path_reference == "/v1/customers"


def test_replay_resolves_references_against_this_sides_own_ids():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, headers={"stripe-version": "2025-03-31.basil"},
                              json={"id": "cus_SIDE_B_ID"})

    with make_client(handler) as client:
        report = replay_corpus(client, CORPUS, "2025-03-31.basil", policy=POLICY)

    # The stored corpus referenced version A's customer; side B must have used
    # the id its own run produced, not the recorded one.
    assert seen[1].endswith("/v1/customers/cus_SIDE_B_ID")
    assert [r["stripe_version"] for r in report.records] == \
        ["2025-03-31.basil"] * 3
    assert report.warnings == []


def test_replay_warns_when_the_served_version_is_not_the_requested_one():
    # Canonicalization drops the version header from the comparison, so this
    # check is the only thing standing between a typo and a replay that
    # silently ran both sides on the same version.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"stripe-version": "2022-11-15"},
                              json={"id": "cus_1"})

    with make_client(handler) as client:
        report = replay_corpus(client, CORPUS, "2025-03-31.basil", policy=POLICY)

    assert len(report.warnings) == 3
    assert "requested 2025-03-31.basil, served 2022-11-15" in report.warnings[0][1]


def test_a_step_is_skipped_when_this_side_cannot_resolve_it():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "nope"}})

    with make_client(handler) as client:
        report = replay_workflow(client, plan(CORPUS)[0][1], "2022-11-15",
                                 policy=POLICY)

    assert [r["step"] for r in report.records] == ["create"]
    assert report.skipped == [("checkout.fetch", "id: no key 'id'")]


def test_replay_carries_targets_and_seq_through_from_the_corpus():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "cus_1"})

    with make_client(handler) as client:
        report = replay_corpus(client, [stored("s", 7, targets=["M1"])],
                               "2022-11-15", policy=POLICY)
    assert report.records[0]["seq"] == 7
    assert report.records[0]["targets"] == ["M1"]


def test_pair_matches_on_workflow_and_step_in_sequence_order():
    side_a = [stored("create", 0), stored("fetch", 1)]
    side_b = [stored("fetch", 1), stored("create", 0)]
    pairs = pair(side_a, side_b)
    assert [p["step"] for p in pairs] == ["create", "fetch"]
    assert all(p["a"] and p["b"] for p in pairs)


def test_a_step_missing_from_one_side_is_still_a_pair():
    # A step that could not even be sent against the new version is among the
    # most severe findings there is; dropping it would hide it from Phase 3.
    pairs = pair([stored("create", 0), stored("fetch", 1)], [stored("create", 0)])
    missing = [p for p in pairs if p["b"] is None]
    assert [p["step"] for p in missing] == ["fetch"]

    pairs = pair([stored("create", 0)], [stored("create", 0), stored("new", 1)])
    assert [p["step"] for p in pairs if p["a"] is None] == ["new"]
