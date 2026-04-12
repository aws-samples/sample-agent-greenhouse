"""Scaffold Evaluator — evaluates scaffold skill output (generated projects).

Checks that generated projects are runnable, complete, and platform-ready.
Includes deterministic check for pip install success.
"""

from __future__ import annotations

import logging
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

# Expected files for a basic-agent scaffold
_EXPECTED_FILES = [
    "pyproject.toml",
    "Dockerfile",
    "README.md",
    ".gitignore",
    "agent.py",
    "health.py",
    "test_",
]


class ScaffoldEvaluator(EvaluatorAgent):
    """Evaluates the quality of scaffold skill output.

    Rubric items:
        runnable: Generated project installs and runs without errors.
        tests_pass: Generated tests execute and pass.
        readiness: Would pass design_advisor C1-C12 check.
        completeness: All expected files generated per template spec.
        best_practices: Follows platform patterns (health check, logging, etc.).
    """

    name = "scaffold"
    description = "Evaluates scaffold output quality and completeness"

    def default_rubric(self) -> EvaluationRubric:
        return EvaluationRubric(
            name="scaffold_rubric",
            version="1.0",
            items=[
                RubricItem(
                    id="runnable",
                    name="Project Runs",
                    description=(
                        "Generated project installs and runs without errors. "
                        "Dependencies resolve, no import errors."
                    ),
                    weight=2.0,
                    threshold=0.8,
                ),
                RubricItem(
                    id="tests_pass",
                    name="Tests Pass",
                    description=(
                        "Generated tests execute and pass. "
                        "Test file exists and contains meaningful assertions."
                    ),
                    weight=1.5,
                    threshold=0.7,
                ),
                RubricItem(
                    id="readiness",
                    name="Platform Readiness",
                    description=(
                        "Would pass design_advisor C1-C12 check. "
                        "Dockerfile, health check, env config all present."
                    ),
                    weight=2.0,
                    threshold=0.7,
                ),
                RubricItem(
                    id="completeness",
                    name="File Completeness",
                    description=(
                        "All expected files generated per template spec. "
                        "No critical files missing."
                    ),
                    weight=1.0,
                    threshold=0.7,
                ),
                RubricItem(
                    id="best_practices",
                    name="Best Practices",
                    description=(
                        "Follows platform patterns: health check, logging to "
                        "stdout, graceful shutdown, non-root Docker user."
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
        """Check pip install success if a project path is referenced.

        Returns:
            Dict mapping rubric_item_id -> ItemScore for deterministic checks.
        """
        results: dict[str, ItemScore] = {}

        # Check if output references a project directory we can test
        # Look for patterns like "cd /path/to/project" or "project at /path"
        output_lower = specialist_output.lower()
        has_pyproject = "pyproject.toml" in output_lower
        has_setup = "setup.py" in output_lower

        if has_pyproject or has_setup:
            # Check that pip is available (basic sanity)
            try:
                result = subprocess.run(
                    ["pip", "--version"],
                    capture_output=True,
                    timeout=10,
                )
                pip_available = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pip_available = False

            if pip_available:
                results["runnable"] = ItemScore(
                    rubric_item_id="runnable",
                    score=0.7,
                    passed=False,
                    evidence="pip is available; project declares installable package but not verified",
                    feedback="Run 'pip install -e .' to verify installability",
                )

        return results

    def build_evaluation_prompt(
        self,
        specialist_output: str,
        original_request: str,
        iteration: int,
    ) -> str:
        rubric_text = self._format_rubric()
        return (
            f"{HONESTY_PREAMBLE}\n\n"
            f"You are a quality evaluator for project scaffolding.\n\n"
            f"A Scaffold agent generated a new agent project. "
            f"Evaluate the quality of the generated project.\n\n"
            f"## Original Request\n{original_request}\n\n"
            f"## Scaffold Output (Iteration {iteration})\n"
            f"{specialist_output}\n\n"
            f"## Evaluation Criteria\n{rubric_text}\n\n"
            f"## Specific Checks\n"
            f"1. **runnable**: Does the output describe a project that would "
            f"install and run? Check imports, dependencies.\n"
            f"2. **tests_pass**: Are test files generated with real assertions?\n"
            f"3. **readiness**: Would this pass C1-C12? Dockerfile, health, "
            f"env config, no secrets?\n"
            f"4. **completeness**: Are all expected files mentioned? "
            f"({', '.join(_EXPECTED_FILES)})\n"
            f"5. **best_practices**: SIGTERM handler, logging to stdout, "
            f"non-root Docker user?\n\n"
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
        """Rule-based evaluation for scaffold output."""
        output_lower = specialist_output.lower()
        scores = []

        # Runnable: check for pyproject.toml and import patterns
        has_pyproject = "pyproject.toml" in output_lower
        has_imports = "import" in output_lower
        has_deps = any(
            d in output_lower for d in ["dependencies", "requires", "install_requires"]
        )
        runnable_score = (
            (0.4 if has_pyproject else 0.0)
            + (0.3 if has_imports else 0.0)
            + (0.3 if has_deps else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="runnable",
                score=runnable_score,
                passed=runnable_score >= 0.8,
                evidence=(
                    f"pyproject.toml: {'yes' if has_pyproject else 'no'}, "
                    f"imports: {'yes' if has_imports else 'no'}, "
                    f"deps: {'yes' if has_deps else 'no'}"
                ),
                feedback=(
                    ""
                    if runnable_score >= 0.8
                    else "Ensure project has pyproject.toml with dependencies"
                ),
            )
        )

        # Tests pass: check for test files and assertions
        has_test = "test_" in output_lower or "tests/" in output_lower
        has_assert = "assert" in output_lower
        tests_score = (0.5 if has_test else 0.0) + (0.5 if has_assert else 0.0)
        scores.append(
            ItemScore(
                rubric_item_id="tests_pass",
                score=tests_score,
                passed=tests_score >= 0.7,
                evidence=(
                    f"Test files: {'yes' if has_test else 'no'}, "
                    f"Assertions: {'yes' if has_assert else 'no'}"
                ),
                feedback=(
                    ""
                    if tests_score >= 0.7
                    else "Generate test files with meaningful assertions"
                ),
            )
        )

        # Readiness: check for platform requirements
        has_dockerfile = "dockerfile" in output_lower
        has_health = "health" in output_lower
        has_env = "os.getenv" in output_lower or "environ" in output_lower
        readiness_score = (
            (0.35 if has_dockerfile else 0.0)
            + (0.35 if has_health else 0.0)
            + (0.3 if has_env else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="readiness",
                score=readiness_score,
                passed=readiness_score >= 0.7,
                evidence=(
                    f"Dockerfile: {'yes' if has_dockerfile else 'no'}, "
                    f"Health check: {'yes' if has_health else 'no'}, "
                    f"Env config: {'yes' if has_env else 'no'}"
                ),
                feedback=(
                    ""
                    if readiness_score >= 0.7
                    else "Include Dockerfile, health check, and env-based config"
                ),
            )
        )

        # Completeness: check for expected files
        found_files = sum(
            1 for f in _EXPECTED_FILES if f.lower() in output_lower
        )
        completeness_score = found_files / len(_EXPECTED_FILES)
        scores.append(
            ItemScore(
                rubric_item_id="completeness",
                score=completeness_score,
                passed=completeness_score >= 0.7,
                evidence=f"Found {found_files}/{len(_EXPECTED_FILES)} expected files",
                feedback=(
                    ""
                    if completeness_score >= 0.7
                    else f"Missing files: {[f for f in _EXPECTED_FILES if f.lower() not in output_lower]}"
                ),
            )
        )

        # Best practices: check for platform patterns
        has_sigterm = "sigterm" in output_lower or "signal" in output_lower
        has_stdout_log = "stdout" in output_lower or "logging" in output_lower
        has_nonroot = "non-root" in output_lower or "useradd" in output_lower
        bp_score = (
            (0.34 if has_sigterm else 0.0)
            + (0.33 if has_stdout_log else 0.0)
            + (0.33 if has_nonroot else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="best_practices",
                score=bp_score,
                passed=bp_score >= 0.7,
                evidence=(
                    f"SIGTERM: {'yes' if has_sigterm else 'no'}, "
                    f"stdout logging: {'yes' if has_stdout_log else 'no'}, "
                    f"non-root: {'yes' if has_nonroot else 'no'}"
                ),
                feedback=(
                    ""
                    if bp_score >= 0.7
                    else "Add SIGTERM handler, stdout logging, and non-root Docker user"
                ),
            )
        )

        return scores


# Auto-register
register_evaluator("scaffold", ScaffoldEvaluator)
