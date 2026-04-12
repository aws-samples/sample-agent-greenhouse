"""Integration tests for evaluator + specialist skill E2E flows.

Tests the full pipeline: sample app code → specialist skill evaluation →
evaluator heuristic scoring → verify expected pass/fail outcomes.

These tests use the actual sample apps in examples/ and the real heuristic
evaluators (no LLM calls — all heuristic-based).
"""

from __future__ import annotations

import asyncio

import pytest

from platform_agent.plato.evaluator import get_evaluator, list_evaluators
from platform_agent.plato.evaluator.base import (
    EvaluationSession,
)
from platform_agent.plato.evaluator.design import DesignEvaluator
from platform_agent.plato.evaluator.code_review import CodeReviewEvaluator
from platform_agent.plato.evaluator.scaffold import ScaffoldEvaluator
from platform_agent.plato.evaluator.deployment import DeployConfigEvaluator


# ---------------------------------------------------------------------------
# Fixtures — realistic specialist output samples
# ---------------------------------------------------------------------------

GOOD_READINESS_OUTPUT = """\
# Platform Readiness Assessment: good-weather-agent

## Summary
Overall: READY ✅ (12/12 checks passed, 0 blockers, 0 warnings)

## Checklist

### C1 — Containerizable 🔴 BLOCKER → PASS ✅
The project includes a well-structured Dockerfile at `./Dockerfile` (line 1-25).
Multi-stage build, slim base image, HEALTHCHECK directive present.

### C2 — No Hardcoded Secrets 🔴 BLOCKER → PASS ✅
Scanned all .py files. No API keys, passwords, or tokens found in source.
Config uses `os.getenv("ANTHROPIC_API_KEY")` in `agent.py:15`.

### C3 — Environment-based Config 🟡 WARNING → PASS ✅
All configuration loaded via `os.getenv()` in `agent.py:12-20`.
```python
model = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
```

### C4 — Health Check Endpoint 🟡 WARNING → PASS ✅
HTTP `/health` endpoint at `health.py:8` returns `{"status": "healthy"}`.

### C5 — Stateless Design 🟡 WARNING → PASS ✅
No local file writes. State managed via AgentCore Memory.

### C6 — Graceful Shutdown 🟢 INFO → PASS ✅
SIGTERM handler in `agent.py:45`:
```python
signal.signal(signal.SIGTERM, lambda s, f: shutdown())
```

### C7 — Logging to stdout 🟢 INFO → PASS ✅
`logging.basicConfig(stream=sys.stdout)` at `agent.py:5`.

### C8 — Error Handling 🟡 WARNING → PASS ✅
All external calls wrapped in try/except with meaningful messages.

### C9 — Dependency Management 🟡 WARNING → PASS ✅
`pyproject.toml` with pinned versions: `claude-agent-sdk>=0.1.0,<0.2.0`.

### C10 — Agent Framework 🟢 INFO → PASS ✅
Uses Claude Agent SDK (Foundation Agent pattern).

### C11 — MCP Tool Safety 🟡 WARNING → PASS ✅
Tool inputs validated with pydantic models. No arbitrary code execution.

### C12 — Memory Pattern 🟢 INFO → PASS ✅
Uses AgentCore Memory for session context. Compatible with hosted runtime.
"""

BAD_READINESS_OUTPUT = """\
# Readiness Check

The agent looks mostly fine. It has some code and a README.

C1: Has Docker — yes
C3: Uses env vars — maybe

No major issues found.
"""

GOOD_REVIEW_OUTPUT = """\
# Code Review: bad-secrets-agent

## Critical Issues 🔴

### 1. Hardcoded API Key (Critical)
File: `agent.py:8`
```python
API_KEY = "sk-ant-api03-realkey123456789"
```
**Fix**: Move to environment variable:
```python
API_KEY = os.getenv("ANTHROPIC_API_KEY")
```

### 2. Hardcoded Database Password (Critical)
File: `agent.py:12`
```python
DB_PASSWORD = "admin123"
```
**Fix**: Use AWS Secrets Manager or environment variable.

### 3. Eval Usage (Critical)
File: `agent.py:30`
```python
result = eval(user_input)  # prompt injection risk
```
**Fix**: Replace with safe parsing: `json.loads(user_input)`.

## Important Issues 🟡

### 4. No Input Validation (Important)
File: `agent.py:25-35`
Tool inputs are not validated. Could lead to injection attacks.
**Fix**: Add pydantic models for tool input validation.

## Suggestions 🟢

### 5. Missing Type Hints (Suggestion)
Several functions lack type annotations.
**Fix**: Add return type hints to all public functions.
"""

SHALLOW_REVIEW_OUTPUT = """\
The code looks OK. No issues found.
"""

GOOD_SCAFFOLD_OUTPUT = """\
# Generated Project: my-weather-agent

## Files Created

### pyproject.toml
```toml
[project]
name = "my-weather-agent"
dependencies = ["claude-agent-sdk>=0.1.0"]
```

### Dockerfile
```dockerfile
FROM python:3.11-slim AS builder
COPY requirements.txt .
RUN pip install -r requirements.txt
FROM python:3.11-slim
COPY --from=builder /usr/local /usr/local
RUN useradd -m agent
USER agent
HEALTHCHECK CMD curl -f http://localhost:8080/health
COPY src/ /app/src/
```

### src/my_weather_agent/agent.py
```python
import os
import sys
import signal
import logging

logging.basicConfig(stream=sys.stdout, level=logging.INFO)

def shutdown():
    logging.info("Shutting down gracefully")
    sys.exit(0)

signal.signal(signal.SIGTERM, lambda s, f: shutdown())

MODEL = os.getenv("MODEL_ID", "claude-sonnet-4-20250514")
```

### src/my_weather_agent/health.py
```python
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status": "healthy"}')
```

### tests/test_agent.py
```python
def test_agent_imports():
    from my_weather_agent.agent import MODEL
    assert MODEL is not None

def test_health_endpoint():
    from my_weather_agent.health import HealthHandler
    assert HealthHandler is not None
```

### .gitignore
```
.env
__pycache__/
*.pyc
```

### README.md
Quick start guide for my-weather-agent.
"""

GOOD_DEPLOY_CONFIG = """\
# Deployment Configuration: weather-agent

## IAM Policy (iam-policy.json)
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream"
            ],
            "Resource": "arn:aws:bedrock:us-west-2:*:foundation-model/anthropic.*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:us-west-2:*:log-group:/aws/agentcore/*"
        }
    ]
}
```

## Dockerfile
```dockerfile
FROM python:3.11-slim AS builder
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
FROM python:3.11-slim
RUN useradd -m agent
COPY --from=builder /usr/local /usr/local
COPY src/ /app/
WORKDIR /app
USER agent
HEALTHCHECK --interval=30s CMD curl -f http://localhost:8080/health || exit 1
CMD ["python", "-m", "weather_agent"]
```

## CDK Stack (cdk/weather_stack.py)
```python
from aws_cdk import Stack
import aws_cdk.aws_iam as iam
import aws_cdk.aws_ecr as ecr_repository
import aws_cdk.aws_cloudwatch as cloudwatch

class WeatherAgentStack(Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        # Agent runtime configuration
```

## buildspec.yml
```yaml
version: 0.2
phases:
  build:
    commands:
      - docker build -t weather-agent .
```

## runtime-config.yaml
```yaml
runtime: agentcore
memory_id: ${MEMORY_ID}
```

## .env.template
```
# Copy to .env and fill in values
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
MODEL_ID=claude-sonnet-4-20250514
MEMORY_ID=${AGENTCORE_MEMORY_ID}
```
"""


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestEvaluatorE2EWithSampleOutput:
    """Test evaluator heuristics against realistic specialist output."""

    def test_good_readiness_passes_design_evaluator(self):
        evaluator = DesignEvaluator()
        scores = evaluator._evaluate_heuristic(GOOD_READINESS_OUTPUT, "check readiness")
        result = evaluator.build_result(scores, iteration=1)
        assert result.passed, f"Good readiness should pass, got {result.overall_score:.0%}: {result.summary}"
        assert result.overall_score >= 0.7

    def test_bad_readiness_fails_design_evaluator(self):
        evaluator = DesignEvaluator()
        scores = evaluator._evaluate_heuristic(BAD_READINESS_OUTPUT, "check readiness")
        result = evaluator.build_result(scores, iteration=1)
        assert not result.passed, f"Bad readiness should fail, got {result.overall_score:.0%}"
        assert result.feedback_for_revision is not None
        assert len(result.feedback_for_revision) > 0

    def test_good_review_passes_code_review_evaluator(self):
        evaluator = CodeReviewEvaluator()
        scores = evaluator._evaluate_heuristic(GOOD_REVIEW_OUTPUT, "review code")
        result = evaluator.build_result(scores, iteration=1)
        assert result.passed, f"Good review should pass, got {result.overall_score:.0%}: {result.summary}"

    def test_shallow_review_fails_code_review_evaluator(self):
        evaluator = CodeReviewEvaluator()
        scores = evaluator._evaluate_heuristic(SHALLOW_REVIEW_OUTPUT, "review code")
        result = evaluator.build_result(scores, iteration=1)
        assert not result.passed, f"Shallow review should fail, got {result.overall_score:.0%}"

    def test_good_scaffold_passes_scaffold_evaluator(self):
        evaluator = ScaffoldEvaluator()
        scores = evaluator._evaluate_heuristic(GOOD_SCAFFOLD_OUTPUT, "scaffold agent")
        result = evaluator.build_result(scores, iteration=1)
        assert result.passed, f"Good scaffold should pass, got {result.overall_score:.0%}: {result.summary}"

    def test_good_deploy_config_passes_deployment_evaluator(self):
        evaluator = DeployConfigEvaluator()
        scores = evaluator._evaluate_heuristic(GOOD_DEPLOY_CONFIG, "generate deploy config")
        result = evaluator.build_result(scores, iteration=1)
        assert result.passed, f"Good deploy config should pass, got {result.overall_score:.0%}: {result.summary}"


class TestReflectRefineIntegration:
    """Test the full reflect-refine loop with mock specialists."""

    @pytest.fixture
    def mock_specialist(self):
        """A mock specialist that improves output on each call."""
        class MockSpecialist:
            name = "mock_specialist"
            call_count = 0

            async def run(self, prompt: str) -> str:
                self.call_count += 1
                if self.call_count == 1:
                    # First call: bad output
                    return BAD_READINESS_OUTPUT
                else:
                    # Second call: improved output
                    return GOOD_READINESS_OUTPUT

        return MockSpecialist()

    @pytest.fixture
    def stubborn_specialist(self):
        """A specialist that never improves."""
        class StubbornSpecialist:
            name = "stubborn"

            async def run(self, prompt: str) -> str:
                return BAD_READINESS_OUTPUT

        return StubbornSpecialist()

    def test_loop_improves_and_passes(self, mock_specialist):
        evaluator = DesignEvaluator()
        session = asyncio.get_event_loop().run_until_complete(
            evaluator.evaluate_with_refinement(
                specialist=mock_specialist,
                original_request="check readiness for good-weather-agent",
                specialist_output=BAD_READINESS_OUTPUT,  # start with bad
            )
        )
        assert session.final_status == "approved"
        assert session.iteration_count >= 2  # at least 1 fail + 1 pass
        assert session.improved

    def test_loop_escalates_stubborn_specialist(self, stubborn_specialist):
        evaluator = DesignEvaluator()
        session = asyncio.get_event_loop().run_until_complete(
            evaluator.evaluate_with_refinement(
                specialist=stubborn_specialist,
                original_request="check readiness",
                specialist_output=BAD_READINESS_OUTPUT,
                max_iterations=2,
            )
        )
        assert session.final_status == "escalated"
        assert session.iteration_count == 2

    def test_loop_passes_first_try_with_good_output(self, mock_specialist):
        evaluator = DesignEvaluator()
        session = asyncio.get_event_loop().run_until_complete(
            evaluator.evaluate_with_refinement(
                specialist=mock_specialist,
                original_request="check readiness",
                specialist_output=GOOD_READINESS_OUTPUT,  # start with good
            )
        )
        assert session.final_status == "approved"
        assert session.iteration_count == 1  # no revision needed
        assert not session.improved  # only 1 iteration, can't improve


class TestEvaluatorSessionReport:
    """Test report formatting for integration scenarios."""

    def test_approved_report_has_checkmarks(self):
        evaluator = DesignEvaluator()
        scores = evaluator._evaluate_heuristic(GOOD_READINESS_OUTPUT, "check readiness")
        result = evaluator.build_result(scores, iteration=1)

        session = EvaluationSession(
            session_id="test-123",
            specialist_name="design_advisor",
            evaluator_name="design",
            rubric=evaluator.rubric,
            original_request="check readiness",
            final_status="approved",
        )
        from platform_agent.plato.evaluator.base import EvaluationIteration
        session.iterations.append(EvaluationIteration(
            iteration_number=1,
            specialist_output=GOOD_READINESS_OUTPUT,
            evaluation=result,
        ))

        report = evaluator.format_session_report(session)
        assert "APPROVED" in report
        assert "✅" in report
        assert "design" in report.lower()

    def test_escalated_report_has_warning(self):
        evaluator = DesignEvaluator()
        scores = evaluator._evaluate_heuristic(BAD_READINESS_OUTPUT, "check readiness")
        result = evaluator.build_result(scores, iteration=1)

        session = EvaluationSession(
            session_id="test-456",
            specialist_name="design_advisor",
            evaluator_name="design",
            rubric=evaluator.rubric,
            original_request="check readiness",
            final_status="escalated",
        )
        from platform_agent.plato.evaluator.base import EvaluationIteration
        session.iterations.append(EvaluationIteration(
            iteration_number=1,
            specialist_output=BAD_READINESS_OUTPUT,
            evaluation=result,
        ))

        report = evaluator.format_session_report(session)
        assert "ESCALAT" in report.upper()
        assert "🚨" in report


class TestCrossEvaluatorConsistency:
    """Test that all evaluators follow the same patterns."""

    def test_all_evaluators_have_5_rubric_items(self):
        for name in list_evaluators():
            cls = get_evaluator(name)
            evaluator = cls()
            assert len(evaluator.rubric.items) == 5, (
                f"{name} evaluator should have 5 rubric items, got {len(evaluator.rubric.items)}"
            )

    def test_all_evaluators_have_default_threshold(self):
        for name in list_evaluators():
            cls = get_evaluator(name)
            evaluator = cls()
            assert evaluator.rubric.overall_threshold == 0.7, (
                f"{name} evaluator threshold should be 0.7"
            )

    def test_all_evaluators_have_max_3_iterations(self):
        for name in list_evaluators():
            cls = get_evaluator(name)
            evaluator = cls()
            assert evaluator.rubric.max_iterations == 3, (
                f"{name} evaluator max_iterations should be 3"
            )

    def test_all_heuristics_return_correct_item_count(self):
        """Every heuristic should return scores for all rubric items."""
        dummy_output = "some output"
        for name in list_evaluators():
            cls = get_evaluator(name)
            evaluator = cls()
            scores = evaluator._evaluate_heuristic(dummy_output, "test request")
            scored_ids = {s.rubric_item_id for s in scores}
            rubric_ids = {item.id for item in evaluator.rubric.items}
            assert scored_ids == rubric_ids, (
                f"{name}: heuristic returned {scored_ids}, expected {rubric_ids}"
            )

    def test_all_evaluators_have_name_and_description(self):
        for name in list_evaluators():
            cls = get_evaluator(name)
            evaluator = cls()
            assert evaluator.name, f"{name} evaluator missing name"
            assert evaluator.description, f"{name} evaluator missing description"
