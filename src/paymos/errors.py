from __future__ import annotations

import json
from collections.abc import Mapping
from email.utils import parsedate_to_datetime
from typing import Any


class PaymosError(Exception):
    pass


class ConfigurationError(PaymosError):
    pass


class SignatureMismatchError(PaymosError):
    pass


class TimestampSkewError(PaymosError):
    pass


class ApiError(PaymosError):
    def __init__(self, status: int, body: str, headers: Mapping[str, str] | None = None):
        self.status = status
        self.body = body
        self.headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        try:
            parsed = json.loads(body) if body else None
            self.problem: dict[str, Any] | None = parsed if _is_canonical_problem(parsed, status) else None
        except json.JSONDecodeError:
            self.problem = None
        detail = self.detail or self.code or (self.problem or {}).get("title") or body or "empty response"
        super().__init__(f"Paymos API {status}: {detail}")

    @property
    def errors(self) -> list[dict[str, Any]]:
        value = (self.problem or {}).get("errors")
        return value if isinstance(value, list) else []

    @property
    def code(self) -> str:
        return str((self.problem or {}).get("code") or "")

    @property
    def field(self) -> str | None:
        value = (self.problem or {}).get("field")
        return str(value) if value is not None else None

    @property
    def detail(self) -> str:
        value = (self.problem or {}).get("detail")
        if value:
            return str(value)
        return ""

    @property
    def retry_after_seconds(self) -> int | None:
        value = self.headers.get("retry-after")
        if not value:
            return None
        if value.isdigit():
            return int(value)
        try:
            from datetime import datetime, timezone

            return max(0, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds() + 0.999))
        except (TypeError, ValueError, OverflowError):
            return None


class ValidationError(ApiError):
    pass


class AuthenticationError(ApiError):
    pass


class NotFoundError(ApiError):
    pass


class ConflictError(ApiError):
    pass


class GoneError(ApiError):
    pass


class RateLimitError(ApiError):
    pass


class ServerError(ApiError):
    pass


class UnavailableError(ServerError):
    pass


def api_error(status: int, body: str, headers: Mapping[str, str] | None = None) -> ApiError:
    error_type = {
        400: ValidationError,
        401: AuthenticationError,
        403: AuthenticationError,
        404: NotFoundError,
        409: ConflictError,
        410: GoneError,
        429: RateLimitError,
        503: UnavailableError,
    }.get(status, ServerError if status >= 500 else ApiError)
    return error_type(status, body, headers)


def _is_canonical_problem(value: Any, status: int) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("type"), str)
        and isinstance(value.get("title"), str)
        and isinstance(value.get("status"), int)
        and not isinstance(value.get("status"), bool)
        and value["status"] == status
        and isinstance(value.get("detail"), str)
        and isinstance(value.get("code"), str)
    )
