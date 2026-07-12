# Paymos Python SDK

Official Python 3.10+ client for the Paymos Merchant API. It includes HMAC request
signing, invoices, withdrawals, balances, bounded cursor iterators, structured
errors, safe retries, and raw-body webhook verification.

```bash
pip install paymos-sdk
```

```python
import os

from paymos import Paymos

paymos = Paymos(
    api_key=os.environ["PAYMOS_API_KEY"],
    api_secret=os.environ["PAYMOS_API_SECRET"],
)
invoice = paymos.invoices.create(
    project_id="prj_...", amount="10.00", currency="USD",
    external_order_id="order_123",
)
```

Use decimal strings for money. `list()` returns one cursor page; `iterate()`
follows cursors lazily and stops after 100 pages by default.

```python
for invoice in paymos.invoices.iterate(status=["paid", "paid_over"], max_pages=10):
    print(invoice["invoice_id"])
```

API failures raise typed subclasses of `ApiError` and preserve the HTTP status,
problem details, field, error code, headers, and `Retry-After` value.

Verify webhooks against the exact raw request body before parsing it:

```python
from paymos import WebhookVerifier

event = WebhookVerifier(os.environ["PAYMOS_WEBHOOK_SECRET"]).construct_event(
    request.headers["X-Webhook-Signature"], request.get_data()
)
```

Never use the API secret in browser or mobile code. Full documentation:
https://paymos.io/docs/server-sdks
