from __future__ import annotations

import hashlib
import hmac
import re
import time

MAX_SIGNATURE_AGE_SECONDS = 300
_LEADING_MENTION = re.compile(r"^\s*<@[A-Z0-9]+>\s*", re.IGNORECASE)


def verify_slack_signature(
    signing_secret: str,
    timestamp: str,
    signature: str,
    body: bytes,
    *,
    now: int | None = None,
) -> bool:
    try:
        request_time = int(timestamp)
    except (TypeError, ValueError):
        return False
    current_time = int(time.time()) if now is None else now
    if abs(current_time - request_time) > MAX_SIGNATURE_AGE_SECONDS:
        return False
    if not signature.startswith("v0="):
        return False
    base = b":".join((b"v0", timestamp.encode(), body))
    expected = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def clean_prompt(text: str, *, max_chars: int = 12_000) -> str:
    cleaned = _LEADING_MENTION.sub("", text, count=1).strip()
    if not cleaned:
        raise ValueError("Slack message contains no prompt")
    if len(cleaned) > max_chars:
        raise ValueError(f"Slack prompt exceeds {max_chars} characters")
    return cleaned
