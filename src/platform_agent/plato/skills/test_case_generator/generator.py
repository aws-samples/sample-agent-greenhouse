"""Test case generator — extract acceptance criteria and generate test cases.

Parses spec.md content, extracts all acceptance criteria (AC-xxx), and
generates one test case per AC in the standard TC format.

Traces to: spec SS2.3 (New Components — test_case_generator),
           SS3.2.3 (test-cases.md format),
           AC-8 (Every AC has a corresponding test case)
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Regex to match acceptance criteria lines like:
#   - AC-001: Description text
#   - **AC-001:** Description text
#   - **AC-001**: Description text
_AC_PATTERN = re.compile(
    r"(?:- |\* )?\*{0,2}(AC-\d+)\*{0,2}[:\s]+\s*(.*?)(?:\s*$)",
    re.MULTILINE,
)

# Section heading pattern for extracting section numbers
_SECTION_PATTERN = re.compile(
    r"^#{1,4}\s+(\d+(?:\.\d+)*)\s+(.+)$",
    re.MULTILINE,
)

# Keywords used to classify test type heuristics
_E2E_KEYWORDS = frozenset({
    "deploy", "deployment", "end-to-end", "e2e", "user flow",
    "channel", "slack", "web", "api endpoint", "ui", "browser",
    "login", "sign up", "signup", "register", "navigate",
})
_INTEGRATION_KEYWORDS = frozenset({
    "integration", "api", "database", "external", "service",
    "connect", "fetch", "push", "pull", "webhook",
    "cross-system", "inter-service", "communicate",
})


def _classify_test_type(description: str) -> str:
    """Classify a test case as unit, integration, or e2e based on keywords.

    Uses simple heuristics: checks description against known keyword sets.
    Priority: e2e > integration > unit (default).

    Args:
        description: The acceptance criterion description text.

    Returns:
        One of 'unit', 'integration', or 'e2e'.
    """
    lower = description.lower()
    for kw in _E2E_KEYWORDS:
        if kw in lower:
            return "e2e"
    for kw in _INTEGRATION_KEYWORDS:
        if kw in lower:
            return "integration"
    return "unit"


def extract_acceptance_criteria(spec_content: str) -> list[dict[str, str]]:
    """Extract all acceptance criteria from spec.md content.

    Parses the spec markdown and finds all AC-xxx entries, recording
    the ID, description, and the section they belong to.

    Args:
        spec_content: Full markdown content of a spec.md file.

    Returns:
        List of dicts with keys: 'id', 'description', 'section'.
    """
    if not spec_content.strip():
        return []

    # Build a mapping of line number -> section heading
    lines = spec_content.splitlines()
    section_at_line: list[str] = []
    current_section = ""
    for line in lines:
        m = _SECTION_PATTERN.match(line)
        if m:
            current_section = m.group(1)
        section_at_line.append(current_section)

    criteria: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    for match in _AC_PATTERN.finditer(spec_content):
        ac_id = match.group(1)
        description = match.group(2).strip().rstrip("*")

        # Avoid duplicates
        if ac_id in seen_ids:
            continue
        seen_ids.add(ac_id)

        # Determine which section this AC belongs to
        line_num = spec_content[:match.start()].count("\n")
        section = section_at_line[line_num] if line_num < len(section_at_line) else ""

        criteria.append({
            "id": ac_id,
            "description": description,
            "section": section,
        })

    return criteria


def generate_test_cases(spec_content: str) -> str:
    """Generate test cases from spec.md acceptance criteria.

    Produces one test case per AC in the format:
        ## TC-001 (traces to AC-001)
        **Description:** [what to test]
        **Setup:** [preconditions]
        **Steps:** [numbered actions]
        **Expected:** [expected outcome]
        **Type:** unit | integration | e2e

    Args:
        spec_content: Full markdown content of a spec.md file.

    Returns:
        Formatted test-cases.md content as a markdown string.

    Traces to: AC-8 (Every AC has a corresponding test case)
    """
    criteria = extract_acceptance_criteria(spec_content)

    if not criteria:
        return "# Test Cases\n\nNo acceptance criteria found in spec.\n"

    md = "# Test Cases\n\n"
    md += "> Auto-generated from spec.md acceptance criteria.\n"
    md += "> One test case per acceptance criterion.\n\n"
    md += "---\n\n"

    for i, ac in enumerate(criteria, start=1):
        ac_id = ac["id"]
        ac_num = ac_id.replace("AC-", "")
        tc_id = f"TC-{ac_num}"
        description = ac["description"]
        test_type = _classify_test_type(description)

        md += f"## {tc_id} (traces to {ac_id})\n\n"
        md += f"**Description:** Verify that {description.lower() if description else 'the criterion is met'}\n\n"
        md += _generate_setup(description, test_type)
        md += _generate_steps(description, test_type)
        md += _generate_expected(description)
        md += f"**Type:** {test_type}\n\n"

        if i < len(criteria):
            md += "---\n\n"

    return md


def _generate_setup(description: str, test_type: str) -> str:
    """Generate the Setup section for a test case.

    Args:
        description: The AC description.
        test_type: The classified test type.

    Returns:
        Formatted setup text.
    """
    if test_type == "e2e":
        return "**Setup:** System is deployed and accessible in test environment\n\n"
    if test_type == "integration":
        return "**Setup:** Required services and dependencies are configured and available\n\n"
    return "**Setup:** Unit under test is instantiated with required dependencies\n\n"


def _generate_steps(description: str, test_type: str) -> str:
    """Generate the Steps section for a test case.

    Args:
        description: The AC description.
        test_type: The classified test type.

    Returns:
        Formatted steps text.
    """
    steps = "**Steps:**\n\n"
    if test_type == "e2e":
        steps += f"1. Navigate to the relevant feature area\n"
        steps += f"2. Perform the action described: {description}\n"
        steps += "3. Observe the system response\n\n"
    elif test_type == "integration":
        steps += f"1. Set up test data and configure dependencies\n"
        steps += f"2. Execute the operation: {description}\n"
        steps += "3. Verify the result across integrated components\n\n"
    else:
        steps += f"1. Arrange test inputs for: {description}\n"
        steps += "2. Execute the function under test\n"
        steps += "3. Assert the output matches expectations\n\n"
    return steps


def _generate_expected(description: str) -> str:
    """Generate the Expected section for a test case.

    Args:
        description: The AC description.

    Returns:
        Formatted expected outcome text.
    """
    return f"**Expected:** {description}\n\n"
