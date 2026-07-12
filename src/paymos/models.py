from __future__ import annotations

from typing import Literal, TypeAlias, TypedDict

InvoiceStatus: TypeAlias = Literal[
    "awaiting_client",
    "awaiting_payment",
    "confirming",
    "underpaid_waiting",
    "paid",
    "paid_over",
    "underpaid",
    "expired",
    "cancelled",
]
WithdrawalStatus: TypeAlias = Literal[
    "created",
    "pending_review",
    "signed",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
]


class OrderRequired(TypedDict):
    external_id: str
    amount: str
    currency: str


class Order(OrderRequired, total=False):
    client_id: str
    network: str


class TransferRequired(TypedDict):
    tx_hash: str
    amount: str
    status: Literal["confirming", "confirmed"]
    created_at: int


class Transfer(TransferRequired, total=False):
    confirmed_at: int
    required_confirmations: int
    estimated_confirmation_at: int
    explorer_url: str


class PaymentRequired(TypedDict):
    currency: str
    network: str
    chain_id: int
    expected: str


class Payment(PaymentRequired, total=False):
    contract_address: str
    address: str
    exchange_rate: str
    paid: str
    remaining: str
    fee: str
    net: str
    transfers: list[Transfer]


class InvoiceRequired(TypedDict):
    invoice_id: str
    project_id: str
    status: InvoiceStatus
    is_final: bool
    is_test: bool
    payment_url: str
    order: Order
    created_at: int
    updated_at: int


class Invoice(InvoiceRequired, total=False):
    payment: Payment
    expires_at: int
    completed_at: int


class InvoiceListItemRequired(TypedDict):
    invoice_id: str
    project_id: str
    external_order_id: str
    status: InvoiceStatus
    is_final: bool
    is_test: bool
    amount: str
    currency: str
    created_at: int


class InvoiceListItem(InvoiceListItemRequired, total=False):
    client_id: str
    network: str
    expires_at: int
    completed_at: int


class InvoicePage(TypedDict):
    items: list[InvoiceListItem]
    next_cursor: str | None


class WithdrawalRequired(TypedDict):
    withdrawal_id: str
    external_order_id: str
    status: WithdrawalStatus
    is_final: bool
    is_test: bool
    amount: str
    currency: str
    network: str
    destination_address: str
    created_at: int


class Withdrawal(WithdrawalRequired, total=False):
    fee: str
    tx_hash: str
    explorer_url: str
    completed_at: int
    failed_at: int
    cancelled_at: int


class WithdrawalPage(TypedDict):
    items: list[Withdrawal]
    next_cursor: str | None


class Balance(TypedDict):
    currency: str
    available: str


class ServerTime(TypedDict):
    server_time: int


class WebhookEventRequired(TypedDict):
    event_id: str
    event_type: str
    version: int
    occurred_at: int
    data: dict[str, object]


class WebhookEvent(WebhookEventRequired, total=False):
    pass
