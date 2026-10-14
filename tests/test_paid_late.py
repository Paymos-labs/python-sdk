"""invoice-late-payment wire contract (late-26).

Invoice decodes paid_late_at (Unix seconds | None | absent legacy), the terminal status and payment
money fields stay untouched, and simulate_payment("paid_late") round-trips the stage verbatim.
"""

import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

from paymos import Paymos  # noqa: E402

EXPIRED_PAYLOAD = {
    "invoice_id": "inv_1",
    "project_id": "prj_1",
    "status": "expired",
    "is_final": True,
    "is_test": False,
    "payment_url": "https://pay.test/inv_1",
    "order": {"external_id": "order_1", "amount": "100.00", "currency": "USD"},
    "payment": {
        "currency": "USDT",
        "network": "tron",
        "chain_id": 728126428,
        "expected": "100.00",
        "paid": "60.00",
    },
    "created_at": 1700000000,
    "updated_at": 1700003600,
    "expires_at": 1700003600,
    "completed_at": 1700003600,
}


def _client_returning(payload):
    _client_returning.fixture = payload
    client = Paymos(api_key="pk", api_secret="sk")
    captured = {}

    def request(method, path, payload=None, query=""):
        captured.update({"method": method, "path": path, "payload": payload})
        return _client_returning.fixture

    client.request = request
    return client, captured


class PaidLateContract(unittest.TestCase):
    def test_decodes_unix_mark_beside_terminal_status(self):
        client, _ = _client_returning({**EXPIRED_PAYLOAD, "paid_late_at": 1700007200})
        invoice = client.invoices.get("inv_1")
        self.assertEqual(invoice["status"], "expired")
        self.assertTrue(invoice["is_final"])
        self.assertEqual(invoice["paid_late_at"], 1700007200)
        self.assertEqual(invoice["payment"]["paid"], "60.00")

    def test_decodes_null_and_absent_marks(self):
        client, _ = _client_returning({**EXPIRED_PAYLOAD, "paid_late_at": None})
        self.assertIsNone(client.invoices.get("inv_1")["paid_late_at"])

        client, _ = _client_returning(dict(EXPIRED_PAYLOAD))
        self.assertNotIn("paid_late_at", client.invoices.get("inv_1"))

    def test_serializes_paid_late_stage(self):
        client, captured = _client_returning(dict(EXPIRED_PAYLOAD))
        client.invoices.simulate_payment("inv_1", "paid_late")
        self.assertEqual(captured["payload"], {"stage": "paid_late"})
        self.assertEqual(captured["path"], "/v1/sandbox/invoices/inv_1/simulate-payment")

    def test_rejects_unknown_stage(self):
        client, _ = _client_returning(dict(EXPIRED_PAYLOAD))
        with self.assertRaises(ValueError):
            client.invoices.simulate_payment("inv_1", "explode")


if __name__ == "__main__":
    json.dumps({})
    unittest.main()
