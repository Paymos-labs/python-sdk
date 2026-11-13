import email.message
import io
import pathlib
import sys
import unittest
import urllib.request
from urllib.response import addinfourl

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "src"))

from paymos import ApiError  # noqa: E402
from paymos import client as client_module  # noqa: E402

ORIGIN = "https://api.paymos.io/v1/invoices"


class ScriptedHttps(urllib.request.HTTPSHandler):
    """Answers every HTTPS request from a script and records what was sent; no socket is opened."""

    def __init__(self, status: int, location: str | None = None) -> None:
        super().__init__()
        self.status = status
        self.location = location
        self.sent: list[tuple[str, str, dict[str, str]]] = []

    def https_open(self, req: urllib.request.Request) -> addinfourl:
        self.sent.append((req.get_method(), req.full_url, dict(req.header_items())))
        headers = email.message.Message()
        headers["Content-Type"] = "application/json"
        if self.location is not None:
            headers["Location"] = self.location
        response = addinfourl(io.BytesIO(b'{"ok":true}'), headers, req.full_url, self.status)
        response.msg = "scripted"  # type: ignore[attr-defined]
        return response


class DefaultTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original = client_module._OPENER

    def tearDown(self) -> None:
        client_module._OPENER = self.original

    def send(self, handler: ScriptedHttps) -> client_module.Response:
        client_module._OPENER = client_module._build_opener(handler)
        headers = {"Authorization": "HMAC-SHA256 pk_test:signature", "X-Request-Timestamp": "1700000000"}
        return client_module._default_transport("POST", ORIGIN, headers, b"{}", 5)

    def test_default_transport_does_not_follow_redirects(self) -> None:
        for status in (301, 302, 303, 307, 308):
            for target in ("https://elsewhere.example/v1/invoices", "http://api.paymos.io/v1/invoices"):
                with self.subTest(status=status, target=target):
                    handler = ScriptedHttps(status, target)

                    response = self.send(handler)

                    self.assertEqual(status, response.status)
                    self.assertEqual(1, len(handler.sent))
                    self.assertEqual(("POST", ORIGIN), handler.sent[0][:2])

    def test_redirect_reaches_the_client_as_an_api_error(self) -> None:
        handler = ScriptedHttps(302, "https://elsewhere.example/v1/invoices")
        client_module._OPENER = client_module._build_opener(handler)
        paymos = client_module.Paymos("pk_test", "sk_test", max_retries=0)

        with self.assertRaises(ApiError) as raised:
            paymos.request("POST", "/v1/invoices", {"amount": "1.00"})
        self.assertEqual(302, raised.exception.status)
        self.assertEqual(1, len(handler.sent))

    def test_default_transport_returns_a_normal_response(self) -> None:
        handler = ScriptedHttps(200)

        response = self.send(handler)

        self.assertEqual(200, response.status)
        self.assertEqual('{"ok":true}', response.body)
        self.assertEqual(1, len(handler.sent))
        self.assertEqual("HMAC-SHA256 pk_test:signature", handler.sent[0][2]["Authorization"])


if __name__ == "__main__":
    unittest.main()
