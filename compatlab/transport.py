"""Where the Stripe test-mode key comes from, in one place.

The CLI and the generated pinned suite both need it, and a second copy of
"read .env, check the prefix, refuse otherwise" is the kind of duplicate that
ends up with only one of the two refusing a live key.
"""

from __future__ import annotations

import pathlib

from dotenv import dotenv_values

TEST_KEY_PREFIX = "sk_test_"


class MissingKey(RuntimeError):
    """No usable test-mode key."""


def stripe_key(root: pathlib.Path) -> str:
    """The test-mode key from `<root>/.env`. A live key is refused outright."""
    key = dotenv_values(root / ".env").get("STRIPE_SECRET_KEY", "") or ""
    if not key.startswith(TEST_KEY_PREFIX):
        raise MissingKey(
            "STRIPE_SECRET_KEY missing or not a test-mode key (.env); refusing.")
    return key
