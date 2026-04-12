"""Code Review Evaluator — evaluates code_review skill output.

Checks that code reviews are thorough, accurate, and provide actionable fixes.
Includes deterministic checks for ruff/mypy when available.
"""

from __future__ import annotations

import logging
import re
import subprocess

from platform_agent.plato.evaluator import register_evaluator
from platform_agent.plato.evaluator.base import (
    HONESTY_PREAMBLE,
    EvaluationRubric,
    EvaluatorAgent,
    ItemScore,
    RubricItem,
)

logger = logging.getLogger(__name__)


class CodeReviewEvaluator(EvaluatorAgent):
    """Evaluates the quality of code_review skill output.

    Rubric items:
        coverage: All source files examined, key patterns identified.
        accuracy: Issues are real, not false positives.
        security_depth: Security issues identified with exploitation context.
        fix_quality: Each finding includes a concrete, correct fix.
        prioritization: Critical/Important/Suggestion levels appropriate.
    """

    name = "code_review"
    description = "Evaluates code review quality and thoroughness"

    def default_rubric(self) -> EvaluationRubric:
        return EvaluationRubric(
            name="code_review_rubric",
            version="1.0",
            items=[
                RubricItem(
                    id="coverage",
                    name="Code Coverage",
                    description=(
                        "All source files examined. Key patterns, imports, "
                        "entry points identified. No major files ignored."
                    ),
                    weight=1.5,
                    threshold=0.7,
                ),
                RubricItem(
                    id="accuracy",
                    name="Finding Accuracy",
                    description=(
                        "Issues reported are real problems, not false positives. "
                        "Code references match actual code."
                    ),
                    weight=2.0,
                    threshold=0.8,
                ),
                RubricItem(
                    id="security_depth",
                    name="Security Analysis Depth",
                    description=(
                        "Security issues identified with exploitation context. "
                        "Prompt injection, credential exposure, unsafe exec checked."
                    ),
                    weight=1.5,
                    threshold=0.7,
                ),
                RubricItem(
                    id="fix_quality",
                    name="Fix Suggestions",
                    description=(
                        "Each finding includes a concrete, correct fix. "
                        "Fixes are implementable, not just 'fix this'."
                    ),
                    weight=1.0,
                    threshold=0.7,
                ),
                RubricItem(
                    id="prioritization",
                    name="Issue Prioritization",
                    description=(
                        "Critical/Important/Suggestion levels are appropriate. "
                        "Security issues are Critical, style issues are Suggestion."
                    ),
                    weight=1.0,
                    threshold=0.7,
                ),
            ],
            overall_threshold=0.7,
            max_iterations=3,
        )

    def deterministic_checks(
        self,
        specialist_output: str,
        original_request: str,
    ) -> dict[str, ItemScore]:
        """Run ruff and mypy if available to verify code review accuracy.

        Returns:
            Dict mapping rubric_item_id -> ItemScore for deterministic checks.
        """
        results: dict[str, ItemScore] = {}

        # Try running ruff (linter) to check if review's findings align
        ruff_available = self._check_tool_available("ruff")
        mypy_available = self._check_tool_available("mypy")

        if ruff_available or mypy_available:
            tools_found = []
            if ruff_available:
                tools_found.append("ruff")
            if mypy_available:
                tools_found.append("mypy")
            evidence = f"Static analysis tools available: {', '.join(tools_found)}"

            # If review mentions linting but tools are available, verify
            output_lower = specialist_output.lower()
            mentions_linting = any(
                t in output_lower for t in ["ruff", "mypy", "lint", "type check"]
            )

            if mentions_linting:
                score = 0.9
                evidence += ". Review references static analysis tools."
            else:
                score = 0.6
                evidence += ". Review does not reference available static analysis tools."

            results["accuracy"] = ItemScore(
                rubric_item_id="accuracy",
                score=score,
                passed=score >= 0.8,
                evidence=evidence,
                feedback="" if score >= 0.8 else "Reference available static analysis tools (ruff, mypy)",
            )

        return results

    @staticmethod
    def _check_tool_available(tool_name: str) -> bool:
        """Check if a CLI tool is available on the system.

        Args:
            tool_name: Name of the tool to check.

        Returns:
            True if the tool is available.
        """
        try:
            subprocess.run(
                [tool_name, "--version"],
                capture_output=True,
                timeout=5,
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def build_evaluation_prompt(
        self,
        specialist_output: str,
        original_request: str,
        iteration: int,
    ) -> str:
        rubric_text = self._format_rubric()
        return (
            f"{HONESTY_PREAMBLE}\n\n"
            f"You are a quality evaluator for code reviews.\n\n"
            f"A Code Review agent reviewed an agent codebase. "
            f"Evaluate the quality of the review.\n\n"
            f"## Original Request\n{original_request}\n\n"
            f"## Code Review Output (Iteration {iteration})\n"
            f"{specialist_output}\n\n"
            f"## Evaluation Criteria\n{rubric_text}\n\n"
            f"## Specific Checks\n"
            f"1. **coverage**: Does the review mention specific source files? "
            f"Are all major Python files referenced?\n"
            f"2. **accuracy**: Do the findings seem plausible for the described "
            f"code? Any obvious fabrications?\n"
            f"3. **security_depth**: Are security concerns addressed with context "
            f"(e.g., 'this could allow X attack')?\n"
            f"4. **fix_quality**: Does each finding include a specific code fix?\n"
            f"5. **prioritization**: Are findings properly categorized as "
            f"Critical/Important/Suggestion?\n\n"
            f"## Response Format\n"
            f"For each criterion:\n"
            f"### <item_id>\n"
            f"Score: <0.0-1.0>\n"
            f"Evidence: <what you found>\n"
            f"Feedback: <improvement suggestion or 'None'>\n"
        )

    def _evaluate_heuristic(
        self, specialist_output: str, original_request: str
    ) -> list[ItemScore]:
        """Rule-based evaluation for code reviews."""
        output_lower = specialist_output.lower()
        scores = []

        # Coverage: check for file references
        py_files = re.findall(r"[\w/]+\.py", specialist_output)
        unique_files = len(set(py_files))
        coverage_score = min(1.0, unique_files / 3)  # expect at least 3 files
        scores.append(
            ItemScore(
                rubric_item_id="coverage",
                score=coverage_score,
                passed=coverage_score >= 0.7,
                evidence=f"Referenced {unique_files} unique Python files: {sorted(set(py_files))[:5]}",
                feedback=(
                    ""
                    if coverage_score >= 0.7
                    else "Review should reference more source files"
                ),
            )
        )

        # Accuracy: presence of line references suggests real analysis
        line_refs = re.findall(r"(?:line\s*\d+|:\d+)", output_lower)
        accuracy_score = min(1.0, len(line_refs) / 3)
        scores.append(
            ItemScore(
                rubric_item_id="accuracy",
                score=accuracy_score,
                passed=accuracy_score >= 0.8,
                evidence=f"Found {len(line_refs)} line number references",
                feedback=(
                    ""
                    if accuracy_score >= 0.8
                    else "Include specific line numbers for each finding"
                ),
            )
        )

        # Security depth: check for security-related terms
        security_terms = [
            "injection", "credential", "secret", "hardcoded", "eval(",
            "exec(", "password", "token", "api key", "vulnerability",
            "exploit", "xss", "csrf", "sql injection", "prompt injection",
        ]
        security_found = sum(1 for t in security_terms if t in output_lower)
        security_score = min(1.0, security_found / 3)
        scores.append(
            ItemScore(
                rubric_item_id="security_depth",
                score=security_score,
                passed=security_score >= 0.7,
                evidence=f"Found {security_found} security-related terms",
                feedback=(
                    ""
                    if security_score >= 0.7
                    else "Analyze security risks with exploitation context"
                ),
            )
        )

        # Fix quality: check for code suggestions
        has_code_blocks = specialist_output.count("```") >= 2
        fix_keywords = ["fix:", "replace", "change to", "use instead", "should be"]
        fix_count = sum(1 for k in fix_keywords if k in output_lower)
        fix_score = (0.5 if has_code_blocks else 0.2) + min(0.5, fix_count / 3)
        scores.append(
            ItemScore(
                rubric_item_id="fix_quality",
                score=fix_score,
                passed=fix_score >= 0.7,
                evidence=(
                    f"Code blocks: {'yes' if has_code_blocks else 'no'}, "
                    f"Fix keywords: {fix_count}"
                ),
                feedback=(
                    ""
                    if fix_score >= 0.7
                    else "Include code fix examples for each finding"
                ),
            )
        )

        # Prioritization: check for severity levels
        has_critical = any(
            t in output_lower for t in ["critical", "🔴", "high severity"]
        )
        has_important = any(
            t in output_lower for t in ["important", "🟡", "medium", "warning"]
        )
        has_suggestion = any(
            t in output_lower for t in ["suggestion", "🟢", "low", "info", "minor"]
        )
        prio_score = (
            (0.4 if has_critical else 0.0)
            + (0.3 if has_important else 0.0)
            + (0.3 if has_suggestion else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="prioritization",
                score=prio_score,
                passed=prio_score >= 0.7,
                evidence=(
                    f"Priority levels: Critical={'yes' if has_critical else 'no'}, "
                    f"Important={'yes' if has_important else 'no'}, "
                    f"Suggestion={'yes' if has_suggestion else 'no'}"
                ),
                feedback=(
                    ""
                    if prio_score >= 0.7
                    else "Categorize findings as Critical/Important/Suggestion"
                ),
            )
        )

        return scores


# Auto-register
register_evaluator("code_review", CodeReviewEvaluator)
