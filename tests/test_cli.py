"""The CLI, including the exit code CI depends on."""

from __future__ import annotations

import json

from compatlab.cli import _mismatches, main
from compatlab.corpus import SCHEMA, write


def make_record(body: dict, step: str = "s") -> dict:
    return {
        "schema": SCHEMA, "id": "abc123", "workflow": "w", "step": step,
        "seq": 0, "method": "POST", "path": "/v1/customers",
        "path_template": "/v1/customers", "targets": ["M1"],
        "stripe_version": "2022-11-15", "captured_at": "2026-11-04T00:00:00Z",
        "redaction": {"policy": "stripe"},
        "response": {"status": 200, "headers": {}, "body": body},
    }


def test_scan_exits_non_zero_on_a_corpus_with_pii(tmp_path, capsys):
    path = tmp_path / "leaky.jsonl"
    write(path, [make_record({"email": "ada@lovelace.org"})])
    assert main(["scan", str(path)]) == 1
    out = capsys.readouterr().out
    assert "finding:" in out and "FAIL" in out
    assert "lovelace" not in out


def test_scan_exits_zero_on_a_redacted_corpus(tmp_path, capsys):
    path = tmp_path / "clean.jsonl"
    write(path, [make_record({"email": "redacted-0123abcd@example.invalid"})])
    assert main(["scan", str(path)]) == 0
    assert "PASS: zero findings" in capsys.readouterr().out


def test_scan_reports_a_record_the_format_does_not_accept(tmp_path, capsys):
    path = tmp_path / "old.jsonl"
    path.write_text(json.dumps({"id": "x"}) + "\n")
    assert main(["scan", str(path)]) == 1
    assert "invalid:" in capsys.readouterr().out


def test_coverage_renders_json_and_markdown(tmp_path, capsys):
    path = tmp_path / "c.jsonl"
    write(path, [make_record({}, step="a"), make_record({}, step="b")])
    assert main(["coverage", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["records"] == 2
    assert main(["coverage", str(path)]) == 0
    assert "Ground-truth breaks exercised: 1 of 8" in capsys.readouterr().out


def test_capture_dry_run_needs_neither_a_key_nor_a_network(capsys):
    assert main(["capture", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "checkout_card_payment: create_customer" in out


def test_capture_rejects_an_unknown_scenario(capsys):
    try:
        main(["capture", "--dry-run", "--scenario", "nope"])
    except SystemExit as exit_code:
        assert "no such scenario: nope" in str(exit_code)
    else:
        raise AssertionError("expected SystemExit")


def control_record(step: str, body: dict, seq: int = 0) -> dict:
    rec = make_record(body, step=step)
    rec["seq"] = seq
    return rec


def test_mismatches_is_empty_when_two_runs_differ_only_in_run_specific_values():
    one = [control_record("create", {"id": "cus_AAAAAAAAAAAA",
                                     "created": 1_793_800_000})]
    two = [control_record("create", {"id": "cus_BBBBBBBBBBBB",
                                     "created": 1_793_800_120})]
    assert _mismatches(one, two) == {}


def test_mismatches_reports_a_real_difference_per_step():
    one = [control_record("create", {"capture_method": "automatic"})]
    two = [control_record("create", {"capture_method": "automatic_async"})]
    out = _mismatches(one, two)
    assert list(out) == ["w.create"]
    assert "capture_method" in out["w.create"][0]


def test_mismatches_flags_a_step_present_on_only_one_side():
    out = _mismatches([control_record("create", {})],
                      [control_record("create", {}), control_record("extra", {}, 1)])
    assert "present on only one side" in out["w.extra"][0]


def pair_line(a_body: dict, b_body: dict, *, status_b: int = 200) -> str:
    a = make_record(a_body)
    b = make_record(b_body)
    b["response"]["status"] = status_b
    b["stripe_version"] = "2025-03-31.basil"
    return json.dumps({
        "workflow": "w", "step": "s", "seq": 0, "method": "POST",
        "path_template": "/v1/customers", "targets": ["M1"], "a": a, "b": b,
    })


def test_diff_writes_findings_and_prints_the_rule_and_the_reason(tmp_path, capsys):
    pairs = tmp_path / "pairs.jsonl"
    pairs.write_text(pair_line({"capture_method": "automatic"},
                               {"capture_method": "automatic_async"}) + "\n")
    out = tmp_path / "findings.jsonl"
    assert main(["diff", "--pairs", str(pairs), "--out", str(out), "--why"]) == 0
    printed = capsys.readouterr().out
    assert "enum-value-changed" in printed
    assert "changed server default" in printed
    written = [json.loads(line) for line in out.read_text().splitlines()]
    assert [f["rule"] for f in written] == ["enum-value-changed"]
    assert written[0]["severity"] == "breaking"


def test_diff_can_print_one_severity_only(tmp_path, capsys):
    pairs = tmp_path / "pairs.jsonl"
    pairs.write_text(pair_line({"a": 1}, {"a": 1, "added": None}) + "\n")
    main(["diff", "--pairs", str(pairs), "--out", str(tmp_path / "f.jsonl"),
          "--severity", "breaking"])
    printed = capsys.readouterr().out
    assert "field-added-empty" not in printed
    assert "1 benign" in printed


def test_diff_refuses_to_finish_if_a_finding_quotes_unredacted_data(tmp_path,
                                                                   capsys):
    pairs = tmp_path / "pairs.jsonl"
    pairs.write_text(pair_line({"email": "ada@lovelace.org"},
                               {"email": "grace@hopper.org"}) + "\n")
    assert main(["diff", "--pairs", str(pairs),
                 "--out", str(tmp_path / "f.jsonl")]) == 1
    assert "REFUSING to stop here" in capsys.readouterr().out


def test_diff_renders_json_when_asked(tmp_path, capsys):
    pairs = tmp_path / "pairs.jsonl"
    pairs.write_text(pair_line({"x": 1}, {"x": 2}) + "\n")
    main(["diff", "--pairs", str(pairs), "--out", str(tmp_path / "f.jsonl"),
          "--json"])
    payload = json.loads(capsys.readouterr().out.split("\nwrote")[0])
    assert payload["steps_compared"] == 1
    assert payload["detail"][0]["axis"] == "value"


def test_score_exits_non_zero_while_a_breaking_finding_is_unadjudicated(
        tmp_path, capsys):
    pairs = tmp_path / "pairs.jsonl"
    pairs.write_text(pair_line({"x": 1}, {"x": 2}) + "\n")
    index = tmp_path / "index.jsonl"
    index.write_text(json.dumps({
        "record": "meta", "rules": [], "entries_matched_paths": 0,
        "entries_corpus_endpoints": 0, "entries_unscoped": 0,
        "oasdiff": {"build": "test"},
    }) + "\n")
    adjudication = tmp_path / "adjudication.json"
    adjudication.write_text(json.dumps({"verdicts": []}))
    code = main(["score", "--pairs", str(pairs), "--baseline", str(index),
                 "--adjudication", str(adjudication)])
    assert code == 1
    assert "no verdict" in capsys.readouterr().out
