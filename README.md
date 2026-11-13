# Paymos Python SDK

Official Python 3.10+ client for the Paymos Merchant API. It includes HMAC request
signing, invoices, withdrawals, balances, static per-customer wallets and their
deposit feed,
bounded cursor iterators, structured errors, safe retries, and raw-body webhook
verification.

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

A payment channel is one payer's reusable set of deposit addresses. Create it,
read its rails, then poll the confirmed-deposit feed and persist the cursor:

```python
channel = paymos.payment_channels.create(project_id="prj_...", external_id="customer_42")
for rail in channel["networks"]:
    print(rail["network"], rail["status"], rail.get("address", "not provisioned yet"))

feed = paymos.payment_channel_deposits.read(cursor=saved_cursor, limit=100)
for deposit in feed["items"]:
    credit_deposit(deposit)  # one credit per deposit["id"], see below
save_cursor(feed["next_cursor"])
```

The feed and the deposit webhook report the same deposits, so both go through one
`credit_deposit` keyed by the deposit's own `id` (`pcd_...`). A sketch with a SQL store
(`credited_deposits.deposit_id` is the primary key; PostgreSQL syntax):

```python
def credit_deposit(deposit):
    if not deposit["is_final"] or deposit["project_id"] != MY_PROJECT_ID or deposit["is_test"] != MY_IS_TEST:
        return
    with db.transaction() as tx:
        # The insert and the balance update commit together or not at all. A second
        # delivery, a second endpoint's copy, or a re-read feed page inserts nothing.
        inserted = tx.execute(
            "INSERT INTO credited_deposits (deposit_id, payer, amount) VALUES (%s, %s, %s::numeric)"
            " ON CONFLICT (deposit_id) DO NOTHING",
            (deposit["id"], deposit["payment_channel_external_id"], deposit["net"]),
        )
        if inserted.rowcount == 1:
            tx.execute(
                "UPDATE balances SET amount = amount + %s::numeric WHERE payer = %s",
                (deposit["net"], deposit["payment_channel_external_id"]),
            )
```

Four things that bite a caller who guesses. Repeating the same `external_id`
returns the **same** channel — `200` instead of `201`, and both bodies are a
channel, so calling this on every checkout is safe: a repeat is not a duplicate
and not an error. A rail's `address` is absent until that rail finishes
provisioning and never changes once it appears, so absent means "not yet", not
"no address". An absent `minimum_deposit` means "we cannot quote a minimum right
now", never "there is no minimum" — reading it as zero is how a merchant accepts
a deposit that lands below the live minimum and is never credited. And
`next_cursor` is never empty, not even on a page with no items: store it and
resume from it, and never loop until it is falsy the way `iterate()` ends a
list, because that loop either spins forever or stops on the first quiet page
and leaves reconciliation silently behind. `confirmed_from` is the first poll's
lower bound only; afterwards the stored cursor is the resume mechanism.

API failures raise typed subclasses of `ApiError` and preserve the HTTP status,
problem details, field, error code, headers, and `Retry-After` value. The default
transport does not follow redirects: a signed request is sent only to `base_url`, and a
`3xx` answer raises `ApiError` with that status. `timeout` (seconds, default 30) bounds each
blocking socket operation — connecting and every read — not the whole request: a server that keeps
sending slowly can make one attempt last longer than `timeout`. Retries add their own attempts.

Verify webhooks against the exact raw request body before parsing it:

```python
from paymos import WebhookVerifier

event = WebhookVerifier(os.environ["PAYMOS_WEBHOOK_SECRET"]).construct_event(
    request.headers["X-Webhook-Signature"], request.get_data()
)
```

The three `payment_channel.deposit.*` events each carry a full payment-channel deposit as
their `data`. `construct_event` returns it untyped, so bind it to `PaymentChannelDeposit`
yourself:

```python
from typing import cast

from paymos import PaymentChannelDeposit

if event["event_type"] == "payment_channel.deposit.confirmed":
    deposit = cast(PaymentChannelDeposit, event["data"])
    if deposit["is_final"]:
        credit_deposit(deposit)  # once per deposit["id"], shared with the feed
```

`event["event_id"]` identifies one delivery, not one payment. Paymos creates a separate
event, with its own `event_id`, for every webhook endpoint subscribed to the event, and
every later event about the same invoice or deposit has its own `event_id` too. Store
`event_id` to skip a redelivered request, but key money and fulfilment on the business
identity: the invoice/order (`data["invoice_id"]`, `data["order"]["external_id"]`) for
invoice events, the deposit `id` for deposit events. Write that key in the same database
transaction as the order or balance change.

`confirming` and `reorged` are advisory and may arrive out of order — a `confirming` can
land after the `confirmed` for the same deposit, and a `reorged` can be superseded by a
later `confirmed`. Credit only on `payment_channel.deposit.confirmed` with `is_final` true,
and never let an advisory event regress a deposit already known to be confirmed: crediting
on `confirming` releases goods against money a reorg can still take back.

Never use the API secret in browser or mobile code. Full documentation:
https://paymos.io/docs/server-sdks

## 401 and 403 are different problems

A **401** means the credential is absent, malformed or unverifiable — fix the key or the signing
clock, and stop retrying.

A **403** means the credential was accepted and something else refused. It covers two very
different situations:

- **the key is wrong for this call** — `payout_key_required`, `payment_key_required`,
  `forbidden`;
- **the key is fine, the account or project state says no** — `whitelist_required`,
  `merchant_suspended`, `widget_inactive`, `terminal_not_enabled`, `not_sandbox`.

A customer entering a payout address that is not whitelisted yet is the second kind: nothing is
wrong with your credentials, and paging the on-call engineer about them is the wrong move. Always
switch on the error `code` before deciding what to do.

`PermissionError` subclasses `AuthenticationError`, so `except AuthenticationError` written
before this split keeps catching 403.
