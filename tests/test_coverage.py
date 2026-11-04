"""Coverage stats over a corpus."""

from __future__ import annotations

from compatlab.coverage import GROUND_TRUTH_M, render, summarize


def rec(workflow: str, method: str, template: str, status: int,
        targets: list[str] | None = None) -> dict:
    return {
        "workflow": workflow, "method": method, "path_template": template,
        "stripe_version": "2022-11-15", "targets": targets or [],
        "response": {"status": status, "headers": {}, "body": {}},
    }


RECORDS = [
    rec("checkout", "POST", "/v1/payment_intents", 200, ["M1", "M2"]),
    rec("checkout", "GET", "/v1/payment_intents/{id}", 200, ["M1", "M2"]),
    rec("checkout", "POST", "/v1/payment_intents", 400, ["M1", "M2"]),
    rec("errors", "GET", "/v1/customers", 404),
]


def test_endpoints_group_by_method_and_template_with_status_counts():
    summary = summarize(RECORDS)
    by_path = {(e["method"], e["path"]): e for e in summary["endpoints"]}
    assert by_path[("POST", "/v1/payment_intents")]["calls"] == 2
    assert by_path[("POST", "/v1/payment_intents")]["statuses"] == {200: 1, 400: 1}
    assert summary["records"] == 4
    assert summary["statuses"] == {200: 2, 400: 1, 404: 1}
    assert summary["versions"] == {"2022-11-15": 3 + 1}


def test_workflows_split_success_from_error_counts():
    summary = summarize(RECORDS)
    checkout = next(w for w in summary["workflows"] if w["workflow"] == "checkout")
    assert (checkout["calls"], checkout["ok"], checkout["errors"]) == (3, 2, 1)


def test_targets_map_a_ground_truth_break_to_the_workflows_that_reach_it():
    assert summarize(RECORDS)["targets"] == {"M1": ["checkout"], "M2": ["checkout"]}


def test_render_states_the_denominator_rather_than_only_what_was_covered():
    out = render(summarize(RECORDS), GROUND_TRUTH_M)
    assert f"Ground-truth breaks exercised: 2 of {GROUND_TRUTH_M}" in out
    assert "| POST | `/v1/payment_intents` | 2 | 200×1, 400×1 |" in out


def test_an_empty_corpus_renders_without_dividing_by_anything():
    out = render(summarize([]), GROUND_TRUTH_M)
    assert "Records: 0" in out
