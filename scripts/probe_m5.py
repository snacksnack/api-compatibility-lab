"""RC1-618 Stage 3 probe: can basil #4 be exercised without a hosted page?

M5 (Checkout Sessions: subscriptions created only after completed payment,
basil) is the last unexercised entry with no external account blocker. The
stage description framed the choice as "scope to the create-only half" versus
"complete a session with browser automation", and the Stage 3 handoff argued
the cheap option might exercise the break's primary clauses outright, because
a `mode=subscription` create plus a list would show the subscription existing
on A and absent on basil.

The detail page
(https://docs.stripe.com/changelog/basil/2025-03-31/checkout-legacy-subscription-upgrade)
does not say that. Its three Impact bullets are all phrased around the
customer's payment attempt - "subscriptions are now created after the user
completes payment", "failed payment attempts no longer result in an incomplete
subscription with a finalized invoice", "an invoice isn't present until the
Checkout Session is in the `complete` state" - and the What's new section puts
the latency win "including when your customer confirms the Session". Read
literally, the old version may create nothing at session create either, in
which case there is no create-time observable and the cheap option exercises
nothing.

That is a question for the API, not for a close reading. This probe asks it:
run the subscription-mode create on both versions and look for anything that
differs before a hosted page is involved.

The probe follows ADR 0003 D2 (re-execute, do not re-send): each version runs
the same sequence of intent against its own object graph, so the comparison is
A-run field vs B-run field, never one object read twice.

It prints only the named observables, redacted through STRIPE_POLICY, and
writes nothing to corpus/. A probe is not capture; widening the corpus is the
cascade work that comes after this stage decides what is worth capturing.

Usage: put STRIPE_SECRET_KEY (test-mode) in .env, then
    uv run python scripts/probe_m5.py
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
# Suffix on an observable's dotted path: report the length of the list it
# names rather than the list itself. "Does a subscription exist yet" is a
# count question, and a count is the whole answer to the cheap option.
LEN = "#len"


@dataclass(frozen=True)
class Step:
    name: str
    method: str
    path: str
    body: dict[str, str] | None = None
    # A step expected to fail on one side (an endpoint that only exists on the
    # other) does not abort the probe.
    may_fail: bool = False


@dataclass(frozen=True)
class Probe:
    label: str
    question: str
    steps: tuple[Step, ...]
    observe: tuple[tuple[str, str], ...]
    statuses: tuple[str, ...] = ()


@dataclass
class Run:
    bodies: dict[str, Any] = field(default_factory=dict)
    statuses: dict[str, int] = field(default_factory=dict)


SUCCESS_URL = "https://example.com/success"
CANCEL_URL = "https://example.com/cancel"

M5 = Probe(
    label="M5",
    question=(
        "Checkout Sessions, basil #4: the detail page's three impacts are all "
        "phrased around the customer's payment attempt. Is ANY of them "
        "readable before a hosted page is involved - a subscription or an "
        "invoice that exists on 2022-11-15 at session create and not on "
        "basil?"
    ),
    steps=(
        Step("customer", "POST", "/v1/customers",
             {"email": "rc1-618-m5-probe@example.com"}),
        Step("price", "POST", "/v1/prices",
             {"currency": "usd", "unit_amount": "1500",
              "recurring[interval]": "month",
              "product_data[name]": "RC1-618 M5 probe plan"}),
        # The cheap option's whole claim lives on this call and the two lists
        # after it. If the subscription is created at create time on A, it is
        # visible here or in list_subs.
        Step("sub_session", "POST", "/v1/checkout/sessions",
             {"mode": "subscription", "customer": "{{customer.id}}",
              "line_items[0][price]": "{{price.id}}",
              "line_items[0][quantity]": "1",
              "success_url": SUCCESS_URL, "cancel_url": CANCEL_URL}),
        Step("read_session", "GET",
             "/v1/checkout/sessions/{{sub_session.id}}"),
        Step("read_session_expanded", "GET",
             "/v1/checkout/sessions/{{sub_session.id}}"
             "?expand[]=subscription&expand[]=invoice", may_fail=True),
        # The customer was created inside this run on each side, so these
        # lists are scoped to traffic this probe generated.
        Step("list_subs", "GET",
             "/v1/subscriptions?customer={{customer.id}}&status=all"),
        Step("list_invoices", "GET",
             "/v1/invoices?customer={{customer.id}}"),
        # The third clause - "sessions editable after a failed attempt" -
        # needs the update endpoint. Probed for the record: if the endpoint is
        # new on basil, oasdiff reports it and the clause is schema-visible,
        # which matters to the headline even though exercising it still needs
        # a completed-then-failed session.
        Step("update_session", "POST",
             "/v1/checkout/sessions/{{sub_session.id}}",
             {"metadata[probe]": "rc1-618"}, may_fail=True),
        # A trial-mode session owes nothing at completion. Asked because if
        # ANY subscription-mode shape creates its subscription eagerly on A,
        # this is the likeliest one.
        Step("trial_session", "POST", "/v1/checkout/sessions",
             {"mode": "subscription", "customer": "{{customer.id}}",
              "line_items[0][price]": "{{price.id}}",
              "line_items[0][quantity]": "1",
              "subscription_data[trial_period_days]": "7",
              "payment_method_collection": "if_required",
              "success_url": SUCCESS_URL, "cancel_url": CANCEL_URL},
             may_fail=True),
        Step("list_subs_after_trial", "GET",
             "/v1/subscriptions?customer={{customer.id}}&status=all"),
    ),
    statuses=("sub_session", "read_session", "read_session_expanded",
              "list_subs", "list_invoices", "update_session",
              "trial_session", "list_subs_after_trial"),
    observe=(
        ("sub_session", "status"),
        ("sub_session", "payment_status"),
        ("sub_session", "subscription"),
        ("sub_session", "invoice"),
        ("sub_session", "payment_intent"),
        ("sub_session", "payment_method_collection"),
        ("sub_session", "amount_total"),
        ("read_session", "status"),
        ("read_session", "subscription"),
        ("read_session", "invoice"),
        ("read_session_expanded", "subscription"),
        ("read_session_expanded", "invoice"),
        ("read_session_expanded", "error.message"),
        ("list_subs", "data" + LEN),
        ("list_subs", "data.0.status"),
        ("list_subs", "data.0.latest_invoice"),
        ("list_invoices", "data" + LEN),
        ("list_invoices", "data.0.status"),
        ("update_session", "error.code"),
        ("update_session", "error.message"),
        ("trial_session", "status"),
        ("trial_session", "subscription"),
        ("trial_session", "payment_method_collection"),
        ("trial_session", "error.message"),
        ("list_subs_after_trial", "data" + LEN),
        ("list_subs_after_trial", "data.0.status"),
    ),
)

PROBES = (M5,)


def read(payload: Any, dotted: str) -> Any:
    """Like capture.dig, but reports absence instead of raising.

    Absent and null are different answers here: a field the new version
    removed is schema-visible, a field that kept its place and changed value
    is the behavioral signal this probe is looking for. `#len` asks for the
    length of a list, and a list that is not there is absent, not zero -
    reporting 0 for "no such field" would invent a difference.
    """
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


def run_probe(client: httpx.Client, probe: Probe, version: str) -> Run:
    run = Run()
    for step in probe.steps:
        try:
            path = resolve(step.path, dict(run.bodies))
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
