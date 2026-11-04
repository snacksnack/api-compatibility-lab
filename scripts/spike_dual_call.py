"""RC1-605 spike: send the same requests under two Stripe-Version headers.

Verifies the Phase 0 exit criterion: a fresh sandbox serves both pinned
versions per request, and the paired responses land in the corpus format.

Usage: put STRIPE_SECRET_KEY (test-mode) in .env, then
    uv run python scripts/spike_dual_call.py
"""

import datetime
import json
import pathlib
import sys
import uuid

import httpx
from dotenv import dotenv_values

VERSION_A = "2022-11-15"
VERSION_B = "2025-03-31.basil"
BASE_URL = "https://api.stripe.com"
CORPUS_PATH = pathlib.Path(__file__).resolve().parent.parent / "corpus" / "spike-pair.jsonl"
HEADER_WHITELIST = ("request-id", "stripe-version")
# Expected to differ between any two calls; excluded from the value diff.
NOISE_KEYS = {"id", "created", "client_secret", "livemode"}

# (name, method, path, form_body) — each chosen to surface a documented
# behavioral break from docs/ground-truth.md on at least one side.
CALLS = [
    # M1 (automatic payment methods default) + M2 (capture_method default)
    ("create_payment_intent", "POST", "/v1/payment_intents",
     {"amount": "1099", "currency": "usd"}),
    # M3: total_count expansion removed in basil
    ("list_customers_total_count", "GET",
     "/v1/customers?limit=3&expand[]=total_count", None),
    # M4: coupons without a specified end time rejected in basil
    ("create_coupon_forever", "POST", "/v1/coupons",
     {"percent_off": "10", "duration": "forever"}),
]


def record(client: httpx.Client, version: str, name: str, method: str,
           path: str, body: dict | None, seq: int) -> dict:
    resp = client.request(method, path, data=body,
                          headers={"Stripe-Version": version})
    return {
        "id": uuid.uuid4().hex[:12],
        "seq": seq,
        "call": name,
        "method": method,
        "path": path,
        "request_body": body,
        "stripe_version": version,
        "captured_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "response": {
            "status": resp.status_code,
            "headers": {k: v for k, v in resp.headers.items()
                        if k.lower() in HEADER_WHITELIST},
            "body": resp.json(),
        },
    }


def shallow_diff(a: dict, b: dict) -> list[str]:
    lines = []
    for key in sorted(set(a) | set(b)):
        if key in NOISE_KEYS:
            continue
        if key not in a:
            lines.append(f"  only in B: {key}")
        elif key not in b:
            lines.append(f"  only in A: {key}")
        elif a[key] != b[key]:
            lines.append(f"  value differs: {key}: "
                         f"{json.dumps(a[key])[:80]} -> {json.dumps(b[key])[:80]}")
    return lines


def main() -> int:
    env = dotenv_values(pathlib.Path(__file__).resolve().parent.parent / ".env")
    key = env.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        print("STRIPE_SECRET_KEY missing or not a test-mode key (.env); refusing.")
        return 1

    CORPUS_PATH.parent.mkdir(exist_ok=True)
    records = []
    with httpx.Client(base_url=BASE_URL, auth=(key, ""), timeout=30) as client:
        for seq, (name, method, path, body) in enumerate(CALLS):
            pair = {}
            for version in (VERSION_A, VERSION_B):
                pair[version] = record(client, version, name, method, path,
                                       body, seq)
            records.extend(pair.values())
            resp_a, resp_b = (pair[v]["response"] for v in (VERSION_A, VERSION_B))
            print(f"\n== {name}: A={resp_a['status']} B={resp_b['status']}")
            served_a = resp_a["headers"].get("stripe-version")
            served_b = resp_b["headers"].get("stripe-version")
            if served_a != VERSION_A or served_b != VERSION_B:
                print(f"  WARNING: served versions A={served_a} B={served_b}")
            print("\n".join(shallow_diff(resp_a["body"], resp_b["body"]))
                  or "  (no top-level differences)")

    with CORPUS_PATH.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    print(f"\nwrote {len(records)} records to {CORPUS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
