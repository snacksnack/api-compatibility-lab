"""The redaction engine: key rules, value detectors, and an auditor.

Nothing here knows about Stripe, HTTP, or the corpus format. A `Policy` is
data — rules, detectors, a salt — so the second consumer of this component
(RC1-594's diagnostic bundle) ships its own policy over the same engine
instead of a second implementation.

Two passes over the same policy, and they are deliberately not symmetric:

- `redact` rewrites a payload before it is ever stored.
- `scan` audits a payload that is already stored and reports what a careless
  writer would have left behind. It does not ask what the writer intended; it
  looks for detectable sensitive values and accepts only a recognized
  surrogate, the drop marker, or an explicitly allowed public test value.

So `scan(redact(x))` coming back empty is evidence, not a tautology, and the
corpus gate in CI asserts exactly that against the committed corpus.

Value detectors run on strings only. Numeric fields are matched by key, which
keeps a 10-digit Unix timestamp from being read as a phone number.

A fourth mechanism decodes before it looks. Stripe's `receipt_url` carries
the account id base64-encoded inside an opaque blob, so a detector reading the
raw string sees nothing: the plain `acct_...` form was caught and the encoded
copy of the same value was not. Encoded personal data is still personal data,
so candidate base64 runs are decoded (at each of the three byte alignments,
standard and url-safe) and the decoded text is re-run through the detectors.

A third mechanism exists because the other two cannot cover one real case: a
sensitive value the server echoed into free text under an innocuous key.
Stripe composes an invoice line item's `description` from the product name, so
a name redacted at its own key reappears in prose where nothing marks it. No
detector can recognize a name. So a policy also carries `known` — literal
values it has been told are sensitive — and replaces them wherever they
appear, with the same surrogate their keyed occurrence gets.
"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from compatlab.redaction.detectors import (
    DETECTORS,
    DROP,
    PII,
    REDACTED,
    SURROGATE,
    Detector,
    is_surrogate,
    surrogate,
)

# A base64-ish run long enough to be worth decoding.
ENCODED_RE = re.compile(r"[A-Za-z0-9_-]{20,}={0,2}")
ENCODED_RULE = "encoded"

DEFAULT_SALT_NAME = "COMPATLAB_REDACTION_SALT"
PUBLIC_DEMO_SALT = b"compatlab-public-demo"


def default_salt() -> bytes:
    """Salt for surrogate derivation, from the environment when set.

    The fallback is public on purpose: this repo's corpus is synthetic sandbox
    traffic, and a reproducible corpus is worth more here than an unguessable
    one. A customer install sets a private salt, which is what stops a
    surrogate from being reversed by hashing a dictionary of candidate values.
    """
    env = os.environ.get(DEFAULT_SALT_NAME)
    return env.encode("utf-8") if env else PUBLIC_DEMO_SALT


def leaf_key(key: str) -> str:
    """`address[line1]` -> `line1`.

    Form-encoded request bodies are flat dicts with bracketed paths, so a rule
    written for `line1` has to match the bracketed spelling too.
    """
    if key.endswith("]") and "[" in key:
        return key[key.rindex("[") + 1 : -1]
    return key


def tails(key: str) -> list[str]:
    """`customer_name` -> ['customer_name', 'name'].

    Stripe snapshots customer fields onto other objects under prefixed names:
    an Invoice carries `customer_name`, `customer_phone`, `customer_address`.
    A rule written for `name` has to match those, or a person's name survives
    into the corpus with no detectable shape to catch it downstream.
    """
    parts = key.split("_")
    return ["_".join(parts[i:]) for i in range(len(parts))]


def mask(value: str) -> str:
    """A locator for a finding that is not itself a copy of the value."""
    return f"{value[:1]}{'*' * min(len(value) - 1, 11)} ({len(value)} chars)"


@dataclass(frozen=True)
class KeyRule:
    """Redact whatever sits under these keys, whatever shape it is."""

    name: str
    kind: str
    action: str
    keys: frozenset[str] = frozenset()
    suffixes: tuple[str, ...] = ()
    shape: str | None = None

    def matches(self, key: str) -> bool:
        leaf = leaf_key(key)
        if leaf.endswith(self.suffixes or ()):
            return True
        return any(tail in self.keys for tail in tails(leaf))


@dataclass(frozen=True)
class Finding:
    """One sensitive value that survived into stored data."""

    path: str
    rule: str
    kind: str
    preview: str

    def __str__(self) -> str:
        return f"{self.path}: {self.rule} ({self.kind}) {self.preview}"


@dataclass(frozen=True)
class Policy:
    name: str
    key_rules: tuple[KeyRule, ...] = ()
    detectors: tuple[Detector, ...] = DETECTORS
    allow_values: frozenset[str] = frozenset()
    known: Mapping[str, str | None] = field(default_factory=dict)
    salt: bytes = field(default_factory=default_salt)

    def with_salt(self, salt: bytes) -> Policy:
        return replace(self, salt=salt)

    def with_known(self, values: Mapping[str, str | None]) -> Policy:
        """Add literal values to redact wherever they appear, keyed or not."""
        return replace(self, known={**self.known, **values})

    def key_rule_for(self, key: str) -> KeyRule | None:
        for rule in self.key_rules:
            if rule.matches(key):
                return rule
        return None

    def redact(self, value: Any, path: str = "$") -> Any:
        """Return a copy with every matched value dropped or surrogated."""
        return self._walk(value, path, None, None)

    def scan(self, value: Any, path: str = "$") -> list[Finding]:
        """Report sensitive values present in already-stored data."""
        findings: list[Finding] = []
        self._walk(value, path, None, findings)
        return findings

    # --- traversal -------------------------------------------------------
    # One walk serves both passes: `findings is None` means rewrite only,
    # a list means audit. Keeping them in one function is what guarantees the
    # scan looks in every place the redactor wrote.

    def _walk(self, value: Any, path: str, rule: KeyRule | None,
              findings: list[Finding] | None) -> Any:
        if isinstance(value, dict):
            return {
                key: self._walk(
                    item,
                    f"{path}.{key}",
                    rule or self.key_rule_for(key),
                    findings,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._walk(item, f"{path}[{i}]", rule, findings)
                for i, item in enumerate(value)
            ]
        if rule is not None:
            return self._under_rule(value, path, rule, findings)
        if isinstance(value, str):
            return self._in_string(value, path, findings)
        return value

    def _under_rule(self, value: Any, path: str, rule: KeyRule,
                    findings: list[Finding] | None) -> Any:
        if value is None or value == "" or isinstance(value, bool):
            return value
        text = str(value)
        if text in self.allow_values or is_surrogate(text):
            return value
        if findings is not None:
            findings.append(Finding(path, rule.name, rule.kind, mask(text)))
        if rule.action == DROP:
            return REDACTED
        return surrogate(self.salt, text, rule.shape)

    def _in_string(self, text: str, path: str,
                   findings: list[Finding] | None) -> str:
        out = self._known_in_string(text, path, findings)
        out = self._encoded_in_string(out, path, findings)
        for detector in self.detectors:
            for hit in detector.findall(out):
                if hit in self.allow_values or is_surrogate(hit):
                    continue
                if findings is not None:
                    findings.append(
                        Finding(path, detector.name, detector.kind, mask(hit))
                    )
                stand_in = (
                    REDACTED
                    if detector.action == DROP
                    else surrogate(self.salt, hit, detector.shape)
                )
                out = out.replace(hit, stand_in)
        return out

    def _encoded_in_string(self, text: str, path: str,
                           findings: list[Finding] | None) -> str:
        out = text
        for candidate in ENCODED_RE.findall(text):
            if is_surrogate(candidate) or candidate in self.allow_values:
                continue
            detector = self._decodes_to_sensitive(candidate)
            if detector is None:
                continue
            if findings is not None:
                findings.append(Finding(
                    path, f"{ENCODED_RULE}_{detector.name}", detector.kind,
                    mask(candidate),
                ))
            out = out.replace(candidate, surrogate(self.salt, candidate))
        return out

    def _decodes_to_sensitive(self, candidate: str) -> Detector | None:
        """The first detector that fires on any decoding of this run."""
        for offset in range(3):
            chunk = candidate[offset:]
            chunk = chunk[: len(chunk) // 4 * 4]
            if len(chunk) < 8:
                continue
            for decode in (base64.urlsafe_b64decode, base64.b64decode):
                try:
                    plain = decode(chunk).decode("latin-1")
                except (ValueError, UnicodeDecodeError):
                    continue
                for detector in self.detectors:
                    hits = [h for h in detector.findall(plain)
                            if h not in self.allow_values]
                    if hits:
                        return detector
        return None

    def _known_in_string(self, text: str, path: str,
                         findings: list[Finding] | None) -> str:
        out = text
        # Longest first: a known value may contain a shorter one.
        for literal in sorted(self.known, key=len, reverse=True):
            if literal not in out:
                continue
            if findings is not None:
                findings.append(
                    Finding(path, "known_value", PII, mask(literal))
                )
            out = out.replace(literal, surrogate(self.salt, literal,
                                                 self.known[literal]))
        return out


__all__ = [
    "DROP",
    "REDACTED",
    "SURROGATE",
    "Finding",
    "KeyRule",
    "Policy",
    "default_salt",
    "leaf_key",
    "mask",
    "tails",
]
