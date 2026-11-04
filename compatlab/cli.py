"""`compatlab capture|scan|coverage|control|replay|diff|baseline|score|impact`.

Three of these matter to CI, and each exits non-zero on failure rather than
printing a warning:

- `scan` is the epic's scored requirement — zero PII findings on the stored
  corpus — run against the committed corpus on every push.
- `score` refuses to publish a false-break rate while any breaking finding is
  unadjudicated, so a new finding cannot slip into the headline unexamined.
- `impact` refuses to publish a workflow-mapping precision while any claim is
  unconfirmed against the replay record, and fails outright on an integration
  inventory that does not match the captured traffic.

`baseline` is the odd one out: it needs the network and a container runtime,
so it is run by hand and its output committed. Everything else works offline
from the committed artifacts.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

import httpx
from dotenv import dotenv_values

from compatlab import STRIPE_BASE_URL, VERSION_A, VERSION_B, impact, scoring
from compatlab import baseline as bl
from compatlab import workflows as wf
from compatlab.canonical import canonical_side, diff_paths
from compatlab.capture import capture_all, seed_known
from compatlab.corpus import files, read, validate, write
from compatlab.coverage import GROUND_TRUTH_M, render, summarize
from compatlab.differ import diff_pairs, sides
from compatlab.findings import SEVERITIES, Finding
from compatlab.impact_html import render_html
from compatlab.impact_report import render as render_impact
from compatlab.redaction import STRIPE_POLICY, Policy
from compatlab.replay import pair, replay_corpus
from compatlab.scenarios import SCENARIO_DIR, load_all
from compatlab.verify import ground_truth_coverage, verify

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
DEFAULT_CORPUS = CORPUS_DIR / "version-a.jsonl"
PAIRS_PATH = ROOT / "replay" / "pairs.jsonl"
FINDINGS_PATH = ROOT / "findings" / "findings.jsonl"
BASELINE_PATH = ROOT / bl.INDEX_PATH
ADJUDICATION_PATH = ROOT / scoring.ADJUDICATION_PATH
SPEC_CACHE = ROOT / ".cache" / "specs"
REPORT_PATH = ROOT / "docs" / "behavioral-diff-report.md"
WORKFLOW_DIR = ROOT / "workflows"
PINS_PATH = ROOT / "pins" / "pins.jsonl"
IMPACT_PATH = ROOT / "docs" / "impact-report.md"
IMPACT_HTML_PATH = ROOT / "docs" / "impact-report.html"


def _slug(version: str) -> str:
    return version.replace(".", "-")


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


def _report_run(report, label: str) -> None:
    print(f"{label}: {len(report.records)} record(s), "
          f"{len(report.failures)} non-2xx, {len(report.skipped)} skipped"
          + (f", {len(report.warnings)} WARNING(S)" if report.warnings else ""))
    for name, reason in report.skipped:
        print(f"    skipped {name}: {reason}")
    for name, reason in report.warnings:
        print(f"    WARNING {name}: {reason}")


def _mismatches(side_one: list[dict], side_two: list[dict]) -> dict[str, list[str]]:
    """Canonicalize both runs and diff them step by step."""
    one, two = canonical_side(side_one), canonical_side(side_two)
    out = {}
    for key in sorted(set(one) | set(two)):
        name = f"{key[0]}.{key[1]}"
        if key not in one or key not in two:
            out[name] = [f"present on only one side ({'A' if key in one else 'B'})"]
            continue
        diffs = diff_paths(one[key], two[key])
        if diffs:
            out[name] = diffs
    return out


def cmd_replay(args: argparse.Namespace) -> int:
    records = read(pathlib.Path(args.corpus))
    print(f"replaying {len(records)} record(s) from {args.corpus}")
    with httpx.Client(base_url=STRIPE_BASE_URL, auth=(_stripe_key(), ""),
                      timeout=30) as client:
        side_a = replay_corpus(client, records, args.a, policy=STRIPE_POLICY)
        _report_run(side_a, f"A {args.a}")
        side_b = replay_corpus(client, records, args.b, policy=STRIPE_POLICY)
        _report_run(side_b, f"B {args.b}")

    for side, version in ((side_a, args.a), (side_b, args.b)):
        out = CORPUS_DIR / f"replay-{_slug(version)}.jsonl"
        write(out, side.records)
        print(f"wrote {len(side.records)} records to {out}")

    pairs = pair(side_a.records, side_b.records)
    PAIRS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PAIRS_PATH.open("w") as handle:
        for item in pairs:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    unmatched = sum(1 for p in pairs if p["a"] is None or p["b"] is None)
    print(f"wrote {len(pairs)} pairs to {PAIRS_PATH} ({unmatched} half-missing)")

    findings = _scan_records(side_a.records + side_b.records, "replay",
                             seeded_policy())
    if findings:
        print(f"REFUSING to stop here: {len(findings)} finding(s) in replayed "
              f"traffic — a sanitized corpus produced unsanitized responses.")
        for finding in findings[:20]:
            print(f"  {finding}")
        return 1
    print("scan: clean")
    return 0


def cmd_control(args: argparse.Namespace) -> int:
    """The A/A control: the same version on both sides must agree exactly."""
    records = read(pathlib.Path(args.corpus))
    print(f"A/A control on {args.version}: {len(records)} record(s)")
    with httpx.Client(base_url=STRIPE_BASE_URL, auth=(_stripe_key(), ""),
                      timeout=30) as client:
        one = replay_corpus(client, records, args.version, policy=STRIPE_POLICY)
        _report_run(one, "run 1")
        two = replay_corpus(client, records, args.version, policy=STRIPE_POLICY)
        _report_run(two, "run 2")

    mismatches = _mismatches(one.records, two.records)
    total = sum(len(v) for v in mismatches.values())
    for name, diffs in mismatches.items():
        print(f"  {name}: {len(diffs)} mismatch(es)")
        for line in diffs[: args.show]:
            print(f"      {line}")
    if mismatches:
        print(f"FAIL: {total} infrastructure-caused mismatch(es) across "
              f"{len(mismatches)} step(s)")
        return 1
    print("PASS: zero infrastructure-caused mismatches")
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


def _read_pairs(path: pathlib.Path) -> list[dict]:
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _corpus_endpoints(pairs: list[dict]) -> tuple[list[str], list[str]]:
    """The endpoints the replay actually called, as templates and as keys."""
    templates = sorted({p["path_template"] for p in pairs})
    keys = sorted({bl.endpoint_key(p["method"], p["path_template"])
                   for p in pairs})
    return templates, keys


def cmd_diff(args: argparse.Namespace) -> int:
    """Classify the paired responses. The heart of Phase 3."""
    pairs = _read_pairs(pathlib.Path(args.pairs))
    report = diff_pairs(pairs)
    wanted = set(args.severity or SEVERITIES)

    if args.json:
        print(json.dumps({
            **report.to_dict(),
            "detail": [f.to_dict() for f in report.sorted_findings()
                       if f.severity in wanted],
        }, indent=2))
    else:
        print(f"compared {report.steps_compared} step(s); "
              f"{report.steps_with_findings} differ")
        print("findings: " + ", ".join(
            f"{n} {s}" for s, n in report.counts("severity").items()) or "none")
        step = None
        for finding in report.sorted_findings():
            if finding.severity not in wanted:
                continue
            if (finding.workflow, finding.step) != step:
                step = (finding.workflow, finding.step)
                print(f"\n  {finding.workflow}.{finding.step} "
                      f"({finding.method} {finding.path_template})")
            print(f"    {finding.line()}")
            if args.why:
                print(f"      why: {finding.rationale}")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as handle:
        for finding in report.sorted_findings():
            handle.write(json.dumps(finding.to_dict(), sort_keys=True) + "\n")
    print(f"\nwrote {len(report.findings)} findings to {out}")

    findings_as_records = [f.to_dict() for f in report.findings]
    leaks = _scan_records(findings_as_records, "findings", seeded_policy())
    if leaks:
        print(f"REFUSING to stop here: {len(leaks)} finding(s) in the findings "
              f"file — a sanitized corpus produced unsanitized findings.")
        for leak in leaks[:20]:
            print(f"  {leak}")
        return 1
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    """Regenerate the schema-diff baseline. Network + container runtime."""
    pairs = _read_pairs(pathlib.Path(args.pairs))
    templates, keys = _corpus_endpoints(pairs)
    match = bl.match_path_regex(templates)
    print(f"scoping to {len(keys)} endpoint(s) over {len(templates)} path(s)")
    try:
        spec_a = bl.fetch_spec("a", pathlib.Path(args.cache))
        spec_b = bl.fetch_spec("b", pathlib.Path(args.cache))
    except bl.BaselineError as exc:
        sys.exit(str(exc))
    print(f"specs: {spec_a.name} -> {spec_b.name} (declared versions verified)")

    unscoped = None
    if args.unscoped:
        print("counting the unscoped diff (this takes a minute)...")
        unscoped = bl.count_oasdiff(spec_a, spec_b)
        print(f"  {unscoped:,} breaking entries over the whole spec pair")

    entries = bl.run_oasdiff(spec_a, spec_b, match=match)
    index = bl.build_index(entries, scope=keys, match=match, unscoped=unscoped)
    count = bl.write_index(pathlib.Path(args.out), index)
    meta = index["meta"]
    print(f"{meta['entries_matched_paths']:,} entries within the matched "
          f"paths, {meta['entries_corpus_endpoints']:,} on the corpus's own "
          f"endpoints")
    print(f"wrote {count} endpoint record(s) to {args.out}")
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    """Score the differ against ground truth and against the baseline."""
    pairs = _read_pairs(pathlib.Path(args.pairs))
    report = diff_pairs(pairs)
    try:
        index = bl.BaselineIndex.load(pathlib.Path(args.baseline))
    except FileNotFoundError:
        sys.exit(f"no baseline at {args.baseline}; run `compatlab baseline` first")
    adjudication = scoring.Adjudication.load(pathlib.Path(args.adjudication))
    card = scoring.score(report, index, adjudication, pairs)

    if args.json:
        print(json.dumps(card, indent=2))
    else:
        print(scoring.render(card))

    if args.out:
        pathlib.Path(args.out).write_text(scoring.render(card) + "\n")
        print(f"\nwrote {args.out}")

    unadjudicated = card["false_breaks"]["unadjudicated"]
    if unadjudicated:
        print(f"\nFAIL: {len(unadjudicated)} breaking finding(s) with no "
              f"verdict in {args.adjudication}; the false-break rate is not "
              f"publishable until every one is adjudicated.")
        return 1
    return 0


def _findings_from(path: pathlib.Path) -> list[Finding]:
    """Read the committed findings file back into Finding objects.

    Phase 4 reads `findings/findings.jsonl` rather than re-running the differ,
    because the impact report has to be about the findings that were scored
    and adjudicated. Re-deriving them here would let the two reports drift.
    """
    out = []
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            raw.pop("key", None)
            raw["targets"] = tuple(raw.get("targets") or ())
            out.append(Finding(**raw))
    return out


def cmd_impact(args: argparse.Namespace) -> int:
    """Map findings onto the integration inventory. The heart of Phase 4."""
    pairs = _read_pairs(pathlib.Path(args.pairs))
    findings = _findings_from(pathlib.Path(args.findings))
    side_a, side_b = sides(pairs)
    canon_a, canon_b = canonical_side(side_a), canonical_side(side_b)
    seqs = {(p["workflow"], p["step"]): p["seq"] for p in pairs}

    try:
        declared = wf.load_all(pathlib.Path(args.workflows))
    except wf.DeclarationError as exc:
        sys.exit(f"integration inventory: {exc}")
    if not declared:
        sys.exit(f"no workflow declarations in {args.workflows}")

    validation = wf.validate(declared, canon_a, seqs)
    print(f"inventory: {len(declared)} workflow(s), "
          f"{validation.steps_checked} declared call(s), "
          f"{validation.reads_checked} declared read(s)")
    for problem in validation.problems:
        print(f"  invalid: {problem}")
    if not validation.ok:
        print(f"FAIL: {len(validation.problems)} problem(s); the inventory "
              f"does not describe the captured traffic, so no claim made from "
              f"it would mean anything.")
        return 1

    report = impact.map_findings(declared, findings, version_a=VERSION_A,
                                 version_b=VERSION_B)
    verification = verify(report, pairs, canon_a, canon_b)
    # The regression guard: the breaks Phase 3 caught, and which findings
    # evidence each one, so the report can show that the mapping still
    # reaches them. Read from the same ground-truth inventory `score` uses.
    diff_report = diff_pairs(pairs)
    caught, evidence_keys = [], {}
    for item in scoring.GROUND_TRUTH:
        found = scoring.evidence(diff_report, item)
        evidence_keys[item.id] = {f.key for f in found}
        if found:
            caught.append({"id": item.id, "summary": item.summary})
    verification.coverage = ground_truth_coverage(report, caught, evidence_keys)
    pin_list = impact.pins(report)

    if args.json:
        print(json.dumps({
            **report.to_dict(),
            "verification": verification.to_dict(),
            "pins": pin_list,
        }, indent=2))
    else:
        print()
        print(render_impact(report, verification, pin_list))

    out = pathlib.Path(args.pins)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as handle:
        for pin in pin_list:
            handle.write(json.dumps(pin, sort_keys=True) + "\n")
    print(f"\nwrote {len(pin_list)} pin(s) to {out}")

    if args.out:
        pathlib.Path(args.out).write_text(
            render_impact(report, verification, pin_list) + "\n")
        print(f"wrote {args.out}")
    if args.html:
        pathlib.Path(args.html).write_text(
            render_html(report, verification, pin_list))
        print(f"wrote {args.html}")

    leaks = _scan_records([p for p in pin_list], "pins", seeded_policy())
    if leaks:
        print(f"REFUSING to stop here: {len(leaks)} finding(s) in the pin "
              f"file — a sanitized corpus produced unsanitized pins.")
        for leak in leaks[:20]:
            print(f"  {leak}")
        return 1

    if not verification.ok:
        print(f"\nFAIL: {len(verification.unconfirmed)} impact claim(s) could "
              f"not be confirmed against the replay record; the "
              f"workflow-mapping precision is not publishable while any claim "
              f"is unverified.")
        return 1
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

    rep = sub.add_parser("replay", help="replay the corpus against two versions")
    rep.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    rep.add_argument("--a", default=VERSION_A)
    rep.add_argument("--b", default=VERSION_B)
    rep.set_defaults(func=cmd_replay)

    ctl = sub.add_parser("control", help="A/A control run: same version twice")
    ctl.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ctl.add_argument("--version", default=VERSION_A)
    ctl.add_argument("--show", type=int, default=6,
                     help="mismatch lines to print per step")
    ctl.set_defaults(func=cmd_control)

    dif = sub.add_parser("diff", help="classify paired A/B responses")
    dif.add_argument("--pairs", default=str(PAIRS_PATH))
    dif.add_argument("--out", default=str(FINDINGS_PATH))
    dif.add_argument("--severity", action="append", choices=SEVERITIES,
                     help="print only this severity; repeatable")
    dif.add_argument("--why", action="store_true", help="print each rationale")
    dif.add_argument("--json", action="store_true")
    dif.set_defaults(func=cmd_diff)

    base = sub.add_parser("baseline", help="regenerate the schema-diff baseline")
    base.add_argument("--pairs", default=str(PAIRS_PATH))
    base.add_argument("--out", default=str(BASELINE_PATH))
    base.add_argument("--cache", default=str(SPEC_CACHE))
    base.add_argument("--unscoped", action="store_true",
                      help="also count the whole-spec diff (slow, ~390MB)")
    base.set_defaults(func=cmd_baseline)

    sco = sub.add_parser("score", help="caught N of M, baseline, false breaks")
    sco.add_argument("--pairs", default=str(PAIRS_PATH))
    sco.add_argument("--baseline", default=str(BASELINE_PATH))
    sco.add_argument("--adjudication", default=str(ADJUDICATION_PATH))
    sco.add_argument("--out", nargs="?", const=str(REPORT_PATH),
                     help="also write the markdown report")
    sco.add_argument("--json", action="store_true")
    sco.set_defaults(func=cmd_score)

    imp = sub.add_parser("impact", help="map findings onto customer workflows")
    imp.add_argument("--pairs", default=str(PAIRS_PATH))
    imp.add_argument("--findings", default=str(FINDINGS_PATH))
    imp.add_argument("--workflows", default=str(WORKFLOW_DIR))
    imp.add_argument("--pins", default=str(PINS_PATH))
    imp.add_argument("--out", nargs="?", const=str(IMPACT_PATH),
                     help="also write the markdown report")
    imp.add_argument("--html", nargs="?", const=str(IMPACT_HTML_PATH),
                     help="also write the self-contained HTML report")
    imp.add_argument("--json", action="store_true")
    imp.set_defaults(func=cmd_impact)

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
