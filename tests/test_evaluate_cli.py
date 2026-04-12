"""Tests for the evaluate CLI command and list-evaluators."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from platform_agent.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


class TestListEvaluators:
    def test_list_evaluators(self, runner):
        result = runner.invoke(cli, ["list-evaluators"])
        assert result.exit_code == 0
        assert "design" in result.output
        assert "code_review" in result.output
        assert "scaffold" in result.output
        assert "deployment" in result.output
        assert "Available evaluators (4)" in result.output

    def test_list_evaluators_rubric_counts(self, runner):
        result = runner.invoke(cli, ["list-evaluators"])
        assert "5 rubric items" in result.output  # all evaluators have 5 items


class TestEvaluateCommand:
    def test_evaluate_help(self, runner):
        result = runner.invoke(cli, ["evaluate", "--help"])
        assert result.exit_code == 0
        assert "reflect-refine" in result.output.lower()
        assert "readiness" in result.output
        assert "review" in result.output

    def test_evaluate_invalid_skill(self, runner):
        result = runner.invoke(cli, ["evaluate", "nonexistent"])
        assert result.exit_code != 0


class TestOrchestrateEvaluateFlag:
    def test_orchestrate_help_shows_evaluate(self, runner):
        result = runner.invoke(cli, ["orchestrate", "--help"])
        assert result.exit_code == 0
        assert "--evaluate" in result.output

    def test_orchestrate_help_shows_max_iterations(self, runner):
        result = runner.invoke(cli, ["orchestrate", "--help"])
        assert "--max-iterations" in result.output


class TestDetectEvaluator:
    def test_detect_design(self):
        from platform_agent.cli import _detect_evaluator
        assert _detect_evaluator("check platform readiness") == "design"
        assert _detect_evaluator("is this agent ready for deployment?") == "design"

    def test_detect_code_review(self):
        from platform_agent.cli import _detect_evaluator
        assert _detect_evaluator("review this codebase") == "code_review"
        assert _detect_evaluator("security audit") == "code_review"

    def test_detect_scaffold(self):
        from platform_agent.cli import _detect_evaluator
        assert _detect_evaluator("scaffold a new project") == "scaffold"
        assert _detect_evaluator("generate a weather agent") == "scaffold"

    def test_detect_deployment(self):
        from platform_agent.cli import _detect_evaluator
        assert _detect_evaluator("generate deployment config") == "deployment"
        assert _detect_evaluator("create IAM policy") == "deployment"

    def test_detect_none(self):
        from platform_agent.cli import _detect_evaluator
        assert _detect_evaluator("hello world") is None
