"""Value-shape detectors and the reserved-range surrogates that replace them.

Every surrogate is drawn from a range reserved for documentation or testing —
`example.invalid`, the 555-01xx fictional phone block, TEST-NET-1, ZIPs
beginning 000, Stripe's published test card — so a surrogate can never collide
with a real value, and an auditor can recognize one on sight. That recognition
is load-bearing: `compatlab.redaction.core.Policy.scan` treats a detectable
value as a finding *unless* it is a surrogate, which is how an independent
scan of a redacted corpus can come back clean without trusting the writer.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Callable
from dataclasses import dataclass

REDACTED = "[redacted]"

# What a rule does with a value it matched.
DROP = "drop"             # replace with REDACTED; never flows, replay included
SURROGATE = "surrogate"   # replace with a type-preserving reserved stand-in

# What kind of value it is, carried into findings so a scan report can say
# whether it blocked on a credential or on personal data.
SECRET = "secret"
PII = "pii"
IDENTITY = "identity"

# Shapes a surrogate can take. A rule names the shape it wants; when it names
# none, the shape is inferred from the value so a surrogate stays type-valid.
EMAIL = "email"
PHONE = "phone"
CARD = "card"
IP = "ip"
SSN = "ssn"
ACCOUNT = "account"
POSTAL = "postal"
STRING = "string"


def token(salt: bytes, value: str, length: int = 8) -> str:
    """Stable hex token for a value: same salt + value -> same token, always.

    Keyed rather than a bare hash: with a private salt, a surrogate cannot be
    reversed by hashing a dictionary of candidate emails. The default salt is
    public (see core.DEFAULT_SALT), which is fine for this repo's synthetic
    sandbox corpus and is not fine for a customer install.
    """
    digest = hmac.new(salt, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:length]


def _digits(salt: bytes, value: str, count: int) -> str:
    return str(int(token(salt, value, 8), 16)).zfill(count)[-count:]


def surrogate(salt: bytes, value: str, shape: str | None = None) -> str:
    """Deterministic, type-preserving stand-in for one sensitive value."""
    shape = shape or infer_shape(value)
    if shape == EMAIL:
        return f"redacted-{token(salt, value)}@example.invalid"
    if shape == PHONE:
        return f"+1555010{_digits(salt, value, 4)}"
    if shape == CARD:
        return "4242424242424242"
    if shape == IP:
        return f"192.0.2.{int(_digits(salt, value, 2)) % 254 + 1}"
    if shape == SSN:
        return "000-00-0000"
    if shape == ACCOUNT:
        return f"acct_redacted{token(salt, value)}"
    if shape == POSTAL:
        return f"000{_digits(salt, value, 2)}"
    return f"redacted-{token(salt, value)}"


# (shape, detector pattern, surrogate recognizer)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A phone number has to carry a formatting signal — a leading + or separators.
# A bare run of digits is far more often an id or a timestamp: the first live
# capture flagged the digit substring of a hex record id as a phone number.
# Bare-digit phone fields are the `phone` key rule's job, not this pattern's.
_PHONE_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:\+\d[\d\-.() ]{7,16}\d|\(?\d{3}\)?[-.\s]\s?\d{3}[-.\s]?\d{4})"
    r"(?![A-Za-z0-9])"
)
_CARD_RE = re.compile(r"(?<![A-Za-z0-9-])(?:\d[ -]?){12,18}\d(?![A-Za-z0-9-])")
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_ACCOUNT_RE = re.compile(r"\bacct_[A-Za-z0-9]{8,}\b")
_STRIPE_KEY_RE = re.compile(r"\b(?:sk|rk|pk)_(?:test|live)_[A-Za-z0-9]{8,}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}")

_SURROGATE_RES = (
    re.compile(r"^redacted-[0-9a-f]{8}@example\.invalid$"),
    re.compile(r"^\+1555010\d{4}$"),
    re.compile(r"^4242424242424242$"),
    re.compile(r"^192\.0\.2\.\d{1,3}$"),
    re.compile(r"^000-00-0000$"),
    re.compile(r"^acct_redacted[0-9a-f]{8}$"),
    re.compile(r"^000\d{2}$"),
    re.compile(r"^redacted-[0-9a-f]{8}$"),
)


def is_surrogate(value: str) -> bool:
    """True for a value this module produced, or the drop marker."""
    return value == REDACTED or any(r.match(value) for r in _SURROGATE_RES)


def luhn(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _plausible_phone(match: str) -> bool:
    digits = [c for c in match if c.isdigit()]
    return 10 <= len(digits) <= 15 and not luhn(match)


@dataclass(frozen=True)
class Detector:
    """One value shape: how to find it, what it is, and what to do with it."""

    name: str
    kind: str
    action: str
    shape: str
    pattern: re.Pattern[str]
    valid: Callable[[str], bool] | None = None

    def findall(self, text: str) -> list[str]:
        out = []
        for match in self.pattern.findall(text):
            hit = match if isinstance(match, str) else match[0]
            if self.valid is None or self.valid(hit):
                out.append(hit)
        return out


# Order matters: a card number also matches the loose phone pattern, so cards
# and keys are detected first and the phone detector rejects Luhn-valid runs.
DETECTORS: tuple[Detector, ...] = (
    Detector("api_key", SECRET, DROP, STRING, _STRIPE_KEY_RE),
    Detector("bearer_token", SECRET, DROP, STRING, _BEARER_RE),
    Detector("email", PII, SURROGATE, EMAIL, _EMAIL_RE),
    Detector("card_number", PII, SURROGATE, CARD, _CARD_RE, luhn),
    Detector("ssn", PII, SURROGATE, SSN, _SSN_RE),
    Detector("account_id", IDENTITY, SURROGATE, ACCOUNT, _ACCOUNT_RE),
    Detector("ip_address", PII, SURROGATE, IP, _IP_RE),
    Detector("phone", PII, SURROGATE, PHONE, _PHONE_RE, _plausible_phone),
)


def infer_shape(value: str) -> str:
    for detector in DETECTORS:
        if detector.pattern.fullmatch(value) and (
            detector.valid is None or detector.valid(value)
        ):
            return detector.shape
    return STRING
