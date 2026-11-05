"""Fixtures for the generated pinned-behavior suite. See ADR 0006.

One suite, two transports, and the same assertions either way:

- **live** replays the corpus against one API version and canonicalizes what
  comes back. This is the run that is evidence: version A's traffic is fetched
  *after* the pins were written, so a pin passing on A is a statement about
  the API and not about the file the pin came from.
- **recorded** canonicalizes a committed replay instead, so the suite runs in
  CI with no key and no network. That run can only ever confirm that the
  generated code compiles and evaluates as specified — the pins were derived
  from those exact records, so it is circular as evidence about the API, and
  `compatlab pin check` labels it that way.

The version is never implicit. In recorded mode the records' own
`stripe_version` has to match `--api-version`, and in live mode a replay
warning about a served version is fatal. Both exist because a suite that
silently ran one version twice would pass every pin and prove nothing
(the Phase 2 lesson, ADR 0003).
"""

from __future__ import annotations

import pathlib

import httpx
import pytest

from compatlab import STRIPE_BASE_URL, VERSION_A
from compatlab.canonical import canonical_side
from compatlab.corpus import read
from compatlab.pinning import canonical_of
from compatlab.replay import replay_corpus
from compatlab.transport import stripe_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_CORPUS = ROOT / "corpus" / "version-a.jsonl"


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("compatlab", "pinned-behavior suite")
    group.addoption("--api-version", default=VERSION_A,
                    help="the API version to pin against (default: version A)")
    group.addoption("--records", default=None,
                    help="canonicalize this recorded replay instead of calling "
                         "the live API")
    group.addoption("--corpus", default=str(DEFAULT_CORPUS),
                    help="the corpus to replay in live mode")


@pytest.fixture(scope="session")
def api_version(request: pytest.FixtureRequest) -> str:
    return str(request.config.getoption("--api-version"))


@pytest.fixture(scope="session")
def side(request: pytest.FixtureRequest,
         api_version: str) -> dict[tuple[str, str], dict]:
    """Every canonical response for one version, keyed by (workflow, step)."""
    recorded = request.config.getoption("--records")
    if recorded:
        records = read(pathlib.Path(recorded))
        served = {rec.get("stripe_version") for rec in records}
        if served != {api_version}:
            raise pytest.UsageError(
                f"{recorded} holds version(s) {sorted(served)}, not "
                f"{api_version!r}: these tests are about one version at a "
                f"time, and running the wrong record would pass every pin")
        return canonical_side(records)

    corpus = read(pathlib.Path(str(request.config.getoption("--corpus"))))
    with httpx.Client(base_url=STRIPE_BASE_URL, auth=(stripe_key(ROOT), ""),
                      timeout=30) as client:
        report = replay_corpus(client, corpus, api_version)
    if report.warnings:
        raise pytest.UsageError(
            "the API did not serve the version that was asked for: "
            + "; ".join(f"{name}: {detail}" for name, detail in report.warnings))
    return canonical_side(report.records)


@pytest.fixture
def canonical(side: dict[tuple[str, str], dict]):
    """`canonical("workflow.step")`, or an `[unreached]` failure."""
    def fetch(corpus: str) -> dict:
        return canonical_of(side, corpus)
    return fetch
