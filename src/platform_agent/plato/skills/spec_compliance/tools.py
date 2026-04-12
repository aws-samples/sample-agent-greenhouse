"""Strands tools for spec compliance checking.

Provides check_spec_compliance and check_single_ac as @strands_tool
functions for the foundation agent.

Traces to: spec SS3.3 (Spec Compliance Checker)
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

try:
    from strands import tool as strands_tool

    _HAS_STRANDS = True
except ImportError:
    _HAS_STRANDS = False
    import functools

    def strands_tool(fn):  # type: ignore[misc]
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)
        return wrapper


@strands_tool
def check_spec_compliance(
    repo: str,
    spec_path: str = "spec.md",
    branch: str = "main",
) -> str:
    """Run spec compliance check on a repo.

    Reads spec.md from the repo, extracts all acceptance criteria,
    and checks each one against the codebase for implementation evidence
    and test coverage.

    Args:
        repo: Full repo name (e.g. 'org/my-agent').
        spec_path: Path to spec.md in the repo. Default 'spec.md'.
        branch: Branch to check. Default 'main'.

    Returns:
        Formatted compliance report as a markdown string.

    Traces to: AC-10 (Checks every AC), AC-11 (Links to file:line),
               AC-12 (Distinguishes statuses), AC-13 (Structured output)
    """
    from platform_agent.foundation.tools.github import github_get_file

    from platform_agent.plato.skills.spec_compliance.checker import (
        SpecComplianceChecker,
    )

    try:
        spec_content = github_get_file(repo=repo, path=spec_path, branch=branch)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Could not read {spec_path} from {repo}@{branch}: {e}",
        })

    checker = SpecComplianceChecker(spec_content)
    criteria = checker.extract_acceptance_criteria()
    if not criteria:
        return json.dumps({
            "status": "error",
            "message": f"No acceptance criteria (AC-xxx) found in {spec_path}",
        })

    report = checker.check_compliance(repo=repo, branch=branch)
    formatted = checker.format_report(report)

    return formatted


@strands_tool
def check_single_ac(
    repo: str,
    ac_id: str,
    spec_path: str = "spec.md",
    branch: str = "main",
) -> str:
    """Check compliance for a single acceptance criterion.

    Reads spec.md, finds the specified AC, and checks for implementation
    evidence and test coverage in the repo.

    Args:
        repo: Full repo name (e.g. 'org/my-agent').
        ac_id: Acceptance criterion ID (e.g. 'AC-001').
        spec_path: Path to spec.md in the repo. Default 'spec.md'.
        branch: Branch to check. Default 'main'.

    Returns:
        JSON string with compliance result for the single AC.
    """
    from platform_agent.foundation.tools.github import github_get_file

    from platform_agent.plato.skills.spec_compliance.checker import (
        SpecComplianceChecker,
    )

    try:
        spec_content = github_get_file(repo=repo, path=spec_path, branch=branch)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": f"Could not read {spec_path} from {repo}@{branch}: {e}",
        })

    checker = SpecComplianceChecker(spec_content)
    criteria = checker.extract_acceptance_criteria()

    # Find the specific AC
    target = None
    for c in criteria:
        if c["id"] == ac_id:
            target = c
            break

    if target is None:
        return json.dumps({
            "status": "error",
            "message": f"Acceptance criterion '{ac_id}' not found in {spec_path}",
        })

    report = checker.check_compliance(repo=repo, branch=branch)

    # Find the matching entry
    for entry in report.entries:
        if entry.ac_id == ac_id:
            return json.dumps({
                "status": "ok",
                "ac_id": entry.ac_id,
                "description": entry.description,
                "section": entry.section,
                "implemented": entry.implemented,
                "impl_file": entry.impl_file,
                "impl_line": entry.impl_line,
                "test_exists": entry.test_exists,
                "test_file": entry.test_file,
                "compliance_status": entry.status,
            })

    return json.dumps({
        "status": "error",
        "message": f"No compliance entry found for {ac_id}",
    })


SPEC_COMPLIANCE_TOOLS = [
    check_spec_compliance,
    check_single_ac,
]
