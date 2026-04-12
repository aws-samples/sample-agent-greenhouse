"""Shared test configuration and mocks.

Mocks both claude_agent_sdk and strands SDK before any platform_agent
modules are imported, so tests can run without either SDK installed.
"""

from __future__ import annotations

import sys
import warnings
import functools
from unittest.mock import MagicMock

# Pre-import bedrock_agentcore with warnings suppressed so that
# PydanticDeprecatedSince20 (raised at class-definition time) is not
# triggered during the tests when -W error::DeprecationWarning is active.
# bedrock_agentcore uses old-style Pydantic class Config which is a
# third-party issue outside our control.
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    try:
        import bedrock_agentcore  # noqa: F401
    except Exception:
        pass  # optional dependency; if absent tests that need it will skip/fail normally


def _make_agent_definition(**kwargs):
    """Create a simple namespace object that stores keyword args as attributes."""
    obj = type("AgentDefinition", (), {})()
    obj.__dict__.update(kwargs)
    return obj


def _make_claude_agent_options(**kwargs):
    """Create a simple namespace object for ClaudeAgentOptions."""
    obj = type("ClaudeAgentOptions", (), {})()
    obj.__dict__.update(kwargs)
    return obj


# ── Claude Agent SDK mock ────────────────────────────────────────────────
_mock_sdk = MagicMock()
_mock_sdk.AgentDefinition = _make_agent_definition
_mock_sdk.ClaudeAgentOptions = _make_claude_agent_options

if "claude_agent_sdk" not in sys.modules:
    sys.modules["claude_agent_sdk"] = _mock_sdk


# ── Strands SDK mock ────────────────────────────────────────────────────
# We need a real @tool decorator that preserves function metadata,
# and proper HookProvider/HookRegistry/event classes.

def _identity_tool(fn):
    """Identity @tool decorator that preserves function metadata."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)
    return wrapper


class _MockHookProvider:
    """Minimal HookProvider base class for testing."""
    def register_hooks(self, registry):
        pass


class _MockHookRegistry:
    """Minimal HookRegistry for testing."""
    def __init__(self):
        self._callbacks = {}

    def add_callback(self, event_type, callback):
        self._callbacks.setdefault(event_type, []).append(callback)


# Create mock event classes
class _MockEvent:
    pass

class _MockBeforeInvocationEvent(_MockEvent):
    messages = None

class _MockAfterInvocationEvent(_MockEvent):
    result = None
    resume = None

class _MockBeforeToolCallEvent(_MockEvent):
    selected_tool = None
    tool_use = {}
    cancel_tool = False

class _MockAfterToolCallEvent(_MockEvent):
    tool_result = None
    tool_use = {}

class _MockMessageAddedEvent(_MockEvent):
    message = {}

class _MockAgentInitializedEvent(_MockEvent):
    pass

class _MockBeforeModelCallEvent(_MockEvent):
    pass

class _MockAfterModelCallEvent(_MockEvent):
    pass


class _FakeBedrockModel:
    """Minimal stand-in for strands.models.BedrockModel."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeAgent:
    """Minimal stand-in for strands.Agent."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __call__(self, prompt):
        return {"content": [{"text": f"Mock response to: {prompt}"}]}


class _FakeAgentSkills:
    """Minimal stand-in for strands.AgentSkills plugin."""
    def __init__(self, skills=None, **kwargs):
        self.skills = skills
        self.__dict__.update(kwargs)


# Build mock strands module hierarchy
_mock_strands = MagicMock()
_mock_strands.Agent = _FakeAgent
_mock_strands.tool = _identity_tool
_mock_strands.AgentSkills = _FakeAgentSkills

_mock_strands_models = MagicMock()
_mock_strands_models.BedrockModel = _FakeBedrockModel
_mock_strands_models_bedrock = MagicMock()
_mock_strands_models_bedrock.BedrockModel = _FakeBedrockModel

_mock_strands_hooks = MagicMock()
_mock_strands_hooks.HookProvider = _MockHookProvider
_mock_strands_hooks.HookRegistry = _MockHookRegistry

_mock_strands_hooks_events = MagicMock()
_mock_strands_hooks_events.BeforeInvocationEvent = _MockBeforeInvocationEvent
_mock_strands_hooks_events.AfterInvocationEvent = _MockAfterInvocationEvent
_mock_strands_hooks_events.BeforeToolCallEvent = _MockBeforeToolCallEvent
_mock_strands_hooks_events.AfterToolCallEvent = _MockAfterToolCallEvent
_mock_strands_hooks_events.MessageAddedEvent = _MockMessageAddedEvent
_mock_strands_hooks_events.AgentInitializedEvent = _MockAgentInitializedEvent
_mock_strands_hooks_events.BeforeModelCallEvent = _MockBeforeModelCallEvent
_mock_strands_hooks_events.AfterModelCallEvent = _MockAfterModelCallEvent

_mock_strands_hooks_registry = MagicMock()
_mock_strands_hooks_registry.HookProvider = _MockHookProvider
_mock_strands_hooks_registry.HookRegistry = _MockHookRegistry
_mock_strands_hooks_registry.BaseHookEvent = _MockEvent
_mock_strands_hooks_registry.HookEvent = _MockEvent
_mock_strands_hooks_registry.HookCallback = None

class _FakeFileSessionManager:
    """Minimal stand-in for strands.session.FileSessionManager."""
    def __init__(self, session_id: str, storage_dir: str | None = None, **kwargs):
        self.session_id = session_id
        self.storage_dir = storage_dir

    def register_hooks(self, registry):
        pass

    def initialize(self, agent):
        pass


_mock_strands_session = MagicMock()
_mock_strands_session.FileSessionManager = _FakeFileSessionManager

# Install all strands mocks
for mod_name, mod_val in [
    ("strands", _mock_strands),
    ("strands.agent", _mock_strands),
    ("strands.models", _mock_strands_models),
    ("strands.models.bedrock", _mock_strands_models_bedrock),
    ("strands.hooks", _mock_strands_hooks),
    ("strands.hooks.events", _mock_strands_hooks_events),
    ("strands.hooks.registry", _mock_strands_hooks_registry),
    ("strands.session", _mock_strands_session),
    ("strands.types", MagicMock()),
    ("strands.types.models", MagicMock()),
    ("strands.types.tools", MagicMock()),
    ("strands.types.content", MagicMock()),
    ("strands.types.agent", MagicMock()),
    ("strands.types.streaming", MagicMock()),
    ("strands.types.interrupt", MagicMock()),
]:
    sys.modules.setdefault(mod_name, mod_val)
