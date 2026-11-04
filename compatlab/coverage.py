"""Per-endpoint coverage stats over a stored corpus.

The number that matters is not how many calls were captured but what they
reach: which endpoints, which status classes, and which of the ground-truth
behavioral breaks from `docs/ground-truth.md` the corpus can actually
exercise. The last one is the honest denominator for the epic's headline —
a break no captured call touches cannot be caught, and the coverage table is
where that shows up instead of being quietly absent from the score.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

# Behavioral breaks in scope per docs/ground-truth.md, after the Phase 0 spike
# disqualified the account-gated and upstream-reversed entries. The M in the
# epic's "caught N of M" headline.
GROUND_TRUTH_M = 8


def summarize(records: list[dict]) -> dict[str, Any]:
    endpoints: dict[tuple[str, str], Counter] = defaultdict(Counter)
    workflows: dict[str, Counter] = defaultdict(Counter)
    targets: dict[str, set[str]] = defaultdict(set)
    versions: Counter = Counter()
    statuses: Counter = Counter()

    for rec in records:
        key = (rec["method"], rec["path_template"])
        status = rec["response"]["status"]
        endpoints[key][status] += 1
        workflows[rec["workflow"]][status] += 1
        versions[rec["stripe_version"]] += 1
        statuses[status] += 1
        for target in rec.get("targets", ()):
            targets[target].add(rec["workflow"])

    return {
        "records": len(records),
        "endpoints": [
            {
                "method": method,
                "path": path,
                "calls": sum(by_status.values()),
                "statuses": dict(sorted(by_status.items())),
            }
            for (method, path), by_status in sorted(endpoints.items(),
                                                    key=lambda kv: kv[0][::-1])
        ],
        "workflows": [
            {
                "workflow": name,
                "calls": sum(by_status.values()),
                "ok": sum(n for s, n in by_status.items() if s < 400),
                "errors": sum(n for s, n in by_status.items() if s >= 400),
            }
            for name, by_status in sorted(workflows.items())
        ],
        "targets": {t: sorted(w) for t, w in sorted(targets.items())},
        "versions": dict(sorted(versions.items())),
        "statuses": dict(sorted(statuses.items())),
    }


def render(summary: dict[str, Any], ground_truth_m: int | None = None) -> str:
    """Markdown, for the CLI and for docs/corpus-coverage.md."""
    lines = [
        f"Records: {summary['records']}",
        f"Versions: {', '.join(f'{v} ({n})' for v, n in summary['versions'].items())}",
        f"Statuses: {', '.join(f'{s}: {n}' for s, n in summary['statuses'].items())}",
        "",
        "| Method | Endpoint | Calls | Statuses |",
        "|--------|----------|-------|----------|",
    ]
    for row in summary["endpoints"]:
        statuses = ", ".join(f"{s}×{n}" for s, n in row["statuses"].items())
        lines.append(
            f"| {row['method']} | `{row['path']}` | {row['calls']} | {statuses} |"
        )
    lines += ["", "| Workflow | Calls | 2xx/3xx | 4xx/5xx |",
              "|----------|-------|---------|---------|"]
    for row in summary["workflows"]:
        lines.append(
            f"| {row['workflow']} | {row['calls']} | {row['ok']} | {row['errors']} |"
        )
    covered = summary["targets"]
    headline = f"Ground-truth breaks exercised: {len(covered)}"
    if ground_truth_m:
        headline += f" of {ground_truth_m}"
    lines += ["", headline]
    for target, workflows in covered.items():
        lines.append(f"- {target}: {', '.join(workflows)}")
    return "\n".join(lines)
