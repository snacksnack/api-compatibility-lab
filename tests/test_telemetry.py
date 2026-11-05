"""The quality gauges, and the ways a telemetry call must fail quietly."""

from __future__ import annotations

import httpx
import pytest

from compatlab import telemetry


def test_the_payload_is_a_gauge_not_a_count():
    """Four runs an hour that each caught 4 breaks must not read as 16."""
    payload = telemetry.series_payload({"detection.caught": 4}, at=1)
    series = payload["series"][0]
    assert series["type"] == telemetry.GAUGE == 3
    assert series["metric"] == "compatlab.detection.caught"
    assert series["points"] == [{"timestamp": 1, "value": 4}]


def test_every_series_carries_service_env_and_version(monkeypatch):
    monkeypatch.setenv("DD_ENV", "ci")
    monkeypatch.setenv("DD_VERSION", "1.2.3")
    tags = telemetry.series_payload({"a": 1})["series"][0]["tags"]
    assert "service:api-compatibility-lab" in tags
    assert "env:ci" in tags
    assert "version:1.2.3" in tags


def test_a_batch_is_one_payload_sorted_by_metric():
    payload = telemetry.series_payload({"b": 2, "a": 1})
    assert [s["metric"] for s in payload["series"]] == ["compatlab.a", "compatlab.b"]


def test_extra_tags_are_joined_on():
    tags = telemetry.series_payload({"a": 1}, tags={"run": "x"})["series"][0]["tags"]
    assert "run:x" in tags


def test_submitting_without_a_key_declines_rather_than_raising(monkeypatch):
    monkeypatch.delenv("DD_API_KEY", raising=False)
    assert telemetry.submit({"a": 1}) is False


def test_a_rejected_payload_is_loud_and_still_does_not_raise(monkeypatch, capsys):
    """A swallowed 400 is indistinguishable from no traffic (RC1-440)."""
    monkeypatch.setenv("DD_API_KEY", "fake")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(
        400, text="bad payload"))
    assert telemetry.submit({"a": 1}) is False
    assert "400" in capsys.readouterr().err


def test_a_transport_failure_is_reported_and_swallowed(monkeypatch, capsys):
    monkeypatch.setenv("DD_API_KEY", "fake")

    def boom(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "post", boom)
    assert telemetry.submit({"a": 1}) is False
    assert "not submitted" in capsys.readouterr().err


def test_an_accepted_payload_returns_true(monkeypatch):
    monkeypatch.setenv("DD_API_KEY", "fake")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(202))
    assert telemetry.submit({"a": 1}) is True


@pytest.mark.parametrize("name", ["package_version", "base_tags"])
def test_the_helpers_are_callable_without_an_environment(name):
    assert getattr(telemetry, name)()
