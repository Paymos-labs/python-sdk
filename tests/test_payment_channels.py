import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

from paymos import Paymos, Response

# One channel exactly as the API renders it: money as strings, timestamps as integers, and
# absent-not-null optionals — the BEP20 rail has not provisioned, so it carries no `address`
# key at all, and its token cannot be quoted, so it carries no `minimum_deposit` key at all.
CHANNEL = {
    "id": "pc_1",
    "project_id": "prj_1",
    "external_id": "customer-42",
    "status": "active",
    "is_accepting_payments": True,
    "is_fully_provisioned": False,
    "is_test": True,
    "applied_fee_percent": 1.5,
    "customer_fee_percent": 0,
    "networks": [
        {
            "network": "TRC20",
            "status": "active",
            "address": "TXYZaddress",
            "tokens": [{"symbol": "USDT", "minimum_deposit": "1.000000"}],
        },
        {"network": "BEP20", "status": "provisioning", "tokens": [{"symbol": "USDT"}]},
    ],
    "created_at": 1700000000,
    "updated_at": 1700000001,
}

DEPOSIT = {
    "id": "pcd_1",
    "payment_channel_id": "pc_1",
    "project_id": "prj_1",
    "payment_channel_external_id": "customer-42",
    "status": "confirmed",
    "is_final": True,
    "is_test": True,
    "currency": "USDT",
    "network": "TRC20",
    "chain_id": 728126428,
    "contract_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
    "gross": "100.000000",
    "fee": "1.500000",
    "net": "98.500000",
    "applied_fee_percent": 1.5,
    "customer_fee_percent": 0,
    "tx_hash": "0xhash",
    "transfer_id": "trf_1",
    "source_address": "TSourceAddress",
    "destination_address": "TXYZaddress",
    "block_height": 65000000,
    "first_included_block_timestamp": 1700000002,
    "explorer_url": "https://tronscan.org/#/transaction/0xhash",
    "created_at": 1700000002,
    "updated_at": 1700000003,
    "confirmed_at": 1700000003,
}


def _client(*responses):
    """A client whose transport replays `(status, payload)` pairs and records every call."""
    queue = list(responses)
    calls = []

    def transport(method, url, _headers, body, _timeout):
        calls.append((method, url.removeprefix("https://api.paymos.io"), body.decode() if body else None))
        if not queue:
            raise AssertionError(f"unexpected extra request: {method} {url}")
        status, payload = queue.pop(0)
        return Response(status, json.dumps(payload), {})

    client = Paymos("pk_test_key", "sk_test_secret", transport=transport, max_retries=0, clock=lambda: 1700000000)
    return client, calls


def _routes(calls):
    return [(method, url) for method, url, _body in calls]


class PaymentChannelTests(unittest.TestCase):
    def test_create_twice_returns_the_channel_both_times(self):
        client, calls = _client((201, CHANNEL), (200, CHANNEL))

        first = client.payment_channels.create(project_id="prj_1", external_id="customer-42")
        second = client.payment_channels.create(project_id="prj_1", external_id="customer-42")

        self.assertEqual("pc_1", first["id"])
        self.assertEqual("pc_1", second["id"], "the idempotent 200 is the existing channel, never an error")
        self.assertEqual([("POST", "/v1/payment-channels")] * 2, _routes(calls))
        self.assertEqual({"project_id": "prj_1", "external_id": "customer-42"}, json.loads(calls[0][2]))

    def test_block_returns_the_updated_channel(self):
        client, calls = _client((200, {**CHANNEL, "status": "blocked", "is_accepting_payments": False}))

        channel = client.payment_channels.block("pc_1")

        self.assertEqual("blocked", channel["status"])
        self.assertFalse(channel["is_accepting_payments"], "block returns the channel; it is not a void call")
        self.assertEqual([("POST", "/v1/payment-channels/pc_1/block")], _routes(calls))

    def test_unblock_returns_the_updated_channel(self):
        client, calls = _client((200, {**CHANNEL, "status": "active", "is_accepting_payments": True}))

        channel = client.payment_channels.unblock("pc_1")

        self.assertEqual("active", channel["status"])
        self.assertTrue(channel["is_accepting_payments"], "unblock returns the channel; it is not a no-op")
        self.assertEqual([("POST", "/v1/payment-channels/pc_1/unblock")], _routes(calls))

    def test_empty_feed_page_still_yields_a_cursor_to_resume_from(self):
        client, calls = _client((200, {"items": [], "next_cursor": "cur_2"}))

        page = client.payment_channel_deposits.read(cursor="cur_1")

        # The feed's positions are global, so a merchant's filter skips most of them. An empty
        # page still advances PAST what was skipped — stop reading here and the poller rescans
        # the same span forever, never reaching its own next payment.
        self.assertEqual([], page["items"])
        self.assertEqual("cur_2", page["next_cursor"])
        self.assertEqual([("GET", "/v1/payment-channel-deposits?cursor=cur_1")], _routes(calls))

    def test_blocked_feed_page_surfaces_which_deposit_and_why(self):
        client, _calls = _client(
            (
                200,
                {
                    "items": [],
                    "next_cursor": "cur_2",
                    "blocked": {"deposit_id": "pcd_9", "reason": "not_confirmed"},
                },
            )
        )

        page = client.payment_channel_deposits.read()

        # Without these two fields a stuck feed is byte-identical to a quiet day.
        self.assertEqual("pcd_9", page["blocked"]["deposit_id"])
        self.assertEqual("not_confirmed", page["blocked"]["reason"])
        self.assertEqual("cur_2", page["next_cursor"])

    def test_every_filter_reaches_the_wire_in_snake_case(self):
        client, calls = _client(
            (200, {"items": [], "next_cursor": None}),
            (200, {"items": [], "next_cursor": "cur_2"}),
        )

        client.payment_channels.list(
            limit=25, cursor="cur_1", status=["blocked", "active"], external_id="customer-42", project_id="prj_1"
        )
        client.payment_channel_deposits.read(
            limit=50, cursor="cur_1", project_id="prj_1", payment_channel_id="pc_1", confirmed_from=1700000000
        )

        # The API rejects unknown query fields outright, so a camelCase slip is a 400 at a
        # merchant rather than a failure here — unless the exact strings are asserted.
        self.assertEqual(
            [
                (
                    "GET",
                    "/v1/payment-channels?cursor=cur_1&external_id=customer-42&limit=25"
                    "&project_id=prj_1&status=active&status=blocked",
                ),
                (
                    "GET",
                    "/v1/payment-channel-deposits?confirmed_from=1700000000&cursor=cur_1&limit=50"
                    "&payment_channel_id=pc_1&project_id=prj_1",
                ),
            ],
            _routes(calls),
        )
        for camel in ("externalId", "projectId", "paymentChannelId", "confirmedFrom"):
            self.assertNotIn(camel, calls[0][1] + calls[1][1])

    def test_ids_are_path_encoded_not_query_encoded(self):
        client, calls = _client((200, CHANNEL), (200, DEPOSIT))

        client.payment_channels.get("pc/1 a")
        client.payment_channel_deposits.get("pcd/1 a")

        self.assertEqual(
            [("GET", "/v1/payment-channels/pc%2F1%20a"), ("GET", "/v1/payment-channel-deposits/pcd%2F1%20a")],
            _routes(calls),
        )
        self.assertNotIn("?", calls[0][1])
        self.assertNotIn("+", calls[1][1], "an id is an RFC3986 path segment, not a form-encoded query value")

    def test_simulate_sends_network_and_omits_stage_when_unset(self):
        client, calls = _client((200, DEPOSIT), (200, DEPOSIT))

        client.payment_channels.simulate_deposit("pc_1", amount="100.00", currency="USDT", network="TRC20")
        client.payment_channels.simulate_deposit(
            "pc_1", amount="100.00", currency="USDT", network="TRC20", stage="confirming"
        )

        default_body = json.loads(calls[0][2])
        self.assertEqual("TRC20", default_body["network"], "network is required on simulate")
        self.assertNotIn("stage", default_body, "an unset stage is absent from the body — not null, not empty")
        self.assertEqual({"amount": "100.00", "currency": "USDT", "network": "TRC20"}, default_body)
        self.assertEqual("confirming", json.loads(calls[1][2])["stage"])
        self.assertEqual([("POST", "/v1/sandbox/payment-channels/pc_1/simulate-deposit")] * 2, _routes(calls))
        with self.assertRaises(ValueError):
            client.payment_channels.simulate_deposit(
                "pc_1", amount="100.00", currency="USDT", network="TRC20", stage="settled"
            )

    def test_channel_list_iterator_terminates_and_the_feed_has_no_iterator(self):
        client, calls = _client(
            (200, {"items": [CHANNEL], "next_cursor": "cur_2"}),
            (200, {"items": [{**CHANNEL, "id": "pc_2"}], "next_cursor": None}),
        )

        self.assertEqual(["pc_1", "pc_2"], [channel["id"] for channel in client.payment_channels.iterate()])
        self.assertEqual(2, len(calls), "a null cursor ends the ordinary keyset list")
        self.assertIn("cursor=cur_2", calls[1][1])

        # The mirror assertion must NOT exist for the feed, and that is the point of keeping both
        # in one file: the feed has no last page, so it is given no auto-iterator at all.
        self.assertFalse(hasattr(client.payment_channel_deposits, "iterate"))
        self.assertFalse(hasattr(client.payment_channel_deposits, "list"))


if __name__ == "__main__":
    unittest.main()
