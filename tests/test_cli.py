"""The CLI, including the exit code CI depends on."""

from __future__ import annotations

import json

from compatlab.cli import main
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
