"""Design Evaluator — evaluates design_advisor (readiness assessment) output.

Checks that readiness assessments are complete, accurate, and actionable.
"""

from __future__ import annotations

import re

from platform_agent.plato.evaluator import register_evaluator
from platform_agent.plato.evaluator.base import (
    HONESTY_PREAMBLE,
    EvaluationRubric,
    EvaluatorAgent,
    ItemScore,
    RubricItem,
)

# The 12 platform readiness checks that design_advisor should cover
_C_CHECKS = [
    "C1", "C2", "C3", "C4", "C5", "C6",
    "C7", "C8", "C9", "C10", "C11", "C12",
]


class DesignEvaluator(EvaluatorAgent):
    """Evaluates the quality of design_advisor readiness assessments.

    Rubric items:
        completeness: All 12 C1-C12 checks addressed with evidence.
        accuracy: Findings match actual code (no hallucinated issues).
        actionability: Each finding has a specific, implementable fix.
        severity_calibration: BLOCKER/WARNING/INFO levels correctly assigned.
        evidence_quality: Findings cite specific files, lines, code snippets.
    """

    name = "design"
    description = "Evaluates design_advisor readiness assessment quality"

    def default_rubric(self) -> EvaluationRubric:
        return EvaluationRubric(
            name="design_review_rubric",
            version="1.0",
            items=[
                RubricItem(
                    id="completeness",
                    name="Assessment Completeness",
                    description=(
                        "All 12 C1-C12 checks addressed with status and evidence. "
                        "No checks skipped without justification."
                    ),
                    weight=1.5,
                    threshold=0.7,
                ),
                RubricItem(
                    id="accuracy",
                    name="Finding Accuracy",
                    description=(
                        "Findings match actual code. No hallucinated issues or "
                        "false positives. PASS/FAIL statuses are correct."
                    ),
                    weight=2.0,
                    threshold=0.8,
                ),
                RubricItem(
                    id="actionability",
                    name="Recommendation Quality",
                    description=(
                        "Each failing check has a specific, implementable fix. "
                        "Recommendations are concrete, not vague."
                    ),
                    weight=1.5,
                    threshold=0.7,
                ),
                RubricItem(
                    id="severity_calibration",
                    name="Severity Calibration",
                    description=(
                        "BLOCKER/WARNING/INFO severity levels are correctly "
                        "assigned per the C1-C12 definitions."
                    ),
                    weight=1.0,
                    threshold=0.7,
                ),
                RubricItem(
                    id="evidence_quality",
                    name="Evidence Quality",
                    description=(
                        "Findings cite specific files, line numbers, and code "
                        "snippets as evidence. Not just general statements."
                    ),
                    weight=1.0,
                    threshold=0.6,
                ),
            ],
            overall_threshold=0.7,
            max_iterations=3,
        )

    def build_evaluation_prompt(
        self,
        specialist_output: str,
        original_request: str,
        iteration: int,
    ) -> str:
        rubric_text = self._format_rubric()
        return (
            f"{HONESTY_PREAMBLE}\n\n"
            f"You are a quality evaluator for platform readiness assessments.\n\n"
            f"A Design Advisor agent was asked to perform a readiness assessment. "
            f"Evaluate the quality of its output.\n\n"
            f"## Original Request\n{original_request}\n\n"
            f"## Design Advisor Output (Iteration {iteration})\n"
            f"{specialist_output}\n\n"
            f"## Evaluation Criteria\n{rubric_text}\n\n"
            f"## Specific Checks\n"
            f"1. **completeness**: Are all 12 checks (C1-C12) explicitly addressed? "
            f"Count how many are present.\n"
            f"2. **accuracy**: Do the findings match what you'd expect for the "
            f"described codebase? Any obvious hallucinations?\n"
            f"3. **actionability**: For each FAIL/WARNING, is there a concrete fix? "
            f"Not just 'fix this' but 'do X in file Y'.\n"
            f"4. **severity_calibration**: Are C1 (Containerizable) and C2 "
            f"(No hardcoded secrets) marked as BLOCKER? Are C6/C7/C10/C12 "
            f"marked as INFO?\n"
            f"5. **evidence_quality**: Are file paths, line numbers, or code "
            f"snippets cited?\n\n"
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
        """Rule-based evaluation for design readiness assessments."""
        output_lower = specialist_output.lower()
        scores = []

        # Completeness: check how many C1-C12 are mentioned
        found_checks = sum(1 for c in _C_CHECKS if c.lower() in output_lower)
        completeness_score = found_checks / len(_C_CHECKS)
        scores.append(
            ItemScore(
                rubric_item_id="completeness",
                score=completeness_score,
                passed=completeness_score >= 0.7,
                evidence=f"Found {found_checks}/{len(_C_CHECKS)} checks mentioned",
                feedback=(
                    f"Missing checks: {[c for c in _C_CHECKS if c.lower() not in output_lower]}"
                    if completeness_score < 0.7
                    else ""
                ),
            )
        )

        # Accuracy: heuristic — check for common hallucination signals
        # (hard to do without actual code, so score based on presence of specifics)
        has_file_refs = any(
            ext in output_lower
            for ext in [".py", ".toml", ".yaml", ".yml", ".json", "dockerfile"]
        )
        has_line_refs = bool(re.search(r"line\s*\d+|:\d+", output_lower))
        accuracy_score = (
            (0.5 if has_file_refs else 0.2)
            + (0.4 if has_line_refs else 0.0)
            + (0.1 if "```" in specialist_output else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="accuracy",
                score=accuracy_score,
                passed=accuracy_score >= 0.8,
                evidence=(
                    "Output references specific file types"
                    if has_file_refs
                    else "No specific file references found"
                ),
                feedback=(
                    ""
                    if accuracy_score >= 0.8
                    else "Include specific file references to support findings"
                ),
            )
        )

        # Actionability: check for recommendation keywords
        action_keywords = [
            "fix", "add", "create", "move", "replace", "remove", "implement",
            "change", "update", "use", "install", "configure",
        ]
        action_count = sum(1 for k in action_keywords if k in output_lower)
        actionability_score = min(1.0, action_count / 5)
        scores.append(
            ItemScore(
                rubric_item_id="actionability",
                score=actionability_score,
                passed=actionability_score >= 0.7,
                evidence=f"Found {action_count} action keywords in recommendations",
                feedback=(
                    ""
                    if actionability_score >= 0.7
                    else "Provide more specific, actionable recommendations"
                ),
            )
        )

        # Severity calibration: check for BLOCKER/WARNING/INFO keywords
        has_blocker = "blocker" in output_lower or "❌" in specialist_output
        has_warning = "warning" in output_lower or "⚠" in specialist_output
        has_info = "info" in output_lower or "ℹ" in specialist_output
        severity_score = (
            (0.4 if has_blocker else 0.0)
            + (0.3 if has_warning else 0.0)
            + (0.3 if has_info else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="severity_calibration",
                score=severity_score,
                passed=severity_score >= 0.7,
                evidence=(
                    f"Severity levels found: "
                    f"BLOCKER={'yes' if has_blocker else 'no'}, "
                    f"WARNING={'yes' if has_warning else 'no'}, "
                    f"INFO={'yes' if has_info else 'no'}"
                ),
                feedback=(
                    ""
                    if severity_score >= 0.7
                    else "Include all severity levels: BLOCKER, WARNING, INFO"
                ),
            )
        )

        # Evidence quality: check for line numbers and code snippets
        has_line_numbers = bool(re.search(r"line\s*\d+|:\d+", output_lower))
        has_code_blocks = "```" in specialist_output or "    " in specialist_output
        evidence_score = (0.5 if has_line_numbers else 0.0) + (
            0.5 if has_code_blocks else 0.2
        )
        scores.append(
            ItemScore(
                rubric_item_id="evidence_quality",
                score=evidence_score,
                passed=evidence_score >= 0.6,
                evidence=(
                    f"Line numbers: {'yes' if has_line_numbers else 'no'}, "
                    f"Code blocks: {'yes' if has_code_blocks else 'no'}"
                ),
                feedback=(
                    ""
                    if evidence_score >= 0.6
                    else "Cite specific line numbers and include code snippets"
                ),
            )
        )

        return scores


# Auto-register
register_evaluator("design", DesignEvaluator)
