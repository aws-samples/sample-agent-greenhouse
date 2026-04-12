"""Tests for specialist evaluators (design, code_review, scaffold, deployment)."""

from __future__ import annotations

import pytest

from platform_agent.plato.evaluator import discover_evaluators, get_evaluator, list_evaluators
from platform_agent.plato.evaluator.design import DesignEvaluator
from platform_agent.plato.evaluator.code_review import CodeReviewEvaluator
from platform_agent.plato.evaluator.scaffold import ScaffoldEvaluator
from platform_agent.plato.evaluator.deployment import DeployConfigEvaluator


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestEvaluatorRegistry:
    def test_discover(self):
        discover_evaluators()
        names = list_evaluators()
        assert "design" in names
        assert "code_review" in names
        assert "scaffold" in names
        assert "deployment" in names

    def test_get_evaluator(self):
        cls = get_evaluator("design")
        assert cls is DesignEvaluator

    def test_get_unknown_evaluator(self):
        with pytest.raises(KeyError, match="Unknown evaluator"):
            get_evaluator("nonexistent_evaluator_xyz")


# ---------------------------------------------------------------------------
# DesignEvaluator tests
# ---------------------------------------------------------------------------


class TestDesignEvaluator:
    def test_rubric(self):
        evaluator = DesignEvaluator()
        assert evaluator.name == "design"
        assert evaluator.rubric.name == "design_review_rubric"
        assert len(evaluator.rubric.items) == 5

    def test_rubric_item_ids(self):
        evaluator = DesignEvaluator()
        ids = {item.id for item in evaluator.rubric.items}
        assert ids == {
            "completeness",
            "accuracy",
            "actionability",
            "severity_calibration",
            "evidence_quality",
        }

    def test_heuristic_complete_output(self):
        """Output mentioning all C1-C12 should score well on completeness."""
        evaluator = DesignEvaluator()
        output = (
            "C1 Containerizable ✅ PASS - Dockerfile found\n"
            "C2 No hardcoded secrets ❌ FAIL BLOCKER - Found sk-proj in agent.py:15\n"
            "C3 Environment config ⚠️ WARNING - Some hardcoded values\n"
            "C4 Health check ✅ PASS\n"
            "C5 Stateless ✅ PASS\n"
            "C6 Graceful shutdown ℹ INFO\n"
            "C7 Logging stdout ℹ INFO\n"
            "C8 Error handling ⚠️ WARNING - bare except at line 28\n"
            "C9 Dependencies ✅ PASS - pyproject.toml present\n"
            "C10 Framework ℹ INFO\n"
            "C11 MCP safety ✅ PASS\n"
            "C12 Memory pattern ℹ INFO\n"
            "Fix: Replace hardcoded key with os.getenv('API_KEY')\n"
            "Add proper error handling in agent.py\n"
            "```python\n# example fix\n```"
        )
        scores = evaluator._evaluate_heuristic(output, "readiness check")

        completeness = next(s for s in scores if s.rubric_item_id == "completeness")
        assert completeness.score == pytest.approx(1.0)
        assert completeness.passed is True

        severity = next(s for s in scores if s.rubric_item_id == "severity_calibration")
        assert severity.score >= 0.7  # has BLOCKER, WARNING, INFO

    def test_heuristic_incomplete_output(self):
        """Output missing most checks should score poorly."""
        evaluator = DesignEvaluator()
        output = "The agent looks fine. No major issues found."
        scores = evaluator._evaluate_heuristic(output, "readiness check")

        completeness = next(s for s in scores if s.rubric_item_id == "completeness")
        assert completeness.score < 0.3
        assert completeness.passed is False

    def test_build_evaluation_prompt(self):
        evaluator = DesignEvaluator()
        prompt = evaluator.build_evaluation_prompt(
            "specialist output", "check readiness", 1
        )
        assert "quality evaluator" in prompt.lower()
        assert "C1-C12" in prompt
        assert "completeness" in prompt


# ---------------------------------------------------------------------------
# CodeReviewEvaluator tests
# ---------------------------------------------------------------------------


class TestCodeReviewEvaluator:
    def test_rubric(self):
        evaluator = CodeReviewEvaluator()
        assert evaluator.name == "code_review"
        assert len(evaluator.rubric.items) == 5

    def test_rubric_item_ids(self):
        evaluator = CodeReviewEvaluator()
        ids = {item.id for item in evaluator.rubric.items}
        assert ids == {
            "coverage",
            "accuracy",
            "security_depth",
            "fix_quality",
            "prioritization",
        }

    def test_heuristic_good_review(self):
        """A thorough review should score well."""
        evaluator = CodeReviewEvaluator()
        output = (
            "🔴 Critical: 2 findings\n\n"
            "1. [critical] agent.py:15 — Hardcoded API key (credential exposure)\n"
            "   Risk: Key exposed in version control, can be scraped\n"
            "   Fix: Replace with os.getenv('API_KEY')\n"
            "   ```python\n   api_key = os.getenv('API_KEY')\n   ```\n\n"
            "2. [critical] agent.py:28 — eval() on user input (injection vulnerability)\n"
            "   Risk: Remote code execution\n"
            "   Fix: Use structured parsing instead\n\n"
            "🟡 Important: 1 finding\n"
            "1. [important] health.py:5 — No timeout on health check\n\n"
            "🟢 Suggestion: 1 finding\n"
            "1. [suggestion] utils.py:10 — Consider adding type hints\n"
        )
        scores = evaluator._evaluate_heuristic(output, "review")

        coverage = next(s for s in scores if s.rubric_item_id == "coverage")
        assert coverage.score > 0  # references .py files

        security = next(s for s in scores if s.rubric_item_id == "security_depth")
        assert security.score >= 0.7  # mentions injection, credential

        prioritization = next(s for s in scores if s.rubric_item_id == "prioritization")
        assert prioritization.score >= 0.7  # has all 3 levels

    def test_heuristic_shallow_review(self):
        """A shallow review should score poorly."""
        evaluator = CodeReviewEvaluator()
        output = "The code looks OK. Maybe add some tests."
        scores = evaluator._evaluate_heuristic(output, "review")

        coverage = next(s for s in scores if s.rubric_item_id == "coverage")
        assert coverage.score < 0.5


# ---------------------------------------------------------------------------
# ScaffoldEvaluator tests
# ---------------------------------------------------------------------------


class TestScaffoldEvaluator:
    def test_rubric(self):
        evaluator = ScaffoldEvaluator()
        assert evaluator.name == "scaffold"
        assert len(evaluator.rubric.items) == 5

    def test_heuristic_good_scaffold(self):
        evaluator = ScaffoldEvaluator()
        output = (
            "Generated project structure:\n"
            "- pyproject.toml (dependencies: claude-agent-sdk, click)\n"
            "- Dockerfile (multi-stage, non-root user, HEALTHCHECK)\n"
            "- src/agent.py (import os; config = os.getenv('MODEL'))\n"
            "- src/health.py (GET /health endpoint)\n"
            "- tests/test_agent.py (assert response.status == 200)\n"
            "- README.md\n"
            "- .gitignore\n"
            "SIGTERM handler included for graceful shutdown.\n"
            "Logging configured to stdout.\n"
        )
        scores = evaluator._evaluate_heuristic(output, "scaffold")

        completeness = next(s for s in scores if s.rubric_item_id == "completeness")
        assert completeness.score >= 0.7

        readiness = next(s for s in scores if s.rubric_item_id == "readiness")
        assert readiness.score >= 0.7

    def test_heuristic_minimal_scaffold(self):
        evaluator = ScaffoldEvaluator()
        output = "Created a basic Python file."
        scores = evaluator._evaluate_heuristic(output, "scaffold")

        completeness = next(s for s in scores if s.rubric_item_id == "completeness")
        assert completeness.score < 0.5


# ---------------------------------------------------------------------------
# DeployConfigEvaluator tests
# ---------------------------------------------------------------------------


class TestDeployConfigEvaluator:
    def test_rubric(self):
        evaluator = DeployConfigEvaluator()
        assert evaluator.name == "deployment"
        assert len(evaluator.rubric.items) == 5

    def test_heuristic_good_config(self):
        evaluator = DeployConfigEvaluator()
        output = (
            "Generated deployment configuration:\n\n"
            "## Dockerfile\n"
            "FROM python:3.11-slim AS builder\n"
            "COPY requirements.txt .\n"
            "RUN pip install -r requirements.txt\n"
            "FROM python:3.11-slim\n"
            "RUN useradd -r agent\n"
            "HEALTHCHECK CMD python -c 'import urllib'\n\n"
            "## buildspec.yml\n"
            "phases:\n  build:\n    commands:\n      - docker build\n\n"
            "## iam-policy.json\n"
            '{"Statement": [{"Action": "bedrock:InvokeModel", '
            '"Resource": "arn:aws:bedrock:*:*:model/*"}]}\n'
            'Also: "logs:CreateLogGroup"\n\n'
            "## cdk/app_stack.py\n"
            "from aws_cdk import Stack\n"
            "class PlatoStack(Stack):\n"
            "    ecr_repository = ecr.Repository()\n\n"
            "## runtime-config.yaml\n"
            "cpu: 1024\nmemory: 2048\n\n"
            "## .env.template\n"
            "MODEL_ID=${BEDROCK_MODEL_ID}\n"
            "API_KEY=${SECRET_API_KEY}\n"
        )
        scores = evaluator._evaluate_heuristic(output, "deploy-config")

        docker = next(s for s in scores if s.rubric_item_id == "dockerfile_quality")
        assert docker.score >= 0.7

        completeness = next(s for s in scores if s.rubric_item_id == "config_completeness")
        assert completeness.score >= 0.7

        env = next(s for s in scores if s.rubric_item_id == "env_safety")
        assert env.score >= 0.7  # has placeholders, template

    def test_heuristic_insecure_config(self):
        evaluator = DeployConfigEvaluator()
        output = (
            "iam-policy.json: {\"Action\": \"*\", \"Resource\": \"*\"}\n"
            "password = 'hunter2'\n"
            "AKIA1234567890ABCDEF\n"
        )
        scores = evaluator._evaluate_heuristic(output, "deploy-config")

        iam = next(s for s in scores if s.rubric_item_id == "iam_least_privilege")
        assert iam.score < 0.5

        env = next(s for s in scores if s.rubric_item_id == "env_safety")
        assert env.score < 0.5
