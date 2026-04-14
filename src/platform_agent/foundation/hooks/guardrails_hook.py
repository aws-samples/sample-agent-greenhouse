"""GuardrailsHook — input/output validation (placeholder for Bedrock Guardrails).

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import BeforeInvocationEvent, AfterInvocationEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



class GuardrailsHook(HookBase):
    """Hook for input/output validation.

    Placeholder implementation that supports custom validator functions.
    Can be extended to integrate with Bedrock Guardrails API.

    Implements strands.hooks.HookProvider for native integration.

    Args:
        input_validator: Optional function that takes messages list and returns
            True if valid, False if blocked.
        output_validator: Optional function that takes output text and returns
            True if valid, False if blocked.
    """

    def __init__(
        self,
        input_validator: Callable | None = None,
        output_validator: Callable | None = None,
    ) -> None:
        self._input_validator = input_validator
        self._output_validator = output_validator

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeInvocationEvent, self.on_before_invocation)
            registry.add_callback(AfterInvocationEvent, self.on_after_invocation)

    def validate_input(self, messages: list[dict]) -> bool:
        """Validate input messages.

        Args:
            messages: List of message dicts.

        Returns:
            True if valid, False if blocked.
        """
        if self._input_validator is None:
            return True
        return self._input_validator(messages)

    def validate_output(self, text: str) -> bool:
        """Validate output text.

        Args:
            text: Output text to validate.

        Returns:
            True if valid, False if blocked.
        """
        if self._output_validator is None:
            return True
        return self._output_validator(text)

    def on_before_invocation(self, event) -> None:
        """Validate input before invocation.

        If the input is blocked, clear the messages to prevent the model call
        from proceeding with violating content.

        Args:
            event: BeforeInvocationEvent with messages field.
        """
        messages = getattr(event, "messages", [])
        if messages and not self.validate_input(messages):
            logger.warning("Input blocked by guardrails — clearing messages")
            # Actually block: clear messages so the model call has nothing to process
            if hasattr(event, "messages") and isinstance(event.messages, list):
                event.messages.clear()

    def on_after_invocation(self, event) -> None:
        """Validate output after invocation.

        If the output is blocked, replace the result text with a safe message.

        Args:
            event: AfterInvocationEvent with result field.
        """
        result = getattr(event, "result", None)
        if result is None:
            return
        # Try to extract text from AgentResult
        text = str(result) if result else ""
        if text and not self.validate_output(text):
            logger.warning("Output blocked by guardrails — sanitizing result")
            # Replace blocked output with safe message
            if hasattr(event, "result"):
                event.result = "I'm unable to respond to that request due to content policy."
