"""Foundation Agent — Strands SDK implementation.

The FoundationStrandsAgent wraps strands.Agent with a soul system, memory
architecture, hook middleware, skill system, and Claude Code CLI integration.

Prompt cache awareness: separates static (cached) system prompt content from
dynamic (per-invocation) content to maximize Bedrock prompt cache hit rate.
Inspired by Claude Code's prompt caching strategy.

Model-agnostic: defaults to Claude via Bedrock but supports switching.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from platform_agent.foundation.soul import SoulSystem
from platform_agent.foundation.memory import WorkspaceMemory
from platform_agent.foundation.skills.registry import SkillRegistry  # noqa: F401 — kept for backward compat import path

# Strands AgentSkills plugin — replaces SkillRegistry for prompt injection.
# Import lazily with fallback for backward compatibility.
try:
    from strands import AgentSkills as _AgentSkills
except ImportError:
    _AgentSkills = None
from platform_agent.foundation.workspace_context import WorkspaceContextLoader
from platform_agent.foundation.hooks.soul_hook import SoulSystemHook
from platform_agent.foundation.hooks.memory_hook import MemoryHook
from platform_agent.foundation.hooks.audit_hook import AuditHook
from platform_agent.foundation.hooks.guardrails_hook import GuardrailsHook
from platform_agent.foundation.hooks.telemetry_hook import TelemetryHook
from platform_agent.foundation.hooks.model_metrics_hook import ModelMetricsHook
from platform_agent.foundation.hooks.tool_policy_hook import ToolPolicyHook
from platform_agent.foundation.hooks.approval_hook import ApprovalHook
from platform_agent.foundation.hooks.memory_extraction_hook import MemoryExtractionHook
from platform_agent.foundation.hooks.consolidation_hook import ConsolidationHook
from platform_agent.foundation.hooks.business_metrics_hook import BusinessMetricsHook
from platform_agent.foundation.hooks.hallucination_detector_hook import HallucinationDetectorHook
from platform_agent.foundation.hooks.otel_span_hook import OTELSpanHook
from platform_agent.foundation.hooks.session_recording_hook import SessionRecordingHook

logger = logging.getLogger(__name__)

# Always-on foundation hooks — loaded regardless of harness configuration.
_ALWAYS_ON_HOOKS: frozenset[str] = frozenset(
    {"AuditHook", "TelemetryHook", "GuardrailsHook", "SoulSystemHook"}
)


def _is_hook_enabled(hook_cfg: Any, harness: Any) -> bool:
    """Evaluate a HookConfig's ``enabled_by`` condition against the harness.

    Args:
        hook_cfg: HookConfig with optional ``enabled_by`` dotted-path string.
        harness: DomainHarness instance to resolve the path against.

    Returns:
        True if the hook should be loaded, False otherwise.
    """
    enabled_by = getattr(hook_cfg, "enabled_by", None)
    if enabled_by is None:
        return True
    obj: Any = harness
    for part in enabled_by.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return False
    return bool(obj)


# Default Bedrock model ID for Claude.
# Default model: Global Opus 4.6 cross-region inference profile
# Fallback: Global Sonnet 4.6 → global.anthropic.claude-sonnet-4-6
# Always use global inference profiles for cross-region availability
_DEFAULT_MODEL_ID = "global.anthropic.claude-opus-4-6-v1"

# Base system prompt when no soul system is configured.
_BASE_SYSTEM_PROMPT = """\
You are a helpful AI assistant powered by the Foundation Agent framework.

You have access to tools that allow you to interact with the workspace,
read and write files, manage memory, and execute tasks.

## Guidelines
- Be concise and direct in your responses.
- Use tools when needed to accomplish tasks.
- Save important context to memory files for future reference.
"""


class FoundationAgent:
    """Foundation Agent built on Strands SDK.

    Wraps strands.Agent with runtime orchestration including soul system,
    memory, hooks, skills, and optional Claude Code CLI integration.

    Args:
        workspace_dir: Path to the workspace directory for soul files,
            memory, and skills. If None, runs without workspace features.
        model_id: Bedrock model identifier. Default: Claude Sonnet.
        extra_tools: Additional tool functions to register with the agent.
        enable_claude_code: Whether to include the Claude Code CLI tool.
        tool_allowlist: Optional tool allowlist for policy enforcement.
        tool_denylist: Optional tool denylist for policy enforcement.
        enable_memory_extraction: Enable the CC-inspired memory extraction
            hook that extracts structured memories after each invocation.
        enable_consolidation: Enable the CC-inspired memory consolidation
            hook with the three-trigger gate pattern.
        session_id: Optional session identifier for context threading
            across observability hooks.
        skill_name: Optional skill name for context threading across
            observability hooks.
        session_manager: Optional Strands SessionManager (e.g.
            FileSessionManager) for durable conversation persistence.
            When provided, the Strands Agent handles message storage
            automatically, replacing the need for manual session_memory
            management.
        harness: Optional DomainHarness configuration. When None, keeps
            exact current behavior.
    """

    def __init__(
        self,
        workspace_dir: str | None = None,
        model_id: str = _DEFAULT_MODEL_ID,
        extra_tools: list[Callable] | None = None,
        enable_claude_code: bool = False,
        tool_allowlist: list[str] | None = None,
        tool_denylist: list[str] | None = None,
        enable_memory_extraction: bool = False,
        enable_consolidation: bool = False,
        session_id: str | None = None,
        skill_name: str | None = None,
        session_manager: Any | None = None,
        harness: Any | None = None,
        actor_id: str | None = None,
    ) -> None:
        self.harness = harness

        # Validate harness configuration at startup (fail-fast).
        if harness is not None and hasattr(harness, "validate"):
            errors = harness.validate()
            if errors:
                error_msg = "Harness validation failed:\n" + "\n".join(
                    f"  - {e}" for e in errors
                )
                raise ValueError(error_msg)

        self.workspace_dir = workspace_dir
        self.model_id = model_id
        self._extra_tools = extra_tools or []
        self._mcp_clients: list = []
        self._enable_claude_code = enable_claude_code
        self._session_manager = session_manager

        # Memory namespace config — populated from harness.memory_config when available
        _memory_namespace_template: str = ""
        _memory_ttl_days: int | None = None
        _memory_namespace_vars: dict[str, str] = {}

        # When a DomainHarness is provided, its policies and memory_config
        # override the explicit keyword arguments (harness is the single
        # source of truth for domain configuration).
        if harness is not None:
            policies = getattr(harness, "policies", None)
            if policies is not None:
                tool_allowlist = getattr(policies, "tool_allowlist", None) or tool_allowlist
                tool_denylist = getattr(policies, "tool_denylist", None) or tool_denylist

            mem_cfg = getattr(harness, "memory_config", None)
            if mem_cfg is not None:
                if getattr(mem_cfg, "extraction_enabled", False):
                    enable_memory_extraction = True
                if getattr(mem_cfg, "consolidation_enabled", False):
                    enable_consolidation = True
                # Extract namespace configuration from memory_config
                _memory_namespace_template = getattr(mem_cfg, "namespace_template", "") or ""
                _memory_ttl_days = getattr(mem_cfg, "ttl_days", None)

            # Build namespace vars from harness identity + session context
            _memory_namespace_vars = {
                "agent_id": getattr(harness, "name", ""),
                "domain": getattr(harness, "name", ""),
            }
            if session_id:
                _memory_namespace_vars["session_id"] = session_id
            if actor_id:
                _memory_namespace_vars["actorId"] = actor_id

            # Initialize MCP tool providers from harness.mcp_servers
            mcp_configs = getattr(harness, "mcp_servers", {}) or {}
            if mcp_configs:
                self._mcp_clients = self._init_mcp_clients(mcp_configs)

        # Soul system
        self.soul_system: SoulSystem | None = None
        if workspace_dir:
            self.soul_system = SoulSystem(workspace_dir=workspace_dir)

        # Workspace context auto-injection
        _ws_context_enabled = True
        if harness is not None:
            _ws_context_enabled = bool(
                getattr(harness, "workspace_context_enabled", True)
            )
        self.workspace_context_loader: WorkspaceContextLoader | None = None
        if workspace_dir:
            self.workspace_context_loader = WorkspaceContextLoader(
                workspace_dir=workspace_dir,
                enabled=_ws_context_enabled,
            )

        # Memory
        # Workspace memory (file-based, optional)
        self.workspace_memory: WorkspaceMemory | None = None
        if workspace_dir:
            self.workspace_memory = WorkspaceMemory(workspace_dir=workspace_dir)

        # Skill registry (kept for backward compat; deprecated when AgentSkills available)
        # SkillRegistry — deprecated, kept for backward compatibility.
        # When AgentSkills plugin is active, SkillRegistry is not used.
        self.skill_registry = SkillRegistry(workspace_dir=workspace_dir)

        # Strands AgentSkills plugin — preferred over SkillRegistry when available.
        # The plugin handles SKILL.md discovery, system-prompt injection, and the
        # skills() tool automatically.
        #
        # Skill source priority:
        #   1. harness.skill_directories (domain-driven — single source of truth)
        #   2. Fallback: workspace/skills/ (backward compat when no harness)
        self._skills_plugin = None
        if _AgentSkills is not None:
            from pathlib import Path
            skill_sources: list[str] = []

            if harness and harness.skill_directories:
                # Domain harness declares where to find skills
                skill_sources = list(harness.skill_directories)
                logger.info(
                    "Skill directories from harness: %s", skill_sources
                )
            elif workspace_dir:
                # Fallback: no harness — scan workspace/skills/ for compat
                ws_skills = Path(workspace_dir) / "skills"
                if ws_skills.is_dir():
                    skill_sources.append(str(ws_skills))
                    logger.info(
                        "Fallback: workspace skills at %s", ws_skills
                    )

            if skill_sources:
                self._skills_plugin = _AgentSkills(skills=skill_sources)
                logger.info("AgentSkills plugin active (sources=%s)", skill_sources)

        # Hooks — two code paths:
        #   harness is None  → legacy: instantiate all 11+ hooks (backward compat)
        #   harness provided → load 4 always-on foundation hooks + harness.hooks
        if harness is None:
            self.soul_hook = SoulSystemHook(workspace_dir=workspace_dir)
            self.memory_hook = MemoryHook(workspace_dir=workspace_dir)
            self.audit_hook = AuditHook()
            self.guardrails_hook = GuardrailsHook()
            self.telemetry_hook = TelemetryHook()
            self.model_metrics_hook = ModelMetricsHook()
            self.tool_policy_hook = ToolPolicyHook(
                allowlist=tool_allowlist,
                denylist=tool_denylist,
            )
            self.business_metrics_hook = BusinessMetricsHook()
            self.hallucination_detector_hook = HallucinationDetectorHook()
            # NOTE: OTELSpanHook is deprecated — Strands SDK natively emits
            # OpenTelemetry traces when strands-agents[otel] is installed.
            # AgentCore Runtime auto-instruments these. Keeping the hook object
            # for backward compatibility but NOT registering it in hook_registry.
            self.otel_span_hook = OTELSpanHook()
            self.session_recording_hook = SessionRecordingHook(
                session_id=session_id,
                skill_name=skill_name,
            )

            # Developer context threading
            if session_id:
                self.audit_hook.session_id = session_id
                self.telemetry_hook.session_id = session_id
                self.business_metrics_hook._current_session_id = session_id
                self.otel_span_hook.session_id = session_id
            if skill_name:
                self.audit_hook.skill_name = skill_name
                self.telemetry_hook.skill_name = skill_name
                self.business_metrics_hook._current_skill_name = skill_name
                self.otel_span_hook.skill_name = skill_name

            # Core hook registry (11 hooks — always active)
            self.hook_registry = [
                self.soul_hook,
                self.memory_hook,
                self.audit_hook,
                self.guardrails_hook,
                self.telemetry_hook,
                self.model_metrics_hook,
                self.tool_policy_hook,
                self.business_metrics_hook,
                self.hallucination_detector_hook,
                self.session_recording_hook,
            ]

            # Optional CC-inspired hooks (opt-in)
            self.memory_extraction_hook: MemoryExtractionHook | None = None
            if enable_memory_extraction:
                self.memory_extraction_hook = MemoryExtractionHook(
                    workspace_dir=workspace_dir,
                )
                self.hook_registry.append(self.memory_extraction_hook)

            self.consolidation_hook: ConsolidationHook | None = None
            if enable_consolidation:
                self.consolidation_hook = ConsolidationHook(
                    workspace_dir=workspace_dir,
                )
                self.hook_registry.append(self.consolidation_hook)

        else:
            # Harness-driven loading: 4 always-on foundation hooks + harness.hooks.
            # Always-on: AuditHook, TelemetryHook, GuardrailsHook, SoulSystemHook.
            self.soul_hook = SoulSystemHook(workspace_dir=workspace_dir)
            self.audit_hook = AuditHook()
            self.guardrails_hook = GuardrailsHook()
            self.telemetry_hook = TelemetryHook()

            # Developer context threading for always-on hooks
            if session_id:
                self.audit_hook.session_id = session_id
                self.telemetry_hook.session_id = session_id
            if skill_name:
                self.audit_hook.skill_name = skill_name
                self.telemetry_hook.skill_name = skill_name

            self.hook_registry = [
                self.soul_hook,
                self.audit_hook,
                self.guardrails_hook,
                self.telemetry_hook,
            ]

            # Load additional hooks from harness configuration
            for hook_cfg in harness.hooks:
                if hook_cfg.hook in _ALWAYS_ON_HOOKS:
                    continue  # already loaded as always-on
                if not _is_hook_enabled(hook_cfg, harness):
                    continue  # optional hook whose condition is not met
                hook_instance = self._make_hook(
                    hook_cfg.hook,
                    tool_allowlist=tool_allowlist,
                    tool_denylist=tool_denylist,
                    session_id=session_id,
                    skill_name=skill_name,
                    workspace_dir=workspace_dir,
                    namespace_template=_memory_namespace_template,
                    namespace_vars=_memory_namespace_vars,
                    ttl_days=_memory_ttl_days,
                )
                if hook_instance is not None:
                    self.hook_registry.append(hook_instance)

        # Cached Strands Agent instance for multi-turn conversation
        self._agent = None

        # Prompt cache tracking — hash of static system prompt for cache awareness
        self._prompt_hash: str = ""

    # ------------------------------------------------------------------
    # Hook factory (harness-driven path)
    # ------------------------------------------------------------------

    def _make_hook(
        self,
        hook_name: str,
        *,
        tool_allowlist: list[str] | None,
        tool_denylist: list[str] | None,
        session_id: str | None,
        skill_name: str | None,
        workspace_dir: str | None,
        namespace_template: str = "",
        namespace_vars: dict[str, str] | None = None,
        ttl_days: int | None = None,
    ) -> Any:
        """Instantiate a hook by class name with appropriate constructor arguments.

        Used by the harness-driven loading path. Returns None and logs a warning
        for unknown hook names so unknown hooks are silently skipped.

        Args:
            hook_name: Class name string (e.g., "MemoryHook").
            tool_allowlist: Passed to ToolPolicyHook.
            tool_denylist: Passed to ToolPolicyHook.
            session_id: Threaded into observability hooks.
            skill_name: Threaded into observability hooks.
            workspace_dir: Passed to workspace-aware hooks.

        Returns:
            Hook instance or None if the name is unknown.
        """
        if hook_name == "MemoryHook":
            return MemoryHook(
                workspace_dir=workspace_dir,
                namespace_template=namespace_template,
                namespace_vars=namespace_vars,
                ttl_days=ttl_days,
            )
        if hook_name == "ModelMetricsHook":
            return ModelMetricsHook()
        if hook_name == "ToolPolicyHook":
            return ToolPolicyHook(allowlist=tool_allowlist, denylist=tool_denylist)
        if hook_name == "ApprovalHook":
            # Get approval configuration from harness if available
            approval_config = None
            if hasattr(self, 'harness') and self.harness:
                approval_config = getattr(self.harness, 'approval_config', None)

            if approval_config:
                return ApprovalHook(config=approval_config)
            else:
                # Default configuration - no tools require approval by default
                from platform_agent.foundation.hooks.approval_hook import ApprovalConfig
                default_config = ApprovalConfig(
                    tools_requiring_approval=[],
                    default_action="block",
                    timeout_seconds=300,
                )
                return ApprovalHook(config=default_config)
        if hook_name == "BusinessMetricsHook":
            hook = BusinessMetricsHook()
            if session_id:
                hook._current_session_id = session_id
            if skill_name:
                hook._current_skill_name = skill_name
            return hook
        if hook_name == "HallucinationDetectorHook":
            return HallucinationDetectorHook()
        if hook_name == "OTELSpanHook":
            hook = OTELSpanHook()
            if session_id:
                hook.session_id = session_id
            if skill_name:
                hook.skill_name = skill_name
            return hook
        if hook_name == "SessionRecordingHook":
            return SessionRecordingHook(session_id=session_id, skill_name=skill_name)
        if hook_name == "MemoryExtractionHook":
            return MemoryExtractionHook(
                workspace_dir=workspace_dir,
                namespace_template=namespace_template,
                namespace_vars=namespace_vars,
                ttl_days=ttl_days,
            )
        if hook_name == "ConsolidationHook":
            return ConsolidationHook(
                workspace_dir=workspace_dir,
                namespace_template=namespace_template,
                namespace_vars=namespace_vars,
                ttl_days=ttl_days,
            )
        if hook_name == "AIDLCTelemetryHook":
            from platform_agent.foundation.hooks.aidlc_telemetry_hook import (
                AIDLCTelemetryHook,
            )
            return AIDLCTelemetryHook()
        logger.warning("Unknown hook class %r in harness configuration — skipped.", hook_name)
        return None

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def build_system_prompt(self) -> str:
        """Assemble the full system prompt from static sources only.

        Separates static (cacheable) content from dynamic content to maximize
        Bedrock prompt cache hit rates. Static content stays in the system
        prompt; dynamic content (date/time, session memory) is injected via
        messages in invoke().

        Static content order:
        1. Base identity (from IDENTITY.md / SOUL.md)
        2. Operating rules (from AGENTS.md)
        3. User context (from USER.md)
        4. Memory context (from MEMORY.md)
        5. Available skills list
        6. Tool usage guidelines

        Dynamic content (injected in invoke(), NOT here):
        - Current date/time
        - Session-specific memory context

        Returns:
            Static system prompt string (stable across invocations for caching).
        """
        parts: list[str] = []

        # Soul system content (static — loaded from workspace files)
        if self.soul_system:
            soul_prompt = self.soul_system.assemble_prompt()
            if soul_prompt:
                parts.append(soul_prompt)

        # Base prompt if no soul content
        if not parts:
            parts.append(_BASE_SYSTEM_PROMPT)

        # Workspace context auto-injection (from AGENTS.md, CLAUDE.md, etc.)
        if self.workspace_context_loader:
            ws_context = self.workspace_context_loader.load_context()
            if ws_context:
                parts.append(ws_context)

        # Skills summary — skip when AgentSkills plugin is active (the plugin
        # injects its own <available_skills> XML into the system prompt).
        if self._skills_plugin is None:
            skills_summary = self.skill_registry.get_prompt_summary()
            if skills_summary:
                parts.append(skills_summary)

        # Static date/time guideline — the actual timestamp is injected
        # dynamically in invoke() to keep the system prompt stable for
        # Bedrock prompt caching.
        parts.append(
            "## Current Time\n"
            "The current date and time is provided dynamically in each message."
        )

        prompt = "\n\n".join(parts)

        # Track prompt hash for cache awareness
        new_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        if self._prompt_hash and new_hash != self._prompt_hash:
            logger.warning(
                "System prompt changed (hash %s -> %s). "
                "This will invalidate the Bedrock prompt cache.",
                self._prompt_hash,
                new_hash,
            )
        self._prompt_hash = new_hash

        return prompt

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def get_tools(self) -> list[Callable]:
        """Get all tool functions for the Strands agent.

        Returns:
            List of callable tool functions.
        """
        tools: list[Callable] = []

        # Workspace tools (bound to workspace_dir)
        if self.workspace_dir:
            tools.extend(self._make_workspace_tools())

        # Claude Code tool
        if self._enable_claude_code:
            from platform_agent.foundation.tools.claude_code import claude_code
            tools.append(claude_code)

        # Extra user-provided tools
        tools.extend(self._extra_tools)

        # MCP tool providers from domain harness configuration
        if self._mcp_clients:
            tools.extend(self._mcp_clients)

        return tools

    @staticmethod
    def _init_mcp_clients(mcp_configs: dict[str, Any]) -> list:
        """Initialize MCP tool provider clients from harness configuration.

        Each entry in mcp_configs maps a server name to its stdio config:
            {
                "command": "awslabs.aws-documentation-mcp-server",
                "args": [],
                "env": {"FASTMCP_LOG_LEVEL": "WARNING"},
            }

        Returns a list of MCPClient instances (Strands ToolProvider).
        """
        import os as _os

        clients: list = []
        try:
            from mcp import StdioServerParameters, stdio_client
            from strands.tools.mcp import MCPClient
        except ImportError:
            logger.info("MCP packages not available — skipping MCP servers")
            return clients

        for name, cfg in mcp_configs.items():
            try:
                # Merge process env with server-specific env overrides
                server_env = {**_os.environ, **cfg.get("env", {})}
                # Ensure AWS region is propagated
                if "AWS_REGION" not in server_env:
                    server_env["AWS_REGION"] = _os.environ.get("AWS_REGION", "us-west-2")
                if "AWS_DEFAULT_REGION" not in server_env:
                    server_env["AWS_DEFAULT_REGION"] = server_env["AWS_REGION"]

                transport = StdioServerParameters(
                    command=cfg["command"],
                    args=cfg.get("args", []),
                    env=server_env,
                )
                client = MCPClient(lambda t=transport: stdio_client(t))
                clients.append(client)
                logger.info("MCP server '%s' configured (command=%s)", name, cfg["command"])
            except Exception as e:
                logger.warning("Failed to configure MCP server '%s': %s", name, e)

        if clients:
            logger.info("Initialized %d MCP tool provider(s) from harness", len(clients))
        return clients

    def _make_workspace_tools(self) -> list[Callable]:
        """Create workspace tool functions bound to the current workspace.

        Uses Strands @tool decorator when available for proper LLM schema registration.
        """
        from platform_agent.foundation.tools.workspace import (
            read_workspace_file,
            write_workspace_file,
            list_workspace_files,
        )

        try:
            from strands import tool as strands_tool
        except ImportError:
            def strands_tool(fn):
                return fn

        ws = self.workspace_dir or "."

        @strands_tool
        def read_file(filepath: str) -> str:
            """Read a file from the agent workspace directory.

            Args:
                filepath: Relative path within the workspace (e.g. 'MEMORY.md', 'memory/2026-03-26.md').

            Returns:
                File contents as text, or an error message if file not found.
            """
            return read_workspace_file(filepath, ws)

        @strands_tool
        def write_file(filepath: str, content: str) -> str:
            """Write content to a file in the agent workspace directory.

            Creates parent directories if needed. Use for saving memory,
            notes, and any persistent data.

            Args:
                filepath: Relative path within the workspace.
                content: Text content to write.

            Returns:
                Confirmation message or error.
            """
            return write_workspace_file(filepath, content, ws)

        @strands_tool
        def list_files(directory: str = ".") -> str:
            """List files in a workspace subdirectory.

            Args:
                directory: Relative directory path within workspace. Default: root.

            Returns:
                Newline-separated list of filenames.
            """
            return list_workspace_files(directory, ws)

        return [read_file, write_file, list_files]

    # ------------------------------------------------------------------
    # Agent building
    # ------------------------------------------------------------------

    def _build_strands_agent(self):
        """Build and return a configured strands.Agent instance.

        Hooks are passed as HookProvider instances to the Strands Agent,
        enabling the full middleware chain (soul, memory, guardrails,
        audit, tool policy, compaction).

        Returns:
            A strands.Agent ready for invocation.
        """
        try:
            from strands import Agent
            from strands.models.bedrock import BedrockModel
        except ImportError:
            raise ImportError(
                "strands-agents is required. Install with: pip install strands-agents"
            )

        model = BedrockModel(model_id=self.model_id)
        system_prompt = self.build_system_prompt()
        tools = self.get_tools()

        agent_kwargs: dict[str, Any] = dict(
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            hooks=self.hook_registry,
        )
        if self._session_manager is not None:
            agent_kwargs["session_manager"] = self._session_manager
        if self._skills_plugin is not None:
            agent_kwargs["plugins"] = [self._skills_plugin]

        agent = Agent(**agent_kwargs)

        return agent

    def _build_strands_agent_with_callback(self, callback_handler):
        """Build a Strands Agent with a custom callback handler.

        Creates a fresh Agent instance with all hooks registered but using
        the provided callback_handler for streaming.  Used by the WS handler
        to get streaming behaviour without mutating the cached agent.

        NOTE: Does NOT share the session_manager with the main agent to
        avoid ``SessionException: agent_id must be unique in a session``.
        The WS agent is ephemeral — conversation history is persisted by
        the main agent's FileSessionManager on the next HTTP invoke.

        Args:
            callback_handler: A callable that receives streaming events.

        Returns:
            A strands.Agent configured for streaming with all hooks.
        """
        try:
            from strands import Agent
            from strands.models.bedrock import BedrockModel
        except ImportError:
            raise ImportError(
                "strands-agents is required. Install with: pip install strands-agents"
            )

        model = BedrockModel(model_id=self.model_id)
        system_prompt = self.build_system_prompt()
        tools = self.get_tools()

        agent_kwargs: dict[str, Any] = dict(
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            hooks=self.hook_registry,
            callback_handler=callback_handler,
        )
        # Deliberately do NOT pass session_manager here.
        # FileSessionManager tracks agent_id uniqueness, and sharing it
        # between the cached agent and this WS clone causes:
        #   SessionException: agent_id must be unique in a session
        # The main agent's session_manager persists history; this WS
        # agent is for streaming only.
        if self._skills_plugin is not None:
            agent_kwargs["plugins"] = [self._skills_plugin]

        return Agent(**agent_kwargs)

    # ------------------------------------------------------------------
    # Invocation
    # ------------------------------------------------------------------

    def _build_dynamic_context(self) -> str:
        """Build dynamic context that changes per invocation.

        This content is injected via the BeforeInvocationEvent hooks rather
        than in the system prompt, ensuring the system prompt stays stable
        for Bedrock prompt caching.

        Returns:
            Dynamic context string with current date/time.
        """
        now = datetime.now(timezone.utc)
        return f"Current date and time (UTC): {now.isoformat()}"

    def invoke(self, prompt: str) -> str:
        """Run the agent with the given prompt and return the text result.

        Reuses the same Strands Agent instance across calls to maintain
        conversation history for multi-turn dialogue.

        Dynamic context (date/time) is injected via BeforeInvocationEvent
        hooks to keep the system prompt stable for Bedrock prompt caching.

        Args:
            prompt: The user's message/task.

        Returns:
            The agent's text response.
        """
        if self._agent is None:
            self._agent = self._build_strands_agent()
        result = self._agent(prompt)
        return self._extract_text(result)

    def invoke_streaming(self, prompt: str, callback_handler: Callable) -> str:
        """Run the agent with a custom callback handler for streaming.

        Reuses the cached Strands Agent instance (preserving conversation
        history) but passes the callback_handler per-call for streaming.
        This avoids the amnesia bug where building a fresh Agent per WS
        invocation discards all prior messages.

        Args:
            prompt: The user's message/task.
            callback_handler: Callback for processing streaming events.

        Returns:
            The agent's text response.
        """
        if self._agent is None:
            self._agent = self._build_strands_agent()
        result = self._agent(prompt, callback_handler=callback_handler)
        return self._extract_text(result)

    def reset(self) -> None:
        """Reset the agent, discarding conversation history.

        Creates a fresh Strands Agent instance on the next invoke call.
        """
        self._agent = None

    @staticmethod
    def _extract_text(result: dict[str, Any] | str) -> str:
        """Extract text from a Strands agent result.

        Args:
            result: The raw result from strands.Agent.__call__.

        Returns:
            Extracted text string.
        """
        if isinstance(result, str):
            return result

        if not isinstance(result, dict):
            return str(result)

        content = result.get("content", [])
        if not content:
            return ""

        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
            elif isinstance(block, str):
                text_parts.append(block)

        return "".join(text_parts)


# Backward-compatible alias
FoundationStrandsAgent = FoundationAgent
