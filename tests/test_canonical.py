"""Canonicalization: remove run-specific noise, keep behavioral signal."""

from __future__ import annotations

from compatlab.canonical import (
    build_id_map,
    canonical_record,
    canonical_side,
    canonicalize,
    diff_paths,
    run_start,
)

ORIGIN = 1_793_800_000


def rec(step: str, body: dict, seq: int = 0, status: int = 200,
        workflow: str = "w", path: str = "/v1/x") -> dict:
    return {
        "schema": 1, "id": "x", "workflow": workflow, "step": step, "seq": seq,
        "method": "POST", "path": path, "path_template": path, "query": {},
        "request_body": None, "stripe_version": "2022-11-15",
        "captured_at": "2026-11-04T00:00:00Z", "redaction": {"policy": "stripe"},
        "response": {"status": status,
                     "headers": {"request-id": f"req_{seq}",
                                 "stripe-version": "2022-11-15"},
                     "body": body},
    }


def test_ids_are_normalized_by_the_step_that_created_them():
    records = [rec("create_customer", {"id": "cus_AAAAAAAAAAAA"})]
    id_map = build_id_map(records)
    assert id_map["cus_AAAAAAAAAAAA"] == "<id:create_customer>"
    later = canonicalize({"customer": "cus_AAAAAAAAAAAA"}, id_map, ORIGIN)
    assert later == {"customer": "<id:create_customer>"}


def test_an_id_with_no_known_provenance_falls_back_to_its_prefix():
    out = canonicalize({"latest_charge": "ch_3ZZZZZZZZZZZZ"}, {}, ORIGIN)
    assert out == {"latest_charge": "<id:ch>"}


def test_an_underscore_joined_prefix_is_recognized():
    # `il_tmp_...` on a preview line item; the A/A control found this one.
    out = canonicalize({"id": "il_tmp_16fe62Atx0eklzIQ433017bd"}, {}, ORIGIN)
    assert out == {"id": "<id:il_tmp>"}


def test_a_prefixless_id_is_still_registered_by_provenance():
    # A Coupon id is a bare 8-character string; the control found this too.
    id_map = build_id_map([rec("create_coupon", {"id": "UVy4x6PO"})])
    assert id_map["UVy4x6PO"] == "<id:create_coupon>"


def test_ids_inside_other_strings_are_replaced():
    id_map = {"in_ABCDEFGHIJKL": "<id:create_invoice>"}
    out = canonicalize({"url": "/v1/invoices/in_ABCDEFGHIJKL/lines"},
                       id_map, ORIGIN)
    assert out == {"url": "/v1/invoices/<id:create_invoice>/lines"}


def test_timestamps_are_bucketed_by_day_not_erased():
    out = canonicalize(
        {"created": ORIGIN + 30, "period_end": ORIGIN + 30 * 86_400},
        {}, ORIGIN,
    )
    # Two runs minutes apart agree; a period a month out stays distinguishable.
    assert out == {"created": "<ts+0d>", "period_end": "<ts+30d>"}


def test_non_epoch_integers_and_booleans_pass_through():
    out = canonicalize({"amount": 1099, "count": 3, "livemode": False},
                       {}, ORIGIN)
    assert out == {"amount": 1099, "count": 3, "livemode": False}


def test_run_start_is_the_earliest_response_timestamp():
    records = [rec("a", {"created": ORIGIN + 500}),
               rec("b", {"created": ORIGIN}, seq=1)]
    assert run_start(records) == ORIGIN


def test_volatile_values_collapse_to_a_key_named_token():
    out = canonicalize({"outcome": {"risk_score": 21},
                        "card": {"authorization_code": "251702"}}, {}, ORIGIN)
    assert out["outcome"]["risk_score"] == "<risk-score>"
    assert out["card"]["authorization_code"] == "<auth-code>"


def test_invoice_prefix_keeps_provenance_when_this_run_created_it():
    records = [rec("create_subscriber", {"id": "cus_AAAAAAAAAAAA",
                                         "invoice_prefix": "QLG9U3Z7"})]
    id_map = build_id_map(records)
    mine = canonicalize({"invoice_prefix": "QLG9U3Z7"}, id_map, ORIGIN)
    assert mine == {"invoice_prefix": "<invoice_prefix:create_subscriber>"}
    # A customer left over from an earlier run collapses to the flat token:
    # list endpoints return account state that outlives a run.
    theirs = canonicalize({"invoice_prefix": "XXPF38WC"}, id_map, ORIGIN)
    assert theirs == {"invoice_prefix": "<invoice-prefix>"}


def test_an_invoice_number_keeps_its_sequence():
    id_map = build_id_map([rec("create_subscriber",
                               {"id": "cus_AAAAAAAAAAAA",
                                "invoice_prefix": "QLG9U3Z7"})])
    out = canonicalize({"number": "QLG9U3Z7-0001"}, id_map, ORIGIN)
    assert out == {"number": "<invoice_prefix:create_subscriber>-0001"}


def test_volatile_headers_are_tokenized_including_the_version():
    out = canonical_record(rec("a", {}), {}, ORIGIN)
    assert out["headers"] == {"request-id": "<request-id>",
                              "stripe-version": "<version>"}


def test_canonical_side_keys_by_workflow_and_step():
    side = canonical_side([rec("a", {}), rec("b", {}, seq=1)])
    assert sorted(side) == [("w", "a"), ("w", "b")]


def test_two_runs_of_the_same_shape_canonicalize_identically():
    one = [rec("create_customer", {"id": "cus_AAAAAAAAAAAA",
                                   "created": ORIGIN, "email": "a@b.co"})]
    two = [rec("create_customer", {"id": "cus_BBBBBBBBBBBB",
                                   "created": ORIGIN + 90, "email": "a@b.co"})]
    assert canonical_side(one) == canonical_side(two)


def test_diff_paths_reports_leaves_sides_and_lengths():
    assert diff_paths({"a": 1}, {"a": 2}) == ["$.a: 1 != 2"]
    assert diff_paths({"a": 1}, {}) == ["$.a: only in A = 1"]
    assert diff_paths({}, {"b": 2}) == ["$.b: only in B = 2"]
    assert diff_paths({"d": [1]}, {"d": [1, 2]}) == ["$.d: length 1 != 2"]
    assert diff_paths({"n": {"x": 1}}, {"n": {"x": 1}}) == []


def test_diff_paths_truncates_long_values():
    [line] = diff_paths({"k": "x" * 400}, {"k": "y" * 400})
    assert len(line) < 160
