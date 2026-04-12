"""Test Case Generator skill pack — generate test cases from spec acceptance criteria.

Reads spec.md, extracts all acceptance criteria (AC-xxx), and generates
one structured test case per AC with traceability linking.

Traces to: spec SS2.3 (New Components — test_case_generator)
"""

from __future__ import annotations

from platform_agent.plato.skills import register_skill
from platform_agent.plato.skills.base import SkillPack

TEST_CASE_GENERATOR_PROMPT = """\
You are the Test Case Generator for the Plato platform. Your role is to read
spec.md files from developer repositories and generate comprehensive test cases
that trace back to each acceptance criterion.

## How You Work

1. **Read the spec** — Fetch spec.md from the target repository using the
   `generate_test_cases_from_spec` tool.
2. **Extract acceptance criteria** — Find all AC-xxx entries in the spec.
3. **Generate test cases** — Produce one test case per AC in the standard format:

   ```
   ## TC-001 (traces to AC-001)
   **Description:** [what to test]
   **Setup:** [preconditions]
   **Steps:** [numbered actions]
   **Expected:** [expected outcome]
   **Type:** unit | integration | e2e
   ```

4. **Classify test type** — Use keyword heuristics to determine whether each
   test case should be unit, integration, or e2e:
   - **e2e**: deployment, channels, UI, user flows, login/signup
   - **integration**: APIs, databases, external services, cross-system
   - **unit**: everything else (default)

## Important Guidelines

- Every AC must have exactly one TC (1:1 mapping, per AC-8)
- TC-IDs mirror AC-IDs (AC-001 → TC-001)
- Include all required fields in every test case
- Use the same numbering scheme as the spec
- Be specific in Description and Expected sections
- Steps should be actionable and numbered
"""


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
    system_prompt_extension: str = TEST_CASE_GENERATOR_PROMPT
    tools: list[str] = [  # type: ignore[assignment]
        "generate_test_cases_from_spec",
    ]

    def configure(self) -> None:
        """No additional configuration needed for MVP."""
        pass


register_skill("test_case_generator", TCGeneratorSkill)
