Records: 41
Versions: 2022-11-15 (41)
Statuses: 200: 37, 400: 3, 404: 1

| Method | Endpoint | Calls | Statuses |
|--------|----------|-------|----------|
| POST | `/v1/accounts` | 2 | 200×2 |
| GET | `/v1/accounts/{id}` | 1 | 200×1 |
| GET | `/v1/charges` | 2 | 200×2 |
| POST | `/v1/checkout/sessions` | 2 | 200×1, 400×1 |
| GET | `/v1/checkout/sessions/{id}` | 1 | 200×1 |
| POST | `/v1/coupons` | 1 | 200×1 |
| GET | `/v1/customers` | 3 | 200×2, 400×1 |
| POST | `/v1/customers` | 3 | 200×3 |
| GET | `/v1/customers/{id}` | 1 | 404×1 |
| POST | `/v1/customers/{id}` | 1 | 200×1 |
| POST | `/v1/invoiceitems` | 1 | 200×1 |
| GET | `/v1/invoices` | 1 | 200×1 |
| POST | `/v1/invoices` | 1 | 200×1 |
| GET | `/v1/invoices/upcoming` | 2 | 200×2 |
| GET | `/v1/invoices/{id}` | 1 | 200×1 |
| POST | `/v1/invoices/{id}/finalize` | 1 | 200×1 |
| POST | `/v1/invoices/{id}/pay` | 1 | 200×1 |
| POST | `/v1/payment_intents` | 3 | 200×2, 400×1 |
| GET | `/v1/payment_intents/{id}` | 1 | 200×1 |
| POST | `/v1/payment_intents/{id}/capture` | 1 | 200×1 |
| POST | `/v1/payment_intents/{id}/confirm` | 1 | 200×1 |
| POST | `/v1/payment_methods` | 2 | 200×2 |
| POST | `/v1/payment_methods/{id}/attach` | 2 | 200×2 |
| POST | `/v1/prices` | 1 | 200×1 |
| POST | `/v1/products` | 1 | 200×1 |
| GET | `/v1/refunds` | 1 | 200×1 |
| POST | `/v1/refunds` | 1 | 200×1 |
| POST | `/v1/subscriptions` | 1 | 200×1 |
| DELETE | `/v1/subscriptions/{id}` | 1 | 200×1 |

| Workflow | Calls | 2xx/3xx | 4xx/5xx |
|----------|-------|---------|---------|
| checkout_card_payment | 8 | 8 | 0 |
| checkout_session_no_cost | 3 | 2 | 1 |
| connected_account_onboarding | 3 | 3 | 0 |
| invoice_out_of_band_payment | 6 | 6 | 0 |
| pagination_and_errors | 6 | 3 | 3 |
| partial_capture_reconcile | 4 | 4 | 0 |
| subscription_billing | 11 | 11 | 0 |

Ground-truth breaks exercised: 7 of 8
- M1: checkout_card_payment
- M2: checkout_card_payment
- M3: partial_capture_reconcile
- M4: subscription_billing
- M6: checkout_session_no_cost
- M7: connected_account_onboarding
- M8: invoice_out_of_band_payment
