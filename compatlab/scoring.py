"""Scoring: caught N of M, what the schema diff said, and the false-break rate.

Three numbers, and the work is in making each one hard to fake.

**Caught N of M.** M is the ground-truth inventory in `docs/ground-truth.md`,
live-verified break by break because the changelog alone overstated it (the
Phase 0 spike disqualified two entries, one account-gated and one reversed
upstream). A break counts as caught when a finding at `risky` or above lands
on one of the loci that break would show up at, inside the workflow that was
written to exercise it. A finding somewhere else does not get to claim it.

Breaks the corpus cannot exercise are reported as *not exercised* rather than
quietly dropped from the denominator, because a denominator that shrinks to
fit the result is the main way a number like this gets dishonest.

**What the schema diff said.** For each caught break, the baseline index is
asked about the field on the endpoint, and the answer is one of four:
`reported` (an entry about that field's own contract, or the path's removal —
a reader would have been warned), `named` (entries mention the field, but only
to say the set of possible values or polymorphic branches grew, which cannot
express a changed default), `green` (nothing at all), or `not-covered` (the
baseline was never generated over that endpoint, because no captured call
reaches it). Only `green` and `named` are misses, and they are counted
separately. `not-covered` is not a miss and is not a green either: the
baseline is scoped to the endpoints the corpus calls, so claiming a schema
diff was silent about an endpoint it never read would be the same kind of
unearned credit as scoring a break no scenario exercises (RC1-618 Stage 1).

**The false-break rate.** Every finding classified `breaking` must be
adjudicated in `scoring/adjudication.json` against the changelog for the span:
`documented` (a published change explains it), `undocumented` (a real
difference Stripe did not write down — a finding in its own right), or
`false-break` (the tool is wrong). The rate is false-breaks over breaking
findings. If any breaking finding has no verdict, scoring **fails** rather
than publishing a rate computed over a subset; an unadjudicated finding is the
one thing that could make this number flattering by accident.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Any

from compatlab.baseline import BaselineIndex
from compatlab.classify import RULES
from compatlab.findings import BENIGN, BREAKING, DiffReport, Finding, normalize

ADJUDICATION_PATH = pathlib.Path("scoring/adjudication.json")

DOCUMENTED = "documented"
UNDOCUMENTED = "undocumented"
FALSE_BREAK = "false-break"
VERDICTS = (DOCUMENTED, UNDOCUMENTED, FALSE_BREAK)

REPORTED = "reported"
NAMED = "named"
GREEN = "green"
NOT_COVERED = "not-covered"

# oasdiff rules that tell a reader something about *this field's own contract*:
# it is gone, it can be null now, its type changed, the path is gone. A reader
# who saw one of these would have been warned.
CONTRACT_RULES = frozenset({
    "api-path-removed-without-deprecation",
    "api-removed-without-deprecation",
    "api-operation-removed-without-deprecation",
    "response-required-property-removed",
    "response-property-removed",
    "response-property-became-nullable",
    "response-property-type-changed",
    "request-property-removed",
    "request-parameter-removed",
})


@dataclass(frozen=True)
class Break:
    """One entry of the ground-truth inventory, with how to detect it."""

    id: str
    summary: str
    version: str
    confirmed: bool
    workflows: tuple[str, ...]
    loci: tuple[str, ...]
    baseline_endpoint: tuple[str, str]
    baseline_field: str
    note: str = ""


# docs/ground-truth.md, "M: behavioral breaks in scope". The loci are where
# each break surfaces in a response; the baseline endpoint and field are where
# a schema diff would have had to say something for the reader to be warned.
GROUND_TRUTH: tuple[Break, ...] = (
    Break(
        id="M1",
        summary="Automatic payment methods enabled by default",
        version="2023-08-16",
        confirmed=True,
        workflows=("checkout_card_payment", "partial_capture_reconcile"),
        loci=("$.body.automatic_payment_methods", "$.body.payment_method_types"),
        baseline_endpoint=("POST", "/v1/payment_intents"),
        baseline_field="automatic_payment_methods",
    ),
    Break(
        id="M2",
        summary="`capture_method` defaults to `automatic_async`",
        version="2024-04-10",
        confirmed=True,
        workflows=("checkout_card_payment",),
        loci=("$.body.capture_method",),
        baseline_endpoint=("POST", "/v1/payment_intents"),
        baseline_field="capture_method",
        note=("Only observable where the request leaves `capture_method` "
              "unspecified, which is why the partial-capture workflow — which "
              "sends `manual` — cannot evidence it."),
    ),
    Break(
        id="M3",
        summary="Partial capture no longer creates a Refund",
        version="2025-03-31.basil",
        confirmed=True,
        workflows=("partial_capture_reconcile",),
        loci=("$.body.data", "$.body.count", "$.body.data[].amount_refunded"),
        baseline_endpoint=("GET", "/v1/charges"),
        baseline_field="amount_refunded",
    ),
    Break(
        id="M4",
        summary="`GET /v1/invoices/upcoming` removed outright",
        version="2025-03-31.basil",
        confirmed=True,
        workflows=("subscription_billing",),
        loci=("$.status",),
        baseline_endpoint=("GET", "/v1/invoices/upcoming"),
        baseline_field="",
        note=("The one break in the inventory with a schema-visible half: the "
              "path is gone from the spec. What the spec cannot say is that "
              "the subscription-context call shape 404s too (RC1-607)."),
    ),
    Break(
        id="M5",
        summary="Checkout Session defers subscription and invoice to completion",
        version="2025-03-31.basil",
        confirmed=True,
        workflows=(),
        loci=("$.body.subscription", "$.body.invoice"),
        baseline_endpoint=("POST", "/v1/checkout/sessions"),
        baseline_field="subscription",
        note=("Narrowed in RC1-618 Stage 3, and narrowed twice. The entry "
              "reads as a happy-path change — `subscriptions created only "
              "after completed payment` — but a session create is identical "
              "across the pair on every observable, and so is a session "
              "driven to a SUCCESSFUL completion: both end with an active "
              "subscription and a paid invoice. The difference appears only "
              "after a FAILED payment attempt, where A leaves an `incomplete` "
              "subscription and an `open` invoice behind and basil leaves "
              "nothing, while both sessions still report `status: open` and "
              "`payment_status: unpaid`. Unexercised by decision, not by "
              "blocker: the observable needs a hosted page driven with a "
              "declining card, and ADR 0003 D2 replays by re-execution, so a "
              "scenario reaching it would put a browser inside `replay` and "
              "`pin certify`. See docs/m5-probe.md."),
    ),
    Break(
        id="M6",
        summary="Checkout `payment_method_collection` defaults to `if_required`",
        version="2023-08-16",
        confirmed=True,
        workflows=("checkout_session_no_cost",),
        loci=("$.body.payment_method_collection", "$.status"),
        baseline_endpoint=("POST", "/v1/checkout/sessions"),
        baseline_field="payment_method_collection",
        note=("Narrowed in RC1-618 Stage 1 to the default flip the detail "
              "page names: `always` -> `if_required` on a `mode=payment` "
              "session create, plus a zero-total session going 400 -> 200. "
              "Both are readable on create, which is why exercising this did "
              "not need M5's completed session."),
    ),
    Break(
        id="M7",
        summary="Checkout statement descriptor derives from the business name",
        version="2023-10-16",
        confirmed=True,
        workflows=("connected_account_onboarding",),
        loci=("$.body.settings.payments.statement_descriptor",
              "$.body.settings.card_payments.statement_descriptor_prefix"),
        baseline_endpoint=("POST", "/v1/accounts"),
        baseline_field="statement_descriptor",
        note=("Narrowed in RC1-618 Stage 2, the fourth entry running where the "
              "title was not the break. 'Auto-populated' understates it: what "
              "changed is the derivation SOURCE. 2022-11-15 derives the "
              "descriptor from `business_profile[url]`; basil derives it from "
              "`business_profile[name]`, falling back to the url with `WWW.` "
              "stripped. With both fields sent, BOTH versions return a "
              "plausible non-null descriptor and disagree only about its "
              "content, so a null check passes on both sides and the merchant "
              "sees a different string on a cardholder's statement. The prefix "
              "half does reproduce, but at "
              "`settings.card_payments.statement_descriptor_prefix`, not the "
              "`settings.payments` path the title implies. The baseline "
              "endpoint moved from `GET /v1/account` to `POST /v1/accounts`: "
              "the own-account read was never what this break surfaces on, and "
              "the corpus does not call it. See docs/m7-probe.md."),
    ),
    Break(
        id="M8",
        summary="Invoice `amount_paid` reflects out-of-band payments",
        version="2025-03-31.basil",
        confirmed=True,
        workflows=("invoice_out_of_band_payment",),
        loci=("$.body.amount_paid", "$.body.amount_remaining"),
        baseline_endpoint=("GET", "/v1/invoices/{id}"),
        baseline_field="amount_paid",
        note=("Narrowed in RC1-618 Stage 1: the entry's breaking list is "
              "removed and added fields, all schema-visible, and the one "
              "behavioral line is `amount_paid` now counting an out-of-band "
              "payment (0 -> 2000, with `amount_remaining` 2000 -> 0). The "
              "underlying `invoice_payment` reads 2000 on both versions, so "
              "only the aggregate disagrees. Needed no test clock, which is "
              "what retired the groomed Stage 4."),
    ),
)

GROUND_TRUTH_M = len(GROUND_TRUTH)


@dataclass
class Adjudication:
    """Hand-written verdicts on the breaking findings, keyed by rule and locus."""

    verdicts: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def load(cls, path: pathlib.Path) -> Adjudication:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(verdicts=data.get("verdicts", []), notes=data.get("notes", ""))

    def verdict_for(self, finding: Finding) -> dict[str, Any] | None:
        locus = normalize(finding.locus)
        for entry in self.verdicts:
            match = entry.get("match", {})
            if match.get("rule") not in (None, finding.rule):
                continue
            if match.get("locus") not in (None, locus):
                continue
            if match.get("workflow") not in (None, finding.workflow):
                continue
            if match.get("endpoint") not in (None, finding.endpoint):
                continue
            return entry
        return None


def exercised_targets(pairs: list[dict]) -> set[str]:
    """Which ground-truth breaks the replayed corpus actually reaches."""
    return {
        target
        for pair in pairs
        for target in (pair.get("targets") or ())
    }


def evidence(report: DiffReport, item: Break) -> list[Finding]:
    """Findings that evidence one break: right workflow, right locus, not benign."""
    return [
        finding
        for finding in report.findings
        if finding.severity != BENIGN
        and finding.workflow in item.workflows
        and normalize(finding.locus) in item.loci
    ]


def baseline_verdict(index: BaselineIndex, item: Break) -> tuple[str, dict[str, int]]:
    """What the schema diff said: reported, named, green, or not-covered.

    `not-covered` comes first because the other three all read an absence of
    entries as evidence, and an endpoint outside the baseline's scope has no
    entries for a reason that has nothing to do with the spec. Before
    RC1-618 Stage 1 this returned `green` for M5, M6 and M7 — three rows
    crediting the schema diff with silence on `POST /v1/checkout/sessions`
    and `GET /v1/account`, neither of which the baseline was generated over.
    """
    method, path = item.baseline_endpoint
    if not index.covers_endpoint(method, path):
        return NOT_COVERED, {}
    path_level = index.path_level(method, path)
    if any(rule in CONTRACT_RULES for rule in path_level):
        return REPORTED, path_level
    rules = index.rules_for(method, path, item.baseline_field)
    if not rules:
        return GREEN, {}
    if any(rule in CONTRACT_RULES for rule in rules):
        return REPORTED, rules
    return NAMED, rules


def score(report: DiffReport, index: BaselineIndex, adjudication: Adjudication,
          pairs: list[dict]) -> dict[str, Any]:
    """The whole scorecard, as data."""
    reached = exercised_targets(pairs)
    breaks = []
    for item in GROUND_TRUTH:
        found = evidence(report, item)
        verdict, rules = baseline_verdict(index, item)
        breaks.append({
            "id": item.id,
            "summary": item.summary,
            "version": item.version,
            "confirmed_live": item.confirmed,
            "exercised": item.id in reached,
            "caught": bool(found),
            "evidence": [f.key for f in found],
            "severities": sorted({f.severity for f in found}),
            "baseline": verdict,
            "baseline_rules": rules,
            "note": item.note,
        })

    exercised = [b for b in breaks if b["exercised"]]
    caught = [b for b in breaks if b["caught"]]
    missed_schema_diff = [
        b for b in caught if b["baseline"] in (GREEN, NAMED)
    ]

    breaking = report.by_severity(BREAKING)
    tally = dict.fromkeys(VERDICTS, 0)
    unadjudicated = []
    adjudicated = []
    for finding in breaking:
        entry = adjudication.verdict_for(finding)
        if entry is None or entry.get("verdict") not in VERDICTS:
            unadjudicated.append(finding.key + f" [{finding.rule}]")
            continue
        tally[entry["verdict"]] += 1
        adjudicated.append({
            "key": finding.key,
            "rule": finding.rule,
            "verdict": entry["verdict"],
            "reference": entry.get("reference", ""),
        })

    rate = None
    if not unadjudicated and breaking:
        rate = tally[FALSE_BREAK] / len(breaking)

    cross_check: dict[str, dict[str, int]] = {}
    for finding in report.findings:
        bucket = cross_check.setdefault(
            finding.severity, dict.fromkeys((REPORTED, NAMED, GREEN), 0))
        rules = index.rules_for(finding.method, finding.path_template,
                               finding.field_name)
        path_rules = index.path_level(finding.method, finding.path_template)
        if any(r in CONTRACT_RULES for r in {**rules, **path_rules}):
            bucket[REPORTED] += 1
        elif rules:
            bucket[NAMED] += 1
        else:
            bucket[GREEN] += 1

    return {
        "ground_truth": {
            "m": GROUND_TRUTH_M,
            "exercised": len(exercised),
            "caught": len(caught),
            "caught_of_exercised": f"{len(caught)} of {len(exercised)}",
            "breaks": breaks,
        },
        "baseline": {
            "oasdiff_build": index.meta.get("oasdiff", {}).get("build"),
            "entries_unscoped": index.entries_unscoped,
            "entries_matched_paths": index.entries_matched_paths,
            "entries_corpus_endpoints": index.entries_corpus_endpoints,
            "green_on_caught": sum(1 for b in caught if b["baseline"] == GREEN),
            "named_only_on_caught": sum(1 for b in caught if b["baseline"] == NAMED),
            "reported_on_caught": sum(1 for b in caught if b["baseline"] == REPORTED),
            "missed_by_schema_diff": [b["id"] for b in missed_schema_diff],
            "rule_mix": index.rule_mix,
        },
        "findings": {
            "total": len(report.findings),
            "by_severity": report.counts("severity"),
            "by_axis": report.counts("axis"),
            "by_rule": report.counts("rule"),
            "steps_compared": report.steps_compared,
            "steps_with_findings": report.steps_with_findings,
        },
        "cross_check": {
            severity: dict(counts)
            for severity, counts in sorted(cross_check.items())
        },
        "false_breaks": {
            "breaking_findings": len(breaking),
            "verdicts": tally,
            "unadjudicated": unadjudicated,
            "rate": rate,
            "adjudicated": adjudicated,
        },
    }


def headline(card: dict[str, Any]) -> str:
    """The one sentence the epic asks for, assembled from the scorecard."""
    truth, base, false = card["ground_truth"], card["baseline"], card["false_breaks"]
    missed = base["green_on_caught"] + base["named_only_on_caught"]
    rate = ("not computed (unadjudicated findings)" if false["rate"] is None
            else f"{false['rate']:.0%} ({false['verdicts'][FALSE_BREAK]} of "
                 f"{false['breaking_findings']})")
    return (
        f"Caught {truth['caught']} of the {truth['exercised']} documented "
        f"behavioral breaks the corpus exercises ({truth['m']} in the "
        f"inventory). The schema-diff baseline gave no usable warning on "
        f"{missed} of them — {base['green_on_caught']} with no entry at all, "
        f"{base['named_only_on_caught']} naming the field but not the "
        f"behavior — while reporting {base['entries_corpus_endpoints']:,} "
        f"breaking changes on the same endpoints. False-break rate: {rate}."
    )


def render(card: dict[str, Any]) -> str:
    """Markdown, for the CLI and for docs/behavioral-diff-report.md."""
    truth, base, false = card["ground_truth"], card["baseline"], card["false_breaks"]
    lines = [
        "# Behavioral diff report",
        "",
        "Generated by `compatlab score`; regenerate it rather than editing it. "
        "The methodology — what each severity means, why the baseline is "
        "`oasdiff` over Stripe's own spec, and what the numbers do not say — "
        "is ADR 0004.",
        "",
        headline(card), "", "## Ground truth", "",
             "| M# | Break | Version | Exercised | Caught | Schema diff |",
             "|----|-------|---------|-----------|--------|-------------|"]
    for item in truth["breaks"]:
        lines.append(
            f"| {item['id']} | {item['summary']} | {item['version']} "
            f"| {'yes' if item['exercised'] else 'no'} "
            f"| {'yes' if item['caught'] else 'no'} | {item['baseline']} |"
        )
    lines += [
        "",
        "Schema diff column: `reported` means an entry about that field's own "
        "contract; `named` means the field is mentioned but not its behavior; "
        "`green` means nothing at all; `not-covered` means the baseline was "
        "never generated over that endpoint, because no captured call reaches "
        "it. A `not-covered` row is a statement about this corpus, not about "
        "Stripe's spec.",
    ]
    lines += [
        "", "## Findings", "",
        f"- Steps compared: {card['findings']['steps_compared']}, "
        f"with findings: {card['findings']['steps_with_findings']}",
        f"- Findings: {card['findings']['total']} — "
        + ", ".join(f"{n} {s}" for s, n in card["findings"]["by_severity"].items()),
        "",
        "| Axis | Findings |", "|------|----------|",
    ]
    for axis, count in card["findings"]["by_axis"].items():
        lines.append(f"| {axis} | {count} |")
    fired = card["findings"]["by_rule"]
    lines += [
        "",
        "Each finding names the rule that classified it. The rules that fired, "
        "with what each one means:",
        "",
        "| Rule | Severity | Findings | Means |",
        "|------|----------|----------|-------|",
        *[f"| `{rule.id}` | {rule.severity} | {fired[rule.id]} | "
          f"{rule.summary} |"
          for rule in RULES if fired.get(rule.id)],
        "",
        "Rules in the table that did not fire on this corpus: "
        + ", ".join(f"`{rule.id}`" for rule in RULES if not fired.get(rule.id))
        + ".",
    ]
    lines += [
        "", "## Schema-diff baseline", "",
        f"- oasdiff build `{base['oasdiff_build']}`, breaking mode",
        f"- {base['entries_unscoped']:,} breaking entries over the whole spec "
        f"pair" if base["entries_unscoped"] else "- whole-spec count not measured",
        f"- {base['entries_matched_paths']:,} within the matched paths, "
        f"{base['entries_corpus_endpoints']:,} on the endpoints the corpus calls",
        f"- On the caught breaks: {base['green_on_caught']} green, "
        f"{base['named_only_on_caught']} named-only, "
        f"{base['reported_on_caught']} reported",
    ]
    mix = card["baseline"]["rule_mix"]
    if mix:
        # The stored mix is JSON, so its key order is alphabetical, not ranked.
        top, count = max(mix.items(), key=lambda kv: (kv[1], kv[0]))
        lines += [
            f"- {count:,} of those {base['entries_corpus_endpoints']:,} are one "
            f"rule, `{top}` — mostly a new country or currency surfacing at "
            f"every nested `anyOf` path that can reach it. The baseline does "
            f"not hand a reader a green light to trust; it hands them a "
            f"haystack, and that is part of its performance.",
        ]
    lines += [
        "",
        "Every finding, cross-checked against the same baseline — the other "
        "direction of the comparison, and the check that the lab is not "
        "missing what a schema diff does catch:",
        "",
        "| Severity | Baseline reported | Named only | Green |",
        "|----------|-------------------|------------|-------|",
        *[f"| {severity} | {counts[REPORTED]} | {counts[NAMED]} | "
          f"{counts[GREEN]} |"
          for severity, counts in card["cross_check"].items()],
        "", "## False breaks", "",
        "Every `breaking` finding is adjudicated by hand against the changelog "
        "for the span, in `scoring/adjudication.json`. A verdict of "
        "`documented` means a published change explains it; `undocumented` "
        "means the difference is real and Stripe did not write it down; "
        "`false-break` means this tool is wrong.",
        "",
        f"- Breaking findings: {false['breaking_findings']}",
        "- Verdicts: " + ", ".join(f"{n} {v}" for v, n in false["verdicts"].items()),
    ]
    if false["rate"] is not None:
        lines += [
            f"- **False-break rate: {false['rate']:.0%}** "
            f"({false['verdicts'][FALSE_BREAK]} of "
            f"{false['breaking_findings']})",
            "",
            f"Read that as *no false breaks observed* rather than as a rate "
            f"measured at scale: the denominator is "
            f"{false['breaking_findings']} findings over "
            f"{card['findings']['steps_compared']} replayed steps in four "
            f"workflows. A corpus with more endpoints — especially list "
            f"endpoints, where account state can masquerade as a version "
            f"difference — is where this number earns its keep.",
        ]
    if false["unadjudicated"]:
        lines.append(f"- **Unadjudicated: {len(false['unadjudicated'])}** — "
                     f"no rate is published while any remain")
        lines += [f"  - {key}" for key in false["unadjudicated"]]
    return "\n".join(lines)
