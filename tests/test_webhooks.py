import hashlib
import hmac
import json
import pathlib
import sys
import unittest
from typing import cast

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

from paymos import PaymentChannelDeposit, WebhookVerifier

SECRET = "whsec_test_secret"


def _signature_header(secret: str, timestamp: int, raw_body: bytes) -> str:
    """The same "timestamp.body" HMAC construction `WebhookVerifier.assert_valid` verifies with."""
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}".encode("ascii") + b"." + raw_body, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


class WebhookPaymentChannelDepositTests(unittest.TestCase):
    def test_confirmed_deposit_round_trips_into_the_deposit_model(self):
        """A `payment_channel.deposit.confirmed` webhook carries the full deposit wire shape as
        `data`, so the same model the deposit feed decodes must survive `construct_event`
        unchanged. This is a native-TRX deposit — no contract, no attributable payer address, no
        explorer link minted yet — so `contract_address`, `source_address`, `explorer_url` and
        `first_included_block_timestamp` are OMITTED from the JSON below, never sent as null,
        and must stay absent (not merely `None`) after decoding.

        This is not one of the shared conformance vectors in conformance/contract.json (that
        vector is an `invoice.paid` body), so the signature is computed here the same way
        WebhookVerifier.assert_valid verifies one, proving the real signed-and-verified path
        rather than a bare `json.loads`.
        """
        timestamp = 1700000000
        raw_body = json.dumps(
            {
                "event_id": "evt_2",
                "event_type": "payment_channel.deposit.confirmed",
                "version": 1,
                "occurred_at": timestamp,
                "data": {
                    "id": "pcd_9",
                    "payment_channel_id": "pc_1",
                    "project_id": "prj_1",
                    "payment_channel_external_id": "customer-42",
                    "status": "confirmed",
                    "is_final": True,
                    "is_test": False,
                    "currency": "TRX",
                    "network": "TRC20",
                    "chain_id": 728126428,
                    "gross": "100.00",
                    "fee": "1.00",
                    "net": "99.00",
                    "applied_fee_percent": 1,
                    "customer_fee_percent": 0,
                    "tx_hash": "9a2f1c",
                    "transfer_id": "trf_1",
                    "destination_address": "TChannelAddress",
                    "block_height": 60000000,
                    "created_at": 1700000000,
                    "updated_at": 1700000100,
                    "confirmed_at": 1700000100,
                },
            }
        )
        header = _signature_header(SECRET, timestamp, raw_body.encode("utf-8"))

        event = WebhookVerifier(SECRET).construct_event(header, raw_body, timestamp)

        self.assertEqual("payment_channel.deposit.confirmed", event["event_type"])
        deposit = cast(PaymentChannelDeposit, event["data"])

        self.assertTrue(deposit["is_final"])

        # Money survives as decimal strings, all the way through — never a float.
        for amount in (deposit["gross"], deposit["fee"], deposit["net"]):
            self.assertIsInstance(amount, str)
        self.assertEqual("100.00", deposit["gross"])
        self.assertEqual("1.00", deposit["fee"])
        self.assertEqual("99.00", deposit["net"])

        # Absent stays absent: a native-coin deposit's optionals are missing keys, not None values.
        for key in ("contract_address", "source_address", "explorer_url", "first_included_block_timestamp"):
            self.assertNotIn(key, deposit)


if __name__ == "__main__":
    unittest.main()
