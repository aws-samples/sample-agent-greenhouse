"""Spec compliance checker skill pack — verifies code against spec.md acceptance criteria.

Reads spec.md from a developer's repo, extracts acceptance criteria (AC-xxx),
and checks the codebase for implementation evidence and test coverage.

Traces to: spec SS3.3 (Spec Compliance Checker)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

SPEC_COMPLIANCE_PROMPT = """\
You are the Spec Compliance Checker for the Plato platform. Your role is to verify
that a developer's codebase correctly implements the acceptance criteria defined in
their spec.md.

## How You Work

1. Read the spec.md from the developer's GitHub repo.
2. Extract all acceptance criteria (AC-xxx patterns).
3. For each AC, search the codebase for:
   - Implementation evidence (code comments like "Traces to: AC-xxx")
   - Corresponding test (TC-xxx matching AC-xxx)
4. Generate a structured compliance report as a markdown table.

## Status Classification

- **PASS**: Implementation found AND matching test exists.
- **PARTIAL**: Implementation found but no test, OR test found but no implementation evidence.
- **NOT_FOUND**: No evidence of implementation or testing found.

Note: NOT_FOUND does not mean "FAIL" — it means the checker could not find
evidence via heuristic search. A human should review NOT_FOUND entries.

## Tools Available

- `check_spec_compliance` — Full compliance check on a repo
- `check_single_ac` — Check a single acceptance criterion

## Output Format

Always return structured, parseable output (markdown table). Never return
freeform prose as the primary output.
"""


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
    system_prompt_extension: str = SPEC_COMPLIANCE_PROMPT
    tools: list[str] = [  # type: ignore[assignment]
        "check_spec_compliance",
        "check_single_ac",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP."""
        pass


register_skill("spec_compliance", SpecComplianceSkill)
