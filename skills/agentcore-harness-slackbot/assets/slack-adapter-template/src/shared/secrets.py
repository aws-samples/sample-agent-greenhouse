from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    value: str
    expires_at: float


class SecretCache:
    def __init__(self, client: Any, *, ttl_seconds: int = 300) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._values: dict[str, CacheEntry] = {}

    def get(self, secret_arn: str) -> str:
        now = time.monotonic()
        cached = self._values.get(secret_arn)
        if cached is not None and cached.expires_at > now:
            return cached.value
        response = self._client.get_secret_value(SecretId=secret_arn)
        value = response.get("SecretString")
        if not isinstance(value, str):
            value = base64.b64decode(response["SecretBinary"]).decode()
        if not value:
            raise ValueError(f"Secret is empty: {secret_arn}")
        self._values[secret_arn] = CacheEntry(value, now + self._ttl_seconds)
        return value
