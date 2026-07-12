from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, cast

from .errors import SignatureMismatchError, TimestampSkewError
from .models import WebhookEvent


class WebhookVerifier:
    def __init__(self, secret: str, tolerance_seconds: int = 300):
        if not isinstance(secret, str) or not secret.strip():
            raise ValueError("Webhook secret must be a non-empty string.")
        if not isinstance(tolerance_seconds, int) or tolerance_seconds < 0:
            raise ValueError("Webhook tolerance must be a non-negative integer.")
        self.secret = secret
        self.tolerance_seconds = tolerance_seconds

    def verify(self, signature_header: str, raw_body: str | bytes, now: int | None = None) -> bool:
        try:
            self.assert_valid(signature_header, raw_body, now)
            return True
        except (SignatureMismatchError, TimestampSkewError, TypeError, ValueError):
            return False

    def assert_valid(self, signature_header: str, raw_body: str | bytes, now: int | None = None) -> None:
        timestamp, signatures = self._parse_header(signature_header)
        current = int(time.time()) if now is None else int(now)
        if abs(current - timestamp) > self.tolerance_seconds:
            raise TimestampSkewError("Webhook timestamp is outside the allowed tolerance.")
        body = raw_body if isinstance(raw_body, bytes) else raw_body.encode("utf-8")
        expected = hmac.new(
            self.secret.encode("utf-8"), str(timestamp).encode("ascii") + b"." + body, hashlib.sha256
        ).hexdigest()
        if not any(len(value) == 64 and hmac.compare_digest(expected, value.lower()) for value in signatures):
            raise SignatureMismatchError("Webhook signature does not match payload.")

    def construct_event(self, signature_header: str, raw_body: str | bytes, now: int | None = None) -> WebhookEvent:
        self.assert_valid(signature_header, raw_body, now)
        value = json.loads(raw_body)
        if not isinstance(value, dict):
            raise ValueError("Webhook payload must be a JSON object.")
        _validate_envelope(value)
        return cast(WebhookEvent, value)

    @staticmethod
    def _parse_header(header: str) -> tuple[int, list[str]]:
        timestamp: int | None = None
        timestamp_count = 0
        signatures: list[str] = []
        for part in str(header).split(","):
            key, separator, value = part.strip().partition("=")
            if separator and key == "t" and value.isdigit():
                timestamp = int(value)
                timestamp_count += 1
            elif separator and key == "v1" and value:
                signatures.append(value)
        if timestamp is None or timestamp_count != 1 or not signatures:
            raise SignatureMismatchError("Webhook signature header is missing or malformed.")
        return timestamp, signatures


def _validate_envelope(value: dict[str, Any]) -> None:
    if not isinstance(value.get("event_id"), str) or not value["event_id"].strip():
        raise ValueError("Webhook event_id must be a non-empty string.")
    if not isinstance(value.get("event_type"), str) or not value["event_type"].strip():
        raise ValueError("Webhook event_type must be a non-empty string.")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("Webhook version must be a positive integer.")
    occurred_at = value.get("occurred_at")
    if isinstance(occurred_at, bool) or not isinstance(occurred_at, int) or occurred_at < 0:
        raise ValueError("Webhook occurred_at must be a non-negative Unix timestamp.")
    if not isinstance(value.get("data"), dict):
        raise ValueError("Webhook data must be a JSON object.")
