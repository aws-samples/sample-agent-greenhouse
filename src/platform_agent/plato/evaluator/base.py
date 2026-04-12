"""Base classes for the evaluator framework.

Defines the core data structures (rubrics, results, sessions) and the
EvaluatorAgent base class with the reflect-refine loop engine.

Inspired by learnings from CC Capybara v8's 29-30% false-claim rate,
which proved that LLM self-evaluation is unreliable without deterministic
checks to ground the scoring.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from platform_agent.foundation import FoundationAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Honesty preamble — prepended to ALL evaluator prompts.
# Defined once here; never duplicated across evaluator subclasses.
# ---------------------------------------------------------------------------

HONESTY_PREAMBLE = (
    "You are an independent evaluator. Your job is to find real problems, "
    "not to validate or approve. If the output is bad, say it is bad. "
    "If you cannot verify a claim, mark it as unverified. Do not fabricate "
    "evidence of quality. A false pass is worse than a false fail."
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RubricItem:
    """A single evaluation criterion.

    Attributes:
        id: Unique identifier (e.g., "completeness", "accuracy").
        name: Human-readable name.
        description: What this criterion measures.
        weight: Relative weight in overall score calculation.
        threshold: Minimum passing score for this item (0.0–1.0).
    """

    id: str
    name: str
    description: str
    weight: float = 1.0
    threshold: float = 0.7


@dataclass
class EvaluationRubric:
    """Collection of criteria for evaluating specialist output.

    Attributes:
        name: Rubric identifier (e.g., "design_review_rubric").
        version: Rubric version for tracking.
        items: List of rubric items to evaluate against.
        overall_threshold: Weighted average must meet this to pass.
        max_iterations: Max reflect-refine loops before escalation.
    """

    name: str
    version: str
    items: list[RubricItem]
    overall_threshold: float = 0.7
    max_iterations: int = 3


@dataclass
class ItemScore:
    """Score for a single rubric item.

    Attributes:
        rubric_item_id: Which rubric item this scores.
        score: Numeric score (0.0–1.0).
        passed: Whether score >= item threshold.
        evidence: What the evaluator found in the output.
        feedback: Specific improvement suggestion (empty if passed).
    """

    rubric_item_id: str
    score: float
    passed: bool
    evidence: str
    feedback: str = ""


@dataclass
class EvaluationResult:
    """Complete evaluation of a specialist's output for one iteration.

    Attributes:
        rubric_name: Which rubric was used.
        iteration: Which iteration of the reflect-refine loop.
        item_scores: Per-item scores.
        overall_score: Weighted average score.
        passed: Whether overall_score >= rubric threshold.
        summary: Human-readable summary.
        feedback_for_revision: Aggregated feedback if not passed (None if passed).
        timestamp: When the evaluation was performed (ISO 8601).
    """

    rubric_name: str
    iteration: int
    item_scores: list[ItemScore]
    overall_score: float
    passed: bool
    summary: str
    feedback_for_revision: str | None = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class EvaluationIteration:
    """One iteration of the reflect-refine loop.

    Attributes:
        iteration_number: 1-based iteration index.
        specialist_output: What the specialist produced.
        evaluation: The evaluator's scoring result.
        revised: Whether the specialist revised after this iteration.
    """

    iteration_number: int
    specialist_output: str
    evaluation: EvaluationResult
    revised: bool = False


@dataclass
class EvaluationSession:
    """Tracks a complete evaluate-refine cycle.

    Attributes:
        session_id: Unique session identifier.
        specialist_name: Which specialist produced the output.
        evaluator_name: Which evaluator scored it.
        rubric: The evaluation rubric used.
        original_request: The developer's original request.
        iterations: All iterations of the loop.
        final_status: "approved" | "escalated" | "in_progress".
    """

    session_id: str
    specialist_name: str
    evaluator_name: str
    rubric: EvaluationRubric
    original_request: str
    iterations: list[EvaluationIteration] = field(default_factory=list)
    final_status: str = "in_progress"

    @property
    def latest_score(self) -> float:
        """The overall score from the most recent iteration."""
        if not self.iterations:
            return 0.0
        return self.iterations[-1].evaluation.overall_score

    @property
    def iteration_count(self) -> int:
        """Number of iterations completed."""
        return len(self.iterations)

    @property
    def improved(self) -> bool:
        """Whether the score improved across iterations."""
        if len(self.iterations) < 2:
            return False
        return (
            self.iterations[-1].evaluation.overall_score
            > self.iterations[0].evaluation.overall_score
        )


# ---------------------------------------------------------------------------
# Score computation helpers
# ---------------------------------------------------------------------------


def compute_overall_score(
    item_scores: list[ItemScore], rubric: EvaluationRubric
) -> float:
    """Compute weighted average score from item scores.

    Args:
        item_scores: Per-item scores.
        rubric: The rubric (for weights).

    Returns:
        Weighted average score (0.0–1.0).
    """
    weight_map = {item.id: item.weight for item in rubric.items}
    total_weight = 0.0
    weighted_sum = 0.0
    for score in item_scores:
        w = weight_map.get(score.rubric_item_id, 1.0)
        weighted_sum += score.score * w
        total_weight += w
    if total_weight == 0:
        return 0.0
    return weighted_sum / total_weight


def aggregate_feedback(item_scores: list[ItemScore]) -> str:
    """Aggregate feedback from failed items into a single revision prompt.

    Args:
        item_scores: Per-item scores.

    Returns:
        Concatenated feedback string for items that didn't pass.
    """
    failed = [s for s in item_scores if not s.passed and s.feedback]
    if not failed:
        return ""
    parts = []
    for s in failed:
        parts.append(f"- **{s.rubric_item_id}** (score: {s.score:.0%}): {s.feedback}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# EvaluatorAgent base class
# ---------------------------------------------------------------------------


class EvaluatorAgent:
    """Base class for evaluator agents.

    Subclasses must implement:
        - `name`: The evaluator's identifier.
        - `rubric`: The default evaluation rubric.
        - `build_evaluation_prompt()`: Prompt for the LLM to score output.
        - `parse_evaluation_response()`: Parse LLM response into ItemScores.

    The reflect-refine loop engine is provided by this base class.
    """

    name: str = "base"
    description: str = "Base evaluator"

    def __init__(self, rubric: EvaluationRubric | None = None) -> None:
        self._rubric = rubric or self.default_rubric()

    @property
    def rubric(self) -> EvaluationRubric:
        return self._rubric

    def default_rubric(self) -> EvaluationRubric:
        """Return the default rubric for this evaluator. Override in subclasses."""
        return EvaluationRubric(
            name="default",
            version="1.0",
            items=[],
            overall_threshold=0.7,
            max_iterations=3,
        )

    def deterministic_checks(
        self,
        specialist_output: str,
        original_request: str,
    ) -> dict[str, ItemScore]:
        """Run deterministic (non-LLM) checks for specific rubric items.

        Override in subclasses to provide evaluator-specific deterministic
        checks (e.g., running ruff/mypy, checking JSON validity, verifying
        pip install success). Results from deterministic checks override
        LLM scores for the same rubric items.

        Args:
            specialist_output: The specialist agent's output to check.
            original_request: The original developer request.

        Returns:
            Dict mapping rubric_item_id -> ItemScore for items that were
            checked deterministically. Empty dict if no deterministic
            checks are implemented.
        """
        return {}

    def build_evaluation_prompt(
        self,
        specialist_output: str,
        original_request: str,
        iteration: int,
    ) -> str:
        """Build the prompt that asks the LLM to evaluate specialist output.

        Includes the HONESTY_PREAMBLE to reduce false-positive evaluations.
        Override in subclasses to provide evaluator-specific prompting.

        Args:
            specialist_output: The specialist agent's output to evaluate.
            original_request: The original developer request.
            iteration: Current iteration number (1-based).

        Returns:
            Prompt string for the evaluation LLM.
        """
        rubric_text = self._format_rubric()
        return (
            f"{HONESTY_PREAMBLE}\n\n"
            f"You are an evaluation agent. Score the following specialist output "
            f"against the rubric below.\n\n"
            f"## Original Request\n{original_request}\n\n"
            f"## Specialist Output (Iteration {iteration})\n{specialist_output}\n\n"
            f"## Evaluation Rubric\n{rubric_text}\n\n"
            f"## Instructions\n"
            f"For each rubric item, provide:\n"
            f"1. A score from 0.0 to 1.0\n"
            f"2. Evidence: what you found in the output\n"
            f"3. Feedback: specific improvement suggestion (if score < threshold)\n\n"
            f"Format your response as:\n"
            f"### <item_id>\n"
            f"Score: <0.0-1.0>\n"
            f"Evidence: <what you found>\n"
            f"Feedback: <improvement suggestion or 'None'>\n"
        )

    def _format_rubric(self) -> str:
        """Format rubric items as text for the prompt."""
        lines = [f"Rubric: {self.rubric.name} v{self.rubric.version}"]
        lines.append(f"Overall threshold: {self.rubric.overall_threshold:.0%}")
        lines.append("")
        for item in self.rubric.items:
            lines.append(
                f"- **{item.id}** ({item.name}): {item.description} "
                f"[weight={item.weight}, threshold={item.threshold:.0%}]"
            )
        return "\n".join(lines)

    def parse_evaluation_response(
        self, response: str, iteration: int
    ) -> list[ItemScore]:
        """Parse the LLM's evaluation response into ItemScores.

        Default implementation parses the structured format from
        build_evaluation_prompt(). Override for custom formats.

        Args:
            response: Raw LLM response text.
            iteration: Current iteration number.

        Returns:
            List of ItemScore objects.
        """
        scores: list[ItemScore] = []
        rubric_ids = {item.id for item in self.rubric.items}
        threshold_map = {item.id: item.threshold for item in self.rubric.items}

        # Parse sections like "### item_id\nScore: 0.8\nEvidence: ...\nFeedback: ..."
        import re

        sections = re.split(r"###\s+", response)
        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n", 1)
            item_id = lines[0].strip().lower().replace(" ", "_")

            # Match against known rubric items (prefer exact, then substring)
            matched_id = None
            for rid in rubric_ids:
                if rid == item_id:
                    matched_id = rid
                    break
            if matched_id is None:
                for rid in rubric_ids:
                    if rid in item_id or item_id in rid:
                        matched_id = rid
                        break

            if matched_id is None:
                continue

            body = lines[1] if len(lines) > 1 else ""

            # Extract score
            score_match = re.search(r"Score:\s*([\d.]+)", body, re.IGNORECASE)
            score_val = float(score_match.group(1)) if score_match else 0.0
            score_val = max(0.0, min(1.0, score_val))

            # Extract evidence
            evidence_match = re.search(
                r"Evidence:\s*(.+?)(?=\nFeedback:|\n###|\Z)",
                body,
                re.IGNORECASE | re.DOTALL,
            )
            evidence = evidence_match.group(1).strip() if evidence_match else ""

            # Extract feedback
            feedback_match = re.search(
                r"Feedback:\s*(.+?)(?=\n###|\Z)",
                body,
                re.IGNORECASE | re.DOTALL,
            )
            feedback_text = feedback_match.group(1).strip() if feedback_match else ""
            if feedback_text.lower() in ("none", "n/a", ""):
                feedback_text = ""

            threshold = threshold_map.get(matched_id, 0.7)
            scores.append(
                ItemScore(
                    rubric_item_id=matched_id,
                    score=score_val,
                    passed=score_val >= threshold,
                    evidence=evidence,
                    feedback=feedback_text,
                )
            )

        # Add zero scores for any rubric items not found in the response
        scored_ids = {s.rubric_item_id for s in scores}
        for item in self.rubric.items:
            if item.id not in scored_ids:
                scores.append(
                    ItemScore(
                        rubric_item_id=item.id,
                        score=0.0,
                        passed=False,
                        evidence="Not addressed in evaluation response",
                        feedback=f"Evaluator did not assess {item.name}",
                    )
                )

        return scores

    def build_result(
        self,
        item_scores: list[ItemScore],
        iteration: int,
    ) -> EvaluationResult:
        """Build an EvaluationResult from item scores.

        Args:
            item_scores: Per-item scores.
            iteration: Current iteration number.

        Returns:
            Complete evaluation result.
        """
        overall = compute_overall_score(item_scores, self.rubric)
        passed = overall >= self.rubric.overall_threshold
        feedback = aggregate_feedback(item_scores) if not passed else None

        failed_count = sum(1 for s in item_scores if not s.passed)
        passed_count = sum(1 for s in item_scores if s.passed)

        if passed:
            summary = (
                f"✅ APPROVED — Overall score: {overall:.0%} "
                f"({passed_count}/{len(item_scores)} items passed)"
            )
        else:
            summary = (
                f"⚠️ NEEDS REVISION — Overall score: {overall:.0%} "
                f"({failed_count}/{len(item_scores)} items below threshold)"
            )

        return EvaluationResult(
            rubric_name=self.rubric.name,
            iteration=iteration,
            item_scores=item_scores,
            overall_score=overall,
            passed=passed,
            summary=summary,
            feedback_for_revision=feedback,
        )

    # -- Reflect-refine loop engine -----------------------------------------

    async def evaluate_once(
        self,
        specialist_output: str,
        original_request: str,
        iteration: int,
        evaluator_agent: FoundationAgent | None = None,
    ) -> EvaluationResult:
        """Evaluate specialist output once against the rubric.

        Runs deterministic checks FIRST, then LLM evaluation. Deterministic
        results override LLM scores for the same rubric items.

        Args:
            specialist_output: Output to evaluate.
            original_request: The original developer request.
            iteration: Current iteration number.
            evaluator_agent: Optional FoundationAgent to use for LLM evaluation.
                If None, uses parse heuristics only.

        Returns:
            EvaluationResult for this iteration.
        """
        # Step 1: Run deterministic checks first
        deterministic_results = self.deterministic_checks(
            specialist_output, original_request
        )
        if deterministic_results:
            logger.debug(
                "Deterministic checks produced scores for: %s",
                list(deterministic_results.keys()),
            )

        # Step 2: Run LLM or heuristic evaluation
        if evaluator_agent is not None:
            prompt = self.build_evaluation_prompt(
                specialist_output, original_request, iteration
            )
            response = await evaluator_agent.run(prompt)
            item_scores = self.parse_evaluation_response(response, iteration)
        else:
            item_scores = self._evaluate_heuristic(specialist_output, original_request)

        # Step 3: Merge — deterministic results override LLM scores
        if deterministic_results:
            merged: list[ItemScore] = []
            for score in item_scores:
                if score.rubric_item_id in deterministic_results:
                    merged.append(deterministic_results[score.rubric_item_id])
                else:
                    merged.append(score)
            # Add any deterministic results for items not in LLM output
            scored_ids = {s.rubric_item_id for s in merged}
            for item_id, det_score in deterministic_results.items():
                if item_id not in scored_ids:
                    merged.append(det_score)
            item_scores = merged

        return self.build_result(item_scores, iteration)

    def _evaluate_heuristic(
        self, specialist_output: str, original_request: str
    ) -> list[ItemScore]:
        """Rule-based evaluation fallback when no LLM agent is available.

        Override in subclasses for domain-specific heuristic checks.
        Default returns zero scores for all items.
        """
        return [
            ItemScore(
                rubric_item_id=item.id,
                score=0.0,
                passed=False,
                evidence="No LLM evaluator available; heuristic not implemented",
                feedback=f"Implement heuristic evaluation for {item.name}",
            )
            for item in self.rubric.items
        ]

    async def evaluate_with_refinement(
        self,
        specialist: FoundationAgent,
        original_request: str,
        specialist_output: str | None = None,
        evaluator_agent: FoundationAgent | None = None,
        max_iterations: int | None = None,
        on_iteration: None = None,
    ) -> EvaluationSession:
        """Run the full reflect-refine loop.

        1. Specialist produces output (or use provided output).
        2. Evaluator scores against rubric.
        3. If passed → approved. If not → feedback to specialist → loop.
        4. After max iterations → escalate.

        Args:
            specialist: The specialist FoundationAgent.
            original_request: The developer's original request.
            specialist_output: Pre-existing output (skip initial specialist run).
            evaluator_agent: FoundationAgent for LLM-based evaluation.
            max_iterations: Override rubric's max_iterations.
            on_iteration: Optional callback(session, iteration) for progress.

        Returns:
            Complete EvaluationSession with all iterations.
        """
        max_iter = max_iterations or self.rubric.max_iterations

        session = EvaluationSession(
            session_id=str(uuid.uuid4()),
            specialist_name=getattr(specialist, "name", "specialist"),
            evaluator_name=self.name,
            rubric=self.rubric,
            original_request=original_request,
        )

        # Get initial output if not provided
        if specialist_output is None:
            specialist_output = await specialist.run(original_request)

        for i in range(1, max_iter + 1):
            # Evaluate
            result = await self.evaluate_once(
                specialist_output, original_request, i, evaluator_agent
            )

            iteration = EvaluationIteration(
                iteration_number=i,
                specialist_output=specialist_output,
                evaluation=result,
                revised=False,
            )
            session.iterations.append(iteration)

            if result.passed:
                session.final_status = "approved"
                return session

            # If not last iteration, ask specialist to revise
            if i < max_iter:
                iteration.revised = True
                revision_prompt = (
                    f"Your previous output was evaluated and scored "
                    f"{result.overall_score:.0%} (threshold: "
                    f"{self.rubric.overall_threshold:.0%}).\n\n"
                    f"Please revise based on this feedback:\n\n"
                    f"{result.feedback_for_revision}\n\n"
                    f"Original request: {original_request}"
                )
                specialist_output = await specialist.run(revision_prompt)

        # Max iterations reached — escalate
        session.final_status = "escalated"
        return session

    # -- Formatting helpers -------------------------------------------------

    def format_session_report(self, session: EvaluationSession) -> str:
        """Format a complete session as a human-readable report.

        Args:
            session: The evaluation session to format.

        Returns:
            Formatted report string.
        """
        lines = []
        lines.append(f"# Evaluation Report: {session.evaluator_name}")
        lines.append(f"Session: {session.session_id}")
        lines.append(f"Status: {session.final_status.upper()}")
        lines.append(f"Iterations: {session.iteration_count}")
        lines.append("")

        for iteration in session.iterations:
            ev = iteration.evaluation
            lines.append(f"## Iteration {iteration.iteration_number}")
            lines.append(ev.summary)
            lines.append("")

            for score in ev.item_scores:
                status = "✅" if score.passed else "❌"
                lines.append(
                    f"  {status} {score.rubric_item_id}: {score.score:.0%}"
                )
                if score.evidence:
                    lines.append(f"     Evidence: {score.evidence}")
                if score.feedback:
                    lines.append(f"     Feedback: {score.feedback}")
            lines.append("")

        if session.final_status == "escalated":
            lines.append("---")
            lines.append(
                "🚨 ESCALATION: Maximum iterations reached without passing. "
                "Human review required."
            )

        return "\n".join(lines)
