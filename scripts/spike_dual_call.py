"""RC1-605 spike: send the same requests under two Stripe-Version headers.

Verifies the Phase 0 exit criterion: a fresh sandbox serves both pinned
versions per request, and the paired responses land in the corpus format
(redacted at write time by compatlab.redaction).

Usage: put STRIPE_SECRET_KEY (test-mode) in .env, then
    uv run python scripts/spike_dual_call.py
"""

import pathlib
import sys

import httpx
from dotenv import dotenv_values

from compatlab import STRIPE_BASE_URL, VERSION_A, VERSION_B
from compatlab.capture import CaptureError, record
from compatlab.corpus import write
from compatlab.diffing import shallow_diff

CORPUS_PATH = pathlib.Path(__file__).resolve().parent.parent / "corpus" / "spike-pair.jsonl"

# (name, method, path, form_body) — each chosen to surface a documented
# behavioral break from docs/ground-truth.md on at least one side.
CALLS = [
    # M1 (automatic payment methods default) + M2 (capture_method default)
    ("create_payment_intent", "POST", "/v1/payment_intents",
     {"amount": "1099", "currency": "usd"}),
    # Account-gated on a fresh sandbox (spike finding 3): kept to pin the
    # same-status, different-error-body pair the differ must catch.
    ("list_customers_total_count", "GET",
     "/v1/customers?limit=3&expand[]=total_count", None),
    # Reversed upstream in clover (spike finding 4): kept as the live
    # evidence that changelog ground truth can be stale.
    ("create_coupon_amount_off_forever", "POST", "/v1/coupons",
     {"amount_off": "500", "currency": "usd", "duration": "forever"}),
]


def main() -> int:
    env = dotenv_values(pathlib.Path(__file__).resolve().parent.parent / ".env")
    key = env.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        print("STRIPE_SECRET_KEY missing or not a test-mode key (.env); refusing.")
        return 1

    CORPUS_PATH.parent.mkdir(exist_ok=True)
    records = []
    with httpx.Client(base_url=STRIPE_BASE_URL, auth=(key, ""), timeout=30) as client:
        for seq, (name, method, path, body) in enumerate(CALLS):
            pair = {}
            for version in (VERSION_A, VERSION_B):
                try:
                    pair[version] = record(client, version, name, method, path,
                                           body, seq,
                                           workflow="spike_version_pair")
                except CaptureError as exc:
                    print(f"capture failed: {exc}")
                    return 1
            records.extend(pair.values())
            resp_a, resp_b = (pair[v]["response"] for v in (VERSION_A, VERSION_B))
            print(f"\n== {name}: A={resp_a['status']} B={resp_b['status']}")
            served_a = resp_a["headers"].get("stripe-version")
            served_b = resp_b["headers"].get("stripe-version")
            if served_a != VERSION_A or served_b != VERSION_B:
                print(f"  WARNING: served versions A={served_a} B={served_b}")
            print("\n".join(shallow_diff(resp_a["body"], resp_b["body"]))
                  or "  (no top-level differences)")

    count = write(CORPUS_PATH, records)
    print(f"\nwrote {count} records to {CORPUS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
