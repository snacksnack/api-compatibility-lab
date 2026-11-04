"""`compatlab capture | scan | coverage`.

`scan` is the one that matters to CI: it is the epic's scored requirement
(zero PII findings on a scan of the stored corpus) as a command that exits
non-zero, run against the committed corpus on every push.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import httpx
from dotenv import dotenv_values

from compatlab import STRIPE_BASE_URL, VERSION_A
from compatlab.capture import capture_all, seed_known
from compatlab.corpus import files, read, validate, write
from compatlab.coverage import GROUND_TRUTH_M, render, summarize
from compatlab.redaction import STRIPE_POLICY, Policy
from compatlab.scenarios import SCENARIO_DIR, load_all

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
DEFAULT_CORPUS = CORPUS_DIR / "version-a.jsonl"


def seeded_policy() -> Policy:
    """The Stripe policy, told the literal values the scenarios send.

    `scan` needs the same seeding the capture path does, or auditing a stored
    corpus would miss a fixture value the server echoed into free text.
    """
    return seed_known(STRIPE_POLICY, load_all(SCENARIO_DIR))


def _stripe_key() -> str:
    """Test-mode key from .env, or exit. A live key is refused outright."""
    key = dotenv_values(ROOT / ".env").get("STRIPE_SECRET_KEY", "") or ""
    if not key.startswith("sk_test_"):
        sys.exit("STRIPE_SECRET_KEY missing or not a test-mode key (.env); refusing.")
    return key


def cmd_capture(args: argparse.Namespace) -> int:
    scenarios = load_all(SCENARIO_DIR)
    if args.scenario:
        wanted = set(args.scenario)
        scenarios = [s for s in scenarios if s.workflow in wanted]
        missing = wanted - {s.workflow for s in scenarios}
        if missing:
            sys.exit(f"no such scenario: {', '.join(sorted(missing))}")
    if not scenarios:
        sys.exit(f"no scenarios found in {SCENARIO_DIR}")

    steps = sum(len(s.steps) for s in scenarios)
    print(f"capturing {len(scenarios)} workflow(s), {steps} step(s) "
          f"on Stripe-Version {args.version}")
    if args.dry_run:
        for scenario in scenarios:
            print(f"  {scenario.workflow}: "
                  f"{', '.join(s.step for s in scenario.steps)}")
        return 0

    with httpx.Client(base_url=STRIPE_BASE_URL, auth=(_stripe_key(), ""),
                      timeout=30) as client:
        report = capture_all(client, scenarios, args.version, policy=STRIPE_POLICY)

    for name, reason in report.skipped:
        print(f"  skipped {name}: {reason}")
    for rec in report.failures:
        body = rec["response"]["body"]
        detail = (body.get("error", {}) or {}).get("message", "")
        print(f"  {rec['response']['status']} {rec['workflow']}.{rec['step']}: "
              f"{detail[:90]}")

    out = pathlib.Path(args.out)
    count = write(out, report.records)
    print(f"wrote {count} records to {out}")

    findings = _scan_records(report.records, out.name, seeded_policy())
    if findings:
        print(f"REFUSING to stop here: {len(findings)} finding(s) in a corpus "
              f"this process just wrote — the redaction policy has a hole.")
        for finding in findings[:20]:
            print(f"  {finding}")
        return 1
    print("scan: clean")
    return 0


def _scan_records(records: list[dict], label: str, policy: Policy) -> list[str]:
    findings = []
    for rec in records:
        prefix = f"{label}:{rec.get('workflow')}.{rec.get('step')}"
        findings += [f"{prefix} {f}" for f in policy.scan(rec)]
    return findings


def cmd_scan(args: argparse.Namespace) -> int:
    paths = [pathlib.Path(p) for p in args.path] or [CORPUS_DIR]
    policy = seeded_policy()
    findings: list[str] = []
    invalid: list[str] = []
    scanned = 0
    for root in paths:
        for path in files(root):
            records = read(path)
            scanned += len(records)
            for i, rec in enumerate(records):
                invalid += [f"{path.name}:{i}: {p}" for p in validate(rec)]
            findings += _scan_records(records, path.name, policy)
    print(f"scanned {scanned} record(s) with the {policy.name} policy "
          f"({len(policy.known)} known literals)")
    for problem in invalid:
        print(f"  invalid: {problem}")
    for finding in findings:
        print(f"  finding: {finding}")
    if findings or invalid:
        print(f"FAIL: {len(findings)} finding(s), {len(invalid)} invalid record(s)")
        return 1
    print("PASS: zero findings")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    path = pathlib.Path(args.path or DEFAULT_CORPUS)
    records = [rec for p in files(path) for rec in read(p)]
    summary = summarize(records)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(render(summary, GROUND_TRUTH_M))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compatlab", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="capture live traffic into the corpus")
    cap.add_argument("--version", default=VERSION_A, help="Stripe-Version to pin")
    cap.add_argument("--out", default=str(DEFAULT_CORPUS))
    cap.add_argument("--scenario", action="append", help="workflow name; repeatable")
    cap.add_argument("--dry-run", action="store_true", help="list steps only")
    cap.set_defaults(func=cmd_capture)

    scan = sub.add_parser("scan", help="audit a stored corpus for PII and secrets")
    scan.add_argument("path", nargs="*", help="corpus file or directory")
    scan.set_defaults(func=cmd_scan)

    cov = sub.add_parser("coverage", help="per-endpoint coverage stats")
    cov.add_argument("path", nargs="?")
    cov.add_argument("--json", action="store_true")
    cov.set_defaults(func=cmd_coverage)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
