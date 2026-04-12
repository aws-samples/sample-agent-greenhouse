"""Spec completeness scoring utility.

Scores a spec.md for completeness by checking for required sections and
acceptance criteria patterns. Used by the observability layer to track
quality metrics.
"""

from __future__ import annotations

import re
from typing import Any

# Required sections for a complete spec (case-insensitive header matching).
SPEC_REQUIRED_SECTIONS: list[str] = [
    "overview",
    "acceptance_criteria",
    "architecture",
    "non_functional",
    "risks",
]

# Patterns that match section headers for each required section.
# Each entry is a list of regex alternatives (case-insensitive).
_SECTION_PATTERNS: dict[str, re.Pattern] = {
    "overview": re.compile(
        r"^#{1,3}\s+(overview|project\s+description|summary)", re.IGNORECASE | re.MULTILINE
    ),
    "acceptance_criteria": re.compile(
        r"^#{1,3}\s+(acceptance[_\s-]?criteria|ac\b)", re.IGNORECASE | re.MULTILINE
    ),
    "architecture": re.compile(
        r"^#{1,3}\s+(architecture|component\s+design|system\s+design|technical\s+design)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "non_functional": re.compile(
        r"^#{1,3}\s+(non[_\s-]?functional|nfr|performance|scalability|security\s+requirements)",
        re.IGNORECASE | re.MULTILINE,
    ),
    "risks": re.compile(
        r"^#{1,3}\s+(risks?|risk\s+assessment|risk\s+analysis|mitigations?)",
        re.IGNORECASE | re.MULTILINE,
    ),
}

# Pattern for acceptance criteria entries (AC-001, AC-2, ac-123, etc.).
_AC_ENTRY_PATTERN = re.compile(r"AC-\d+", re.IGNORECASE)


def score_spec(spec_text: str) -> dict[str, Any]:
    """Score a spec.md for completeness.

    Checks for the presence of required sections and counts acceptance
    criteria entries.

    Args:
        spec_text: The full text content of a spec.md file.

    Returns:
        Dictionary with:
        - score: float (0-100) — percentage of required sections present
        - sections_found: list[str] — which required sections were found
        - sections_missing: list[str] — which required sections are missing
        - ac_count: int — number of AC-xxx entries found
        - total_sections: int — total required sections checked
    """
    if not spec_text or not spec_text.strip():
        return {
            "score": 0.0,
            "sections_found": [],
            "sections_missing": list(SPEC_REQUIRED_SECTIONS),
            "ac_count": 0,
            "total_sections": len(SPEC_REQUIRED_SECTIONS),
        }

    sections_found: list[str] = []
    sections_missing: list[str] = []

    for section_name in SPEC_REQUIRED_SECTIONS:
        pattern = _SECTION_PATTERNS[section_name]
        if pattern.search(spec_text):
            sections_found.append(section_name)
        else:
            sections_missing.append(section_name)

    total = len(SPEC_REQUIRED_SECTIONS)
    found = len(sections_found)
    score = (found / total * 100) if total > 0 else 0.0

    ac_count = len(_AC_ENTRY_PATTERN.findall(spec_text))

    return {
        "score": score,
        "sections_found": sections_found,
        "sections_missing": sections_missing,
        "ac_count": ac_count,
        "total_sections": total,
    }
