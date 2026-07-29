from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from shared.models import SlackMessage


@dataclass(frozen=True)
class HarnessIdentity:
    runtime_session_id: str
    actor_id: str


def _digest(key: bytes, namespace: str, value: str) -> str:
    return hmac.new(key, f"{namespace}:{value}".encode(), hashlib.sha256).hexdigest()


def derive_harness_identity(secret: str, message: SlackMessage) -> HarnessIdentity:
    key = secret.encode()
    if len(key) < 32:
        raise ValueError("Session HMAC secret must be at least 32 bytes")
    conversation = _digest(key, "conversation", message.conversation_key)
    sender = _digest(key, "sender", f"{message.team_id}:{message.user_id}")
    actor_id = (
        f"slack-user-{sender}"
        if message.is_direct_message
        else f"slack-conversation-{conversation}"
    )
    return HarnessIdentity(
        runtime_session_id=f"slack-{conversation}",
        actor_id=actor_id,
    )
