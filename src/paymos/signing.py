from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Mapping, Sequence
from urllib.parse import quote


def string_to_sign(timestamp: str | int, method: str, path: str, query: str = "", body: str = "") -> str:
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""
    return f"{timestamp}\n{method.upper()}\n{path}\n{query}\n{body_hash}"


def sign(secret: str, value: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def authorization_header(
    api_key: str,
    api_secret: str,
    timestamp: str | int,
    method: str,
    path: str,
    query: str = "",
    body: str = "",
) -> str:
    signature = sign(api_secret, string_to_sign(timestamp, method, path, query, body))
    return f"HMAC-SHA256 {api_key}:{signature}"


def encode_path_segment(value: str) -> str:
    return quote(str(value), safe="-._~")


def build_query(filters: Mapping[str, object]) -> str:
    parts: list[str] = []
    for key in sorted(filters):
        raw = filters[key]
        if raw is None:
            continue
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            values = sorted(raw, key=str)
            if not values:
                raise ValueError(f"Paymos list filter cannot be empty: {key}")
        else:
            values = [raw]
        for value in values:
            if isinstance(value, bool) or not isinstance(value, (str, int)) or str(value) == "":
                raise ValueError(f"Invalid Paymos list filter: {key}")
            parts.append(f"{quote(key, safe='-._~')}={quote(str(value), safe='-._~')}")
    return "?" + "&".join(parts) if parts else ""
