import base64
import hashlib
import hmac
import json
import pathlib
import sys
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

from paymos import (
    ConflictError,
    NotFoundError,
    Paymos,
    PaymosError,
    PermissionError,
    Response,
    UnavailableError,
    ValidationError,
)

CONTRACT = json.loads((pathlib.Path(__file__).parents[1] / "conformance" / "contract.json").read_text())
REFUNDS = CONTRACT["vectors"]["refunds"]
SIGNING = CONTRACT["vectors"]["post_signing"]
CREATE = REFUNDS["create"]
OVERPAYMENT = REFUNDS["overpayment"]
INVOICE_ID = CREATE["body"]["invoice_id"]
REFUND_ID = "wdr_74BPZFhr9qy9Uz2fbRkdJX"
FULL_ID = "wdr_74BPZFhr9qy9Uz2fbRkdJY"
REFUND = {
    "withdrawal_id": REFUND_ID,
    "invoice_id": INVOICE_ID,
    "mode": "full",
    "external_order_id": CREATE["body"]["external_order_id"],
    "status": "created",
    "is_final": False,
    "is_test": True,
    "amount": "120",
    "fee": "0.25",
    "currency": "USDT",
    "network": "TRC20",
    "destination_address": "TFirstSender",
    "first_sender": "TFirstSender",
    "created_at": 1700000000,
}


def _problem(status, code, detail, **fields):
    return {
        "type": "about:blank",
        "title": "Request failed",
        "status": status,
        "detail": detail,
        "code": code,
        **fields,
    }


def _client(*responses, max_retries=0):
    queue = list(responses)
    calls = []

    def transport(method, url, headers, body, _timeout):
        calls.append((method, url.removeprefix("https://api.paymos.io"), headers, body))
        if not queue:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        response = queue.pop(0)
        if isinstance(response, Exception):
            raise response
        status, payload = response
        return Response(status, json.dumps(payload), {"Cache-Control": "private, no-store"})

    client = Paymos(
        SIGNING["api_key"],
        SIGNING["api_secret"],
        transport=transport,
        clock=lambda: int(SIGNING["timestamp"]),
        max_retries=max_retries,
        sleep=lambda _delay: None,
        base_delay=0,
    )
    return client, calls


class RefundTests(unittest.TestCase):
    def assert_signed(self, call, method, target, payload=None):
        actual_method, actual_target, headers, body = call
        self.assertEqual((method, target), (actual_method, actual_target))
        body_text = "" if payload is None else json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        self.assertEqual(body_text.encode() if payload is not None else None, body)
        path, separator, query = target.partition("?")
        body_hash = hashlib.sha256(body_text.encode()).hexdigest() if body_text else ""
        canonical = f"{SIGNING['timestamp']}\n{method}\n{path}\n{separator}{query}\n{body_hash}"
        digest = hmac.new(SIGNING["api_secret"].encode(), canonical.encode(), hashlib.sha256).digest()
        signature = base64.b64encode(digest).decode()
        self.assertEqual(f"HMAC-SHA256 {SIGNING['api_key']}:{signature}", headers["Authorization"])
        self.assertEqual(SIGNING["timestamp"], headers["X-Request-Timestamp"])
        self.assertNotIn("Idempotency-Key", headers)

    def test_simulate_signed_terminal_status_and_current_refund_shape(self):
        address = "UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA"
        for status in ("completed", "failed", "cancelled"):
            with self.subTest(status=status):
                wire = {
                    **REFUND,
                    "status": status,
                    "is_final": True,
                    "network": "TON",
                    "destination_address": address,
                    "first_sender": address,
                    "type": "refund",
                    "project_id": "prj_1",
                }
                client, calls = _client((200, wire))
                result = client.refunds.simulate("wdr/1 ?", status)
                self.assertEqual(wire, result)
                self.assert_signed(calls[0], "POST", "/v1/sandbox/refunds/wdr%2F1%20%3F/simulate", {"status": status})

    def test_create_both_modes_sends_only_the_shared_contract_fields(self):
        for vector, amount in ((CREATE, "120"), (OVERPAYMENT, "20")):
            with self.subTest(mode=vector["body"]["mode"]):
                payload = {**REFUND, **vector["body"], "amount": amount}
                client, calls = _client((CREATE["new_status"], payload))

                refund = client.refunds.create(**vector["body"])

                self.assertEqual(payload, refund)
                self.assertTrue(set(REFUNDS["wire"]["required_fields"]).issubset(refund))
                self.assertEqual(REFUND_ID, refund["withdrawal_id"])
                self.assertEqual(amount, refund["amount"])
                self.assert_signed(calls[0], vector["method"], vector["path"], vector["body"])
                self.assertEqual(1, len(calls))

    def test_create_rejects_client_amount_recipient_currency_network_and_parts(self):
        client, calls = _client()
        for field in CREATE["rejected_fields"]:
            with self.subTest(field=field), self.assertRaises(TypeError):
                client.refunds.create(**CREATE["body"], **{field: "1"})
        self.assertEqual([], calls)

    def test_create_requires_invoice_mode_and_the_callers_key(self):
        client, calls = _client()
        for field in CREATE["body"]:
            payload = {key: value for key, value in CREATE["body"].items() if key != field}
            with self.subTest(field=field), self.assertRaises(TypeError):
                client.refunds.create(**payload)
        self.assertEqual([], calls)

    def test_same_key_accepts_201_then_200_with_the_same_withdrawal_id(self):
        client, calls = _client((CREATE["new_status"], REFUND), (CREATE["replay_status"], REFUND))

        first = client.refunds.create(**CREATE["body"])
        replay = client.refunds.create(**CREATE["body"])

        self.assertEqual(first, replay)
        self.assertEqual(REFUND_ID, replay["withdrawal_id"])
        self.assertEqual(2, len(calls))
        for call in calls:
            self.assert_signed(call, "POST", "/v1/refunds", CREATE["body"])

    def test_changed_mode_for_the_same_key_raises_structured_409(self):
        problem = _problem(
            CREATE["changed_mode_status"],
            "conflict",
            "Refund key belongs to a different mode.",
            field="external_order_id",
        )
        client, calls = _client((201, REFUND), (problem["status"], problem), max_retries=2)
        client.refunds.create(**CREATE["body"])

        changed = {**CREATE["body"], "mode": "overpayment"}
        with self.assertRaises(ConflictError) as caught:
            client.refunds.create(**changed)

        self.assertEqual(409, caught.exception.status)
        self.assertEqual(problem, caught.exception.problem)
        self.assertEqual("conflict", caught.exception.code)
        self.assertEqual("external_order_id", caught.exception.field)
        self.assertEqual(problem["detail"], caught.exception.detail)
        self.assertEqual([], caught.exception.errors)
        self.assertEqual(2, len(calls))
        self.assert_signed(calls[1], "POST", "/v1/refunds", changed)

    def test_unknown_create_result_is_replayed_explicitly_with_the_same_key(self):
        client, calls = _client(TimeoutError("response lost"), (CREATE["replay_status"], REFUND), max_retries=2)

        with self.assertRaises(PaymosError):
            client.refunds.create(**CREATE["body"])
        self.assertEqual(1, len(calls), "an ambiguous POST must not retry automatically")
        replay = client.refunds.create(**CREATE["body"])

        self.assertEqual(REFUND_ID, replay["withdrawal_id"])
        self.assertEqual(2, len(calls))
        for call in calls:
            self.assert_signed(call, "POST", "/v1/refunds", CREATE["body"])

    def test_create_does_not_retry_a_server_failure_with_a_new_key(self):
        problem = _problem(503, "unavailable", "Try the same key later.")
        client, calls = _client((503, problem), max_retries=2)

        with self.assertRaises(UnavailableError) as caught:
            client.refunds.create(**CREATE["body"])

        self.assertEqual("unavailable", caught.exception.code)
        self.assertEqual(1, len(calls))
        self.assert_signed(calls[0], "POST", "/v1/refunds", CREATE["body"])

    def test_rate_limit_retry_keeps_the_same_mode_and_key(self):
        client, calls = _client((429, _problem(429, "rate_limited", "Wait.")), (201, REFUND), max_retries=1)

        refund = client.refunds.create(**CREATE["body"])

        self.assertEqual(REFUND_ID, refund["withdrawal_id"])
        self.assertEqual(2, len(calls))
        for call in calls:
            self.assert_signed(call, "POST", "/v1/refunds", CREATE["body"])

    def test_sandbox_120_paid_on_100_invoice_returns_over20_then_full100(self):
        invoice = {
            "invoice_id": INVOICE_ID,
            "status": "paid_over",
            "is_test": True,
            "order": {"amount": "100", "currency": "USD"},
            "payment": {"expected": "100", "paid": "120", "currency": "USDT", "network": "TRC20"},
        }
        over = {**REFUND, **OVERPAYMENT["body"], "amount": "20"}
        completed = {**over, "status": "completed", "is_final": True, "completed_at": 1700000001}
        full_body = {**CREATE["body"], "external_order_id": "full-after-overpayment"}
        full = {**REFUND, **full_body, "withdrawal_id": FULL_ID, "amount": "100"}
        client, calls = _client((200, invoice), (201, over), (200, completed), (201, full))

        paid = client.invoices.simulate_payment(INVOICE_ID, "overpaid")
        partial = client.refunds.create(**OVERPAYMENT["body"])
        settled = client.refunds.get(partial["withdrawal_id"])
        remaining = client.refunds.create(**full_body)

        self.assertEqual(("120", "100"), (paid["payment"]["paid"], paid["payment"]["expected"]))
        self.assertEqual(("20", "completed", "100"), (partial["amount"], settled["status"], remaining["amount"]))
        self.assertEqual((REFUND_ID, FULL_ID), (partial["withdrawal_id"], remaining["withdrawal_id"]))
        self.assertTrue(all(refund["is_test"] for refund in (partial, settled, remaining)))
        self.assertEqual(4, len(calls))
        self.assert_signed(
            calls[0], "POST", f"/v1/sandbox/invoices/{INVOICE_ID}/simulate-payment", {"stage": "overpaid"}
        )
        self.assert_signed(calls[1], "POST", "/v1/refunds", OVERPAYMENT["body"])
        self.assert_signed(calls[2], "GET", f"/v1/refunds/{REFUND_ID}")
        self.assert_signed(calls[3], "POST", "/v1/refunds", full_body)

    def test_list_preserves_every_filter_and_signs_the_encoded_query(self):
        page = {"items": [REFUND], "next_cursor": "next+/="}
        client, calls = _client((200, page))

        result = client.refunds.list(
            invoice_id=INVOICE_ID,
            status=["pending_review", "created"],
            created_from="2026-10-01T00:00:00+03:00",
            created_to="2026-11-01T00:00:00Z",
            cursor="cursor+/=",
            limit=100,
        )

        self.assertEqual(page, result)
        target = (
            "/v1/refunds?created_from=2026-10-01T00%3A00%3A00%2B03%3A00"
            "&created_to=2026-11-01T00%3A00%3A00Z&cursor=cursor%2B%2F%3D"
            f"&invoice_id={INVOICE_ID}&limit=100&status=created&status=pending_review"
        )
        self.assert_signed(calls[0], REFUNDS["list"]["method"], target)

    def test_list_without_filters_sends_no_query_or_body(self):
        client, calls = _client((200, {"items": [], "next_cursor": None}))

        self.assertEqual({"items": [], "next_cursor": None}, client.refunds.list())

        self.assert_signed(calls[0], "GET", REFUNDS["list"]["path"])

    def test_cursor_iterator_keeps_scope_and_reads_all_205_items(self):
        sizes = REFUNDS["list"]["page_sizes"]
        pages = []
        expected_ids = []
        for page_index, size in enumerate(sizes):
            items = [{**REFUND, "withdrawal_id": f"wdr_{page_index}_{index}"} for index in range(size)]
            expected_ids.extend(item["withdrawal_id"] for item in items)
            cursor = f"cursor{page_index + 1}" if page_index + 1 < len(sizes) else None
            pages.append((200, {"items": items, "next_cursor": cursor}))
        client, calls = _client(*pages)

        items = list(
            client.refunds.iterate(
                limit=100,
                invoice_id=INVOICE_ID,
                status=["completed"],
                created_from="2026-10-01T00:00:00Z",
                created_to="2026-11-01T00:00:00Z",
            )
        )

        self.assertEqual(205, len(items))
        self.assertEqual(expected_ids, [item["withdrawal_id"] for item in items])
        self.assertEqual(3, len(calls))
        filters = (
            "created_from=2026-10-01T00%3A00%3A00Z&created_to=2026-11-01T00%3A00%3A00Z"
            f"&invoice_id={INVOICE_ID}&limit=100&status=completed"
        )
        for index, call in enumerate(calls):
            query = filters if index == 0 else filters.replace("&invoice_id=", f"&cursor=cursor{index}&invoice_id=")
            self.assert_signed(call, "GET", f"/v1/refunds?{query}")

    def test_iterator_honors_starting_cursor_and_max_pages(self):
        client, calls = _client((200, {"items": [REFUND], "next_cursor": "next"}))

        self.assertEqual([REFUND], list(client.refunds.iterate(max_pages=1, cursor="start")))
        self.assertEqual(1, len(calls))
        self.assert_signed(calls[0], "GET", "/v1/refunds?cursor=start")

    def test_iterator_rejects_repeated_cursor(self):
        client, calls = _client((200, {"items": [REFUND], "next_cursor": "start"}))

        with self.assertRaises(PaymosError):
            list(client.refunds.iterate(cursor="start"))

        self.assertEqual(1, len(calls))

    def test_invalid_cursor_retains_structured_validation_error(self):
        problem = _problem(
            REFUNDS["list"]["invalid_cursor_status"], "pagination_cursor_invalid", "Cursor is invalid.", field="cursor"
        )
        client, calls = _client((problem["status"], problem))

        with self.assertRaises(ValidationError) as caught:
            client.refunds.list(cursor="foreign-environment")

        self.assertEqual(400, caught.exception.status)
        self.assertEqual("pagination_cursor_invalid", caught.exception.code)
        self.assertEqual("cursor", caught.exception.field)
        self.assertEqual(problem, caught.exception.problem)
        self.assert_signed(calls[0], "GET", "/v1/refunds?cursor=foreign-environment")

    def test_get_encodes_the_withdrawal_id_as_one_path_segment(self):
        client, calls = _client((200, REFUND))

        self.assertEqual(REFUND, client.refunds.get("wdr/1 ?#"))

        self.assert_signed(calls[0], "GET", "/v1/refunds/wdr%2F1%20%3F%23")
        self.assertEqual("", urlsplit(calls[0][1]).query)

    def test_get_foreign_missing_and_other_environment_ids_are_404(self):
        status = REFUNDS["get"]["foreign_or_missing_status"]
        problem = _problem(status, "withdrawal_not_found", "Refund not found.")
        for refund_id in ("wdr_foreign", "wdr_missing", "wdr_production", "invalid-id"):
            with self.subTest(refund_id=refund_id):
                client, calls = _client((status, problem), max_retries=2)

                with self.assertRaises(NotFoundError) as caught:
                    client.refunds.get(refund_id)

                self.assertEqual(404, caught.exception.status)
                self.assertEqual("withdrawal_not_found", caught.exception.code)
                self.assertEqual(problem, caught.exception.problem)
                self.assertEqual(1, len(calls))
                self.assert_signed(calls[0], "GET", f"/v1/refunds/{refund_id}")

    def test_multi_field_validation_retains_the_top_level_code(self):
        problem = CONTRACT["vectors"]["problem_details"]["multi"]
        client, _calls = _client((400, problem))

        with self.assertRaises(ValidationError) as caught:
            client.refunds.create(**CREATE["body"])

        self.assertEqual("validation_failed", caught.exception.code)
        self.assertIsNone(caught.exception.field)
        self.assertEqual(problem["errors"], caught.exception.errors)
        self.assertEqual(problem["detail"], caught.exception.detail)

    def test_wrong_key_type_retains_403_and_business_code(self):
        problem = _problem(403, "payment_key_required", "Refunds require a Payment key.")
        client, calls = _client((403, problem), max_retries=2)

        with self.assertRaises(PermissionError) as caught:
            client.refunds.create(**CREATE["body"])

        self.assertEqual(403, caught.exception.status)
        self.assertEqual("payment_key_required", caught.exception.code)
        self.assertEqual(1, len(calls))

    def test_get_always_reads_the_current_server_state(self):
        completed = {**REFUND, "status": "completed", "is_final": True, "completed_at": 1700000001}
        client, calls = _client((200, REFUND), (200, completed))

        self.assertEqual("created", client.refunds.get(REFUND_ID)["status"])
        self.assertEqual(completed, client.refunds.get(REFUND_ID))

        self.assertEqual(2, len(calls))
        for call in calls:
            self.assert_signed(call, "GET", f"/v1/refunds/{REFUND_ID}")

    def test_read_preserves_server_amount_strings_and_optional_fields(self):
        for is_test in (True, False):
            with self.subTest(is_test=is_test):
                payload = {**REFUND, "amount": "9007199254740993.000001", "fee": "0.000001", "is_test": is_test}
                client, _calls = _client((200, payload), (200, {"items": [payload], "next_cursor": None}))

                refund = client.refunds.get(REFUND_ID)
                listed = client.refunds.list()["items"][0]

                self.assertEqual(payload, refund)
                self.assertEqual(payload, listed)
                self.assertIsInstance(refund["amount"], str)
                self.assertIsInstance(refund["fee"], str)
                self.assertIsInstance(refund["created_at"], int)
                self.assertNotIn("completed_at", refund)


if __name__ == "__main__":
    unittest.main()
