# Pinned-behavior regression tests

**19 of 19 pinned regression tests pass on 2022-11-15 and fail on 2025-03-31.basil.**

Phase 4 ended with 19 places where a difference between `2022-11-15` and `2025-03-31.basil` reaches a field a declared customer workflow actually reads. This phase compiles each one into a test that passes on the old version and fails on the new one, and then runs them both ways to show that it does.

A pinned test is not a test of the API. It is the sentence *this customer's integration depends on this behavior*, written so that a version bump has to argue with it. It goes in the customer's own CI, where it fails the day someone changes the version pin.

## What was pinned

| test | workflow(s) | consequence | live A / B | recorded A / B |
|---|---|---|---|---|
| `test_checkout_card_payment_create_payment_intent__automatic_payment_methods` | guest_checkout_capture | corrupts | holds / breaks | holds / breaks |
| `test_checkout_card_payment_create_payment_intent__capture_method` | guest_checkout_capture | corrupts | holds / breaks | holds / breaks |
| `test_checkout_card_payment_create_payment_intent__payment_method_types` | guest_checkout_capture | corrupts | holds / breaks | holds / breaks |
| `test_checkout_session_no_cost_create_paid_session__payment_method_collection` | free_sample_fulfillment | corrupts | holds / breaks | holds / breaks |
| `test_checkout_session_no_cost_create_zero_total_session__status` | free_sample_fulfillment | unblocks | holds / breaks | holds / breaks |
| `test_checkout_session_no_cost_retrieve_paid_session__payment_method_collection` | free_sample_fulfillment | corrupts | holds / breaks | holds / breaks |
| `test_invoice_out_of_band_payment_pay_invoice_out_of_band__amount_paid` | offline_invoice_settlement | corrupts | holds / breaks | holds / breaks |
| `test_invoice_out_of_band_payment_pay_invoice_out_of_band__paid_out_of_band` | offline_invoice_settlement | corrupts | holds / breaks | holds / breaks |
| `test_invoice_out_of_band_payment_retrieve_invoice_after_payment__amount_paid` | offline_invoice_settlement | corrupts | holds / breaks | holds / breaks |
| `test_invoice_out_of_band_payment_retrieve_invoice_after_payment__amount_remaining` | offline_invoice_settlement | corrupts | holds / breaks | holds / breaks |
| `test_invoice_out_of_band_payment_retrieve_invoice_after_payment__paid` | offline_invoice_settlement | corrupts | holds / breaks | holds / breaks |
| `test_partial_capture_reconcile_list_refunds_for_intent__count` | nightly_refund_reconciliation | corrupts | holds / breaks | holds / breaks |
| `test_partial_capture_reconcile_list_refunds_for_intent__data` | nightly_refund_reconciliation | corrupts | holds / breaks | holds / breaks |
| `test_partial_capture_reconcile_retrieve_charge_after_partial__data_0_amount_refunded` | nightly_refund_reconciliation | corrupts | holds / breaks | holds / breaks |
| `test_subscription_billing_cancel_subscription__current_period_end` | subscription_renewal_billing | corrupts | holds / breaks | holds / breaks |
| `test_subscription_billing_create_subscription__current_period_end` | subscription_renewal_billing | corrupts | holds / breaks | holds / breaks |
| `test_subscription_billing_list_subscription_invoices__data_0_paid` | subscription_renewal_billing | corrupts | holds / breaks | holds / breaks |
| `test_subscription_billing_list_subscription_invoices__data_0_payment_intent` | subscription_renewal_billing | corrupts | holds / breaks | holds / breaks |
| `test_subscription_billing_preview_upcoming_by_subscription__status` | subscription_renewal_billing | blocks | holds / breaks | holds / breaks |

## What each test asserts, and how the new version fails it

The right-hand column is the assertion message from the live run on `2025-03-31.basil`, quoted out of the certification record. It is the clearest short statement of the break there is: a refund count that went to zero, a billing period that stopped being returned, a preview endpoint that answers 404.

| test | pins | fails on the new version with |
|---|---|---|
| `checkout_card_payment_create_payment_intent__automatic_payment_methods` | `$.body.automatic_payment_methods` equals null | `AssertionError: assert {'allow_redirects': 'always', 'enabled': True} is None` |
| `checkout_card_payment_create_payment_intent__capture_method` | `$.body.capture_method` equals "automatic" | `AssertionError: assert 'automatic_async' == 'automatic' - automatic + automatic_async ? ++++++` |
| `checkout_card_payment_create_payment_intent__payment_method_types` | `$.body.payment_method_types` equals ["card"] | `AssertionError: assert ['card', 'kla... 'amazon_pay'] == ['card'] Left contains 4 more items, first extra item: 'klarna' Use -v to get more diff` |
| `checkout_session_no_cost_create_paid_session__payment_method_collection` | `$.body.payment_method_collection` equals "always" | `AssertionError: assert 'if_required' == 'always' - always + if_required` |
| `checkout_session_no_cost_create_zero_total_session__status` | `checkout_session_no_cost.create_zero_total_session` returns status 400 and not 200 | `assert 200 == 400` |
| `checkout_session_no_cost_retrieve_paid_session__payment_method_collection` | `$.body.payment_method_collection` equals "always" | `AssertionError: assert 'if_required' == 'always' - always + if_required` |
| `invoice_out_of_band_payment_pay_invoice_out_of_band__amount_paid` | `$.body.amount_paid` equals 0 | `AssertionError: assert 2000 == 0` |
| `invoice_out_of_band_payment_pay_invoice_out_of_band__paid_out_of_band` | `$.body.paid_out_of_band` is present and equals true | `AssertionError: assert <missing> is True` |
| `invoice_out_of_band_payment_retrieve_invoice_after_payment__amount_paid` | `$.body.amount_paid` equals 0 | `AssertionError: assert 2000 == 0` |
| `invoice_out_of_band_payment_retrieve_invoice_after_payment__amount_remaining` | `$.body.amount_remaining` equals 2000 | `AssertionError: assert 0 == 2000` |
| `invoice_out_of_band_payment_retrieve_invoice_after_payment__paid` | `$.body.paid` is present and equals true | `AssertionError: assert <missing> is True` |
| `partial_capture_reconcile_list_refunds_for_intent__count` | `$.body.count` equals 1 | `AssertionError: assert 0 == 1` |
| `partial_capture_reconcile_list_refunds_for_intent__data` | `$.body.data` comes back as a non-empty collection | `AssertionError: assert 0 > 0` |
| `partial_capture_reconcile_retrieve_charge_after_partial__data_0_amount_refunded` | `$.body.data[0].amount_refunded` equals 3000 | `AssertionError: assert 0 == 3000` |
| `subscription_billing_cancel_subscription__current_period_end` | `$.body.current_period_end` is present and equals "<ts+30d>" | `AssertionError: assert <missing> == '<ts+30d>'` |
| `subscription_billing_create_subscription__current_period_end` | `$.body.current_period_end` is present and equals "<ts+30d>" | `AssertionError: assert <missing> == '<ts+30d>'` |
| `subscription_billing_list_subscription_invoices__data_0_paid` | `$.body.data[0].paid` is present and equals true | `AssertionError: assert <missing> is True` |
| `subscription_billing_list_subscription_invoices__data_0_payment_intent` | `$.body.data[0].payment_intent` is present and equals "<id:pi>" | `AssertionError: assert <missing> == '<id:pi>'` |
| `subscription_billing_preview_upcoming_by_subscription__status` | `subscription_billing.preview_upcoming_by_subscription` returns status 200 and not 404 | `assert 404 == 200` |

Certified live on 2026-11-05T19:01:13+00:00 against `2022-11-15` and `2025-03-31.basil`; the record is [`pins/certification.json`](../pins/certification.json), and the suite is [`pinned/test_pinned_behavior.py`](../pinned/test_pinned_behavior.py), generated from the pins.

## The expected values are canonical, not literal

The suite asserts over the same canonicalized responses the differ compares, so the tokens come with it: `<ts+30d>` is a timestamp in the 30-day bucket from the start of the run, and `<id:pi>` is *some* payment-intent id rather than one particular one. That is what makes a pinned timestamp a relative assertion: `current_period_end` is pinned as about thirty days out, which is the behavior, rather than as a date that would be wrong tomorrow. Ids are pinned by provenance for the same reason (ADR 0003).

## The two runs are not equally good evidence

The suite runs either against the live API or against a committed replay, with the same assertions. Only one of those is evidence.

The **live** run replays the corpus against each version now and asserts against what comes back. Version A's traffic is fetched after the pins were written, so a pin passing on `2022-11-15` is a statement about the API: 19 of 19 held there and broke on `2025-03-31.basil`.

The **recorded** run is a compilation check and is labelled one. The pins were derived from exactly those records, so a pin failing on the recorded B side is true by construction and says nothing about the API. What it does say is worth having in CI: that the generated code still compiles, still runs, and still evaluates the way the certification says it did, with no key and no network.

## Three outcomes, because two would be generous

A test can hold, it can break, or the replay can never have reached its step. Only the middle one is a pinned break. A workflow that falls over at call two turns every test behind it red, and counting those as *fails on the new version* would certify a suite that proves nothing — so an unreached step fails with `[unreached]` in the message, and the gate rejects a certification that rests on one.

## The gate

`compatlab pin check` runs offline in CI and fails when: the generated suite does not match what the pins compile to; any pin has no live certification; a certification was made against a different assertion than the one in the file now; a certified pin did not hold on the old version or did not break on the new one; or a certification entry refers to a pin that no longer exists. The last one matters as much as the rest: keeping a verdict while quietly losing the test it was about is the same dishonesty as never verifying.

A behavioral break the upstream later reverses is real and can be waived, with a reason, in the certification. A waived pin is named in the headline rather than dropped from the denominator.

## Running them

```
uv run pytest pinned/ --api-version 2022-11-15    # all pass
uv run pytest pinned/ --api-version 2025-03-31.basil  # all fail
uv run python -m compatlab pin check              # offline gate
```

Design decisions behind all of this: [`docs/adr/0006-regression-test-generation.md`](adr/0006-regression-test-generation.md).
