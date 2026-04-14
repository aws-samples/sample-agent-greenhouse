"""Test Case Generator skill pack — generate test cases from spec acceptance criteria.

Reads spec.md, extracts all acceptance criteria (AC-xxx), and generates
one structured test case per AC with traceability linking.

Traces to: spec SS2.3 (New Components — test_case_generator)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

# TEST_CASE_GENERATOR_PROMPT removed — SKILL.md is the sole prompt source.
class TCGeneratorSkill(SkillPack):
    """Test Case Generator skill pack.

    Generates structured test cases from spec.md acceptance criteria,
    with 1:1 traceability between ACs and TCs.

    Traces to: spec SS2.3 (New Components — test_case_generator)
    """

    __test__ = False

    name: str = "test_case_generator"
    description: str = (
        "Generate structured test cases from spec.md acceptance criteria "
        "with 1:1 AC-to-TC traceability"
    )
    version: str = "0.1.0"
    system_prompt_extension: str = ""  # SKILL.md is the sole prompt source
    tools: list[str] = [  # type: ignore[assignment]
        "generate_test_cases_from_spec",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP."""
        pass


register_skill("test_case_generator", TCGeneratorSkill)
