"""The corpus file format and its write-time validation."""

from __future__ import annotations

import pytest

from compatlab.corpus import SCHEMA, files, read, validate, write


def make_record(**overrides) -> dict:
    rec = {
        "schema": SCHEMA, "id": "abc123", "workflow": "w", "step": "s",
        "seq": 0, "method": "GET", "path": "/v1/x", "path_template": "/v1/x",
        "stripe_version": "2022-11-15", "captured_at": "2026-11-04T00:00:00Z",
        "redaction": {"policy": "stripe"},
        "response": {"status": 200, "headers": {}, "body": {}},
    }
    rec.update(overrides)
    return rec


def test_a_complete_record_validates():
    assert validate(make_record()) == []


def test_missing_fields_are_each_reported():
    rec = make_record()
    del rec["workflow"], rec["path_template"]
    problems = validate(rec)
    assert "missing field: workflow" in problems
    assert "missing field: path_template" in problems


def test_an_older_schema_is_rejected():
    assert "unsupported schema: None" in validate(make_record(schema=None))


def test_a_malformed_response_is_reported():
    assert "response is not an object" in validate(make_record(response="200"))
    problems = validate(make_record(response={"status": 200}))
    assert "missing response field: body" in problems


def test_write_refuses_an_invalid_record(tmp_path):
    path = tmp_path / "c.jsonl"
    with pytest.raises(ValueError, match="refusing to write"):
        write(path, [make_record(), make_record(schema=99)])


def test_roundtrip_preserves_records(tmp_path):
    path = tmp_path / "nested" / "c.jsonl"
    records = [make_record(seq=i, id=f"r{i}") for i in range(3)]
    assert write(path, records) == 3
    assert read(path) == records


def test_files_lists_a_directory_or_a_single_file(tmp_path):
    (tmp_path / "b.jsonl").write_text("")
    (tmp_path / "a.jsonl").write_text("")
    (tmp_path / "notes.md").write_text("ignored")
    assert [p.name for p in files(tmp_path)] == ["a.jsonl", "b.jsonl"]
    assert [p.name for p in files(tmp_path / "a.jsonl")] == ["a.jsonl"]
