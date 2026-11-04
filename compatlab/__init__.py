"""API Compatibility Lab: find the behavioral breaks a schema diff misses."""

# The pinned version pair, per ADR 0001 D1. A predates 2023-08-16 so the span
# contains both PaymentIntent default changes; B is basil, the richest single
# release of behavioral breaks in the changelog.
VERSION_A = "2022-11-15"
VERSION_B = "2025-03-31.basil"

STRIPE_BASE_URL = "https://api.stripe.com"
