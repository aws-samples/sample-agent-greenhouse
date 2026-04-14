"""Spec compliance checker skill pack — verifies code against spec.md acceptance criteria.

Reads spec.md from a developer's repo, extracts acceptance criteria (AC-xxx),
and checks the codebase for implementation evidence and test coverage.

Traces to: spec SS3.3 (Spec Compliance Checker)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

# SPEC_COMPLIANCE_PROMPT removed — SKILL.md is the sole prompt source.
class SpecComplianceSkill(SkillPack):
    """Spec compliance checker skill pack.

    Verifies that a developer's codebase implements the acceptance criteria
    defined in their spec.md file.

    Traces to: spec SS3.3 (Spec Compliance Checker)
    """

    name: str = "spec_compliance"
    description: str = (
        "Verify codebase compliance against spec.md acceptance criteria"
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = [  # type: ignore[assignment]
        "check_spec_compliance",
        "check_single_ac",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP."""
        pass


register_skill("spec_compliance", SpecComplianceSkill)
