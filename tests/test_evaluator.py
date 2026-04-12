"""Tests for the evaluator base framework."""

from __future__ import annotations

import pytest

from platform_agent.plato.evaluator.base import (
    EvaluationIteration,
    EvaluationResult,
    EvaluationRubric,
    EvaluationSession,
    EvaluatorAgent,
    ItemScore,
    RubricItem,
    aggregate_feedback,
    compute_overall_score,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_rubric():
    return EvaluationRubric(
        name="test_rubric",
        version="1.0",
        items=[
            RubricItem(
                id="quality",
                name="Output Quality",
                description="Is the output high quality?",
                weight=2.0,
                threshold=0.7,
            ),
            RubricItem(
                id="completeness",
                name="Completeness",
                description="Is everything covered?",
                weight=1.0,
                threshold=0.6,
            ),
            RubricItem(
                id="accuracy",
                name="Accuracy",
                description="Is the output accurate?",
                weight=1.5,
                threshold=0.8,
            ),
        ],
        overall_threshold=0.7,
        max_iterations=3,
    )


@pytest.fixture
def passing_scores():
    return [
        ItemScore(
            rubric_item_id="quality",
            score=0.9,
            passed=True,
            evidence="Good quality output",
        ),
        ItemScore(
            rubric_item_id="completeness",
            score=0.8,
            passed=True,
            evidence="Everything covered",
        ),
        ItemScore(
            rubric_item_id="accuracy",
            score=0.85,
            passed=True,
            evidence="Accurate results",
        ),
    ]


@pytest.fixture
def mixed_scores():
    return [
        ItemScore(
            rubric_item_id="quality",
            score=0.9,
            passed=True,
            evidence="Good quality",
        ),
        ItemScore(
            rubric_item_id="completeness",
            score=0.4,
            passed=False,
            evidence="Missing sections",
            feedback="Cover all 12 checks",
        ),
        ItemScore(
            rubric_item_id="accuracy",
            score=0.5,
            passed=False,
            evidence="Some hallucinations",
            feedback="Verify findings against code",
        ),
    ]


@pytest.fixture
def failing_scores():
    return [
        ItemScore(
            rubric_item_id="quality",
            score=0.3,
            passed=False,
            evidence="Low quality",
            feedback="Improve output quality",
        ),
        ItemScore(
            rubric_item_id="completeness",
            score=0.2,
            passed=False,
            evidence="Very incomplete",
            feedback="Cover all checks",
        ),
        ItemScore(
            rubric_item_id="accuracy",
            score=0.1,
            passed=False,
            evidence="Mostly wrong",
            feedback="Fix accuracy issues",
        ),
    ]


# ---------------------------------------------------------------------------
# RubricItem tests
# ---------------------------------------------------------------------------


class TestRubricItem:
    def test_creation(self):
        item = RubricItem(
            id="test",
            name="Test Item",
            description="A test",
        )
        assert item.id == "test"
        assert item.weight == 1.0
        assert item.threshold == 0.7

    def test_custom_weight_threshold(self):
        item = RubricItem(
            id="test",
            name="Test",
            description="A test",
            weight=2.5,
            threshold=0.9,
        )
        assert item.weight == 2.5
        assert item.threshold == 0.9


# ---------------------------------------------------------------------------
# EvaluationRubric tests
# ---------------------------------------------------------------------------


class TestEvaluationRubric:
    def test_creation(self, sample_rubric):
        assert sample_rubric.name == "test_rubric"
        assert len(sample_rubric.items) == 3
        assert sample_rubric.overall_threshold == 0.7
        assert sample_rubric.max_iterations == 3

    def test_defaults(self):
        rubric = EvaluationRubric(name="r", version="1", items=[])
        assert rubric.overall_threshold == 0.7
        assert rubric.max_iterations == 3


# ---------------------------------------------------------------------------
# ItemScore tests
# ---------------------------------------------------------------------------


class TestItemScore:
    def test_passing_score(self):
        score = ItemScore(
            rubric_item_id="test",
            score=0.9,
            passed=True,
            evidence="Good",
        )
        assert score.passed is True
        assert score.feedback == ""

    def test_failing_score(self):
        score = ItemScore(
            rubric_item_id="test",
            score=0.3,
            passed=False,
            evidence="Bad",
            feedback="Fix it",
        )
        assert score.passed is False
        assert score.feedback == "Fix it"


# ---------------------------------------------------------------------------
# EvaluationResult tests
# ---------------------------------------------------------------------------


class TestEvaluationResult:
    def test_passing_result(self, passing_scores):
        result = EvaluationResult(
            rubric_name="test",
            iteration=1,
            item_scores=passing_scores,
            overall_score=0.87,
            passed=True,
            summary="All good",
        )
        assert result.passed is True
        assert result.feedback_for_revision is None
        assert result.timestamp  # auto-set

    def test_failing_result(self, failing_scores):
        result = EvaluationResult(
            rubric_name="test",
            iteration=1,
            item_scores=failing_scores,
            overall_score=0.2,
            passed=False,
            summary="Needs work",
            feedback_for_revision="Fix everything",
        )
        assert result.passed is False
        assert result.feedback_for_revision == "Fix everything"


# ---------------------------------------------------------------------------
# EvaluationSession tests
# ---------------------------------------------------------------------------


class TestEvaluationSession:
    def test_creation(self, sample_rubric):
        session = EvaluationSession(
            session_id="test-123",
            specialist_name="design_advisor",
            evaluator_name="design",
            rubric=sample_rubric,
            original_request="Check readiness",
        )
        assert session.final_status == "in_progress"
        assert session.iteration_count == 0
        assert session.latest_score == 0.0

    def test_latest_score(self, sample_rubric, passing_scores):
        session = EvaluationSession(
            session_id="test-123",
            specialist_name="design_advisor",
            evaluator_name="design",
            rubric=sample_rubric,
            original_request="Check readiness",
        )
        result = EvaluationResult(
            rubric_name="test",
            iteration=1,
            item_scores=passing_scores,
            overall_score=0.87,
            passed=True,
            summary="Good",
        )
        session.iterations.append(
            EvaluationIteration(
                iteration_number=1,
                specialist_output="output",
                evaluation=result,
            )
        )
        assert session.latest_score == 0.87
        assert session.iteration_count == 1

    def test_improved_property(self, sample_rubric, passing_scores, failing_scores):
        session = EvaluationSession(
            session_id="test-123",
            specialist_name="design_advisor",
            evaluator_name="design",
            rubric=sample_rubric,
            original_request="Check readiness",
        )
        # First iteration: failing
        r1 = EvaluationResult(
            rubric_name="test", iteration=1,
            item_scores=failing_scores, overall_score=0.2,
            passed=False, summary="Bad",
        )
        session.iterations.append(
            EvaluationIteration(1, "out1", r1)
        )
        assert session.improved is False  # only 1 iteration

        # Second iteration: better
        r2 = EvaluationResult(
            rubric_name="test", iteration=2,
            item_scores=passing_scores, overall_score=0.87,
            passed=True, summary="Good",
        )
        session.iterations.append(
            EvaluationIteration(2, "out2", r2)
        )
        assert session.improved is True


# ---------------------------------------------------------------------------
# compute_overall_score tests
# ---------------------------------------------------------------------------


class TestComputeOverallScore:
    def test_equal_weights(self):
        rubric = EvaluationRubric(
            name="test",
            version="1.0",
            items=[
                RubricItem(id="a", name="A", description="", weight=1.0),
                RubricItem(id="b", name="B", description="", weight=1.0),
            ],
        )
        scores = [
            ItemScore(rubric_item_id="a", score=0.8, passed=True, evidence=""),
            ItemScore(rubric_item_id="b", score=0.6, passed=True, evidence=""),
        ]
        assert compute_overall_score(scores, rubric) == pytest.approx(0.7)

    def test_weighted_scores(self, sample_rubric):
        scores = [
            ItemScore(rubric_item_id="quality", score=1.0, passed=True, evidence=""),
            ItemScore(rubric_item_id="completeness", score=0.0, passed=False, evidence=""),
            ItemScore(rubric_item_id="accuracy", score=0.5, passed=False, evidence=""),
        ]
        # (1.0*2.0 + 0.0*1.0 + 0.5*1.5) / (2.0+1.0+1.5) = 2.75 / 4.5
        expected = 2.75 / 4.5
        assert compute_overall_score(scores, sample_rubric) == pytest.approx(expected)

    def test_empty_scores(self, sample_rubric):
        assert compute_overall_score([], sample_rubric) == 0.0


# ---------------------------------------------------------------------------
# aggregate_feedback tests
# ---------------------------------------------------------------------------


class TestAggregateFeedback:
    def test_no_failures(self, passing_scores):
        assert aggregate_feedback(passing_scores) == ""

    def test_with_failures(self, mixed_scores):
        feedback = aggregate_feedback(mixed_scores)
        assert "completeness" in feedback
        assert "accuracy" in feedback
        assert "Cover all 12 checks" in feedback

    def test_all_failures(self, failing_scores):
        feedback = aggregate_feedback(failing_scores)
        assert "quality" in feedback
        assert "completeness" in feedback
        assert "accuracy" in feedback


# ---------------------------------------------------------------------------
# EvaluatorAgent base class tests
# ---------------------------------------------------------------------------


class TestEvaluatorAgentBase:
    def test_default_rubric(self):
        agent = EvaluatorAgent()
        assert agent.rubric.name == "default"
        assert agent.rubric.items == []

    def test_custom_rubric(self, sample_rubric):
        agent = EvaluatorAgent(rubric=sample_rubric)
        assert agent.rubric.name == "test_rubric"
        assert len(agent.rubric.items) == 3

    def test_format_rubric(self, sample_rubric):
        agent = EvaluatorAgent(rubric=sample_rubric)
        text = agent._format_rubric()
        assert "test_rubric" in text
        assert "quality" in text
        assert "completeness" in text

    def test_build_evaluation_prompt(self, sample_rubric):
        agent = EvaluatorAgent(rubric=sample_rubric)
        prompt = agent.build_evaluation_prompt(
            "specialist output", "original request", 1
        )
        assert "specialist output" in prompt
        assert "original request" in prompt
        assert "Iteration 1" in prompt

    def test_parse_evaluation_response(self, sample_rubric):
        agent = EvaluatorAgent(rubric=sample_rubric)
        response = (
            "### quality\n"
            "Score: 0.85\n"
            "Evidence: Good output quality\n"
            "Feedback: None\n\n"
            "### completeness\n"
            "Score: 0.6\n"
            "Evidence: Mostly complete\n"
            "Feedback: Add more details\n\n"
            "### accuracy\n"
            "Score: 0.9\n"
            "Evidence: Very accurate\n"
            "Feedback: None\n"
        )
        scores = agent.parse_evaluation_response(response, 1)
        assert len(scores) == 3

        quality_score = next(s for s in scores if s.rubric_item_id == "quality")
        assert quality_score.score == pytest.approx(0.85)
        assert quality_score.passed is True

        completeness_score = next(
            s for s in scores if s.rubric_item_id == "completeness"
        )
        assert completeness_score.score == pytest.approx(0.6)
        assert completeness_score.passed is True  # threshold is 0.6

    def test_parse_missing_items(self, sample_rubric):
        """Items not in response get zero scores."""
        agent = EvaluatorAgent(rubric=sample_rubric)
        response = "### quality\nScore: 0.8\nEvidence: ok\nFeedback: None\n"
        scores = agent.parse_evaluation_response(response, 1)
        # Should have all 3 items (1 parsed + 2 zero)
        assert len(scores) == 3
        zero_scores = [s for s in scores if s.score == 0.0]
        assert len(zero_scores) == 2

    def test_build_result_passing(self, sample_rubric, passing_scores):
        agent = EvaluatorAgent(rubric=sample_rubric)
        result = agent.build_result(passing_scores, 1)
        assert result.passed is True
        assert "APPROVED" in result.summary
        assert result.feedback_for_revision is None

    def test_build_result_failing(self, sample_rubric, failing_scores):
        agent = EvaluatorAgent(rubric=sample_rubric)
        result = agent.build_result(failing_scores, 1)
        assert result.passed is False
        assert "REVISION" in result.summary
        assert result.feedback_for_revision is not None

    def test_heuristic_fallback(self, sample_rubric):
        agent = EvaluatorAgent(rubric=sample_rubric)
        scores = agent._evaluate_heuristic("output", "request")
        assert len(scores) == 3
        assert all(s.score == 0.0 for s in scores)


# ---------------------------------------------------------------------------
# EvaluatorAgent.evaluate_once tests
# ---------------------------------------------------------------------------


class TestEvaluateOnce:
    @pytest.mark.asyncio
    async def test_evaluate_once_heuristic(self, sample_rubric):
        agent = EvaluatorAgent(rubric=sample_rubric)
        result = await agent.evaluate_once("output", "request", 1)
        assert result.passed is False  # heuristic returns zeros

    @pytest.mark.asyncio
    async def test_evaluate_once_with_agent(self, sample_rubric):
        """Test with a mock FoundationAgent."""

        class MockAgent:
            async def run(self, prompt):
                return (
                    "### quality\nScore: 0.9\nEvidence: Great\nFeedback: None\n\n"
                    "### completeness\nScore: 0.8\nEvidence: Full\nFeedback: None\n\n"
                    "### accuracy\nScore: 0.85\nEvidence: Correct\nFeedback: None\n"
                )

        agent = EvaluatorAgent(rubric=sample_rubric)
        result = await agent.evaluate_once("output", "request", 1, MockAgent())
        assert result.passed is True


# ---------------------------------------------------------------------------
# EvaluatorAgent.evaluate_with_refinement tests
# ---------------------------------------------------------------------------


class TestEvaluateWithRefinement:
    @pytest.mark.asyncio
    async def test_passes_first_iteration(self, sample_rubric):
        """Specialist output passes on first try."""
        call_count = 0

        class MockSpecialist:
            name = "test_specialist"

            async def run(self, prompt):
                nonlocal call_count
                call_count += 1
                return "specialist output"

        class PassingEvaluator(EvaluatorAgent):
            name = "passing_eval"

            async def evaluate_once(self, output, request, iteration, agent=None):
                scores = [
                    ItemScore(
                        rubric_item_id=item.id,
                        score=0.9,
                        passed=True,
                        evidence="Good",
                    )
                    for item in self.rubric.items
                ]
                return self.build_result(scores, iteration)

        evaluator = PassingEvaluator(rubric=sample_rubric)
        session = await evaluator.evaluate_with_refinement(
            MockSpecialist(), "request"
        )
        assert session.final_status == "approved"
        assert session.iteration_count == 1
        assert call_count == 1  # only initial run

    @pytest.mark.asyncio
    async def test_improves_and_passes(self, sample_rubric):
        """Specialist fails first, then passes after revision."""
        iteration_scores = [0.5, 0.8]  # fail, then pass

        class MockSpecialist:
            name = "improving_specialist"

            async def run(self, prompt):
                return f"output for: {prompt[:20]}"

        class ImprovingEvaluator(EvaluatorAgent):
            name = "improving_eval"
            _call_count = 0

            async def evaluate_once(self, output, request, iteration, agent=None):
                idx = min(self._call_count, len(iteration_scores) - 1)
                score = iteration_scores[idx]
                self._call_count += 1
                scores = [
                    ItemScore(
                        rubric_item_id=item.id,
                        score=score,
                        passed=score >= item.threshold,
                        evidence=f"Score: {score}",
                        feedback="" if score >= item.threshold else "Improve",
                    )
                    for item in self.rubric.items
                ]
                return self.build_result(scores, iteration)

        evaluator = ImprovingEvaluator(rubric=sample_rubric)
        session = await evaluator.evaluate_with_refinement(
            MockSpecialist(), "request"
        )
        assert session.final_status == "approved"
        assert session.iteration_count == 2
        assert session.improved is True

    @pytest.mark.asyncio
    async def test_escalates_after_max_iterations(self, sample_rubric):
        """Specialist never passes — should escalate."""

        class MockSpecialist:
            name = "bad_specialist"

            async def run(self, prompt):
                return "bad output"

        class FailingEvaluator(EvaluatorAgent):
            name = "failing_eval"

            async def evaluate_once(self, output, request, iteration, agent=None):
                scores = [
                    ItemScore(
                        rubric_item_id=item.id,
                        score=0.2,
                        passed=False,
                        evidence="Bad",
                        feedback="Fix it",
                    )
                    for item in self.rubric.items
                ]
                return self.build_result(scores, iteration)

        evaluator = FailingEvaluator(rubric=sample_rubric)
        session = await evaluator.evaluate_with_refinement(
            MockSpecialist(), "request", max_iterations=2
        )
        assert session.final_status == "escalated"
        assert session.iteration_count == 2

    @pytest.mark.asyncio
    async def test_pre_existing_output(self, sample_rubric):
        """Specialist output provided upfront — should not call specialist.run()."""
        specialist_called = False

        class MockSpecialist:
            name = "should_not_call"

            async def run(self, prompt):
                nonlocal specialist_called
                specialist_called = True
                return "should not be called"

        class PassingEvaluator(EvaluatorAgent):
            name = "passing_eval"

            async def evaluate_once(self, output, request, iteration, agent=None):
                scores = [
                    ItemScore(
                        rubric_item_id=item.id,
                        score=0.9,
                        passed=True,
                        evidence="Good",
                    )
                    for item in self.rubric.items
                ]
                return self.build_result(scores, iteration)

        evaluator = PassingEvaluator(rubric=sample_rubric)
        session = await evaluator.evaluate_with_refinement(
            MockSpecialist(),
            "request",
            specialist_output="pre-existing output",
        )
        assert session.final_status == "approved"
        assert not specialist_called

    @pytest.mark.asyncio
    async def test_single_iteration_escalates(self, sample_rubric):
        """With max_iterations=1, failing output should escalate immediately (no revise)."""

        class MockSpecialist:
            name = "single_iter_specialist"
            run_count = 0

            async def run(self, prompt):
                self.run_count += 1
                return "bad output"

        class FailingEvaluator(EvaluatorAgent):
            name = "failing_eval"

            async def evaluate_once(self, output, request, iteration, agent=None):
                scores = [
                    ItemScore(
                        rubric_item_id=item.id,
                        score=0.3,
                        passed=False,
                        evidence="Bad",
                        feedback="Fix it",
                    )
                    for item in self.rubric.items
                ]
                return self.build_result(scores, iteration)

        specialist = MockSpecialist()
        evaluator = FailingEvaluator(rubric=sample_rubric)
        session = await evaluator.evaluate_with_refinement(
            specialist, "request", max_iterations=1
        )
        assert session.final_status == "escalated"
        assert session.iteration_count == 1
        # Specialist should be called only once (initial run), no revision
        assert specialist.run_count == 1


# ---------------------------------------------------------------------------
# format_session_report tests
# ---------------------------------------------------------------------------


class TestFormatSessionReport:
    def test_approved_report(self, sample_rubric, passing_scores):
        agent = EvaluatorAgent(rubric=sample_rubric)
        result = agent.build_result(passing_scores, 1)
        session = EvaluationSession(
            session_id="test-123",
            specialist_name="test",
            evaluator_name="test_eval",
            rubric=sample_rubric,
            original_request="test request",
            iterations=[
                EvaluationIteration(1, "output", result)
            ],
            final_status="approved",
        )
        report = agent.format_session_report(session)
        assert "APPROVED" in report
        assert "Iteration 1" in report

    def test_escalated_report(self, sample_rubric, failing_scores):
        agent = EvaluatorAgent(rubric=sample_rubric)
        result = agent.build_result(failing_scores, 1)
        session = EvaluationSession(
            session_id="test-456",
            specialist_name="test",
            evaluator_name="test_eval",
            rubric=sample_rubric,
            original_request="test request",
            iterations=[
                EvaluationIteration(1, "output", result)
            ],
            final_status="escalated",
        )
        report = agent.format_session_report(session)
        assert "ESCALATION" in report
        assert "Human review" in report
