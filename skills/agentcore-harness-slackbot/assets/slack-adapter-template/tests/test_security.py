from __future__ import annotations

import hashlib
import hmac

from shared.security import clean_prompt, verify_slack_signature


def test_verifies_current_slack_signature() -> None:
    body = b'{"type":"url_verification","challenge":"abc"}'
    timestamp = "1700000000"
    secret = "signing-secret"
    base = b":".join((b"v0", timestamp.encode(), body))
    signature = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    assert verify_slack_signature(
        secret,
        timestamp,
        signature,
        body,
        now=1_700_000_000,
    )
    assert not verify_slack_signature(
        secret,
        timestamp,
        "v0=bad",
        body,
        now=1_700_000_000,
    )


def test_cleans_one_leading_bot_mention() -> None:
    assert clean_prompt(" <@U123ABC>  Explain AgentCore ") == "Explain AgentCore"
