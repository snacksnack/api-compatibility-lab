"""The key lookup, which both the CLI and the pinned suite go through."""

from __future__ import annotations

import pytest

from compatlab.transport import MissingKey, stripe_key


def test_a_test_mode_key_is_returned(tmp_path):
    (tmp_path / ".env").write_text("STRIPE_SECRET_KEY=sk_test_abc123\n")
    assert stripe_key(tmp_path) == "sk_test_abc123"


def test_a_live_key_is_refused_outright(tmp_path):
    """One place to refuse it, so the two callers cannot disagree."""
    (tmp_path / ".env").write_text("STRIPE_SECRET_KEY=sk_live_abc123\n")
    with pytest.raises(MissingKey):
        stripe_key(tmp_path)


def test_no_env_file_is_refused(tmp_path):
    with pytest.raises(MissingKey):
        stripe_key(tmp_path)
