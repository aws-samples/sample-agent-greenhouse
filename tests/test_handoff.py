"""Tests for human handoff agent."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from platform_agent.cli import cli
from platform_agent.foundation.handoff import (
    CLIHandoffChannel,
    HandoffAgent,
    HandoffRequest,
    HandoffStatus,
)
from platform_agent.foundation.handoff.agent import HandoffPriority


# ---------------------------------------------------------------------------
# HandoffRequest tests
# ---------------------------------------------------------------------------


class TestHandoffRequest:
    def test_default_fields(self):
        req = HandoffRequest()
        assert req.request_id  # non-empty
        assert req.timestamp > 0
        assert req.status == HandoffStatus.PENDING
        assert req.priority == HandoffPriority.MEDIUM
        assert not req.is_evaluator_escalation

    def test_evaluator_escalation_flag(self):
        req = HandoffRequest(evaluation_report="some report")
        assert req.is_evaluator_escalation

    def test_to_dict(self):
        req = HandoffRequest(
            source_agent="test-agent",
            reason="confidence low",
            summary="Need human review",
        )
        d = req.to_dict()
        assert d["source_agent"] == "test-agent"
        assert d["reason"] == "confidence low"
        assert d["status"] == "pending"
        assert d["priority"] == "medium"

    def test_custom_priority(self):
        req = HandoffRequest(priority=HandoffPriority.CRITICAL)
        assert req.priority == HandoffPriority.CRITICAL
        assert req.to_dict()["priority"] == "critical"


# ---------------------------------------------------------------------------
# CLIHandoffChannel tests
# ---------------------------------------------------------------------------


class TestCLIHandoffChannel:
    @pytest.mark.asyncio
    async def test_send(self):
        channel = CLIHandoffChannel()
        req = HandoffRequest(source_agent="test", reason="test reason")
        result = await channel.send(req)
        assert result is True
        assert len(channel.pending_requests) == 1

    @pytest.mark.asyncio
    async def test_poll_no_response(self):
        channel = CLIHandoffChannel()
        result = await channel.poll("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_and_poll(self):
        channel = CLIHandoffChannel()
        req = HandoffRequest(source_agent="test")
        await channel.send(req)

        response = channel.resolve(req.request_id, "approve", "looks good")
        assert response.status == HandoffStatus.RESOLVED
        assert response.decision == "approve"

        polled = await channel.poll(req.request_id)
        assert polled is not None
        assert polled.decision == "approve"

    def test_resolve_nonexistent_raises(self):
        channel = CLIHandoffChannel()
        with pytest.raises(KeyError, match="No pending"):
            channel.resolve("nonexistent", "approve")

    @pytest.mark.asyncio
    async def test_resolve_reject(self):
        channel = CLIHandoffChannel()
        req = HandoffRequest(source_agent="test")
        await channel.send(req)

        response = channel.resolve(req.request_id, "reject", "not ready")
        assert response.status == HandoffStatus.REJECTED

    @pytest.mark.asyncio
    async def test_pending_requests_excludes_resolved(self):
        channel = CLIHandoffChannel()
        req1 = HandoffRequest(source_agent="test1")
        req2 = HandoffRequest(source_agent="test2")
        await channel.send(req1)
        await channel.send(req2)
        assert len(channel.pending_requests) == 2

        channel.resolve(req1.request_id, "approve")
        assert len(channel.pending_requests) == 1
        assert channel.pending_requests[0].request_id == req2.request_id


# ---------------------------------------------------------------------------
# HandoffAgent tests
# ---------------------------------------------------------------------------


class TestHandoffAgent:
    def test_create_request(self):
        agent = HandoffAgent()
        req = agent.create_request(
            source_agent="design-advisor",
            reason="Low confidence",
            summary="Need review",
        )
        assert req.source_agent == "design-advisor"
        assert req.reason == "Low confidence"
        assert req.request_id in [r.request_id for r in agent.pending_requests]

    @pytest.mark.asyncio
    async def test_escalate(self):
        agent = HandoffAgent()
        req = agent.create_request(
            source_agent="test",
            reason="test reason",
            summary="test summary",
        )
        result = await agent.escalate(req)
        assert result is True
        assert req.status == HandoffStatus.PENDING

    @pytest.mark.asyncio
    async def test_check_status_pending(self):
        agent = HandoffAgent()
        req = agent.create_request(
            source_agent="test",
            reason="test",
            summary="test",
        )
        await agent.escalate(req)
        response = await agent.check_status(req.request_id)
        assert response is None  # No response yet

    @pytest.mark.asyncio
    async def test_check_status_resolved(self):
        channel = CLIHandoffChannel()
        agent = HandoffAgent(channel=channel)
        req = agent.create_request(
            source_agent="test",
            reason="test",
            summary="test",
        )
        await agent.escalate(req)

        # Simulate human response
        channel.resolve(req.request_id, "approve", "good to go", "reviewer-1")

        response = await agent.check_status(req.request_id)
        assert response is not None
        assert response.decision == "approve"
        assert response.reviewer == "reviewer-1"
        # Agent's internal request should be updated
        assert agent.get_request(req.request_id).status == HandoffStatus.RESOLVED

    def test_get_request(self):
        agent = HandoffAgent()
        req = agent.create_request(
            source_agent="test",
            reason="test",
            summary="test",
        )
        found = agent.get_request(req.request_id)
        assert found is req

    def test_get_request_nonexistent(self):
        agent = HandoffAgent()
        assert agent.get_request("nonexistent") is None

    def test_format_handoff_report(self):
        agent = HandoffAgent()
        req = agent.create_request(
            source_agent="evaluator:design",
            reason="Evaluator escalation after 3 iterations",
            summary="Design review failed",
            priority=HandoffPriority.HIGH,
        )
        report = agent.format_handoff_report(req)
        assert "HUMAN REVIEW REQUIRED" in report
        assert "evaluator:design" in report
        assert "HIGH" in report

    def test_format_with_evaluation_report(self):
        agent = HandoffAgent()
        req = HandoffRequest(
            source_agent="evaluator:code_review",
            reason="Escalation",
            summary="Code review failed",
            evaluation_report="Evaluator: code_review\nIterations: 3\nLast Score: 60%",
        )
        report = agent.format_handoff_report(req)
        assert "Evaluation Details" in report
        assert "Last Score: 60%" in report

    def test_format_with_conversation_history(self):
        agent = HandoffAgent()
        req = HandoffRequest(
            source_agent="test",
            reason="test",
            summary="test",
            conversation_history=["User: help", "Agent: here's my analysis"],
        )
        report = agent.format_handoff_report(req)
        assert "Conversation History" in report
        assert "help" in report

    def test_pending_requests(self):
        agent = HandoffAgent()
        agent.create_request(
            source_agent="a", reason="r", summary="s"
        )
        agent.create_request(
            source_agent="b", reason="r", summary="s"
        )
        assert len(agent.pending_requests) == 2

    def test_auto_escalate_threshold(self):
        agent = HandoffAgent(auto_escalate_threshold=0.3)
        assert agent.auto_escalate_threshold == 0.3


# ---------------------------------------------------------------------------
# create_from_evaluation tests
# ---------------------------------------------------------------------------


class TestCreateFromEvaluation:
    """Test creating handoff requests from evaluator sessions."""

    def _make_mock_session(self, evaluator_name="design", iterations=3, score=0.6, threshold=0.8):
        """Create a mock evaluation session."""
        from dataclasses import dataclass, field as dc_field

        @dataclass
        class MockScore:
            rubric_item_id: str = "item-1"
            score: float = 0.5
            passed: bool = False
            evidence: str = "test evidence"
            feedback: str = "needs improvement"

        @dataclass
        class MockEvaluation:
            overall_score: float = 0.6
            threshold: float = 0.8
            item_scores: list = dc_field(default_factory=lambda: [MockScore()])
            summary: str = "evaluation summary"

        @dataclass
        class MockIteration:
            iteration_number: int = 1
            evaluation: MockEvaluation = dc_field(default_factory=MockEvaluation)

        @dataclass
        class MockSession:
            session_id: str = "test-session"
            evaluator_name: str = "design"
            final_status: str = "escalated"
            iteration_count: int = 3
            iterations: list = dc_field(default_factory=lambda: [MockIteration()])

        return MockSession(
            evaluator_name=evaluator_name,
            iteration_count=iterations,
            iterations=[
                MockIteration(
                    iteration_number=i + 1,
                    evaluation=MockEvaluation(
                        overall_score=score,
                        threshold=threshold,
                    ),
                )
                for i in range(iterations)
            ],
        )

    def test_create_from_evaluation(self):
        agent = HandoffAgent()
        session = self._make_mock_session()
        req = agent.create_from_evaluation(session)

        assert req.source_agent == "evaluator:design"
        assert req.is_evaluator_escalation
        assert req.iteration_count == 3
        assert req.last_score == 0.6
        assert req.threshold == 0.8
        assert req.priority == HandoffPriority.HIGH
        assert "design" in req.reason
        assert "60%" in req.summary

    def test_create_from_evaluation_report_content(self):
        agent = HandoffAgent()
        session = self._make_mock_session()
        req = agent.create_from_evaluation(session)

        assert "Evaluator: design" in req.evaluation_report
        assert "Iterations: 3" in req.evaluation_report
        assert "Failed items:" in req.evaluation_report

    def test_create_from_evaluation_empty_iterations(self):
        agent = HandoffAgent()
        from dataclasses import dataclass, field as dc_field

        @dataclass
        class EmptySession:
            session_id: str = "empty"
            evaluator_name: str = "test"
            final_status: str = "escalated"
            iteration_count: int = 0
            iterations: list = dc_field(default_factory=list)

        session = EmptySession()
        req = agent.create_from_evaluation(session)
        assert req.last_score == 0.0
        assert req.threshold == 0.0

    def test_create_from_real_evaluation_session(self):
        """Integration test using real EvaluationSession objects."""
        from platform_agent.plato.evaluator.base import (
            EvaluationIteration,
            EvaluationResult,
            EvaluationRubric,
            EvaluationSession,
            ItemScore,
            RubricItem,
        )

        rubric = EvaluationRubric(
            name="test-rubric",
            version="1.0",
            items=[RubricItem(id="item-1", name="Test Item", description="Test", weight=1.0, threshold=0.7)],
            overall_threshold=0.8,
        )
        result = EvaluationResult(
            rubric_name="test-rubric",
            iteration=1,
            item_scores=[ItemScore(rubric_item_id="item-1", score=0.5, passed=False, evidence="test", feedback="needs work")],
            overall_score=0.5,
            passed=False,
            summary="Did not pass",
        )
        iteration = EvaluationIteration(
            iteration_number=1,
            specialist_output="test output",
            evaluation=result,
        )
        session = EvaluationSession(
            session_id="real-session",
            specialist_name="test-specialist",
            evaluator_name="design",
            rubric=rubric,
            original_request="review my design",
            iterations=[iteration],
            final_status="escalated",
        )

        agent = HandoffAgent()
        req = agent.create_from_evaluation(session)
        assert req.last_score == 0.5
        assert req.threshold == 0.8  # From rubric, not from result
        assert req.source_agent == "evaluator:design"
        assert "design" in req.reason


# ---------------------------------------------------------------------------
# Validation and edge case tests
# ---------------------------------------------------------------------------


class TestHandoffValidation:
    def test_invalid_decision_raises(self):
        channel = CLIHandoffChannel()
        import asyncio
        req = HandoffRequest(source_agent="test")
        asyncio.run(channel.send(req))
        with pytest.raises(ValueError, match="Invalid decision"):
            channel.resolve(req.request_id, "invalid_decision")

    def test_age_property(self):
        req = HandoffRequest()
        assert req.age >= 0
        assert req.age < 5  # Should be very recent


# ---------------------------------------------------------------------------
# Handoff CLI tests
# ---------------------------------------------------------------------------


class TestHandoffCLI:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_handoff_help(self, runner):
        result = runner.invoke(cli, ["handoff", "--help"])
        assert result.exit_code == 0
        assert "handoff" in result.output.lower()

    def test_handoff_list_empty(self, runner):
        result = runner.invoke(cli, ["handoff", "list"])
        assert result.exit_code == 0
        assert "No pending" in result.output

    def test_handoff_show_nonexistent(self, runner):
        result = runner.invoke(cli, ["handoff", "show", "nonexistent"])
        assert result.exit_code == 0
        assert "No handoff request found" in result.output

    def test_handoff_resolve_nonexistent(self, runner):
        result = runner.invoke(cli, ["handoff", "resolve", "nonexistent", "approve"])
        assert result.exit_code == 0
        assert "No pending request" in result.output
