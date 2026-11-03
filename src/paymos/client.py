from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .errors import ConfigurationError, PaymosError, api_error
from .models import (
    Balance,
    Invoice,
    InvoiceListItem,
    InvoicePage,
    InvoiceStatus,
    PaymentChannel,
    PaymentChannelDeposit,
    PaymentChannelDepositFeedPage,
    PaymentChannelPage,
    PaymentChannelStatus,
    Refund,
    RefundMode,
    RefundPage,
    ServerTime,
    SimulateDepositStage,
    Withdrawal,
    WithdrawalPage,
    WithdrawalStatus,
)
from .signing import authorization_header, build_query, encode_path_segment
from .version import VERSION


@dataclass(frozen=True)
class Response:
    status: int
    body: str
    headers: Mapping[str, str]


class Transport(Protocol):
    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> Response: ...


def _default_transport(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
) -> Response:
    request = Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return Response(response.status, response.read().decode("utf-8"), dict(response.headers.items()))
    except HTTPError as error:
        return Response(error.code, error.read().decode("utf-8"), dict(error.headers.items()))


def _validate_base_url(value: str) -> str:
    """Reject a base URL that would put the API secret on the wire in the clear.

    The secret signs every request, so the scheme of the base URL decides whether that
    credential is readable in transit. HTTPS is the only acceptable answer in production;
    plain HTTP is allowed solely against a loopback host, which is what a local integration
    test points at. Mirrors the Rust SDK's validate_base_url — same rule, same wording, in
    every language.
    """
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ConfigurationError("base_url must use HTTPS (HTTP is allowed only for loopback tests).")
    return value.rstrip("/")


class Paymos:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = "https://api.paymos.io",
        timeout: float = 30,
        max_retries: int = 2,
        base_delay: float = 0.150,
        transport: Transport = _default_transport,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_key or not api_secret:
            raise ConfigurationError("api_key and api_secret are required.")
        if timeout <= 0 or max_retries < 0 or base_delay < 0:
            raise ConfigurationError("timeout, max_retries, and base_delay are invalid.")
        self.api_key, self.api_secret = api_key, api_secret
        self.base_url, self.timeout = _validate_base_url(base_url), timeout
        self.max_retries, self.base_delay = max_retries, base_delay
        self.transport, self.clock, self.sleep = transport, clock, sleep
        self.invoices = Invoices(self)
        self.withdrawals = Withdrawals(self)
        self.refunds = Refunds(self)
        self.payment_channels = PaymentChannels(self)
        self.payment_channel_deposits = PaymentChannelDeposits(self)
        self.balances = Balances(self)
        self.system = System(self)

    def request(self, method: str, path: str, payload: Mapping[str, Any] | None = None, query: str = "") -> Any:
        body_text = "" if payload is None else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        body = body_text.encode("utf-8") if body_text else None
        url = self.base_url + path + query
        for attempt in range(self.max_retries + 1):
            timestamp = str(int(self.clock()))
            headers = {
                "Authorization": authorization_header(
                    self.api_key, self.api_secret, timestamp, method, path, query, body_text
                ),
                "X-Request-Timestamp": timestamp,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"paymos-python/{VERSION}",
            }
            try:
                response = self.transport(method, url, headers, body, self.timeout)
            except (OSError, URLError) as error:
                if attempt >= self.max_retries or method.upper() not in {"GET", "HEAD", "OPTIONS"}:
                    raise PaymosError(f"Paymos request failed: {error}") from error
                self._wait(attempt, None)
                continue
            if attempt < self.max_retries and (
                response.status == 429 or (response.status >= 500 and method.upper() in {"GET", "HEAD", "OPTIONS"})
            ):
                self._wait(attempt, response.headers.get("Retry-After") or response.headers.get("retry-after"))
                continue
            if not 200 <= response.status < 300:
                raise api_error(response.status, response.body, response.headers)
            if not response.body:
                return {}
            try:
                return json.loads(response.body)
            except json.JSONDecodeError as error:
                raise PaymosError("Paymos API returned invalid JSON.") from error
        raise AssertionError("unreachable")

    def _wait(self, attempt: int, retry_after: str | None) -> None:
        delay = self.base_delay * (2**attempt) + random.uniform(0, self.base_delay)
        if retry_after and retry_after.isdigit():
            delay = max(delay, float(retry_after))
        self.sleep(delay)


class Invoices:
    def __init__(self, client: Paymos):
        self.client = client

    def create(
        self,
        *,
        project_id: str,
        amount: str,
        currency: str,
        external_order_id: str,
        network: str | None = None,
        customer_fee_percent: int | None = None,
        client_id: str | None = None,
    ) -> Invoice:
        payload: dict[str, object] = {
            "project_id": project_id,
            "amount": amount,
            "currency": currency,
            "external_order_id": external_order_id,
        }
        _optional(payload, "network", network)
        _optional(payload, "customer_fee_percent", customer_fee_percent)
        _optional(payload, "client_id", client_id)
        return cast(Invoice, self.client.request("POST", "/v1/invoices", payload))

    def get(self, invoice_id: str) -> Invoice:
        return cast(Invoice, self.client.request("GET", f"/v1/invoices/{encode_path_segment(invoice_id)}"))

    def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        status: Sequence[InvoiceStatus] | None = None,
        external_order_id: str | None = None,
        project_id: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
    ) -> InvoicePage:
        filters = _filters(
            limit=limit,
            cursor=cursor,
            status=status,
            external_order_id=external_order_id,
            project_id=project_id,
            created_from=created_from,
            created_to=created_to,
        )
        return cast(InvoicePage, self.client.request("GET", "/v1/invoices", query=build_query(filters)))

    def iterate(
        self,
        max_pages: int = 100,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        status: Sequence[InvoiceStatus] | None = None,
        external_order_id: str | None = None,
        project_id: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
    ) -> Iterator[InvoiceListItem]:
        filters = _filters(
            limit=limit,
            cursor=cursor,
            status=status,
            external_order_id=external_order_id,
            project_id=project_id,
            created_from=created_from,
            created_to=created_to,
        )
        yield from _iterate(self.list, max_pages, filters)

    def cancel(self, invoice_id: str, reason: str) -> Invoice:
        _reason(reason)
        return cast(
            Invoice,
            self.client.request("POST", f"/v1/invoices/{encode_path_segment(invoice_id)}/cancel", {"reason": reason}),
        )

    def confirm_payment(self, invoice_id: str, currency: str, network: str) -> Invoice:
        return cast(
            Invoice,
            self.client.request(
                "POST",
                f"/v1/invoices/{encode_path_segment(invoice_id)}/confirm-payment",
                {"currency": currency, "network": network},
            ),
        )

    def simulate_payment(self, invoice_id: str, stage: str) -> Invoice:
        if stage not in {"paid", "overpaid", "underpay", "cancel", "paid_late"}:
            raise ValueError("Invalid simulation stage.")
        return cast(
            Invoice,
            self.client.request(
                "POST", f"/v1/sandbox/invoices/{encode_path_segment(invoice_id)}/simulate-payment", {"stage": stage}
            ),
        )


class Withdrawals:
    def __init__(self, client: Paymos):
        self.client = client

    def create(
        self,
        *,
        destination_address: str,
        network: str,
        currency: str,
        amount: str,
        external_order_id: str,
    ) -> Withdrawal:
        return cast(
            Withdrawal,
            self.client.request(
                "POST",
                "/v1/withdrawals",
                {
                    "destination_address": destination_address,
                    "network": network,
                    "currency": currency,
                    "amount": amount,
                    "external_order_id": external_order_id,
                },
            ),
        )

    def get(self, withdrawal_id: str) -> Withdrawal:
        return cast(Withdrawal, self.client.request("GET", f"/v1/withdrawals/{encode_path_segment(withdrawal_id)}"))

    def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        status: Sequence[WithdrawalStatus] | None = None,
        external_order_id: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
    ) -> WithdrawalPage:
        filters = _filters(
            limit=limit,
            cursor=cursor,
            status=status,
            external_order_id=external_order_id,
            created_from=created_from,
            created_to=created_to,
        )
        return cast(WithdrawalPage, self.client.request("GET", "/v1/withdrawals", query=build_query(filters)))

    def iterate(
        self,
        max_pages: int = 100,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        status: Sequence[WithdrawalStatus] | None = None,
        external_order_id: str | None = None,
        created_from: int | None = None,
        created_to: int | None = None,
    ) -> Iterator[Withdrawal]:
        filters = _filters(
            limit=limit,
            cursor=cursor,
            status=status,
            external_order_id=external_order_id,
            created_from=created_from,
            created_to=created_to,
        )
        yield from _iterate(self.list, max_pages, filters)

    def cancel(self, withdrawal_id: str, reason: str) -> Withdrawal:
        _reason(reason)
        return cast(
            Withdrawal,
            self.client.request(
                "POST", f"/v1/withdrawals/{encode_path_segment(withdrawal_id)}/cancel", {"reason": reason}
            ),
        )

    def simulate_completion(self, withdrawal_id: str) -> Withdrawal:
        return cast(
            Withdrawal,
            self.client.request(
                "POST", f"/v1/sandbox/withdrawals/{encode_path_segment(withdrawal_id)}/simulate-completion"
            ),
        )


class Refunds:
    def __init__(self, client: Paymos):
        self.client = client

    def create(self, *, invoice_id: str, mode: RefundMode, external_order_id: str) -> Refund:
        return cast(
            Refund,
            self.client.request(
                "POST",
                "/v1/refunds",
                {"invoice_id": invoice_id, "mode": mode, "external_order_id": external_order_id},
            ),
        )

    def get(self, refund_id: str) -> Refund:
        return cast(Refund, self.client.request("GET", f"/v1/refunds/{encode_path_segment(refund_id)}"))

    def simulate(self, refund_id: str, status: str) -> Refund:
        if not refund_id.strip() or status not in {"completed", "failed", "cancelled"}:
            raise ValueError("A refund ID and terminal simulation status are required.")
        return cast(
            Refund,
            self.client.request(
                "POST", f"/v1/sandbox/refunds/{encode_path_segment(refund_id)}/simulate", {"status": status}
            ),
        )

    def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        invoice_id: str | None = None,
        status: Sequence[WithdrawalStatus] | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> RefundPage:
        filters = _filters(
            limit=limit,
            cursor=cursor,
            invoice_id=invoice_id,
            status=status,
            created_from=created_from,
            created_to=created_to,
        )
        return cast(RefundPage, self.client.request("GET", "/v1/refunds", query=build_query(filters)))

    def iterate(
        self,
        max_pages: int = 100,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        invoice_id: str | None = None,
        status: Sequence[WithdrawalStatus] | None = None,
        created_from: str | None = None,
        created_to: str | None = None,
    ) -> Iterator[Refund]:
        filters = _filters(
            limit=limit,
            cursor=cursor,
            invoice_id=invoice_id,
            status=status,
            created_from=created_from,
            created_to=created_to,
        )
        yield from _iterate(self.list, max_pages, filters)


class PaymentChannels:
    def __init__(self, client: Paymos):
        self.client = client

    def create(self, *, project_id: str, external_id: str) -> PaymentChannel:
        """Create — or fetch.

        The same project plus external id answers 200 with the channel that already exists
        instead of 201 with a duplicate. Both bodies are a channel, so a caller never inspects
        the status: calling this on every checkout is safe.
        """
        return cast(
            PaymentChannel,
            self.client.request(
                "POST",
                "/v1/payment-channels",
                {"project_id": project_id, "external_id": external_id},
            ),
        )

    def get(self, payment_channel_id: str) -> PaymentChannel:
        return cast(
            PaymentChannel,
            self.client.request("GET", f"/v1/payment-channels/{encode_path_segment(payment_channel_id)}"),
        )

    def list(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        status: Sequence[PaymentChannelStatus] | None = None,
        external_id: str | None = None,
        project_id: str | None = None,
    ) -> PaymentChannelPage:
        filters = _filters(
            limit=limit,
            cursor=cursor,
            status=status,
            external_id=external_id,
            project_id=project_id,
        )
        return cast(PaymentChannelPage, self.client.request("GET", "/v1/payment-channels", query=build_query(filters)))

    def iterate(
        self,
        max_pages: int = 100,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        status: Sequence[PaymentChannelStatus] | None = None,
        external_id: str | None = None,
        project_id: str | None = None,
    ) -> Iterator[PaymentChannel]:
        filters = _filters(
            limit=limit,
            cursor=cursor,
            status=status,
            external_id=external_id,
            project_id=project_id,
        )
        yield from _iterate(self.list, max_pages, filters)

    def block(self, payment_channel_id: str) -> PaymentChannel:
        return cast(
            PaymentChannel,
            self.client.request("POST", f"/v1/payment-channels/{encode_path_segment(payment_channel_id)}/block"),
        )

    def unblock(self, payment_channel_id: str) -> PaymentChannel:
        return cast(
            PaymentChannel,
            self.client.request("POST", f"/v1/payment-channels/{encode_path_segment(payment_channel_id)}/unblock"),
        )

    def simulate_deposit(
        self,
        payment_channel_id: str,
        *,
        amount: str,
        currency: str,
        network: str,
        stage: SimulateDepositStage | None = None,
    ) -> PaymentChannelDeposit:
        """Sandbox only — a production credential gets an error, not a deposit.

        ``network`` is required. ``stage`` is omitted from the body entirely when unset, which
        the API reads as ``confirmed``; sending it empty or null is an unknown value.
        """
        if stage is not None and stage not in {"confirming", "reorged", "confirmed"}:
            raise ValueError("Invalid simulation stage.")
        payload: dict[str, object] = {"amount": amount, "currency": currency, "network": network}
        _optional(payload, "stage", stage)
        return cast(
            PaymentChannelDeposit,
            self.client.request(
                "POST",
                f"/v1/sandbox/payment-channels/{encode_path_segment(payment_channel_id)}/simulate-deposit",
                payload,
            ),
        )


class PaymentChannelDeposits:
    def __init__(self, client: Paymos):
        self.client = client

    def get(self, deposit_id: str) -> PaymentChannelDeposit:
        return cast(
            PaymentChannelDeposit,
            self.client.request("GET", f"/v1/payment-channel-deposits/{encode_path_segment(deposit_id)}"),
        )

    def read(
        self,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        project_id: str | None = None,
        payment_channel_id: str | None = None,
        confirmed_from: int | None = None,
    ) -> PaymentChannelDepositFeedPage:
        """Read ONE page of the confirmed-deposit feed.

        Deliberately not called ``list`` and deliberately without an ``iterate`` companion: the
        feed has no last page, and a helper that loops until the cursor is empty would either
        spin forever or stop on the first quiet page and leave a merchant's reconciliation
        silently behind. Store ``next_cursor`` — it is always present, even on an empty page —
        and pass it back on the next poll. ``confirmed_from`` is the initial-sync lower bound
        for the very first call only; it is not how you resume.
        """
        filters = _filters(
            limit=limit,
            cursor=cursor,
            project_id=project_id,
            payment_channel_id=payment_channel_id,
            confirmed_from=confirmed_from,
        )
        return cast(
            PaymentChannelDepositFeedPage,
            self.client.request("GET", "/v1/payment-channel-deposits", query=build_query(filters)),
        )


class Balances:
    def __init__(self, client: Paymos):
        self.client = client

    def get(self) -> list[Balance]:
        return cast(list[Balance], self.client.request("GET", "/v1/balances"))


class System:
    def __init__(self, client: Paymos):
        self.client = client

    def time(self) -> ServerTime:
        return cast(ServerTime, self.client.request("GET", "/v1/time"))


def _optional(target: dict[str, object], key: str, value: object | None) -> None:
    if value is not None:
        target[key] = value


def _filters(**values: object | None) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}


def _reason(reason: str) -> None:
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValueError("Cancellation reason must contain 1 to 500 characters.")


def _iterate(fetch: Callable[..., Any], max_pages: int, filters: dict[str, object]) -> Iterator[Any]:
    if not isinstance(max_pages, int) or max_pages < 1:
        raise ValueError("max_pages must be a positive integer.")
    cursor = filters.get("cursor")
    for _ in range(max_pages):
        page = fetch(**filters)
        yield from page.get("items", [])
        next_cursor = page.get("next_cursor")
        if not next_cursor:
            return
        if next_cursor == cursor:
            raise PaymosError("Paymos API returned the same pagination cursor twice.")
        cursor = next_cursor
        filters["cursor"] = cursor
