"""Slack event handler for Plato agent.

Processes Slack events (messages, app_mentions) and routes them to the
Plato agent deployed on AgentCore Runtime.

Memory is handled entirely by the AgentCore Runtime agent (plato-agentcore/main.py)
which stores conversation events via create_event() and retrieves history via
list_events(). The Slack handler's job is just to relay messages and responses.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SlackConfig:
    """Configuration for Slack integration."""

    bot_token: str = ""
    signing_secret: str = ""
    app_id: str = ""

    # AgentCore settings (production mode)
    agentcore_runtime_arn: str = ""
    agentcore_runtime_endpoint: str = ""
    agentcore_agent_id: str = ""

    # Mode: "echo" | "agentcore"
    mode: str = "echo"

    # Bot user ID (auto-detected on first message)
    bot_user_id: str = ""

    # Region for AgentCore API calls
    agentcore_region: str = ""

    # Identity toggle: when True, pass runtimeUserId for per-user OAuth tokens
    # When False (default), use static GITHUB_TOKEN fallback
    identity_enabled: bool = False

    @classmethod
    def from_env(cls) -> "SlackConfig":
        """Load configuration from environment variables."""
        mode = os.environ.get("PLATO_SLACK_MODE", "echo")
        return cls(
            bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
            signing_secret=os.environ.get("SLACK_SIGNING_SECRET", ""),
            app_id=os.environ.get("SLACK_APP_ID", ""),
            agentcore_runtime_arn=os.environ.get("AGENTCORE_RUNTIME_ARN", ""),
            agentcore_runtime_endpoint=os.environ.get("AGENTCORE_RUNTIME_ENDPOINT", ""),
            agentcore_agent_id=os.environ.get("AGENTCORE_AGENT_ID", ""),
            mode=mode,
            bot_user_id=os.environ.get("SLACK_BOT_USER_ID", ""),
            agentcore_region=os.environ.get("PLATO_REGION", "us-west-2"),
            identity_enabled=os.environ.get("PLATO_IDENTITY_ENABLED", "false").lower() == "true",
        )


@dataclass
class SlackMessage:
    """Parsed Slack message."""

    text: str
    user_id: str
    channel_id: str
    thread_ts: str | None = None
    ts: str = ""
    is_dm: bool = False
    is_mention: bool = False
    user_name: str = ""

    @property
    def reply_ts(self) -> str:
        """Thread timestamp to reply in (maintains thread context)."""
        return self.thread_ts or self.ts

    @property
    def memory_session_id(self) -> str:
        """Session ID for memory storage.

        - In DMs: use dm_ + user_id (persistent across all messages in DM,
          including thread replies — DM threads are continuations, not
          separate conversations)
        - In a thread (channels): use thread_ts (all messages share context)
        - In a channel (no thread): use channel_id + user_id

        Session IDs do NOT include a date suffix so that AgentCore Memory
        strategies can accumulate long-term insights across days within the
        same persistent session.  Short-term history windowing is controlled
        by max_turns, not by daily session rotation.

        AgentCore requires min 33 chars for runtimeSessionId and only allows
        [a-zA-Z0-9][a-zA-Z0-9-_]* — no dots or other special characters.

        SESSION_VERSION is bumped when container code changes require
        breaking session affinity (e.g. identity injection changes).
        """
        SESSION_VERSION = "v2"
        if self.is_dm:
            raw = f"plato-dm-{SESSION_VERSION}-{self.user_id}"
        elif self.thread_ts:
            raw = f"plato-thread-{self.thread_ts.replace('.', '-')}"
        else:
            raw = f"plato-chan-{self.channel_id}-{self.user_id}"
        # Pad to meet AgentCore 33-char minimum
        return raw.ljust(33, "-")

    @property
    def memory_actor_id(self) -> str:
        """Actor ID for memory storage — always the Slack user ID."""
        return self.user_id


@dataclass
class SlackResponse:
    """Response to send back to Slack."""

    text: str
    channel_id: str
    thread_ts: str | None = None
    blocks: list[dict[str, Any]] = field(default_factory=list)


class SlackEventHandler:
    """Handles incoming Slack events and routes to Plato agent.

    This handler is designed to be used inside a Lambda function.
    It verifies request signatures, parses events, invokes the agent,
    and posts responses back to Slack.
    """

    # Handler-level dedup: tracks event timestamps we've already processed.
    # This catches duplicates from SQS at-least-once delivery across
    # different Lambda invocations (module-level dedup only works within
    # the same warm Lambda instance).
    # Uses a class-level dict so it persists across handler instances
    # within the same Lambda container (warm starts).
    _processed_events: dict[str, float] = {}
    _DEDUP_TTL = 600  # 10 minutes

    def __init__(self, config: SlackConfig | None = None):
        self.config = config or SlackConfig.from_env()

    def _bot_already_replied(self, message: SlackMessage, exclude_ts: str | None = None) -> bool:
        """Check if the bot already replied to this message (cross-container dedup).

        Queries Slack's conversations.replies to see if the bot has already
        posted a response in the thread. This catches duplicate SQS deliveries
        that hit different Lambda containers (where the in-memory dedup dict
        doesn't help).

        Args:
            message: The inbound Slack message.
            exclude_ts: Timestamp of the thinking indicator to skip in the check.
                        Without this, the indicator itself would be detected as
                        an existing bot reply, causing the real invocation to be
                        skipped (the "flash and disappear" bug).

        Returns True if bot already replied (caller should skip).
        """
        if not self.config.bot_token:
            return False

        # Skip this check for DMs: conversations.replies in DMs returns
        # all recent channel messages (not thread-scoped), so any previous
        # bot reply to a *different* user message triggers a false positive.
        # DMs rely on FIFO dedup + handler-level dedup instead.
        if message.is_dm and not message.thread_ts:
            return False

        try:
            import urllib.request

            # For DMs without threads, check channel history
            # For threaded messages, check thread replies
            thread_ts = message.reply_ts  # thread_ts or message ts

            params = f"channel={message.channel_id}&ts={thread_ts}&limit=5"
            req = urllib.request.Request(
                f"https://slack.com/api/conversations.replies?{params}",
                headers={
                    "Authorization": f"Bearer {self.config.bot_token}",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not data.get("ok"):
                    return False

                messages = data.get("messages", [])
                bot_user_id = self.config.bot_user_id

                for msg in messages:
                    # Skip the original user message itself
                    if msg.get("ts") == message.ts:
                        continue
                    # Skip the thinking indicator we just posted
                    if exclude_ts and msg.get("ts") == exclude_ts:
                        continue
                    # Check if any reply is from our bot
                    if msg.get("bot_id") or (bot_user_id and msg.get("user") == bot_user_id):
                        logger.info(
                            "Found existing bot reply (ts=%s) for message %s",
                            msg.get("ts"), message.ts,
                        )
                        return True

            return False

        except Exception as e:
            logger.debug("Failed to check for existing bot reply: %s", e)
            return False  # On error, proceed (don't block legitimate requests)

    def verify_signature(
        self, body: str, timestamp: str, signature: str
    ) -> bool:
        """Verify Slack request signature (v0 scheme).

        Args:
            body: Raw request body string.
            timestamp: X-Slack-Request-Timestamp header.
            signature: X-Slack-Signature header.

        Returns:
            True if signature is valid.
        """
        if not self.config.signing_secret:
            logger.warning("No signing secret configured — skipping verification")
            return True

        # Reject requests older than 5 minutes (replay attack prevention)
        try:
            if abs(time.time() - float(timestamp)) > 300:
                logger.warning("Request timestamp too old: %s", timestamp)
                return False
        except (ValueError, TypeError):
            return False

        sig_basestring = f"v0:{timestamp}:{body}"
        expected = (
            "v0="
            + hmac.new(
                self.config.signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        )
        return hmac.compare_digest(expected, signature)

    def _resolve_user_name(self, user_id: str) -> str:
        """Resolve a Slack user ID to their display name.

        Tries multiple strategies in order:
        1. In-memory cache (warm Lambda invocations)
        2. Slack users.info API (requires users:read scope)
        3. Fallback: empty string (agent will use user ID)

        Returns the display name, real name, or empty string on failure.
        """
        if not hasattr(self, "_user_name_cache"):
            self._user_name_cache: dict[str, str] = {}

        if user_id in self._user_name_cache:
            return self._user_name_cache[user_id]

        if not self.config.bot_token:
            return ""

        # Strategy 1: Try users.info API (needs users:read scope)
        try:
            import urllib.request

            req = urllib.request.Request(
                f"https://slack.com/api/users.info?user={user_id}",
                headers={
                    "Authorization": f"Bearer {self.config.bot_token}",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok"):
                    profile = data.get("user", {}).get("profile", {})
                    name = (
                        profile.get("display_name")
                        or profile.get("real_name")
                        or data.get("user", {}).get("real_name", "")
                    )
                    if name:
                        self._user_name_cache[user_id] = name
                        logger.info("Resolved user %s → %s via users.info", user_id, name)
                        return name
                else:
                    error = data.get("error", "unknown")
                    logger.warning(
                        "users.info failed for %s: %s. "
                        "Add 'users:read' scope to the Slack app to enable user name resolution.",
                        user_id, error,
                    )
        except Exception:
            logger.debug("Failed to resolve user name for %s", user_id, exc_info=True)

        # Strategy 2: Try conversations.info for DM channels to get user name
        # (This doesn't work without users:read either, but leaving as placeholder)

        self._user_name_cache[user_id] = ""
        return ""

    def parse_event(self, body: dict[str, Any]) -> SlackMessage | None:
        """Parse a Slack event payload into a SlackMessage.

        Handles:
        - URL verification challenge (returns None, handled separately)
        - message events (channels + DMs)
        - app_mention events

        Returns:
            SlackMessage if actionable, None if should be skipped.
        """
        event = body.get("event", {})
        event_type = event.get("type", "")

        # Skip bot messages (avoid infinite loops)
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            logger.debug("Skipping bot message")
            return None

        # Skip message_changed, message_deleted, etc.
        if event.get("subtype"):
            logger.debug("Skipping subtype: %s", event.get("subtype"))
            return None

        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = event.get("text", "").strip()
        thread_ts = event.get("thread_ts")
        ts = event.get("ts", "")

        if not text or not user_id or not channel_id:
            return None

        # Determine if DM or mention
        channel_type = event.get("channel_type", "")
        is_dm = channel_type == "im"
        is_mention = event_type == "app_mention"

        # DM dedup: In DMs, Slack fires BOTH message.im AND app_mention events
        # for the same message (with different event_ids). Only process the
        # message event; skip app_mention in DMs to prevent double replies.
        if is_mention and channel_type == "im":
            logger.debug("Skipping app_mention in DM (message.im handles it)")
            return None

        # Strip bot mention from text for cleaner input
        if self.config.bot_user_id and not is_dm:
            text = text.replace(f"<@{self.config.bot_user_id}>", "").strip()

        # Only respond to DMs or explicit mentions in channels
        if not is_dm and not is_mention:
            logger.debug("Ignoring non-DM, non-mention message in channel")
            return None

        return SlackMessage(
            text=text,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            ts=ts,
            is_dm=is_dm,
            is_mention=is_mention,
            user_name=self._resolve_user_name(user_id),
        )

    def invoke_agent(self, message: SlackMessage, indicator_ts: str | None = None) -> str:
        """Invoke Plato agent with the user's message.

        Modes:
        - echo: Return the message back (testing)
        - agentcore: Call InvokeAgentRuntime API (production)
          In agentcore mode, tries WebSocket streaming first for real-time
          updates, falls back to HTTP if WebSocket is unavailable.

        Args:
            message: Parsed Slack message.
            indicator_ts: Timestamp of the "⏳ Processing..." indicator message.
                If provided and WebSocket streaming is available, will progressively
                update this message with streaming tokens.

        Returns:
            Agent response text.
        """
        mode = self.config.mode
        if mode == "echo":
            return self._invoke_echo(message)
        if mode == "agentcore":
            # Try WebSocket streaming first (progressive Slack updates)
            if indicator_ts:
                try:
                    return self._invoke_agentcore_ws(message, indicator_ts)
                except Exception as e:
                    logger.warning(
                        "WebSocket streaming failed, falling back to HTTP: %s", e
                    )
            # Fallback to HTTP (original behavior)
            return self._invoke_agentcore(message)
        # Default to echo for safety
        logger.warning("Unknown mode %r, falling back to echo", mode)
        return self._invoke_echo(message)

    def _invoke_echo(self, message: SlackMessage) -> str:
        """Echo mode — return the user's message back (for testing)."""
        return (
            f":wave: *Plato Agent* received your message!\n\n"
            f"> {message.text}\n\n"
            f"_I'm running in echo mode. Connect me to AgentCore to get "
            f"real responses._\n"
            f"_Mode: `echo` | Channel: `{message.channel_id}`_"
        )

    def _invoke_agentcore(self, message: SlackMessage) -> str:
        """Invoke agent via AgentCore InvokeAgentRuntime API.

        Memory is handled entirely by the AgentCore Runtime agent
        (plato-agentcore/main.py) which stores events and retrieves
        conversation history. The Slack handler just relays messages.

        No retry here — if the agent is busy (ConcurrencyException / 500),
        the Lambda fails and SQS handles retry with visibility timeout backoff.
        This avoids blocking the Lambda for 60s+ per retry attempt.

        NOTE: When identity_enabled=True and JWT Authorizer is configured,
        the boto3 SDK (SigV4) cannot be used. Use the HTTPS path with
        Bearer token instead.
        """
        # When identity is enabled, we must use HTTPS + Bearer token
        # because the JWT Authorizer rejects SigV4 requests
        if self.config.identity_enabled:
            return self._invoke_agentcore_https_oauth(message)

        try:
            import boto3

            client = boto3.client(
                "bedrock-agentcore",
                region_name=self.config.agentcore_region,
            )

            # Use memory-aware session ID (thread-based)
            # AgentCore requires min 33 chars for runtimeSessionId
            session_id = message.memory_session_id

            runtime_arn = self.config.agentcore_runtime_arn
            if not runtime_arn:
                logger.error("AGENTCORE_RUNTIME_ARN not configured")
                return "AgentCore runtime ARN not configured. Set AGENTCORE_RUNTIME_ARN."

            # Build the payload — keys must match entrypoint.py expectations
            payload = json.dumps({
                "prompt": message.text,
                "user_id": message.memory_actor_id,
                "user_name": message.user_name,
            }).encode()

            invoke_params = {
                "agentRuntimeArn": runtime_arn,
                "payload": payload,
                "qualifier": os.environ.get("AGENTCORE_ENDPOINT", "DEFAULT"),
                "runtimeSessionId": session_id,
            }

            # When Identity is enabled, pass runtimeUserId for per-user OAuth tokens
            if self.config.identity_enabled:
                invoke_params["runtimeUserId"] = message.user_id
                logger.info("Identity enabled: passing runtimeUserId=%s", message.user_id)

            response = client.invoke_agent_runtime(**invoke_params)

            # Read streaming response (SSE format from AgentCore)
            result_bytes = response.get("response", response.get("body", b""))
            if result_bytes is None:
                result_bytes = b""
            if hasattr(result_bytes, "read"):
                result_bytes = result_bytes.read()

            if isinstance(result_bytes, bytes):
                result_text = result_bytes.decode("utf-8")
            else:
                result_text = str(result_bytes)

            # Parse SSE response: extract content from response_delta events
            collected = []
            for line in result_text.split("\n"):
                line = line.strip()
                if line.startswith("data: "):
                    try:
                        event = json.loads(line[6:])
                        if event.get("type") == "response_delta" and "content" in event:
                            collected.append(event["content"])
                        elif event.get("type") == "auth_required" and "url" in event:
                            return f"🔐 I need access to your GitHub account. Please authorize here:\n{event['url']}\n\nAfter authorizing, send your message again."
                        elif event.get("type") == "error":
                            return f"Agent error: {event.get('message', 'Unknown error')}"
                    except json.JSONDecodeError:
                        continue

            if collected:
                return "".join(collected)

            # Fallback: try parsing as single JSON
            try:
                result = json.loads(result_text)
                if isinstance(result, dict):
                    if "result" in result:
                        content = result["result"]
                        if isinstance(content, dict):
                            return content.get("content", content.get("text", str(content)))
                        return str(content)
                    elif "error" in result:
                        return f"Agent error: {result['error']}"
                return result_text
            except (json.JSONDecodeError, ValueError):
                return result_text or "I received your message but couldn't generate a response."

        except Exception as e:
            error_name = type(e).__name__
            error_msg = str(e)
            logger.error("AgentCore invocation failed: %s: %s", error_name, error_msg)

            # ConcurrencyException: don't retry — the message is queued server-side
            if "ConcurrencyException" in error_msg or "is busy" in error_msg:
                logger.warning(
                    "Session busy in HTTP fallback — returning gracefully"
                )
                return None  # Caller will handle

            # For transient runtime errors (500, timeout),
            # raise to let Lambda fail → SQS will retry.
            is_transient = (
                "RuntimeClientError" in error_name
                or "500" in error_msg
            )
            if is_transient:
                logger.warning(
                    "Transient error, raising to let SQS retry: %s", error_name
                )
                raise

            # For non-transient errors (auth, validation, etc.), tell the user
            return f"Sorry, I encountered an error: {error_name}. Please try again."

    def _invoke_agentcore_https_oauth(self, message: SlackMessage) -> str:
        """Invoke agent via HTTPS with OAuth Bearer token.

        Used when JWT Authorizer is enabled on the Runtime (identity mode).
        The boto3 SDK uses SigV4 which is rejected by the JWT Authorizer,
        so we make a direct HTTPS POST with Bearer token instead.
        """
        import urllib.request
        import urllib.parse

        from platform_agent.slack.cognito_exchange import CognitoTokenExchange

        if not hasattr(self, "_token_exchange"):
            self._token_exchange = CognitoTokenExchange()

        # Use ID token (contains custom claims: custom:slack_id, custom:role,
        # email, cognito:username) instead of access token.
        bearer_token = self._token_exchange.get_id_token(message.user_id)
        if not bearer_token:
            return (
                "Authentication failed — your Slack account is not linked to "
                "a Plato identity. Please contact an administrator."
            )

        runtime_arn = self.config.agentcore_runtime_arn
        if not runtime_arn:
            return "AgentCore runtime ARN not configured."

        # Construct endpoint URL using the full ARN (URL-encoded)
        # API path: POST /runtimes/{agentRuntimeArn}/invocations
        from urllib.parse import quote
        arn_parts = runtime_arn.split(":")
        region = arn_parts[3]
        encoded_arn = quote(runtime_arn, safe="")
        endpoint_name = os.environ.get("AGENTCORE_ENDPOINT", "DEFAULT")

        url = (
            f"https://bedrock-agentcore.{region}.amazonaws.com"
            f"/runtimes/{encoded_arn}/invocations"
            f"?qualifier={endpoint_name}"
        )

        session_id = message.memory_session_id
        payload_data = json.dumps({
            "prompt": message.text,
            "user_id": message.memory_actor_id,
            "user_name": message.user_name,
        }).encode("utf-8")

        headers_dict = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        }

        try:
            req = urllib.request.Request(
                url, data=payload_data, headers=headers_dict, method="POST"
            )
            with urllib.request.urlopen(req, timeout=600) as resp:
                result_bytes = resp.read()
                result_text = result_bytes.decode("utf-8")

            # Parse SSE or JSON response
            try:
                result_json = json.loads(result_text)
                return result_json.get("result", result_text)
            except json.JSONDecodeError:
                return result_text

        except Exception as e:
            logger.error("HTTPS OAuth invoke failed: %s", e)
            return f"Sorry, I encountered an error: {e}"

    def _invoke_agentcore_ws(self, message: SlackMessage, indicator_ts: str) -> str:
        """Invoke agent via AgentCore WebSocket for streaming responses.

        Connects to AgentCore Runtime's WebSocket endpoint, sends the prompt,
        and progressively updates the Slack "thinking" indicator with streaming
        tokens. Provides a ChatGPT-like typing experience.

        Args:
            message: Parsed Slack message.
            indicator_ts: Timestamp of the "⏳ Processing..." indicator to update.

        Returns:
            Full agent response text.

        Raises:
            Exception: On connection failure (caller falls back to HTTP).
        """
        import asyncio

        # Bridge sync Lambda → async WebSocket
        # Lambda doesn't have a running event loop, so asyncio.run() is safe.
        return asyncio.run(self._invoke_agentcore_ws_async(message, indicator_ts))

    async def _invoke_agentcore_ws_async(self, message: SlackMessage, indicator_ts: str) -> str:
        """Async implementation of WebSocket streaming invoke.

        Protocol:
            Send:    {"prompt": "...", "user_id": "...", "user_name": "...", "session_id": "..."}
            Receive: {"type": "delta", "content": "token"}      (streaming text)
                     {"type": "tool_start", "name": "..."}      (tool invocation)
                     {"type": "complete", "content": "full"}     (done)
                     {"type": "error", "message": "..."}         (failure)
        """
        import asyncio
        import websockets

        runtime_arn = self.config.agentcore_runtime_arn
        if not runtime_arn:
            raise ValueError("AGENTCORE_RUNTIME_ARN not configured")

        session_id = message.memory_session_id

        # Generate WebSocket connection — SigV4 or OAuth depending on config
        from bedrock_agentcore.runtime import AgentCoreRuntimeClient

        ac_client = AgentCoreRuntimeClient(region=self.config.agentcore_region)

        if self.config.identity_enabled:
            # OAuth path: exchange Slack user ID for Cognito JWT
            from platform_agent.slack.cognito_exchange import CognitoTokenExchange

            if not hasattr(self, "_token_exchange"):
                self._token_exchange = CognitoTokenExchange()

            bearer_token = self._token_exchange.get_id_token(message.user_id)
            if not bearer_token:
                logger.error(
                    "Failed to get ID token for Slack user %s — "
                    "user may not be registered in Cognito",
                    message.user_id,
                )
                raise ValueError(
                    f"Authentication failed for user {message.user_id}. "
                    "Please contact an administrator to set up your account."
                )

            ws_url, headers = ac_client.generate_ws_connection_oauth(
                runtime_arn=runtime_arn,
                bearer_token=bearer_token,
                session_id=session_id,
                endpoint_name=os.environ.get("AGENTCORE_ENDPOINT", "DEFAULT"),
            )
            logger.info(
                "OAuth WebSocket connecting to AgentCore (session=%s, user=%s)",
                session_id, message.user_id,
            )
        else:
            # SigV4 path (legacy / non-identity mode)
            ws_url, headers = ac_client.generate_ws_connection(
                runtime_arn=runtime_arn,
                session_id=session_id,
                endpoint_name=os.environ.get("AGENTCORE_ENDPOINT", "DEFAULT"),
            )
            logger.info("SigV4 WebSocket connecting to AgentCore (session=%s)", session_id)

        # Streaming state
        collected_tokens: list[str] = []
        last_update_time = time.time()
        last_update_len = 0
        active_tool: str | None = None

        # Rate-limiting constants for chat.update
        UPDATE_INTERVAL_S = 3.0     # Max frequency: every 3 seconds
        MIN_CHARS_DELTA = 200       # Or every 200 new characters
        HEARTBEAT_INTERVAL_S = 8.0  # Update indicator every 8s during tool use

        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            close_timeout=10,
            open_timeout=30,
        ) as ws:
            # Send prompt
            await ws.send(json.dumps({
                "prompt": message.text,
                "user_id": message.memory_actor_id,
                "user_name": message.user_name,
                "user_role": self._token_exchange.get_user_role(message.user_id) if self.config.identity_enabled else "",
                "session_id": session_id,
            }))

            logger.info("WebSocket prompt sent, waiting for streaming response...")

            # Update indicator to show agent is thinking
            self._update_message(
                message.channel_id, indicator_ts, "🤔 _Thinking..._"
            )

            # Heartbeat: periodically update indicator during long tool operations
            # so the user knows the agent is still working
            tool_start_time: float | None = None
            heartbeat_dots = 0

            while True:
                # Use short timeout so we can send heartbeats during tool execution
                # (when the server sends no WS messages for a long time)
                try:
                    raw_msg = await asyncio.wait_for(ws.recv(), timeout=HEARTBEAT_INTERVAL_S)
                except asyncio.TimeoutError:
                    # No message received — send heartbeat if tool is active
                    if active_tool and tool_start_time:
                        elapsed = time.time() - tool_start_time
                        heartbeat_dots = (heartbeat_dots % 3) + 1
                        dots = "." * heartbeat_dots
                        elapsed_str = f"{int(elapsed)}s"
                        current_text = "".join(collected_tokens) if collected_tokens else ""
                        display = f"🔧 _Using {active_tool}{dots}_ ({elapsed_str})"
                        if current_text:
                            display = f"{current_text}\n\n{display}"
                        self._update_message(
                            message.channel_id, indicator_ts, display
                        )
                        last_update_time = time.time()
                    continue
                except websockets.exceptions.ConnectionClosed:
                    break

                try:
                    event = json.loads(raw_msg)
                except (json.JSONDecodeError, TypeError):
                    continue

                event_type = event.get("type", "")

                if event_type == "delta":
                    token = event.get("content", "")
                    if token:
                        # When resuming text after a tool call, insert a
                        # separator so the two model turns don't run together.
                        if active_tool and collected_tokens:
                            collected_tokens.append("\n\n")
                        collected_tokens.append(token)
                        current_text = "".join(collected_tokens)
                        # Clear tool state — text is now streaming
                        active_tool = None
                        tool_start_time = None

                        # Progressive update: throttled to avoid Slack rate limits
                        now = time.time()
                        chars_since_update = len(current_text) - last_update_len
                        time_since_update = now - last_update_time

                        if (time_since_update >= UPDATE_INTERVAL_S
                                or chars_since_update >= MIN_CHARS_DELTA):
                            # Show cursor "▌" to indicate still typing
                            display_text = current_text + " ▌"
                            if active_tool:
                                display_text = f"🔧 _{active_tool}_\n\n{display_text}"
                            # Truncate progressive updates to avoid msg_too_long
                            # (full text is sent via _build_response at the end)
                            if len(display_text) > self.SLACK_MAX_TEXT_LENGTH:
                                truncated = display_text[
                                    -(self.SLACK_MAX_TEXT_LENGTH - 100):
                                ]
                                display_text = (
                                    "_(response truncated, full text at end)_\n\n"
                                    + truncated
                                )
                            self._update_message(
                                message.channel_id, indicator_ts, display_text
                            )
                            last_update_time = now
                            last_update_len = len(current_text)

                elif event_type == "tool_start":
                    tool_name = event.get("name", "unknown")
                    active_tool = tool_name
                    tool_start_time = time.time()
                    heartbeat_dots = 0
                    # Show tool usage in the indicator
                    current_text = "".join(collected_tokens) if collected_tokens else ""
                    display_text = f"🔧 _Using {tool_name}..._"
                    if current_text:
                        display_text = f"{current_text}\n\n{display_text}"
                    self._update_message(
                        message.channel_id, indicator_ts, display_text
                    )
                    last_update_time = time.time()

                elif event_type == "complete":
                    # When the model uses tools mid-response, Strands'
                    # result only contains the LAST assistant turn's text.
                    # The streamed tokens, however, include ALL text from
                    # every model turn (pre-tool + post-tool).  Prefer
                    # the streamed text when it's longer — it has the
                    # complete multi-turn output.
                    complete_text = event.get("content", "")
                    streamed_text = "".join(collected_tokens)
                    if len(streamed_text) >= len(complete_text):
                        final_text = streamed_text
                    else:
                        final_text = complete_text
                    logger.info(
                        "WebSocket streaming complete: %d chars "
                        "(streamed=%d, complete=%d)",
                        len(final_text),
                        len(streamed_text),
                        len(complete_text),
                    )
                    return final_text

                elif event_type == "error":
                    error_msg = event.get("message", "Unknown agent error")
                    logger.error("WebSocket agent error: %s", error_msg)
                    raise RuntimeError(f"Agent error: {error_msg}")

        # If we exit the loop without a "complete" event, assemble from tokens
        final_text = "".join(collected_tokens)
        if final_text:
            return final_text
        raise RuntimeError("WebSocket closed without response")

    def post_response(self, response: SlackResponse) -> dict[str, Any]:
        """Post a response back to Slack via Web API.

        Args:
            response: SlackResponse with text and channel info.

        Returns:
            Slack API response dict.
        """
        try:
            import urllib.request

            payload = {
                "channel": response.channel_id,
                "text": response.text,
                "unfurl_links": False,
                "unfurl_media": False,
            }
            if response.thread_ts:
                payload["thread_ts"] = response.thread_ts
            if response.blocks:
                payload["blocks"] = response.blocks

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://slack.com/api/chat.postMessage",
                data=data,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": f"Bearer {self.config.bot_token}",
                },
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if not result.get("ok"):
                    logger.error("Slack API error: %s", result.get("error"))
                return result

        except Exception as e:
            logger.error("Failed to post to Slack: %s", e)
            return {"ok": False, "error": str(e)}

    # Slack's max text length for chat.update / chat.postMessage
    SLACK_MAX_TEXT_LENGTH = 39_000  # 40k limit, leave margin for formatting

    def _update_message(self, channel_id: str, message_ts: str, text: str,
                        blocks: list[dict[str, Any]] | None = None,
                        thread_ts: str | None = None) -> dict[str, Any]:
        """Update an existing Slack message via chat.update.

        Used to replace the "⏳ Processing..." indicator with the real response.
        If the text exceeds Slack's 40k character limit, the first chunk updates
        the indicator and remaining chunks are posted as follow-up messages
        in the same thread.

        Args:
            channel_id: Channel containing the message.
            message_ts: Timestamp of the message to update.
            text: New text content.
            blocks: Optional Block Kit blocks.
            thread_ts: Thread timestamp for follow-up messages (if splitting).

        Returns:
            Slack API response dict.
        """
        if len(text) > self.SLACK_MAX_TEXT_LENGTH:
            return self._update_message_chunked(
                channel_id, message_ts, text, thread_ts=thread_ts
            )

        try:
            import urllib.request

            payload: dict[str, Any] = {
                "channel": channel_id,
                "ts": message_ts,
                "text": text,
                "unfurl_links": False,
                "unfurl_media": False,
            }
            if blocks:
                payload["blocks"] = blocks

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://slack.com/api/chat.update",
                data=data,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": f"Bearer {self.config.bot_token}",
                },
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if not result.get("ok"):
                    logger.error("Slack chat.update error: %s", result.get("error"))
                return result

        except Exception as e:
            logger.error("Failed to update Slack message: %s", e)
            return {"ok": False, "error": str(e)}

    def _update_message_chunked(
        self,
        channel_id: str,
        message_ts: str,
        text: str,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Handle messages that exceed Slack's 40k character limit.

        Splits the text at paragraph boundaries, updates the indicator with
        the first chunk, and posts remaining chunks as follow-up thread messages.

        Args:
            channel_id: Channel containing the message.
            message_ts: Timestamp of the indicator to update.
            text: Full text (>40k chars).
            thread_ts: Thread timestamp. Falls back to message_ts.

        Returns:
            Slack API response from the first update.
        """
        import urllib.request

        max_len = self.SLACK_MAX_TEXT_LENGTH
        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= max_len:
                chunks.append(remaining)
                break

            # Try to split at a double newline (paragraph boundary)
            split_pos = remaining.rfind("\n\n", 0, max_len)
            if split_pos < max_len // 2:
                # No good paragraph break — try single newline
                split_pos = remaining.rfind("\n", 0, max_len)
            if split_pos < max_len // 2:
                # No good line break — hard split
                split_pos = max_len

            chunks.append(remaining[:split_pos])
            remaining = remaining[split_pos:].lstrip("\n")

        logger.info(
            "Message too long (%d chars), splitting into %d chunks",
            len(text), len(chunks),
        )

        # Update indicator with first chunk
        first_result = self._update_message(
            channel_id, message_ts, chunks[0]
        )

        # Post remaining chunks as follow-up messages in the thread
        reply_thread_ts = thread_ts or message_ts
        for i, chunk in enumerate(chunks[1:], start=2):
            chunk_header = f"_(continued {i}/{len(chunks)})_\n\n{chunk}"
            try:
                payload = json.dumps({
                    "channel": channel_id,
                    "thread_ts": reply_thread_ts,
                    "text": chunk_header,
                    "unfurl_links": False,
                    "unfurl_media": False,
                }).encode("utf-8")

                req = urllib.request.Request(
                    "https://slack.com/api/chat.postMessage",
                    data=payload,
                    headers={
                        "Content-Type": "application/json; charset=utf-8",
                        "Authorization": f"Bearer {self.config.bot_token}",
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    if not result.get("ok"):
                        logger.error(
                            "Slack chat.postMessage error (chunk %d): %s",
                            i, result.get("error"),
                        )
            except Exception as e:
                logger.error("Failed to post chunk %d: %s", i, e)

        return first_result

    def _delete_message(self, channel_id: str, message_ts: str) -> dict[str, Any]:
        """Delete a Slack message via chat.delete.

        Used to clean up the "⏳ Processing..." indicator on transient errors
        (before SQS retry posts a new one).

        Args:
            channel_id: Channel containing the message.
            message_ts: Timestamp of the message to delete.

        Returns:
            Slack API response dict.
        """
        try:
            import urllib.request

            payload = {
                "channel": channel_id,
                "ts": message_ts,
            }

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://slack.com/api/chat.delete",
                data=data,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": f"Bearer {self.config.bot_token}",
                },
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if not result.get("ok"):
                    logger.error("Slack chat.delete error: %s", result.get("error"))
                return result

        except Exception as e:
            logger.error("Failed to delete Slack message: %s", e)
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _markdown_to_slack_mrkdwn(text: str) -> str:
        """Convert standard Markdown to Slack mrkdwn format.

        Key differences:
        - **bold** → *bold*  (Slack uses single asterisks)
        - [text](url) → <url|text>
        - ### heading → *heading* (bold, Slack has no headings)
        - Preserve code blocks and inline code (same syntax)
        """
        import re

        # Protect code blocks from transformation
        code_blocks: list[str] = []

        def _save_code_block(match: re.Match) -> str:
            code_blocks.append(match.group(0))
            return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

        # Save fenced code blocks (```...```)
        text = re.sub(r'```[\s\S]*?```', _save_code_block, text)

        # Save inline code (`...`)
        text = re.sub(r'`[^`]+`', _save_code_block, text)

        # Convert **bold** → *bold* (Slack mrkdwn)
        # Must handle **text** but not touch *text* (already Slack-compatible)
        text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

        # Convert [text](url) → <url|text>
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<\2|\1>', text)

        # Convert headings: ### text → *text*
        text = re.sub(r'^#{1,6}\s+(.+)$', r'*\1*', text, flags=re.MULTILINE)

        # Restore code blocks
        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

        return text

    def _build_response(self, text: str, message: SlackMessage) -> SlackResponse:
        """Build a SlackResponse, converting OAuth auth URLs to Slack buttons.

        Also converts standard Markdown to Slack mrkdwn format.

        Slack buttons open URLs directly in the browser without any server-side
        pre-fetching, which preserves the single-use request_uri tokens used by
        AgentCore Identity OAuth.
        """
        import re

        # Convert Markdown → Slack mrkdwn (before any other processing)
        text = self._markdown_to_slack_mrkdwn(text)

        auth_url_pattern = re.compile(
            r'(https://bedrock-agentcore\.[^/]+/identities/oauth2/authorize\?request_uri=\S+)'
        )
        match = auth_url_pattern.search(text)

        if not match:
            return SlackResponse(
                text=text,
                channel_id=message.channel_id,
                thread_ts=message.reply_ts,
            )

        auth_url = match.group(1).rstrip('.')
        # Build Block Kit with a button instead of a plain URL
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":closed_lock_with_key: I need access to your GitHub account to proceed."
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": ":link: Connect GitHub Account",
                            "emoji": True
                        },
                        "url": auth_url,
                        "action_id": "github_oauth_authorize",
                        "style": "primary"
                    }
                ]
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "Click the button above → authorize on GitHub → then send your message again."
                    }
                ]
            }
        ]

        return SlackResponse(
            text="🔐 I need access to your GitHub account. Click the button to authorize.",
            channel_id=message.channel_id,
            thread_ts=message.reply_ts,
            blocks=blocks,
        )

    def handle(self, body: dict[str, Any]) -> dict[str, Any]:
        """Main entry point: handle a Slack event.

        Handles URL verification, parses the event, invokes the agent,
        and posts the response. Uses a "thinking indicator" pattern:
        1. Post "⏳ Processing..." immediately (user sees instant feedback)
        2. Invoke the agent (may take 10-60s)
        3. Update the message with the real response (chat.update)

        On transient errors, deletes the indicator so SQS retry starts clean.

        Args:
            body: Parsed JSON body from Slack.

        Returns:
            HTTP response dict with statusCode and body.
        """
        # URL verification challenge
        if body.get("type") == "url_verification":
            return {
                "statusCode": 200,
                "body": json.dumps({"challenge": body.get("challenge", "")}),
            }

        # Parse event
        message = self.parse_event(body)
        if message is None:
            return {"statusCode": 200, "body": "ok"}

        # Handler-level dedup: prevent double replies from SQS at-least-once
        # delivery or Slack retries. Uses the message timestamp (unique per
        # Slack message) as the dedup key.
        dedup_key = f"{message.channel_id}-{message.ts}"
        now = time.time()
        # Clean expired entries
        expired = [k for k, v in self._processed_events.items() if now - v > self._DEDUP_TTL]
        for k in expired:
            del self._processed_events[k]
        # Check if already processed
        if dedup_key in self._processed_events:
            logger.info("Handler dedup: skipping already-processed event %s", dedup_key)
            return {"statusCode": 200, "body": "ok"}
        # Mark as processing BEFORE doing any work (prevents race between
        # concurrent SQS deliveries hitting different Lambda instances —
        # though class-level dict only helps within same container).
        # Note: _processed_events is a class-level dict intentionally —
        # Lambda reuses the same module across warm invocations, so class-level
        # state persists. This is the fast first-layer dedup.
        self._processed_events[dedup_key] = now

        # Post thinking indicator FIRST — give user instant feedback.
        # Cross-container dedup check comes AFTER because conversations.replies
        # adds ~50-100ms latency. Better to show "⏳" fast and dedup later.
        indicator_ts = None
        try:
            indicator_result = self.post_response(SlackResponse(
                text="⏳ Processing your request...",
                channel_id=message.channel_id,
                thread_ts=message.reply_ts,
            ))
            if indicator_result.get("ok"):
                indicator_ts = indicator_result.get("ts")
                logger.info("Posted thinking indicator: %s", indicator_ts)
        except Exception as e:
            # Non-fatal: if indicator fails, continue without it
            logger.warning("Failed to post thinking indicator: %s", e)

        # Cross-container dedup: DISABLED.
        # conversations.replies cannot distinguish "bot replied to THIS message"
        # from "bot replied to ANY message in this thread/channel", causing
        # false positives on consecutive messages in threads and DMs.
        # Dedup is now handled by:
        #   1. SQS FIFO content-based deduplication (exactly-once delivery)
        #   2. Handler-level in-memory dedup (_processed_events dict)
        # These two layers are sufficient for production use.

        # Invoke agent (passes indicator_ts for WebSocket streaming updates)
        try:
            agent_response = self.invoke_agent(message, indicator_ts=indicator_ts)
        except Exception as e:
            error_name = type(e).__name__
            error_msg = str(e)
            logger.error("Agent invocation failed: %s: %s", error_name, error_msg)

            # ConcurrencyException: session is busy processing a previous request.
            # Don't delete the indicator — tell the user what's happening.
            # Don't raise (no SQS retry) — the previous request will complete
            # and the user's message was already saved for pickup.
            if "ConcurrencyException" in error_msg or "is busy" in error_msg:
                logger.warning("Session busy — user's message queued for pickup")
                if indicator_ts:
                    self._update_message(
                        message.channel_id, indicator_ts,
                        "⏳ _Plato is still working on a previous request. "
                        "Your message has been queued and will be processed next._"
                    )
                return {"statusCode": 200, "body": "ok"}

            # Other transient errors: clean up indicator, then let Lambda fail → SQS retry
            is_transient = (
                "RuntimeClientError" in error_name
                or "500" in error_msg
            )
            if is_transient:
                if indicator_ts:
                    self._delete_message(message.channel_id, indicator_ts)
                raise  # Lambda fails → SQS redelivers → clean retry

            # Non-transient: update indicator with error message
            agent_response = "Sorry, I encountered an error processing your request."

        # Build response (handles OAuth URL → Slack button conversion)
        slack_response = self._build_response(agent_response, message)

        # If we have a thinking indicator, update it with the real response.
        # Otherwise, post a new message (fallback).
        if indicator_ts:
            self._update_message(
                channel_id=message.channel_id,
                message_ts=indicator_ts,
                text=slack_response.text,
                blocks=slack_response.blocks if slack_response.blocks else None,
                thread_ts=message.reply_ts,
            )
        else:
            self.post_response(slack_response)

        return {"statusCode": 200, "body": "ok"}
