"""RC1-618 Stage 1 probe: live-test the two title-only ground-truth entries.

M6 (Checkout no-cost orders, 2023-08-16) and M8 (multiple/partial invoice
payments, basil) were inventoried from changelog titles alone, so neither has
a named observable and both sit in M as "pending (title-only)". Stage 1 reads
their detail pages and probes them live, with three possible outcomes per
entry: scoreable with a named observable, narrowed to a smaller behavioral
claim, or disqualified in docs/ground-truth.md with its reason.

The probe follows ADR 0003 D2 (re-execute, do not re-send): each version runs
the same sequence of intent against its own object graph, so the comparison is
A-run field vs B-run field, never one object read twice.

It prints only the named observables, redacted through STRIPE_POLICY, and
writes nothing to corpus/. A probe is not capture; widening the corpus is the
cascade work that comes after this stage decides what is worth capturing.

Usage: put STRIPE_SECRET_KEY (test-mode) in .env, then
    uv run python scripts/probe_m6_m8.py
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import dotenv_values

from compatlab import STRIPE_BASE_URL, VERSION_A, VERSION_B
from compatlab.capture import CaptureError, call, resolve, resolve_body
from compatlab.redaction import STRIPE_POLICY

ABSENT = object()


@dataclass(frozen=True)
class Step:
    name: str
    method: str
    path: str
    body: dict[str, str] | None = None
    # A step that is expected to fail on one side (an endpoint or expand
    # parameter that only exists on the other) does not abort the probe.
    may_fail: bool = False


@dataclass(frozen=True)
class Probe:
    label: str
    question: str
    steps: tuple[Step, ...]
    # (step name, dotted path) pairs read from that step's response body.
    observe: tuple[tuple[str, str], ...]
    statuses: tuple[str, ...] = ()


@dataclass
class Run:
    bodies: dict[str, Any] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)


SUCCESS_URL = "https://example.com/success"
LINE_ITEM = {
    "line_items[0][price_data][currency]": "usd",
    "line_items[0][price_data][product_data][name]": "RC1-618 probe item",
    "line_items[0][quantity]": "1",
    "mode": "payment",
    "success_url": SUCCESS_URL,
}

M6 = Probe(
    label="M6",
    question=(
        "Checkout no-cost orders: the detail page says the change moved "
        "payment_method_collection from 'always' to 'if_required'. Is that "
        "default readable on a created session, and does a zero-total session "
        "behave differently across the pair?"
    ),
    steps=(
        Step("paid_session", "POST", "/v1/checkout/sessions",
             {**LINE_ITEM, "line_items[0][price_data][unit_amount]": "1099"}),
        Step("free_session", "POST", "/v1/checkout/sessions",
             {**LINE_ITEM, "line_items[0][price_data][unit_amount]": "0"},
             may_fail=True),
    ),
    statuses=("paid_session", "free_session"),
    observe=(
        ("paid_session", "payment_method_collection"),
        ("paid_session", "amount_total"),
        ("paid_session", "status"),
        ("paid_session", "payment_status"),
        ("free_session", "payment_method_collection"),
        ("free_session", "amount_total"),
        ("free_session", "status"),
        ("free_session", "payment_status"),
        ("free_session", "payment_intent"),
        ("free_session", "error.code"),
        ("free_session", "error.message"),
    ),
)

M8 = Probe(
    label="M8",
    question=(
        "Multiple (partial) invoice payments: the detail page's breaking list "
        "is removed and added fields (schema), with one behavioral line - "
        "'the amount_paid field on the Invoice object now reflects out of "
        "band payments'. Does amount_paid differ across the pair after an "
        "out-of-band payment, on a field present in both versions?"
    ),
    steps=(
        Step("customer", "POST", "/v1/customers",
             {"email": "rc1-618-probe@example.com"}),
        # The invoice is created first and the item attached to it by id. A
        # pending invoice item does not get pulled into a draft invoice on
        # either version (`pending_invoice_items_behavior`), and an empty
        # invoice finalizes straight to `paid` with amount_due 0, which makes
        # the out-of-band payment unexercisable rather than absent.
        Step("invoice", "POST", "/v1/invoices",
             {"customer": "{{customer.id}}",
              "collection_method": "send_invoice", "days_until_due": "30"}),
        Step("item", "POST", "/v1/invoiceitems",
             {"customer": "{{customer.id}}", "invoice": "{{invoice.id}}",
              "amount": "2000", "currency": "usd",
              "description": "RC1-618 probe item"}),
        Step("finalize", "POST", "/v1/invoices/{{invoice.id}}/finalize"),
        Step("pay_oob", "POST", "/v1/invoices/{{invoice.id}}/pay",
             {"paid_out_of_band": "true"}, may_fail=True),
        Step("read", "GET", "/v1/invoices/{{invoice.id}}"),
        # Both of these are schema-visible on purpose: they establish that the
        # replacement surface is new-on-B, so the behavioral claim has to rest
        # on a field that exists on both sides.
        Step("read_expanded", "GET",
             "/v1/invoices/{{invoice.id}}?expand[]=payments", may_fail=True),
        Step("list_invoice_payments", "GET", "/v1/invoice_payments",
             may_fail=True),
    ),
    statuses=("finalize", "pay_oob", "read", "read_expanded",
              "list_invoice_payments"),
    observe=(
        ("finalize", "status"),
        ("finalize", "amount_due"),
        ("pay_oob", "amount_paid"),
        ("pay_oob", "status"),
        ("pay_oob", "error.code"),
        ("pay_oob", "error.message"),
        ("read", "status"),
        ("read", "amount_due"),
        ("read", "amount_paid"),
        ("read", "amount_remaining"),
        ("read", "amount_overpaid"),
        ("read", "paid"),
        ("read", "paid_out_of_band"),
        ("read", "payment_intent"),
        ("read", "charge"),
        ("read", "payments"),
        ("read_expanded", "payments.object"),
        ("read_expanded", "payments.data.0.status"),
        ("read_expanded", "payments.data.0.amount_paid"),
        ("read_expanded", "error.message"),
        ("list_invoice_payments", "object"),
        ("list_invoice_payments", "data.0.object"),
        ("list_invoice_payments", "error.message"),
    ),
)

PROBES = (M6, M8)


def read(payload: Any, dotted: str) -> Any:
    """Like capture.dig, but reports absence instead of raising.

    Absent and null are different answers here: a field the new version
    removed is schema-visible, a field that kept its place and changed value is
    the behavioral signal this probe is looking for.
    """
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
    return cursor


def show(dotted: str, value: Any) -> str:
    if value is ABSENT:
        return "<absent>"
    leaf = dotted.rsplit(".", 1)[-1]
    redacted = STRIPE_POLICY.redact({leaf: value})[leaf]
    text = repr(redacted)
    return text if len(text) <= 90 else text[:87] + "..."


def run_probe(client: httpx.Client, probe: Probe, version: str) -> Run:
    run = Run()
    for step in probe.steps:
        try:
            path = resolve(step.path, {k: v for k, v in run.bodies.items()})
            body = resolve_body(step.body, run.bodies)
        except LookupError as exc:
            print(f"  [{version}] {step.name}: skipped, unresolved ({exc})")
            continue
        raw = call(client, version, step.method, path, body)
        run.bodies[step.name] = raw.payload
        run.statuses[step.name] = raw.status
        if raw.status >= 400 and not step.may_fail:
            code = read(raw.payload, "error.code")
            message = read(raw.payload, "error.message")
            print(f"  [{version}] {step.name}: HTTP {raw.status} "
                  f"{show('code', code)} {show('message', message)}")
            break
    return run


def report(probe: Probe, runs: dict[str, Run]) -> None:
    print(f"\n=== {probe.label} ===\n{probe.question}\n")
    for name in probe.statuses:
        a = runs[VERSION_A].statuses.get(name, "-")
        b = runs[VERSION_B].statuses.get(name, "-")
        flag = "  DIFF" if a != b else ""
        print(f"  status  {name:<24} A={a} B={b}{flag}")
    print()
    for step_name, dotted in probe.observe:
        a = read(runs[VERSION_A].bodies.get(step_name, {}), dotted)
        b = read(runs[VERSION_B].bodies.get(step_name, {}), dotted)
        if a is ABSENT and b is ABSENT:
            continue
        flag = "  DIFF" if a != b else ""
        print(f"  {step_name}.{dotted}")
        print(f"      A={show(dotted, a)}  B={show(dotted, b)}{flag}")


def main() -> int:
    env = dotenv_values(pathlib.Path(__file__).resolve().parent.parent / ".env")
    key = env.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        print("STRIPE_SECRET_KEY missing or not a test-mode key (.env); refusing.")
        return 1

    with httpx.Client(base_url=STRIPE_BASE_URL, auth=(key, ""), timeout=30) as client:
        for probe in PROBES:
            runs: dict[str, Run] = {}
            for version in (VERSION_A, VERSION_B):
                try:
                    runs[version] = run_probe(client, probe, version)
                except CaptureError as exc:
                    print(f"capture failed: {exc}")
                    return 1
            report(probe, runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
