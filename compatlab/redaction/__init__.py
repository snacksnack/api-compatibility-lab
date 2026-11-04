"""Deterministic redaction and independent auditing of captured payloads.

Standalone and reusable on purpose: RC1-603 Phase 1 needs it for the traffic
corpus and RC1-594 needs the same component for its diagnostic bundle, which
is why this epic was sequenced first. Depends on nothing but the standard
library — no HTTP, no Stripe, no corpus format.

    from compatlab.redaction import STRIPE_POLICY

    clean = STRIPE_POLICY.redact(payload)      # before storing
    findings = STRIPE_POLICY.scan(stored)      # after storing, independently
"""

from compatlab.redaction.core import (
    DROP,
    PUBLIC_DEMO_SALT,
    REDACTED,
    SURROGATE,
    Finding,
    KeyRule,
    Policy,
    default_salt,
    leaf_key,
    mask,
)
from compatlab.redaction.detectors import (
    DETECTORS,
    IDENTITY,
    PII,
    SECRET,
    Detector,
    is_surrogate,
    luhn,
    surrogate,
)
from compatlab.redaction.policies import (
    BASE_POLICY,
    PUBLIC_TEST_VALUES,
    STRIPE_POLICY,
)

__all__ = [
    "BASE_POLICY",
    "DETECTORS",
    "DROP",
    "IDENTITY",
    "PII",
    "PUBLIC_DEMO_SALT",
    "PUBLIC_TEST_VALUES",
    "REDACTED",
    "SECRET",
    "STRIPE_POLICY",
    "SURROGATE",
    "Detector",
    "Finding",
    "KeyRule",
    "Policy",
    "default_salt",
    "is_surrogate",
    "leaf_key",
    "luhn",
    "mask",
    "surrogate",
]
