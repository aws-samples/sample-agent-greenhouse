"""Foundation package — canonical agent implementation and domain harness.

Exports:
    FoundationAgent          — Strands SDK agent with soul, memory, hooks, skills.
    FoundationStrandsAgent   — Backward-compatible alias for FoundationAgent.
    DomainHarness            — Domain harness configuration dataclass.
    PolicyConfig, MemoryConfig, EvalRule, HookConfig, PersonaConfig, SkillRef
                             — Sub-configuration types used by DomainHarness.
    LegacyFoundationAgent    — (optional) Original non-Strands agent from
                               _legacy_foundation.py.  None if unavailable.
"""

from platform_agent.foundation.agent import FoundationAgent, FoundationStrandsAgent
from platform_agent.foundation.harness import (
    DomainHarness,
    PolicyConfig,
    MemoryConfig,
    EvalRule,
    HookConfig,
    PersonaConfig,
    SkillRef,
)

# Try-import the pre-Strands legacy agent so callers that need it can
# access it without a hard dependency.
try:
    from platform_agent._legacy_foundation import FoundationAgent as LegacyFoundationAgent  # type: ignore[attr-defined]
except Exception:  # ImportError, ModuleNotFoundError, AttributeError
    LegacyFoundationAgent = None  # type: ignore[assignment,misc]

__all__ = [
    "FoundationAgent",
    "FoundationStrandsAgent",
    "DomainHarness",
    "PolicyConfig",
    "MemoryConfig",
    "EvalRule",
    "HookConfig",
    "PersonaConfig",
    "SkillRef",
    "LegacyFoundationAgent",
]
