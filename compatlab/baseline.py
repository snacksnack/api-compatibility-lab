"""The schema-diff baseline: what an OpenAPI diff reports over the same pair.

The epic's headline is a comparison, and a comparison needs an opponent that
cannot be accused of being built to lose. So the baseline is not a schema
differ written here. It is `oasdiff` — the most widely used OpenAPI breaking-
change tool — run in `breaking` mode over Stripe's *own* published spec at two
commits pinned in ADR 0001 D3, with the tool's container pinned by digest and
the spec's self-declared version checked against the version it is supposed to
be. Anyone can re-run it and get the same file.

Two things about that run are worth knowing before reading any score.

**It is not quiet.** Over the whole spec pair it reports 254,576 breaking
changes. Scoped to the twenty endpoints this corpus touches, 17,938 — of which
16,422 are one rule, `response-property-enum-value-added`, mostly from
Stripe's deeply recursive `anyOf` chains, where a new country or currency
appears at a hundred nested paths. A reader who diffs these two specs does not
get a green light they can trust; they get a haystack. That is as much a part
of the baseline's performance as anything it misses.

**It is given every benefit of the doubt.** Matching a lab finding to the
baseline is done on *field name within endpoint*, over every backticked token
in the entry's text, with `anyOf[...]` noise stripped — so an entry about
`error/payment_intent/capture_method` counts as the baseline having said
something about `capture_method` on that endpoint. That is deliberately
generous: the claim being made is that the baseline missed things, and a
generous match makes it harder to claim, not easier. The scoring report then
separates "said nothing at all" from "named the field but not the behavior",
because those are different failures and only one of them is a miss.

`compatlab baseline` regenerates `baseline/schema-diff-index.json`. It needs
network and a container runtime, so it is run by hand and its output is
committed; `compatlab score` reads the index and needs neither.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import httpx

# ADR 0001 D3. The SHA is the contract; the version string is the check that
# the SHA is the one meant, and a spec that fails it is not diffed.
SPEC_REPO = "stripe/openapi"
SPEC_PATH = "openapi/spec3.json"
SPEC_PINS: dict[str, tuple[str, str]] = {
    "a": ("c3ae0d4c07", "2022-11-15"),
    "b": ("31b29ff897", "2025-03-31.basil"),
}

# Pinned by digest, not by tag: `tufin/oasdiff:latest` is a moving target and
# a baseline that moves is not a baseline.
OASDIFF_IMAGE = (
    "tufin/oasdiff@sha256:"
    "6f3b5b168f26349bc3ff91f571c86694381548822b47aeebefddb93d422c4830"
)
OASDIFF_BUILD = "dbf670e"

INDEX_PATH = pathlib.Path("baseline/schema-diff-index.jsonl")
BACKTICKED = re.compile(r"`([^`]+)`")
ANY_OF = re.compile(r"anyOf\[[^]]*\]")
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
PATH_PARAM = re.compile(r"\{[^}]+\}")
# One per entry in oasdiff's JSON output, used to count a stream too large to
# parse: the unscoped diff is roughly 390 MB of JSON.
FINGERPRINT = re.compile(rb'"fingerprint"')


class BaselineError(RuntimeError):
    """The baseline could not be produced, so there is nothing to score."""


def spec_url(sha: str) -> str:
    return f"https://raw.githubusercontent.com/{SPEC_REPO}/{sha}/{SPEC_PATH}"


def fetch_spec(side: str, dest: pathlib.Path) -> pathlib.Path:
    """Download one pinned spec and verify the version it declares."""
    sha, expected = SPEC_PINS[side]
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"spec3-{sha}.json"
    if not out.exists():
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            response = client.get(spec_url(sha))
            response.raise_for_status()
            out.write_bytes(response.content)
    declared = json.loads(out.read_text())["info"]["version"]
    if declared != expected:
        raise BaselineError(
            f"{SPEC_REPO}@{sha} declares version {declared!r}, expected "
            f"{expected!r}: the pin in ADR 0001 D3 is wrong or the history moved"
        )
    return out


def normalize_path(path: str) -> str:
    """`/v1/customers/{customer}` and `/v1/customers/{id}` are one endpoint."""
    return PATH_PARAM.sub("{}", path)


def endpoint_key(method: str, path: str) -> str:
    return f"{method.upper()} {normalize_path(path)}"


def match_path_regex(path_templates: list[str]) -> str:
    """An oasdiff `--match-path` covering exactly the corpus's endpoints."""
    alternatives = sorted({
        "/".join(
            r"\{[^}]+\}" if segment.startswith("{") else re.escape(segment)
            for segment in template.split("/")
        )
        for template in path_templates
    })
    return "^(?:" + "|".join(alternatives) + ")$"


def _oasdiff_command(spec_a: pathlib.Path, spec_b: pathlib.Path,
                     match: str | None) -> list[str]:
    local = shutil.which("oasdiff")
    if local:
        command = [local, "breaking", str(spec_a), str(spec_b)]
    elif shutil.which("docker"):
        mount = spec_a.parent.resolve()
        command = [
            "docker", "run", "--rm", "-v", f"{mount}:/specs:ro", OASDIFF_IMAGE,
            "breaking", f"/specs/{spec_a.name}", f"/specs/{spec_b.name}",
        ]
    else:
        raise BaselineError(
            "neither `oasdiff` nor `docker` is on PATH; the baseline needs one "
            "of them (ADR 0004 D5)"
        )
    command += ["-f", "json"]
    if match:
        command += ["-p", match]
    return command


def run_oasdiff(spec_a: pathlib.Path, spec_b: pathlib.Path, *,
                match: str | None = None) -> list[dict]:
    """Every breaking-change entry oasdiff reports, parsed."""
    command = _oasdiff_command(spec_a, spec_b, match)
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode not in (0, 1):
        raise BaselineError(
            f"oasdiff exited {result.returncode}: "
            f"{result.stderr.decode()[:400]}"
        )
    return json.loads(result.stdout or b"[]")


def count_oasdiff(spec_a: pathlib.Path, spec_b: pathlib.Path) -> int:
    """How many entries the *unscoped* diff reports, without parsing it.

    The whole-spec run is around 390 MB of JSON. The number is worth having —
    it is the single most informative fact about the baseline — and loading it
    into memory to count a list is not.
    """
    command = _oasdiff_command(spec_a, spec_b, None)
    total = 0
    with subprocess.Popen(command, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        assert process.stdout is not None
        tail = b""
        while chunk := process.stdout.read(1 << 20):
            buffer = tail + chunk
            total += len(FINGERPRINT.findall(buffer))
            tail = buffer[-16:]
    return total


def fields_named(text: str) -> set[str]:
    """Every field name an entry's text mentions, generously.

    oasdiff describes a property by a slash-joined path, sometimes with
    `anyOf[subschema #2: Charge]` segments wedged in. Taking every plausible
    segment, at any depth, is the generosity the module docstring promises:
    the baseline gets credit for naming a field however deep inside a
    polymorphic chain it managed to name it.
    """
    out: set[str] = set()
    for token in BACKTICKED.findall(text):
        for segment in ANY_OF.sub("", token).split("/"):
            segment = segment.strip().lstrip("#").strip()
            if FIELD_NAME.match(segment):
                out.add(segment)
    return out


def build_index(entries: list[dict], *, scope: list[str],
                match: str, unscoped: int | None = None) -> dict[str, Any]:
    """Collapse oasdiff's entries into something a scorer can query.

    Rule ids are stored as indices into a table carried in the meta record.
    Pure encoding, no information dropped: spelled out, the index is 743 KB of
    the same fourteen strings repeated, and a committed artifact nobody can
    bear to open is a committed artifact nobody checks.
    """
    rules = sorted({entry.get("id", "unknown") for entry in entries})
    rule_index = {name: str(i) for i, name in enumerate(rules)}

    endpoints: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = endpoint_key(entry.get("operation", ""), entry.get("path", ""))
        bucket = endpoints.setdefault(
            key, {"entries": 0, "path_level": {}, "fields": {}})
        bucket["entries"] += 1
        rule = rule_index[entry.get("id", "unknown")]
        names = fields_named(entry.get("text", ""))
        if not names:
            bucket["path_level"][rule] = bucket["path_level"].get(rule, 0) + 1
            continue
        for name in names:
            by_rule = bucket["fields"].setdefault(name, {})
            by_rule[rule] = by_rule.get(rule, 0) + 1

    on_scope = sum(endpoints.get(key, {}).get("entries", 0) for key in scope)
    # The rule mix is the fact that explains the entry count: one rule carries
    # almost all of it. Stored rather than quoted in prose, so the report can
    # cite a number the index can be re-derived to check.
    mix: dict[str, int] = {}
    for entry in entries:
        if endpoint_key(entry.get("operation", ""), entry.get("path", "")) in scope:
            name = entry.get("id", "unknown")
            mix[name] = mix.get(name, 0) + 1
    return {
        "meta": {
            "record": "meta",
            "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "oasdiff": {"image": OASDIFF_IMAGE, "build": OASDIFF_BUILD},
            "specs": {
                side: {"repo": SPEC_REPO, "sha": sha, "declared_version": version}
                for side, (sha, version) in SPEC_PINS.items()
            },
            "rules": rules,
            "match_path": match,
            "scope": sorted(scope),
            # Three numbers, because only the narrowest is a fair comparison
            # and the widest is the most informative thing about the baseline.
            "entries_unscoped": unscoped,
            "entries_matched_paths": len(entries),
            "entries_corpus_endpoints": on_scope,
            # Written sorted for the reader; JSON key order is not load-bearing
            # and the consumer ranks by count.
            "rule_mix_corpus_endpoints": dict(
                sorted(mix.items(), key=lambda kv: (-kv[1], kv[0]))),
        },
        "endpoints": {
            key: {
                "record": "endpoint",
                "endpoint": key,
                "entries": value["entries"],
                "path_level": dict(sorted(value["path_level"].items())),
                "fields": {
                    name: dict(sorted(rules_seen.items()))
                    for name, rules_seen in sorted(value["fields"].items())
                },
            }
            for key, value in sorted(endpoints.items())
        },
    }


def write_index(path: pathlib.Path, index: dict[str, Any]) -> int:
    """JSONL: the meta record, then one line per endpoint.

    Same reason the corpus is JSONL — a regenerated index shows up in review
    as the endpoints that changed, not as one unreadable blob.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        handle.write(json.dumps(index["meta"], sort_keys=True) + "\n")
        for endpoint in index["endpoints"].values():
            handle.write(json.dumps(endpoint, sort_keys=True) + "\n")
    return len(index["endpoints"])


@dataclass(frozen=True)
class BaselineIndex:
    """The committed baseline, queried by endpoint and field name."""

    meta: dict[str, Any]
    endpoints: dict[str, dict[str, Any]]

    @classmethod
    def from_index(cls, index: dict[str, Any]) -> BaselineIndex:
        return cls(index["meta"], index["endpoints"])

    @classmethod
    def load(cls, path: pathlib.Path) -> BaselineIndex:
        meta: dict[str, Any] = {}
        endpoints: dict[str, dict[str, Any]] = {}
        with path.open() as handle:
            for line in filter(str.strip, handle):
                record = json.loads(line)
                if record.get("record") == "meta":
                    meta = record
                else:
                    endpoints[record["endpoint"]] = record
        if not meta:
            raise BaselineError(f"{path} has no meta record")
        return cls(meta, endpoints)

    @property
    def rules(self) -> list[str]:
        return self.meta.get("rules", [])

    @property
    def entries_unscoped(self) -> int | None:
        return self.meta.get("entries_unscoped")

    @property
    def entries_corpus_endpoints(self) -> int:
        return self.meta.get("entries_corpus_endpoints", 0)

    @property
    def entries_matched_paths(self) -> int:
        return self.meta.get("entries_matched_paths", 0)

    @property
    def rule_mix(self) -> dict[str, int]:
        return self.meta.get("rule_mix_corpus_endpoints", {})

    def _named(self, indices: dict[str, int]) -> dict[str, int]:
        return {
            self.rules[int(key)] if int(key) < len(self.rules) else key: count
            for key, count in sorted(indices.items(), key=lambda kv: int(kv[0]))
        }

    def endpoint(self, method: str, path: str) -> dict[str, Any]:
        return self.endpoints.get(endpoint_key(method, path), {})

    def entry_count(self, method: str, path: str) -> int:
        return self.endpoint(method, path).get("entries", 0)

    def path_level(self, method: str, path: str) -> dict[str, int]:
        return self._named(self.endpoint(method, path).get("path_level", {}))

    def rules_for(self, method: str, path: str, field: str) -> dict[str, int]:
        fields = self.endpoint(method, path).get("fields", {})
        return self._named(fields.get(field, {}))

    def covers_endpoint(self, method: str, path: str) -> bool:
        return endpoint_key(method, path) in self.endpoints
