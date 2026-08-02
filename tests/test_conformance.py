import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

from paymos import (
    VERSION,
    Paymos,
    PaymosError,
    RateLimitError,
    Response,
    UnavailableError,
    WebhookVerifier,
    authorization_header,
    build_query,
)
from paymos.errors import api_error

CONTRACT = json.loads((pathlib.Path(__file__).parents[1] / "conformance" / "contract.json").read_text())


class ConformanceTests(unittest.TestCase):
    def test_signing_vectors(self):
        post = CONTRACT["vectors"]["post_signing"]
        self.assertEqual(
            post["authorization"],
            authorization_header(
                post["api_key"],
                post["api_secret"],
                post["timestamp"],
                post["method"],
                post["path"],
                post["query"],
                post["body"],
            ),
        )
        get = CONTRACT["vectors"]["get_query_signing"]
        self.assertEqual(
            get["query"], build_query({"status": ["paid_over", "paid"], "project_id": "prj/a", "limit": 50})
        )

    def test_webhook_vector(self):
        vector = CONTRACT["vectors"]["webhook"]
        verifier = WebhookVerifier(vector["secret"], vector["tolerance_seconds"])
        self.assertTrue(verifier.verify(vector["header"], vector["raw_body"], vector["now"]))
        event = verifier.construct_event(vector["header"], vector["raw_body"], vector["now"])
        self.assertEqual("evt_123", event["event_id"])
        self.assertEqual(1700000000, event["occurred_at"])
        self.assertFalse(
            verifier.verify(
                vector["header"].replace("t=1700000000", "t=1700000000,t=1700000000"), vector["raw_body"], vector["now"]
            )
        )

    def test_complete_resource_routes(self):
        calls = []

        def transport(method, url, headers, body, timeout):
            calls.append((method, url, body.decode() if body else None, headers["User-Agent"]))
            return Response(200, '{"items":[],"next_cursor":null}', {})

        client = Paymos("pk_test_key", "sk_test_secret", transport=transport, max_retries=0, clock=lambda: 1700000000)
        client.system.time()
        client.invoices.create(project_id="prj_1", amount="10.00", currency="USD", external_order_id="order_1")
        client.invoices.get("inv/1")
        client.invoices.list(limit=1)
        client.invoices.cancel("inv_1", "reason")
        client.invoices.confirm_payment("inv_1", "USDT", "tron")
        client.invoices.simulate_payment("inv_1", "paid")
        client.withdrawals.create(
            destination_address="address", network="TRC20", currency="USDT", amount="5.00", external_order_id="w_1"
        )
        client.withdrawals.get("wdr_1")
        client.withdrawals.list(limit=1)
        client.withdrawals.cancel("wdr_1", "reason")
        client.withdrawals.simulate_completion("wdr_1")
        client.balances.get()
        self.assertEqual(
            [
                ("GET", "/v1/time"),
                ("POST", "/v1/invoices"),
                ("GET", "/v1/invoices/inv%2F1"),
                ("GET", "/v1/invoices?limit=1"),
                ("POST", "/v1/invoices/inv_1/cancel"),
                ("POST", "/v1/invoices/inv_1/confirm-payment"),
                ("POST", "/v1/sandbox/invoices/inv_1/simulate-payment"),
                ("POST", "/v1/withdrawals"),
                ("GET", "/v1/withdrawals/wdr_1"),
                ("GET", "/v1/withdrawals?limit=1"),
                ("POST", "/v1/withdrawals/wdr_1/cancel"),
                ("POST", "/v1/sandbox/withdrawals/wdr_1/simulate-completion"),
                ("GET", "/v1/balances"),
            ],
            [(method, url.removeprefix("https://api.paymos.io")) for method, url, _body, _agent in calls],
        )
        self.assertTrue(all(call[3] == f"paymos-python/{VERSION}" for call in calls))
        create_body = json.loads(calls[1][2])
        self.assertEqual(
            {"project_id": "prj_1", "amount": "10.00", "currency": "USD", "external_order_id": "order_1"}, create_body
        )

    def test_problem_details_uses_top_level_code(self):
        vector = CONTRACT["vectors"]["problem_details"]["multi"]
        error = api_error(400, json.dumps(vector))

        self.assertEqual("validation_failed", error.code)
        self.assertIsNone(error.field)
        self.assertEqual("field_required", error.errors[0]["code"])

    def test_retry_and_error_contract(self):
        responses = [Response(429, '{"detail":"slow down"}', {"Retry-After": "0"}), Response(200, "{}", {})]
        sleeps = []
        client = Paymos("pk", "sk", transport=lambda *_args: responses.pop(0), sleep=sleeps.append, base_delay=0)
        self.assertEqual(
            {}, client.invoices.create(project_id="prj_1", amount="10.00", currency="USD", external_order_id="order_1")
        )
        self.assertEqual(1, len(sleeps))

        attempts = []

        def unavailable(*_args):
            attempts.append(1)
            return Response(503, '{"errors":[{"code":"temporarily_unavailable","field":null,"message":"retry"}]}', {})

        client = Paymos("pk", "sk", transport=unavailable, sleep=lambda _delay: None)
        with self.assertRaises(RateLimitError):
            Paymos("pk", "sk", transport=lambda *_args: Response(429, "{}", {}), max_retries=0).invoices.create(
                project_id="prj_1", amount="10.00", currency="USD", external_order_id="order_1"
            )
        with self.assertRaises(UnavailableError):
            client.invoices.create(project_id="prj_1", amount="10.00", currency="USD", external_order_id="order_1")
        self.assertEqual(1, len(attempts), "POST must not retry a generic 503")

    def test_cursor_repetition_is_rejected(self):
        pages = iter(
            [
                Response(200, '{"items":[{"invoice_id":"one"}],"next_cursor":"same"}', {}),
                Response(200, '{"items":[],"next_cursor":"same"}', {}),
            ]
        )
        client = Paymos("pk", "sk", transport=lambda *_args: next(pages), max_retries=0)
        iterator = client.invoices.iterate(max_pages=3)
        self.assertEqual("one", next(iterator)["invoice_id"])
        with self.assertRaises(PaymosError):
            next(iterator)

    def test_query_rejects_non_contract_scalar_types(self):
        with self.assertRaises(ValueError):
            build_query({"limit": 1.5})
        with self.assertRaises(ValueError):
            build_query({"limit": True})


if __name__ == "__main__":
    unittest.main()
