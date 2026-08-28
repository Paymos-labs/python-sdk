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
PaymentChannelStatus: TypeAlias = Literal["active", "blocked", "provisioning"]
PaymentChannelNetworkStatus: TypeAlias = Literal["provisioning", "active"]
PaymentChannelDepositStatus: TypeAlias = Literal["confirming", "reorged", "confirmed"]
# ORDERING: `confirming` and `reorged` are ADVISORY and may arrive out of order — a
# `confirming` can land after the `confirmed` for the same deposit, and a `reorged` can be
# superseded by a later `confirmed`. Credit a merchant only on `payment_channel.deposit.confirmed`
# with `is_final` true, and never let an advisory event regress a deposit already known to be
# confirmed. Crediting on `confirming` releases goods against money a reorg can still take back.
PaymentChannelDepositEventType: TypeAlias = Literal[
    "payment_channel.deposit.confirming",
    "payment_channel.deposit.reorged",
    "payment_channel.deposit.confirmed",
]
# The three stages the sandbox can drive a simulated deposit to. Omitting it means "confirmed".
SimulateDepositStage: TypeAlias = Literal["confirming", "reorged", "confirmed"]


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


class PaymentChannelTokenRequired(TypedDict):
    symbol: str


class PaymentChannelToken(PaymentChannelTokenRequired, total=False):
    # Absent = the rail cannot quote a minimum right now. It NEVER means "no minimum".
    minimum_deposit: str


class PaymentChannelNetworkRequired(TypedDict):
    # Rail code, e.g. "TRC20" — not a chain nickname.
    network: str
    status: PaymentChannelNetworkStatus
    tokens: list[PaymentChannelToken]


class PaymentChannelNetwork(PaymentChannelNetworkRequired, total=False):
    # Absent until this rail provisions; never changes once present.
    address: str


class PaymentChannel(TypedDict):
    id: str
    project_id: str
    external_id: str
    status: PaymentChannelStatus
    is_accepting_payments: bool
    is_fully_provisioned: bool
    is_test: bool
    applied_fee_percent: float
    customer_fee_percent: int
    networks: list[PaymentChannelNetwork]
    created_at: int
    updated_at: int


class PaymentChannelPage(TypedDict):
    items: list[PaymentChannel]
    # Null on the LAST page — the ordinary keyset convention invoices and withdrawals share.
    next_cursor: str | None


class PaymentChannelDepositRequired(TypedDict):
    id: str
    payment_channel_id: str
    project_id: str
    payment_channel_external_id: str
    status: PaymentChannelDepositStatus
    is_final: bool
    is_test: bool
    currency: str
    network: str
    chain_id: int
    gross: str
    fee: str
    net: str
    applied_fee_percent: float
    customer_fee_percent: int
    tx_hash: str
    transfer_id: str
    destination_address: str
    block_height: int
    created_at: int
    updated_at: int


class PaymentChannelDeposit(PaymentChannelDepositRequired, total=False):
    """The full payment-channel deposit wire shape.

    Also the exact `data` payload of every `PaymentChannelDepositEventType` webhook, so a
    handler decodes one with ``cast(PaymentChannelDeposit, event["data"])`` after
    `WebhookVerifier.construct_event`. See `PaymentChannelDepositEventType` for the
    delivery-ordering rule.
    """

    contract_address: str
    source_address: str
    first_included_block_timestamp: int
    explorer_url: str
    confirmed_at: int


class PaymentChannelDepositFeedBlockage(TypedDict):
    """The one feed position that could not be rendered, and why.

    Without it a stuck feed is byte-identical to a quiet day, and a merchant cannot tell
    "no new payments" from "I am not seeing my money". Surface it; never drop it.
    """

    deposit_id: str
    # booked_auth_missing, inconsistent, deposit_missing, channel_missing,
    # transfer_missing or not_confirmed.
    reason: str


class PaymentChannelDepositFeedPageRequired(TypedDict):
    items: list[PaymentChannelDeposit]
    # NOT optional. The feed never ends, and an empty page still advances past the global
    # positions this merchant's filter skipped. Store it and resume; never break on it.
    next_cursor: str


class PaymentChannelDepositFeedPage(PaymentChannelDepositFeedPageRequired, total=False):
    blocked: PaymentChannelDepositFeedBlockage


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
