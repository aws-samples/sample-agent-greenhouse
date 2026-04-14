"""AIDLC Inception skill pack — structured requirements gathering and artifact generation.

Guides developer teams through the AIDLC (AI-Driven Life Cycle) Inception
phase via stage-by-stage questions, approval gates, and artifact generation.

Traces to: spec §3.1 (AIDLC Inception Skill)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

# AIDLC_INCEPTION_PROMPT removed — SKILL.md is the sole prompt source.
class AIDLCInceptionSkill(SkillPack):
    """AIDLC Inception skill pack.

    Guides developer teams through structured requirements gathering,
    design decisions, and artifact generation using the AIDLC methodology.

    Usage:
        agent = FoundationAgent()
        agent.load_skill(load_skill(AIDLCInceptionSkill))
        result = await agent.run("I want to build a new agent")

    Traces to: spec §3.1 (AIDLC Inception Skill)
    """

    name: str = "aidlc-inception"
    description: str = (
        "Guide developer teams through AIDLC Inception — structured "
        "requirements gathering, design, and artifact generation"
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = [  # type: ignore[assignment]
        "aidlc_start_inception",
        "aidlc_get_questions",
        "aidlc_submit_answers",
        "aidlc_approve_stage",
        "aidlc_reject_stage",
        "aidlc_get_status",
        "aidlc_generate_artifacts",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP.

        Future: could register with orchestrator for automatic routing,
        or configure workspace paths from environment.
        """
        pass


register_skill("aidlc-inception", AIDLCInceptionSkill)
