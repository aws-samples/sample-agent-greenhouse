"""Strands tools for test case generation from spec acceptance criteria.

Provides generate_test_cases_from_spec as a @strands_tool function
for the foundation agent.

Traces to: spec SS2.3 (New Components — test_case_generator),
           AC-8 (Every AC has a corresponding test case)
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
def generate_test_cases_from_spec(
    repo: str,
    spec_path: str = "spec.md",
    branch: str = "main",
) -> str:
    """Generate test cases from a spec.md file in a GitHub repo.

    Reads the spec file, extracts all acceptance criteria (AC-xxx),
    and generates one structured test case per AC with traceability.

    Args:
        repo: Full repo name (e.g. 'org/my-agent').
        spec_path: Path to spec.md in the repo. Default 'spec.md'.
        branch: Branch to read from. Default 'main'.

    Returns:
        Formatted test-cases.md content as a markdown string,
        or a JSON error message if the spec cannot be read.

    Traces to: AC-8 (Every AC has a corresponding test case)
    """
    from platform_agent.plato.skills.test_case_generator.generator import (
        extract_acceptance_criteria,
        generate_test_cases,
    )

    # Try to import the GitHub tool for fetching files
    try:
        from platform_agent.foundation.tools.github import github_get_file
    except ImportError:
        return json.dumps({
            "status": "error",
            "message": "GitHub tools not available. Cannot fetch spec file.",
        })

    try:
        spec_content = github_get_file(repo=repo, path=spec_path, branch=branch)
    except Exception as e:
        logger.error(
            "Failed to read spec file: repo=%s path=%s branch=%s error=%s",
            repo, spec_path, branch, e,
        )
        return json.dumps({
            "status": "error",
            "message": f"Could not read {spec_path} from {repo}@{branch}: {e}",
        })

    criteria = extract_acceptance_criteria(spec_content)
    if not criteria:
        return json.dumps({
            "status": "error",
            "message": f"No acceptance criteria (AC-xxx) found in {spec_path}",
        })

    test_cases_md = generate_test_cases(spec_content)

    return test_cases_md


TEST_CASE_GENERATOR_TOOLS = [
    generate_test_cases_from_spec,
]
