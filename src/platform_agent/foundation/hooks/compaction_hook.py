"""CompactionHook — structured compaction with 9-section format (DEPRECATED).

Deprecated in v1: FileSessionManager + Strands native context-window
management replace the custom prompt-injection compaction approach.

The hook is retained for backward compatibility (constants, static methods)
but is no longer registered in the active hook registry.  The
``on_before_invocation`` method now only logs a warning instead of injecting
a compaction prompt into the conversation.

Original design inspired by Claude Code's compact prompt pattern
(services/compact/prompt.ts).
"""

from __future__ import annotations

import logging

from platform_agent.foundation.memory import SessionMemory

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

# Default token threshold for triggering flush reminder.
_DEFAULT_TOKEN_THRESHOLD = 80000

# Maximum output tokens for compaction (matching CC pattern).
MAX_COMPACTION_TOKENS = 20000

# Token budget: reserve for system prompt + skills.
SYSTEM_PROMPT_TOKEN_RESERVE = 15000

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import BeforeInvocationEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



# 9-section structured compaction prompt (inspired by CC services/compact/prompt.ts).
COMPACTION_PROMPT = """\
Summarize the conversation so far into the following 9 sections. Be thorough but \
concise. Output ONLY the sections below, no extra commentary.

## 1. System Context Summary
Summarize the system prompt, agent identity, and operating constraints.

## 2. Skill/Tool State
List the tools and skills available, any tool configurations or state changes.

## 3. Current Task Description
Describe the user's current task or goal in full detail.

## 4. Key Decisions Made
List all decisions made during the conversation with their rationale.

## 5. Files Modified/Created
List every file that was modified or created, with a one-line summary of changes.

## 6. User Messages (Verbatim)
IRON RULE: Reproduce ALL user/developer messages EXACTLY as written. \
Never summarize, paraphrase, or omit user messages. Include every single one.

## 7. Recent Assistant Actions Summary
Summarize what the assistant did in the most recent turns (last 3-5 actions).

## 8. Open Questions/Blockers
List any unresolved questions, blockers, or items needing user input.

## 9. Next Steps
List the planned next steps or remaining work items."""


class CompactionHook(HookBase):
    """Hook that performs structured compaction when approaching token limits.

    Monitors session memory token usage and injects a structured compaction
    prompt using the 9-section format inspired by Claude Code's compact pattern.

    The 9 sections are:
    1. System context summary
    2. Skill/tool state
    3. Current task description
    4. Key decisions made
    5. Files modified/created
    6. ALL user messages (verbatim — IRON RULE: never summarize)
    7. Recent assistant actions summary
    8. Open questions/blockers
    9. Next steps

    Args:
        token_threshold: Token count at which to trigger compaction. Default: 80000.
    """

    def __init__(self, token_threshold: int = _DEFAULT_TOKEN_THRESHOLD) -> None:
        self.token_threshold = token_threshold
        self.session_memory: SessionMemory | None = None
        self._flush_triggered = False

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)

    def should_flush(self) -> bool:
        """Check if token usage exceeds the flush threshold."""
        if self.session_memory is None:
            return False
        return self.session_memory.estimate_tokens() >= self.token_threshold

    def on_before_invocation(self, event) -> None:
        """Log a warning when approaching token limits (v1: log-only).

        In v1, FileSessionManager + Strands native context-window management
        replace prompt-injection compaction.  This method no longer modifies
        ``event.messages``.

        Args:
            event: BeforeInvocationEvent (not modified).
        """
        if not self.should_flush():
            self._flush_triggered = False
            return

        if self._flush_triggered:
            return

        self._flush_triggered = True
        logger.warning(
            "Token threshold reached (%d tokens). "
            "FileSessionManager + Strands native context management "
            "will handle conversation persistence.",
            self.session_memory.estimate_tokens() if self.session_memory else 0,
        )

    @staticmethod
    def get_compaction_prompt() -> str:
        """Return the 9-section structured compaction prompt.

        Returns:
            The compaction prompt string.
        """
        return COMPACTION_PROMPT

    @staticmethod
    def get_section_names() -> list[str]:
        """Return the names of all 9 compaction sections.

        Returns:
            List of section name strings.
        """
        return [
            "System Context Summary",
            "Skill/Tool State",
            "Current Task Description",
            "Key Decisions Made",
            "Files Modified/Created",
            "User Messages (Verbatim)",
            "Recent Assistant Actions Summary",
            "Open Questions/Blockers",
            "Next Steps",
        ]
