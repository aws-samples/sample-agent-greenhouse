"""Deprecated — use platform_agent.foundation instead.

Legacy Foundation Agent module. This file is retained for backwards compatibility
only. All new code should import from ``platform_agent.foundation``.
"""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "platform_agent._legacy_foundation is deprecated; "
    "use platform_agent.foundation instead.",
    DeprecationWarning,
    stacklevel=2,
)

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
import logging

logger = logging.getLogger(__name__)

# Runtime selection:
#   PLATO_RUNTIME=sdk     → Claude Agent SDK (production, AgentCore)
#   PLATO_RUNTIME=bedrock → Bedrock Converse API (local dev, CLI)
#   unset                 → auto-detect (SDK if available, else Bedrock)
_FORCE_RUNTIME = os.environ.get("PLATO_RUNTIME", "").lower()

if _FORCE_RUNTIME == "bedrock":
    _HAS_SDK = False
elif _FORCE_RUNTIME == "sdk":
    from claude_agent_sdk import ClaudeAgentOptions, query
    _HAS_SDK = True
else:
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
        _HAS_SDK = True
    except ImportError:
        _HAS_SDK = False

if TYPE_CHECKING:
    from platform_agent.memory import MemoryStore
    from platform_agent.plato.skills.base import SkillPack


FOUNDATION_SYSTEM_PROMPT = """\
You are Plato, the platform agent for Amazon Bedrock AgentCore.

You help internal development teams build, deploy, and govern their AI agent \
applications. You are NOT a coding agent — you are an architect, advisor, and \
governance enforcer.

## Your Role

Teams use their own coding tools (Claude Code, Cursor, Copilot, etc.) to write \
application code. Your job is to:

1. **Clarify requirements** — Ask 2-3 targeted questions before producing anything
2. **Create a GitHub repo and push CLAUDE.md** — Use your tools to do this \
   automatically. NEVER paste CLAUDE.md content in chat.
3. **Review readiness** — Check if the team's agent meets platform standards
4. **Configure deployment** — Generate IAM policies, Dockerfiles, CDK stacks
5. **Govern at runtime** — Manage policies, monitor fleet health, handle incidents

## Conversation Rules

- **Ask first, act second.** Never assume requirements — clarify scope, integrations, \
  and constraints before generating artifacts.
- **Keep chat responses to 3-5 sentences.** No exceptions. No long lists. No code blocks.
- **NEVER paste CLAUDE.md, code, YAML, or config content in chat.** Use your tools \
  (create_repo, push_file) to put content in GitHub. In chat, only say WHAT you did \
  and give the link.
- **Use tools automatically.** When you have enough info to generate CLAUDE.md, \
  immediately call create_repo then push_file. Do NOT ask the user to create a repo \
  or copy-paste anything. You do it for them.
- **Be opinionated.** Recommend specific patterns, models, and architectures. \
  Don't list every option — pick the best one and explain why.

## Workflow — FOLLOW THIS EXACTLY

Step 1: User describes what they want to build.
Step 2: You ask 2-3 clarifying questions (one message, keep it short).
Step 3: User answers.
Step 4: You IMMEDIATELY use tools:
  a) Call create_repo to create a private GitHub repo
  b) Call push_file to push CLAUDE.md into the repo
  c) Call push_file to push any other config files (IAM policy, etc.)
Step 5: Reply in chat with ONLY a short summary + repo link:
  "Done! Created your project:
   ✅ Repo: github.com/org/agent-name (private)
   ✅ CLAUDE.md pushed with full spec
   Next: clone the repo and run: claude 'Read CLAUDE.md and scaffold the project'"

That's it. 5 lines max. The detailed spec lives in the repo, not in chat.

## WHAT NEVER TO DO

- ❌ Paste CLAUDE.md content in chat
- ❌ Paste code blocks in chat
- ❌ Ask the user to create a repo themselves
- ❌ Ask the user to copy-paste anything
- ❌ Send a message longer than 5 lines after generating artifacts
- ❌ List every option when one good recommendation will do

## Platform Knowledge

You have deep expertise in:
- AgentCore runtime (deployment, scaling, monitoring)
- Cedar authorization policies (default-deny, FORBID overrides PERMIT)
- Multi-agent communication patterns (direct, broadcast, capability-match)
- Agent lifecycle management (cold start, heartbeat, graceful shutdown)
- Production readiness (the C1-C12 checklist)
"""


@dataclass
class FoundationAgent:
    """Plato's base agent, augmented with domain-specific skill packs.

    Plato is itself an agent application built on the Foundation Agent + Skills
    pattern. It runs in two modes:

    - **SDK mode**: Claude Agent SDK (production — Plato deployed on AgentCore)
    - **Bedrock mode**: Bedrock Converse API (local dev — CLI prototype)

    Both modes provide the same skill-based capabilities. The difference is
    where Plato runs and how it calls Claude.

    Note: Plato helps users build *their* agents. The agents Plato generates
    (via scaffold) are separate applications — they use Claude Agent SDK too,
    but they're the user's code, not Plato's.

    Usage:
        agent = FoundationAgent()
        agent.load_skill(design_advisor_skill)
        await agent.run("Review my agent architecture")
    """

    model: str = "claude-sonnet-4-20250514"
    skills: list[SkillPack] = field(default_factory=list)
    max_turns: int = 50
    cwd: str | None = None
    memory_store: MemoryStore | None = None

    # Core tools available to all Plato agents
    _base_tools: list[str] = field(
        default_factory=lambda: ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    )

    @property
    def runtime(self) -> str:
        """Return which runtime mode Plato is using.

        'claude-agent-sdk' = production (AgentCore)
        'bedrock' = local dev (CLI)
        """
        return "claude-agent-sdk" if _HAS_SDK else "bedrock"

    def load_skill(self, skill: SkillPack) -> None:
        """Attach a skill pack to Plato, extending its capabilities."""
        self.skills.append(skill)

    def _build_system_prompt(self) -> str:
        """Compose Plato's full system prompt from foundation + loaded skills + memory."""
        parts = [FOUNDATION_SYSTEM_PROMPT]

        if self.memory_store is not None:
            parts.append(
                "\n## Memory\n"
                "You have access to a persistent memory store. Prior context and decisions "
                "from previous sessions may be available. Use this to maintain continuity "
                "across interactions."
            )

        for skill in self.skills:
            if skill.system_prompt_extension:
                parts.append(f"\n## {skill.name} Capabilities\n{skill.system_prompt_extension}")
        return "\n".join(parts)

    def _build_tools(self) -> list[str]:
        """Collect tools from base set + loaded skills (deduplicated)."""
        seen: set[str] = set()
        tools: list[str] = []
        for name in self._base_tools:
            if name not in seen:
                seen.add(name)
                tools.append(name)
        for skill in self.skills:
            for name in skill.tools:
                if name not in seen:
                    seen.add(name)
                    tools.append(name)
        return tools

    def _build_mcp_servers(self) -> dict:
        """Collect MCP server configs from loaded skills."""
        servers: dict = {}
        for skill in self.skills:
            servers.update(skill.mcp_servers)
        return servers

    # -- SDK mode (production — Plato on AgentCore) ----------------------------

    def _build_options(self, **overrides):
        """Build ClaudeAgentOptions for SDK mode.

        Only available when running in SDK mode (Plato deployed on AgentCore).
        """
        if not _HAS_SDK:
            raise RuntimeError(
                "claude_agent_sdk is not installed. "
                "Use PLATO_RUNTIME=bedrock for local development, "
                "or install claude-agent-sdk for production mode."
            )
        mcp_servers = self._build_mcp_servers()
        opts = {
            "allowed_tools": self._build_tools(),
            "system_prompt": self._build_system_prompt(),
            "model": self.model,
            "max_turns": self.max_turns,
        }
        if self.cwd:
            opts["cwd"] = self.cwd
        if mcp_servers:
            opts["mcp_servers"] = mcp_servers
        opts.update(overrides)
        return ClaudeAgentOptions(**opts)

    # -- Main execution --------------------------------------------------------

    async def run(self, prompt: str, **overrides) -> str:
        """Run Plato with the given prompt and return the result.

        Automatically selects runtime based on PLATO_RUNTIME env var or
        SDK availability.

        If a memory store is attached, relevant context is retrieved before
        the run and the result is stored after.

        Args:
            prompt: The task or question for Plato.
            **overrides: Additional options passed to the runtime.

        Returns:
            Plato's final text response.
        """
        # Enrich prompt with memory context if available
        enriched_prompt = await self._enrich_with_memory(prompt)

        if _HAS_SDK:
            result = await self._run_sdk(enriched_prompt, **overrides)
        else:
            result = await self._run_bedrock(enriched_prompt, **overrides)

        # Store interaction in memory if available
        await self._store_to_memory(prompt, result)

        return result

    async def _enrich_with_memory(self, prompt: str) -> str:
        """Retrieve relevant memories and prepend to prompt.

        Searches memory for context related to the current prompt.
        Returns enriched prompt or original if no memory is available.
        """
        if self.memory_store is None:
            return prompt

        try:
            memories = await self.memory_store.search("interactions", prompt, limit=3)
            if not memories:
                return prompt

            context_parts = ["<memory_context>"]
            for mem in memories:
                summary = mem.get("summary", mem.get("content", ""))
                if summary:
                    context_parts.append(f"- {summary}")
            context_parts.append("</memory_context>")
            context_parts.append("")
            context_parts.append(prompt)
            return "\n".join(context_parts)
        except Exception:
            # Memory retrieval should never block the agent
            logger.debug("Memory enrichment failed, using original prompt", exc_info=True)
            return prompt

    async def _store_to_memory(self, prompt: str, result: str) -> None:
        """Store interaction summary in memory for future context.

        Only stores if a memory store is attached. Failures are silently
        ignored to avoid blocking agent responses.
        """
        if self.memory_store is None:
            return

        try:
            import time
            import uuid

            key = uuid.uuid4().hex[:16]
            await self.memory_store.put("interactions", key, {
                "prompt": prompt[:500],  # Truncate to save space
                "summary": result[:500],
                "timestamp": time.time(),
            })
        except Exception:
            logger.debug("Memory storage failed", exc_info=True)

    async def _run_sdk(self, prompt: str, **overrides) -> str:
        """Execute via Claude Agent SDK (production mode)."""
        options = self._build_options(**overrides)
        result = ""
        async for message in query(prompt=prompt, options=options):
            if message.type == "result":
                result = message.result
        return result

    async def _run_bedrock(self, prompt: str, **overrides) -> str:
        """Execute via Bedrock Converse API (local dev mode)."""
        from platform_agent.bedrock_runtime import converse

        return await converse(
            prompt=prompt,
            system_prompt=self._build_system_prompt(),
            tool_names=self._build_tools(),
            model=overrides.get("model"),
            cwd=self.cwd,
        )

    async def stream(self, prompt: str, **overrides):
        """Stream Plato's messages for the given prompt.

        Full streaming in SDK mode. Single-message yield in Bedrock mode.
        """
        if not _HAS_SDK:
            result = await self._run_bedrock(prompt, **overrides)
            yield BedrockMessage(type="result", result=result)
            return

        options = self._build_options(**overrides)
        async for message in query(prompt=prompt, options=options):
            yield message


@dataclass
class BedrockMessage:
    """Simple message type for Bedrock mode streaming."""

    type: str
    content: str = ""
    result: str = ""
