"""SecurityGuardrailHook — runtime security enforcement at tool-call boundary.

Two-layer enforcement:
1. Harness-level: checks DomainHarness PolicyConfig tool_denylist
2. Skill-level: checks activated skill's allowed_tools

Also does:
- Parameter constraint validation
- Output injection pattern detection
- Audit logging of all decisions
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks.events import AfterToolCallEvent, BeforeToolCallEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False

logger = logging.getLogger(__name__)

# Default injection patterns for output scanning (raw strings — compiled at init).
INJECTION_PATTERNS: list[str] = [
    r"ignore\s+(previous|above|all)\s+(instructions?|prompts?)",
    r"you\s+are\s+now\s+(a|an)\s+",
    r"system\s*:\s*",
    r"<\s*/?system\s*>",
    r"\[INST\]",
    r"human\s*:\s*",
    r"assistant\s*:\s*",
]


@dataclass(frozen=True)
class Constraint:
    """Single parameter constraint for tool input validation.

    Attributes:
        param_name: Name of the parameter to validate.
        constraint_type: One of "allowlist", "denylist", "regex", "range".
        values: Allowed/denied values for allowlist/denylist constraints.
        pattern: Regex pattern string for regex constraints.
        min_val: Minimum value for range constraints.
        max_val: Maximum value for range constraints.
    """

    param_name: str
    constraint_type: str  # "allowlist" | "denylist" | "regex" | "range"
    values: list[str] | None = None
    pattern: str | None = None
    min_val: float | None = None
    max_val: float | None = None

    def validate(self, value: Any) -> str | None:
        """Check value against this constraint.

        Returns None if valid, or a reason string if violated.
        """
        if self.constraint_type == "allowlist":
            if self.values is not None and str(value) not in self.values:
                return (
                    f"'{self.param_name}' value '{value}' "
                    f"not in allowlist {self.values}"
                )
        elif self.constraint_type == "denylist":
            if self.values is not None and str(value) in self.values:
                return (
                    f"'{self.param_name}' value '{value}' is in denylist"
                )
        elif self.constraint_type == "regex":
            if self.pattern is not None and not re.match(self.pattern, str(value)):
                return (
                    f"'{self.param_name}' value '{value}' "
                    f"does not match pattern '{self.pattern}'"
                )
        elif self.constraint_type == "range":
            try:
                num = float(value)
            except (TypeError, ValueError):
                return (
                    f"'{self.param_name}' value '{value}' "
                    f"is not numeric for range constraint"
                )
            if self.min_val is not None and num < self.min_val:
                return (
                    f"'{self.param_name}' value {num} "
                    f"below minimum {self.min_val}"
                )
            if self.max_val is not None and num > self.max_val:
                return (
                    f"'{self.param_name}' value {num} "
                    f"above maximum {self.max_val}"
                )
        return None


@dataclass(frozen=True)
class RuleSet:
    """Configuration for parameter constraints and output scanning.

    Attributes:
        parameter_constraints: Mapping of tool_name -> list of Constraints.
        output_patterns: Compiled regex patterns for injection detection.
        audit_level: "full" logs all details; "decisions_only" logs action+reason.
    """

    parameter_constraints: dict[str, list[Constraint]] = field(
        default_factory=dict,
    )
    output_patterns: list[re.Pattern[str]] = field(default_factory=list)
    audit_level: str = "full"  # "full" | "decisions_only"


def _compile_default_patterns() -> list[re.Pattern[str]]:
    """Compile the default injection detection patterns."""
    return [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


class AuditLogger:
    """Structured JSON audit logger for security guardrail decisions."""

    def __init__(self, logger_instance: logging.Logger | None = None) -> None:
        self._logger = logger_instance or logging.getLogger(f"{__name__}.audit")

    def log_decision(
        self,
        tool: str,
        action: str,
        reason: str,
        trace_id: str,
        skill_name: str | None = None,
    ) -> None:
        """Log a security decision as structured JSON.

        Args:
            tool: Tool name that was checked.
            action: "ALLOW" or "BLOCK".
            reason: Human-readable reason for the decision.
            trace_id: Trace ID for correlating related decisions.
            skill_name: Active skill name, if any.
        """
        entry: dict[str, Any] = {
            "event": "security_guardrail_decision",
            "tool": tool,
            "action": action,
            "reason": reason,
            "trace_id": trace_id,
        }
        if skill_name is not None:
            entry["skill_name"] = skill_name
        self._logger.info(json.dumps(entry, default=str))

    def log_injection_warning(
        self,
        tool: str,
        pattern: str,
        trace_id: str,
    ) -> None:
        """Log a warning when an injection pattern is detected in tool output.

        Args:
            tool: Name of the tool whose output matched.
            pattern: The regex pattern that matched.
            trace_id: Request trace identifier for correlation.
        """
        entry: dict[str, Any] = {
            "event": "security_guardrail_injection_detected",
            "tool": tool,
            "matched_pattern": pattern,
            "trace_id": trace_id,
        }
        self._logger.warning(json.dumps(entry, default=str))


class SecurityGuardrailHook(HookBase):
    """Runtime security enforcement at tool-call boundary.

    Two-layer enforcement:
    1. Harness-level: checks DomainHarness PolicyConfig
    2. Skill-level: checks activated skill's allowed_tools

    Also does:
    - Parameter constraint validation
    - Output injection pattern detection
    - Audit logging of all decisions

    Args:
        harness: DomainHarness instance for PolicyConfig access.
        skills_plugin: AgentSkills plugin instance for skill allowed_tools lookup.
        ruleset: Optional RuleSet for parameter constraints and output patterns.
        audit_logger: Optional custom AuditLogger instance.
    """

    def __init__(
        self,
        harness: Any | None = None,
        skills_plugin: Any | None = None,
        ruleset: RuleSet | None = None,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self._harness = harness
        self._skills_plugin = skills_plugin
        self._ruleset = ruleset or RuleSet()
        self._audit = audit_logger or AuditLogger()

        # Pre-compute harness denylist as frozenset for O(1) lookup.
        self._harness_denylist: frozenset[str] = frozenset()
        if harness is not None:
            policies = getattr(harness, "policies", None)
            if policies is not None:
                denylist = getattr(policies, "tool_denylist", None)
                if denylist:
                    self._harness_denylist = frozenset(denylist)

        # Pre-build skill name -> allowed_tools lookup for O(1) access.
        self._skill_allowed_tools: dict[str, set[str] | None] = {}
        if skills_plugin is not None and hasattr(skills_plugin, "get_available_skills"):
            for skill in skills_plugin.get_available_skills():
                allowed = getattr(skill, "allowed_tools", None)
                self._skill_allowed_tools[skill.name] = (
                    set(allowed) if allowed is not None else None
                )

        # Compile output injection patterns.
        self._output_patterns: list[re.Pattern[str]] = (
            list(self._ruleset.output_patterns)
            if self._ruleset.output_patterns
            else _compile_default_patterns()
        )

    def register_hooks(self, registry: Any) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(BeforeToolCallEvent, self.on_before_tool_call)
            registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    # ------------------------------------------------------------------
    # BeforeToolCallEvent handler
    # ------------------------------------------------------------------

    def on_before_tool_call(self, event: Any) -> None:
        """Enforce security policies before tool execution.

        Checks (in order):
        1. Harness-level denylist
        2. Skill-level allowed_tools
        3. Parameter constraints from RuleSet

        Sets ``event.cancel_tool`` with reason string to block.
        """
        tool_use = getattr(event, "tool_use", {})
        tool_name: str = (
            tool_use.get("name", "")
            if isinstance(tool_use, dict)
            else ""
        )
        tool_input: dict[str, Any] = (
            tool_use.get("input", {})
            if isinstance(tool_use, dict)
            else {}
        )
        trace_id = self._extract_trace_id(event)
        current_skill = self._get_current_skill(event)

        # --- Layer 1: Harness-level denylist ---
        if tool_name in self._harness_denylist:
            reason = f"Tool '{tool_name}' is in harness denylist"
            event.cancel_tool = f"Blocked by SecurityGuardrailHook: {reason}"
            self._audit.log_decision(
                tool=tool_name,
                action="BLOCK",
                reason=reason,
                trace_id=trace_id,
                skill_name=current_skill,
            )
            return

        # --- Layer 2: Skill-level allowed_tools ---
        if current_skill is not None:
            allowed = self._skill_allowed_tools.get(current_skill)
            if allowed is not None and tool_name not in allowed:
                reason = (
                    f"Tool '{tool_name}' not in skill '{current_skill}' "
                    f"allowed_tools {sorted(allowed)}"
                )
                event.cancel_tool = f"Blocked by SecurityGuardrailHook: {reason}"
                self._audit.log_decision(
                    tool=tool_name,
                    action="BLOCK",
                    reason=reason,
                    trace_id=trace_id,
                    skill_name=current_skill,
                )
                return

        # --- Layer 3: Parameter constraint check ---
        constraints = self._ruleset.parameter_constraints.get(tool_name, [])
        for constraint in constraints:
            param_value = tool_input.get(constraint.param_name)
            if param_value is not None:
                violation = constraint.validate(param_value)
                if violation is not None:
                    reason = f"Parameter constraint violated: {violation}"
                    event.cancel_tool = (
                        f"Blocked by SecurityGuardrailHook: {reason}"
                    )
                    self._audit.log_decision(
                        tool=tool_name,
                        action="BLOCK",
                        reason=reason,
                        trace_id=trace_id,
                        skill_name=current_skill,
                    )
                    return

        # --- All checks passed → ALLOW ---
        self._audit.log_decision(
            tool=tool_name,
            action="ALLOW",
            reason="All security checks passed",
            trace_id=trace_id,
            skill_name=current_skill,
        )

    # ------------------------------------------------------------------
    # AfterToolCallEvent handler
    # ------------------------------------------------------------------

    def on_after_tool_call(self, event: Any) -> None:
        """Scan tool output for injection patterns.

        Logs a warning for each match found. Does not block (tool already ran).
        """
        tool_use = getattr(event, "tool_use", {})
        tool_name: str = (
            tool_use.get("name", "")
            if isinstance(tool_use, dict)
            else ""
        )
        trace_id = self._extract_trace_id(event)

        # AfterToolCallEvent.result is the tool result.
        result = getattr(event, "result", None)
        if result is None:
            return

        output_text = self._extract_output_text(result)
        if not output_text:
            return

        for pattern in self._output_patterns:
            if pattern.search(output_text):
                self._audit.log_injection_warning(
                    tool=tool_name,
                    pattern=pattern.pattern,
                    trace_id=trace_id,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_current_skill(event: Any) -> str | None:
        """Extract the currently activated skill from agent state.

        Reads ``agent.state["agent_skills"]["activated_skills"]`` and
        returns the last element (most recently activated), or None.
        """
        agent = getattr(event, "agent", None)
        if agent is None:
            return None
        state = getattr(agent, "state", None)
        if state is None:
            return None

        # agent.state is a State object with .get(), or a plain dict.
        # Strands SDK JSONSerializableDict.get() may not accept a default arg.
        try:
            skills_state = state.get("agent_skills", {})
        except TypeError:
            try:
                skills_state = state.get("agent_skills")
            except Exception:
                return None
        if skills_state is None:
            skills_state = {}

        if not isinstance(skills_state, dict):
            return None

        try:
            activated: list[str] = skills_state.get("activated_skills", [])
        except TypeError:
            activated = skills_state.get("activated_skills") or []
        if activated:
            return activated[-1]
        return None

    @staticmethod
    def _extract_trace_id(event: Any) -> str:
        """Extract or generate a trace ID from the event's invocation state."""
        invocation_state = getattr(event, "invocation_state", None)
        if isinstance(invocation_state, dict):
            tid = invocation_state.get("trace_id")
            if tid:
                return str(tid)
        return str(uuid.uuid4())

    @staticmethod
    def _extract_output_text(result: Any) -> str:
        """Extract text content from a tool result for injection scanning."""
        if result is None:
            return ""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            content = result.get("content", [])
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        parts.append(block["text"])
                    elif isinstance(block, str):
                        parts.append(block)
                return " ".join(parts)
        return str(result)
