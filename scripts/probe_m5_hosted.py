"""RC1-618 Stage 3 feasibility check: drive a hosted Checkout page once.

scripts/probe_m5.py settled the cheap option: a `mode=subscription` session
create is byte-identical across the pinned pair on every observable basil #4
names, so scoping Stage 3 to the create-only half exercises nothing. All three
of the entry's clauses sit behind a completed payment.

That leaves one question before the stage can be decided, and the Stage 3
handoff names it: can a test-mode hosted Checkout page be driven to completion
at all? If it cannot, the decision is made. If it can, the decision is a
judgment about the replay contract (ADR 0003 D2) rather than about capability,
and this script measures what that judgment would buy - the actual observable
difference a completed session produces.

Two phases, with a human driving a browser in between, because that is exactly
the property under examination: completion is not an HTTP call this project can
make.

    uv run python scripts/probe_m5_hosted.py create --state <path>
    # drive both printed URLs to completion with test card 4242...
    uv run python scripts/probe_m5_hosted.py read --state <path>

The state file holds live test-mode object ids and the hosted-page URLs, which
is why it is written to a path the caller names rather than anywhere in the
repo: the URL carries the session id and is exactly the value redaction drops
at capture. Nothing here writes to corpus/.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

import httpx
from dotenv import dotenv_values

from compatlab import STRIPE_BASE_URL, VERSION_A, VERSION_B
from compatlab.capture import CaptureError, call
from compatlab.redaction import STRIPE_POLICY

ABSENT = object()
LEN = "#len"
SUCCESS_URL = "https://example.com/success"
CANCEL_URL = "https://example.com/cancel"

# Read after completion. The three clauses of basil #4, in order: whether a
# subscription exists, whether an invoice exists, and what the session itself
# reports about both.
OBSERVE: tuple[tuple[str, str], ...] = (
    ("session", "status"),
    ("session", "payment_status"),
    ("session", "subscription"),
    ("session", "invoice"),
    ("session", "payment_intent"),
    ("subs", "data" + LEN),
    ("subs", "data.0.status"),
    ("subs", "data.0.latest_invoice"),
    ("invoices", "data" + LEN),
    ("invoices", "data.0.status"),
    ("invoices", "data.0.amount_paid"),
    ("invoices", "data.0.billing_reason"),
)


def read(payload: Any, dotted: str) -> Any:
    """`data.0.status` over a decoded payload; absence is an answer."""
    want_len = dotted.endswith(LEN)
    if want_len:
        dotted = dotted[: -len(LEN)]
    cursor = payload
    for part in dotted.split("."):
        if isinstance(cursor, list):
            if not part.isdigit() or int(part) >= len(cursor):
                return ABSENT
            cursor = cursor[int(part)]
        elif isinstance(cursor, dict):
            if part not in cursor:
                return ABSENT
            cursor = cursor[part]
        else:
            return ABSENT
    if want_len:
        return len(cursor) if isinstance(cursor, list) else ABSENT
    return cursor


def show(dotted: str, value: Any) -> str:
    if value is ABSENT:
        return "<absent>"
    leaf = dotted.removesuffix(LEN).rsplit(".", 1)[-1]
    redacted = STRIPE_POLICY.redact({leaf: value})[leaf]
    text = repr(redacted)
    return text if len(text) <= 90 else text[:87] + "..."


def create(client: httpx.Client, version: str) -> dict[str, str]:
    customer = call(client, version, "POST", "/v1/customers",
                    {"email": "rc1-618-m5-hosted@example.com"})
    price = call(client, version, "POST", "/v1/prices",
                 {"currency": "usd", "unit_amount": "1500",
                  "recurring[interval]": "month",
                  "product_data[name]": "RC1-618 M5 hosted probe plan"})
    session = call(client, version, "POST", "/v1/checkout/sessions",
                   {"mode": "subscription",
                    "customer": customer.payload["id"],
                    "line_items[0][price]": price.payload["id"],
                    "line_items[0][quantity]": "1",
                    "success_url": SUCCESS_URL, "cancel_url": CANCEL_URL})
    for label, raw in (("customer", customer), ("price", price),
                       ("session", session)):
        if raw.status >= 400:
            raise CaptureError(f"{version} {label}: HTTP {raw.status}")
    return {"customer": customer.payload["id"],
            "session": session.payload["id"],
            "url": session.payload["url"]}


def observe(client: httpx.Client, version: str,
            state: dict[str, str]) -> dict[str, Any]:
    session = call(client, version, "GET",
                   f"/v1/checkout/sessions/{state['session']}", None)
    subs = call(client, version, "GET",
                f"/v1/subscriptions?customer={state['customer']}&status=all",
                None)
    invoices = call(client, version, "GET",
                    f"/v1/invoices?customer={state['customer']}", None)
    return {"session": session.payload, "subs": subs.payload,
            "invoices": invoices.payload}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("create", "read"))
    parser.add_argument("--state", required=True,
                        help="path for the live-id scratch file; keep it out "
                             "of the repo")
    args = parser.parse_args()

    env = dotenv_values(pathlib.Path(__file__).resolve().parent.parent / ".env")
    key = env.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        print("STRIPE_SECRET_KEY missing or not a test-mode key (.env); refusing.")
        return 1
    state_path = pathlib.Path(args.state)

    with httpx.Client(base_url=STRIPE_BASE_URL, auth=(key, ""),
                      timeout=30) as client:
        if args.phase == "create":
            state = {v: create(client, v) for v in (VERSION_A, VERSION_B)}
            state_path.write_text(json.dumps(state, indent=2))
            for version, entry in state.items():
                print(f"\n{version}\n  session {entry['session']}\n"
                      f"  {entry['url']}")
            print(f"\nstate -> {state_path}\nDrive both to completion with "
                  "4242 4242 4242 4242, any future expiry, any CVC, then run "
                  "the read phase.")
            return 0

        state = json.loads(state_path.read_text())
        runs = {v: observe(client, v, state[v]) for v in (VERSION_A, VERSION_B)}

    print("\n=== M5 after hosted completion ===\n")
    for step, dotted in OBSERVE:
        a = read(runs[VERSION_A][step], dotted)
        b = read(runs[VERSION_B][step], dotted)
        if a is ABSENT and b is ABSENT:
            continue
        flag = "  DIFF" if a != b else ""
        print(f"  {step}.{dotted}")
        print(f"      A={show(dotted, a)}  B={show(dotted, b)}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
