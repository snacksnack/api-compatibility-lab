"""Quality gauges to the Datadog v2 series API.

The dashboard, monitors and SLOs in `tpm-automation-platform/datadog/` read
these series: how many documented breaks the differ caught, the false-break
rate, workflow-mapping precision, how many pins are certified, and the PII
count on the committed corpus.

Decoration, like tracing is elsewhere in the estate: without `DD_API_KEY` in
the environment, `submit()` declines and the caller is unaffected. But never
*silently* — the v2 series endpoint takes `type` as an integer enum and
answers a malformed payload with a 400 that, swallowed, is indistinguishable
from no traffic (the RC1-440 lesson, and the day RC1-613 spent chasing a
query bug that looked like missing data). A failed POST prints to stderr and
returns False; it never raises.

These are **gauges**, not counts. A quality rate is a level, not a tally: four
runs in an hour that each caught 4 breaks must not read as 16.
"""

from __future__ import annotations

import json
import os
import sys
import time
from importlib.metadata import PackageNotFoundError, version

import httpx

METRIC_PREFIX = "compatlab."
SERVICE = "api-compatibility-lab"
# The v2 series integer enum: 0 unspecified, 1 count, 2 rate, 3 gauge.
GAUGE = 3
COUNT = 1


def package_version() -> str:
    try:
        return version("api-compatibility-lab")
    except PackageNotFoundError:  # pragma: no cover - installed in every run
        return "0.0.0"


def base_tags() -> list[str]:
    return [
        f"service:{SERVICE}",
        f"env:{os.environ.get('DD_ENV', 'prod')}",
        # Without a version tag a root span's tags are dropped, and the same
        # habit keeps a series attributable to the code that produced it (the
        # dropped-root-span-tags lesson, RC1-429).
        f"version:{os.environ.get('DD_VERSION') or package_version()}",
    ]


def series_payload(points: dict[str, float], *, metric_type: int = GAUGE,
                   tags: dict[str, str] | None = None,
                   at: int | None = None) -> dict:
    """One payload for POST /api/v2/series. Pure, so the shape is testable."""
    extra = [f"{k}:{v}" for k, v in sorted((tags or {}).items())]
    stamp = at or int(time.time())
    return {
        "series": [
            {
                "metric": METRIC_PREFIX + name,
                "type": metric_type,
                "points": [{"timestamp": stamp, "value": value}],
                "tags": base_tags() + extra,
            }
            for name, value in sorted(points.items())
        ]
    }


def submit(points: dict[str, float], *, metric_type: int = GAUGE,
           tags: dict[str, str] | None = None) -> bool:
    """Submit a batch of points, or decline without a key.

    Returns whether Datadog accepted them. One POST for the whole batch: a
    partial publish would leave a dashboard mixing two runs.
    """
    api_key = os.environ.get("DD_API_KEY")
    if not api_key:
        return False
    payload = series_payload(points, metric_type=metric_type, tags=tags)
    site = os.environ.get("DD_SITE", "datadoghq.com")
    try:
        response = httpx.post(
            f"https://api.{site}/api/v2/series",
            headers={"DD-API-KEY": api_key, "Content-Type": "application/json"},
            content=json.dumps(payload),
            timeout=10,
        )
    except httpx.HTTPError as exc:
        print(f"datadog: {len(points)} point(s) not submitted: {exc}",
              file=sys.stderr)
        return False
    if response.status_code >= 300:
        # Printed in full on purpose: a 400 here is a payload bug, and the
        # whole failure mode being guarded against is one that looks like
        # silence on the dashboard.
        print(f"datadog: {response.status_code} {response.text[:300]}",
              file=sys.stderr)
        return False
    return True
