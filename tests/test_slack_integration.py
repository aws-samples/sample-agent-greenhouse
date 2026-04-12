"""Tests for Slack integration handler."""

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from platform_agent.slack.handler import (
    SlackConfig,
    SlackEventHandler,
    SlackMessage,
    SlackResponse,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def config():
    return SlackConfig(
        bot_token="xoxb-test-token",
        signing_secret="test-secret-12345",
        app_id="A12345",
        bot_user_id="U_PLATO_BOT",
    )


@pytest.fixture
def handler(config):
    return SlackEventHandler(config)


def _make_signature(secret: str, body: str, timestamp: str) -> str:
    """Helper to create a valid Slack signature."""
    sig_basestring = f"v0:{timestamp}:{body}"
    return "v0=" + hmac.new(
        secret.encode("utf-8"),
        sig_basestring.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# SlackConfig tests
# ---------------------------------------------------------------------------

class TestSlackConfig:
    def test_from_env_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            config = SlackConfig.from_env()
            assert config.bot_token == ""
            assert config.signing_secret == ""
            assert config.identity_enabled is False
            assert config.mode == "echo"

    def test_from_env_populated(self):
        env = {
            "SLACK_BOT_TOKEN": "xoxb-123",
            "SLACK_SIGNING_SECRET": "secret",
            "SLACK_APP_ID": "A999",
            "AGENTCORE_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-west-2:123456789:runtime/plato_agent-abc123",
            "AGENTCORE_RUNTIME_ENDPOINT": "https://runtime.example.com",
            "AGENTCORE_AGENT_ID": "agent-abc",
            "PLATO_SLACK_MODE": "agentcore",
        }
        with patch.dict("os.environ", env, clear=True):
            config = SlackConfig.from_env()
            assert config.bot_token == "xoxb-123"
            assert config.signing_secret == "secret"
            assert config.identity_enabled is False
            assert config.mode == "agentcore"
            assert config.agentcore_agent_id == "agent-abc"

    def test_identity_enabled_toggle(self):
        """PLATO_IDENTITY_ENABLED=true enables per-user Identity OAuth."""
        with patch.dict("os.environ", {"PLATO_IDENTITY_ENABLED": "true"}, clear=True):
            config = SlackConfig.from_env()
            assert config.identity_enabled is True

        with patch.dict("os.environ", {"PLATO_IDENTITY_ENABLED": "false"}, clear=True):
            config = SlackConfig.from_env()
            assert config.identity_enabled is False

        with patch.dict("os.environ", {"PLATO_IDENTITY_ENABLED": "True"}, clear=True):
            config = SlackConfig.from_env()
            assert config.identity_enabled is True

        # Default (not set) should be False
        with patch.dict("os.environ", {}, clear=True):
            config = SlackConfig.from_env()
            assert config.identity_enabled is False


# ---------------------------------------------------------------------------
# Signature verification tests
# ---------------------------------------------------------------------------

class TestSignatureVerification:
    def test_valid_signature(self, handler):
        body = '{"type":"event_callback"}'
        ts = str(int(time.time()))
        sig = _make_signature("test-secret-12345", body, ts)
        assert handler.verify_signature(body, ts, sig) is True

    def test_invalid_signature(self, handler):
        body = '{"type":"event_callback"}'
        ts = str(int(time.time()))
        assert handler.verify_signature(body, ts, "v0=bad") is False

    def test_old_timestamp_rejected(self, handler):
        body = '{"type":"event_callback"}'
        ts = str(int(time.time()) - 600)  # 10 minutes old
        sig = _make_signature("test-secret-12345", body, ts)
        assert handler.verify_signature(body, ts, sig) is False

    def test_no_signing_secret_allows_all(self, config):
        config.signing_secret = ""
        h = SlackEventHandler(config)
        assert h.verify_signature("body", "123", "any") is True

    def test_invalid_timestamp_format(self, handler):
        assert handler.verify_signature("body", "not-a-number", "v0=x") is False


# ---------------------------------------------------------------------------
# Event parsing tests
# ---------------------------------------------------------------------------

class TestEventParsing:
    def test_parse_dm_message(self, handler):
        body = {
            "event": {
                "type": "message",
                "user": "U_USER",
                "channel": "D_DM_CHANNEL",
                "channel_type": "im",
                "text": "help me deploy my agent",
                "ts": "1234567890.123456",
            }
        }
        msg = handler.parse_event(body)
        assert msg is not None
        assert msg.text == "help me deploy my agent"
        assert msg.is_dm is True
        assert msg.is_mention is False
        assert msg.user_id == "U_USER"
        assert msg.channel_id == "D_DM_CHANNEL"

    def test_parse_app_mention(self, handler):
        body = {
            "event": {
                "type": "app_mention",
                "user": "U_USER",
                "channel": "C_CHANNEL",
                "text": "<@U_PLATO_BOT> scaffold a RAG agent",
                "ts": "1234567890.123456",
            }
        }
        msg = handler.parse_event(body)
        assert msg is not None
        assert msg.text == "scaffold a RAG agent"  # Bot mention stripped
        assert msg.is_mention is True
        assert msg.is_dm is False

    def test_parse_threaded_message(self, handler):
        body = {
            "event": {
                "type": "app_mention",
                "user": "U_USER",
                "channel": "C_CHANNEL",
                "text": "<@U_PLATO_BOT> check readiness",
                "ts": "1234567890.999999",
                "thread_ts": "1234567890.000001",
            }
        }
        msg = handler.parse_event(body)
        assert msg is not None
        assert msg.thread_ts == "1234567890.000001"
        assert msg.reply_ts == "1234567890.000001"

    def test_non_threaded_reply_ts(self, handler):
        body = {
            "event": {
                "type": "message",
                "user": "U_USER",
                "channel": "D_DM",
                "channel_type": "im",
                "text": "hello",
                "ts": "1234567890.123456",
            }
        }
        msg = handler.parse_event(body)
        assert msg.reply_ts == "1234567890.123456"

    def test_skip_bot_messages(self, handler):
        body = {
            "event": {
                "type": "message",
                "bot_id": "B_OTHER_BOT",
                "channel": "C_CHANNEL",
                "text": "I am a bot",
                "ts": "1234567890.123456",
            }
        }
        assert handler.parse_event(body) is None

    def test_skip_bot_subtype(self, handler):
        body = {
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "user": "U_BOT",
                "channel": "C_CHANNEL",
                "text": "automated message",
                "ts": "1234567890.123456",
            }
        }
        assert handler.parse_event(body) is None

    def test_skip_message_changed(self, handler):
        body = {
            "event": {
                "type": "message",
                "subtype": "message_changed",
                "user": "U_USER",
                "channel": "C_CHANNEL",
                "text": "edited",
                "ts": "1234567890.123456",
            }
        }
        assert handler.parse_event(body) is None

    def test_skip_non_mention_channel_message(self, handler):
        """Regular channel messages without mention should be ignored."""
        body = {
            "event": {
                "type": "message",
                "user": "U_USER",
                "channel": "C_CHANNEL",
                "channel_type": "channel",
                "text": "just chatting among ourselves",
                "ts": "1234567890.123456",
            }
        }
        assert handler.parse_event(body) is None

    def test_skip_empty_text(self, handler):
        body = {
            "event": {
                "type": "message",
                "user": "U_USER",
                "channel": "D_DM",
                "channel_type": "im",
                "text": "",
                "ts": "1234567890.123456",
            }
        }
        assert handler.parse_event(body) is None

    def test_skip_missing_user(self, handler):
        body = {
            "event": {
                "type": "message",
                "channel": "D_DM",
                "channel_type": "im",
                "text": "hello",
                "ts": "1234567890.123456",
            }
        }
        assert handler.parse_event(body) is None


# ---------------------------------------------------------------------------
# URL verification tests
# ---------------------------------------------------------------------------

class TestURLVerification:
    def test_challenge_response(self, handler):
        body = {
            "type": "url_verification",
            "challenge": "test_challenge_token_abc123",
        }
        result = handler.handle(body)
        assert result["statusCode"] == 200
        response_body = json.loads(result["body"])
        assert response_body["challenge"] == "test_challenge_token_abc123"


# ---------------------------------------------------------------------------
# Agent invocation tests
# ---------------------------------------------------------------------------

class TestAgentInvocation:
    def test_echo_mode(self, handler):
        """Echo mode returns the message back."""
        msg = SlackMessage(
            text="hello world",
            user_id="U_USER",
            channel_id="D_DM",
            is_dm=True,
        )
        response = handler.invoke_agent(msg)
        assert "hello world" in response
        assert "echo mode" in response

    @patch("boto3.client")
    def test_agentcore_mode_invocation(self, mock_boto3, config):
        config.mode = "agentcore"
        config.agentcore_runtime_arn = "arn:aws:bedrock-agentcore:us-west-2:123456789:runtime/plato_agent-abc123"
        h = SlackEventHandler(config)

        mock_client = MagicMock()
        mock_boto3.return_value = mock_client

        # AgentCore returns a response body with the agent's text
        mock_response_body = MagicMock()
        mock_response_body.read.return_value = b"Here's your scaffold output."
        mock_client.invoke_agent_runtime.return_value = {
            "body": mock_response_body,
        }

        msg = SlackMessage(
            text="scaffold",
            user_id="U_USER",
            channel_id="C_CHAN",
        )
        response = h.invoke_agent(msg)
        assert "scaffold" in response.lower()
        mock_client.invoke_agent_runtime.assert_called_once()

    @patch("boto3.client")
    def test_agentcore_error_handling(self, mock_boto3, config):
        config.mode = "agentcore"
        config.agentcore_runtime_arn = "arn:aws:bedrock-agentcore:us-west-2:123456789:runtime/plato_agent-abc123"
        h = SlackEventHandler(config)

        mock_client = MagicMock()
        mock_boto3.return_value = mock_client
        mock_client.invoke_agent_runtime.side_effect = RuntimeError("Connection failed")

        msg = SlackMessage(text="help", user_id="U_USER", channel_id="C_CHAN")
        response = h.invoke_agent(msg)
        assert "error" in response.lower()


# ---------------------------------------------------------------------------
# Slack response posting tests
# ---------------------------------------------------------------------------

class TestPostResponse:
    @patch("urllib.request.urlopen")
    def test_post_message(self, mock_urlopen, handler):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true, "ts": "123"}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        response = SlackResponse(
            text="Here's your agent scaffold.",
            channel_id="C_CHANNEL",
            thread_ts="123.456",
        )
        result = handler.post_response(response)
        assert result["ok"] is True

        # Verify the request
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "https://slack.com/api/chat.postMessage"
        assert "Bearer xoxb-test-token" in req.headers["Authorization"]
        payload = json.loads(req.data.decode())
        assert payload["channel"] == "C_CHANNEL"
        assert payload["thread_ts"] == "123.456"
        assert payload["text"] == "Here's your agent scaffold."

    @patch("urllib.request.urlopen")
    def test_post_without_thread(self, mock_urlopen, handler):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        response = SlackResponse(text="Hello!", channel_id="D_DM")
        handler.post_response(response)

        payload = json.loads(mock_urlopen.call_args[0][0].data.decode())
        assert "thread_ts" not in payload

    @patch("urllib.request.urlopen")
    def test_post_failure_handling(self, mock_urlopen, handler):
        mock_urlopen.side_effect = ConnectionError("Network error")
        response = SlackResponse(text="test", channel_id="C_CHAN")
        result = handler.post_response(response)
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# End-to-end handle() tests
# ---------------------------------------------------------------------------

class TestHandle:
    @patch.object(SlackEventHandler, "post_response")
    @patch.object(SlackEventHandler, "invoke_agent", return_value="Done!")
    def test_full_dm_flow(self, mock_invoke, mock_post, handler):
        body = {
            "event": {
                "type": "message",
                "user": "U_USER",
                "channel": "D_DM",
                "channel_type": "im",
                "text": "scaffold a support agent",
                "ts": "1234567890.123456",
            }
        }
        result = handler.handle(body)
        assert result["statusCode"] == 200
        mock_invoke.assert_called_once()
        mock_post.assert_called_once()

        # Verify response was posted to correct channel
        posted = mock_post.call_args[0][0]
        assert posted.channel_id == "D_DM"
        assert posted.text == "Done!"
        assert posted.thread_ts == "1234567890.123456"

    @patch.object(SlackEventHandler, "post_response")
    @patch.object(SlackEventHandler, "invoke_agent", return_value="Here you go!")
    def test_full_mention_flow(self, mock_invoke, mock_post, handler):
        body = {
            "event": {
                "type": "app_mention",
                "user": "U_USER",
                "channel": "C_CHANNEL",
                "text": "<@U_PLATO_BOT> check my agent readiness",
                "ts": "1234567890.123456",
                "thread_ts": "1234567890.000001",
            }
        }
        result = handler.handle(body)
        assert result["statusCode"] == 200
        mock_invoke.assert_called_once()

        # Should reply in thread
        posted = mock_post.call_args[0][0]
        assert posted.thread_ts == "1234567890.000001"

    @patch.object(SlackEventHandler, "post_response")
    def test_bot_message_ignored(self, mock_post, handler):
        body = {
            "event": {
                "type": "message",
                "bot_id": "B_BOT",
                "channel": "C_CHANNEL",
                "text": "automated",
                "ts": "123.456",
            }
        }
        result = handler.handle(body)
        assert result["statusCode"] == 200
        mock_post.assert_not_called()

    @patch.object(SlackEventHandler, "post_response")
    @patch.object(SlackEventHandler, "invoke_agent", side_effect=Exception("boom"))
    def test_agent_error_posts_error_message(self, mock_invoke, mock_post, handler):
        body = {
            "event": {
                "type": "message",
                "user": "U_USER",
                "channel": "D_DM",
                "channel_type": "im",
                "text": "do something",
                "ts": "123.456",
            }
        }
        result = handler.handle(body)
        assert result["statusCode"] == 200
        mock_post.assert_called_once()
        posted = mock_post.call_args[0][0]
        assert "error" in posted.text.lower()


# ---------------------------------------------------------------------------
# Lambda handler tests
# ---------------------------------------------------------------------------

class TestLambdaHandler:
    @patch.dict("os.environ", {
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SLACK_SIGNING_SECRET": "",
        "PLATO_SLACK_MODE": "local",
    })
    def test_url_verification(self):
        from platform_agent.slack.lambda_function import lambda_handler

        event = {
            "body": json.dumps({
                "type": "url_verification",
                "challenge": "abc123",
            }),
            "headers": {},
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["challenge"] == "abc123"

    @patch.dict("os.environ", {
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SLACK_SIGNING_SECRET": "secret",
    })
    def test_invalid_signature_rejected(self):
        from platform_agent.slack.lambda_function import lambda_handler

        # Reset cached handler
        import platform_agent.slack.lambda_function as lf
        lf._handler = None

        body_str = '{"event":{"type":"message"}}'
        event = {
            "body": body_str,
            "headers": {
                "x-slack-request-timestamp": str(int(time.time())),
                "x-slack-signature": "v0=invalid",
            },
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 401

    def test_invalid_json_body(self):
        from platform_agent.slack.lambda_function import lambda_handler

        event = {
            "body": "not json!!!",
            "headers": {},
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 400

    @patch.dict("os.environ", {
        "SLACK_BOT_TOKEN": "xoxb-test",
        "SLACK_SIGNING_SECRET": "",
        "ASYNC_QUEUE_URL": "https://sqs.us-east-1.amazonaws.com/123456789/plato-slack",
    })
    @patch("boto3.client")
    def test_async_mode_enqueues(self, mock_boto3):
        from platform_agent.slack.lambda_function import lambda_handler
        import platform_agent.slack.lambda_function as lf
        lf._handler = None

        mock_sqs = MagicMock()
        mock_boto3.return_value = mock_sqs

        event = {
            "body": json.dumps({
                "event": {
                    "type": "message",
                    "user": "U_USER",
                    "channel": "D_DM",
                    "channel_type": "im",
                    "text": "hello",
                    "ts": "123.456",
                }
            }),
            "headers": {},
        }
        result = lambda_handler(event, None)
        assert result["statusCode"] == 200
        mock_sqs.send_message.assert_called_once()
