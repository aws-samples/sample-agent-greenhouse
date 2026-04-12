"""Deployment Config Evaluator — evaluates deployment_config skill output.

Checks that generated deployment configurations are secure, complete, and correct.
Includes deterministic check for IAM policy JSON validity.
"""

from __future__ import annotations

import json
import logging
import re

from platform_agent.plato.evaluator import register_evaluator
from platform_agent.plato.evaluator.base import (
    HONESTY_PREAMBLE,
    EvaluationRubric,
    EvaluatorAgent,
    ItemScore,
    RubricItem,
)

logger = logging.getLogger(__name__)

# Expected deployment artifacts
_EXPECTED_ARTIFACTS = [
    "Dockerfile",
    "buildspec.yml",
    "iam-policy.json",
    "cdk",
    "runtime-config",
    ".env",
]


class DeployConfigEvaluator(EvaluatorAgent):
    """Evaluates deployment_config skill output.

    Rubric items:
        iam_least_privilege: No overly broad permissions, no `*` resources.
        dockerfile_quality: Multi-stage, non-root, HEALTHCHECK, layer caching.
        config_completeness: All expected artifacts generated.
        env_safety: No secrets in templates, proper placeholder pattern.
        cdk_correctness: Valid CDK constructs, proper resource configuration.
    """

    name = "deployment"
    description = "Evaluates deployment configuration quality and security"

    def default_rubric(self) -> EvaluationRubric:
        return EvaluationRubric(
            name="deploy_config_rubric",
            version="1.0",
            items=[
                RubricItem(
                    id="iam_least_privilege",
                    name="IAM Least Privilege",
                    description=(
                        "No overly broad permissions. No 'Action: *' or "
                        "'Resource: *' unless justified. Scoped to specific "
                        "services and resources."
                    ),
                    weight=2.0,
                    threshold=0.8,
                ),
                RubricItem(
                    id="dockerfile_quality",
                    name="Dockerfile Quality",
                    description=(
                        "Multi-stage build, non-root user, HEALTHCHECK directive, "
                        "layer caching (copy deps first, then source)."
                    ),
                    weight=1.5,
                    threshold=0.7,
                ),
                RubricItem(
                    id="config_completeness",
                    name="Config Completeness",
                    description=(
                        "All expected deployment artifacts generated: "
                        f"{', '.join(_EXPECTED_ARTIFACTS)}."
                    ),
                    weight=1.0,
                    threshold=0.7,
                ),
                RubricItem(
                    id="env_safety",
                    name="Environment Safety",
                    description=(
                        "No actual secrets in templates. Placeholders used "
                        "(e.g., ${SECRET_NAME}). .env.template not .env."
                    ),
                    weight=1.5,
                    threshold=0.8,
                ),
                RubricItem(
                    id="cdk_correctness",
                    name="CDK Correctness",
                    description=(
                        "Valid CDK constructs. Proper imports, resource "
                        "configuration, and stack structure."
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
        """Check IAM policy JSON validity deterministically.

        Extracts JSON blocks from the output that look like IAM policies
        and validates them with json.loads().

        Returns:
            Dict mapping rubric_item_id -> ItemScore for deterministic checks.
        """
        results: dict[str, ItemScore] = {}

        # Extract JSON blocks from the output
        json_blocks = re.findall(
            r'```(?:json)?\s*\n(.*?)\n```',
            specialist_output,
            re.DOTALL,
        )

        # Also try to find inline JSON that looks like IAM policy
        iam_blocks = [
            b for b in json_blocks
            if '"Statement"' in b or '"Effect"' in b or '"Action"' in b
        ]

        if iam_blocks:
            all_valid = True
            errors: list[str] = []
            for block in iam_blocks:
                try:
                    parsed = json.loads(block)
                    # Verify it has IAM policy structure
                    if not isinstance(parsed, dict):
                        all_valid = False
                        errors.append("IAM policy is not a JSON object")
                except json.JSONDecodeError as e:
                    all_valid = False
                    errors.append(f"Invalid JSON: {e}")

            if all_valid:
                results["iam_least_privilege"] = ItemScore(
                    rubric_item_id="iam_least_privilege",
                    score=0.7,
                    passed=False,
                    evidence=f"Found {len(iam_blocks)} valid IAM policy JSON block(s)",
                    feedback="JSON is valid but needs manual review for least privilege",
                )
            else:
                results["iam_least_privilege"] = ItemScore(
                    rubric_item_id="iam_least_privilege",
                    score=0.2,
                    passed=False,
                    evidence=f"IAM policy JSON validation failed: {'; '.join(errors)}",
                    feedback="Fix IAM policy JSON syntax errors",
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
            f"You are a quality evaluator for deployment configurations.\n\n"
            f"A Deployment Config agent generated deployment artifacts. "
            f"Evaluate the quality and security of the output.\n\n"
            f"## Original Request\n{original_request}\n\n"
            f"## Deployment Config Output (Iteration {iteration})\n"
            f"{specialist_output}\n\n"
            f"## Evaluation Criteria\n{rubric_text}\n\n"
            f"## Specific Checks\n"
            f"1. **iam_least_privilege**: Any 'Action: *' or 'Resource: *'? "
            f"Are permissions scoped to specific services?\n"
            f"2. **dockerfile_quality**: Multi-stage? Non-root user? "
            f"HEALTHCHECK? Layer caching order?\n"
            f"3. **config_completeness**: Are all expected artifacts present? "
            f"({', '.join(_EXPECTED_ARTIFACTS)})\n"
            f"4. **env_safety**: Any hardcoded secrets? Proper placeholders?\n"
            f"5. **cdk_correctness**: Valid CDK imports and constructs?\n\n"
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
        """Rule-based evaluation for deployment configs."""
        output_lower = specialist_output.lower()
        scores = []

        # IAM least privilege
        has_star_action = '"action": "*"' in output_lower or "'*'" in output_lower
        has_star_resource = '"resource": "*"' in output_lower
        has_scoped = any(
            svc in output_lower
            for svc in ["bedrock:", "logs:", "s3:", "secretsmanager:"]
        )
        iam_score = 0.3 if not has_star_action else 0.0
        iam_score += 0.3 if not has_star_resource else 0.0
        iam_score += 0.4 if has_scoped else 0.0
        scores.append(
            ItemScore(
                rubric_item_id="iam_least_privilege",
                score=iam_score,
                passed=iam_score >= 0.8,
                evidence=(
                    f"Star action: {'yes' if has_star_action else 'no'}, "
                    f"Star resource: {'yes' if has_star_resource else 'no'}, "
                    f"Scoped services: {'yes' if has_scoped else 'no'}"
                ),
                feedback=(
                    ""
                    if iam_score >= 0.8
                    else "Scope IAM permissions to specific actions and resources"
                ),
            )
        )

        # Dockerfile quality
        has_multistage = "as builder" in output_lower or "from " in output_lower
        has_nonroot = "useradd" in output_lower or "non-root" in output_lower
        has_healthcheck = "healthcheck" in output_lower
        has_layer_cache = (
            "copy" in output_lower and "requirements" in output_lower
        )
        docker_score = (
            (0.25 if has_multistage else 0.0)
            + (0.25 if has_nonroot else 0.0)
            + (0.25 if has_healthcheck else 0.0)
            + (0.25 if has_layer_cache else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="dockerfile_quality",
                score=docker_score,
                passed=docker_score >= 0.7,
                evidence=(
                    f"Multi-stage: {'yes' if has_multistage else 'no'}, "
                    f"Non-root: {'yes' if has_nonroot else 'no'}, "
                    f"HEALTHCHECK: {'yes' if has_healthcheck else 'no'}, "
                    f"Layer cache: {'yes' if has_layer_cache else 'no'}"
                ),
                feedback=(
                    ""
                    if docker_score >= 0.7
                    else "Add multi-stage build, non-root user, HEALTHCHECK, layer caching"
                ),
            )
        )

        # Config completeness
        found = sum(
            1 for a in _EXPECTED_ARTIFACTS if a.lower() in output_lower
        )
        completeness_score = found / len(_EXPECTED_ARTIFACTS)
        scores.append(
            ItemScore(
                rubric_item_id="config_completeness",
                score=completeness_score,
                passed=completeness_score >= 0.7,
                evidence=f"Found {found}/{len(_EXPECTED_ARTIFACTS)} expected artifacts",
                feedback=(
                    ""
                    if completeness_score >= 0.7
                    else f"Missing: {[a for a in _EXPECTED_ARTIFACTS if a.lower() not in output_lower]}"
                ),
            )
        )

        # Env safety
        secret_patterns = [
            r"sk-[a-zA-Z0-9]{20,}",
            r"AKIA[A-Z0-9]{16}",
            r"password\s*=\s*['\"][^'\"]+['\"]",
        ]
        has_secrets = any(
            re.search(p, specialist_output) for p in secret_patterns
        )
        has_placeholders = "${" in specialist_output or "{{" in specialist_output
        has_template = ".env.template" in output_lower or ".env.example" in output_lower
        env_score = (
            (0.0 if has_secrets else 0.4)
            + (0.3 if has_placeholders else 0.0)
            + (0.3 if has_template else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="env_safety",
                score=env_score,
                passed=env_score >= 0.8,
                evidence=(
                    f"Secrets found: {'yes' if has_secrets else 'no'}, "
                    f"Placeholders: {'yes' if has_placeholders else 'no'}, "
                    f"Template file: {'yes' if has_template else 'no'}"
                ),
                feedback=(
                    ""
                    if env_score >= 0.8
                    else "Use placeholders for secrets, provide .env.template not .env"
                ),
            )
        )

        # CDK correctness
        has_cdk_imports = "aws_cdk" in output_lower or "from cdk" in output_lower
        has_stack = "stack" in output_lower
        has_constructs = any(
            c in output_lower
            for c in ["ecr_repository", "iam.role", "cloudwatch", "lambda"]
        )
        cdk_score = (
            (0.4 if has_cdk_imports else 0.0)
            + (0.3 if has_stack else 0.1)
            + (0.3 if has_constructs else 0.0)
        )
        scores.append(
            ItemScore(
                rubric_item_id="cdk_correctness",
                score=cdk_score,
                passed=cdk_score >= 0.7,
                evidence=(
                    f"CDK imports: {'yes' if has_cdk_imports else 'no'}, "
                    f"Stack class: {'yes' if has_stack else 'no'}, "
                    f"AWS constructs: {'yes' if has_constructs else 'no'}"
                ),
                feedback=(
                    ""
                    if cdk_score >= 0.7
                    else "Include proper CDK imports, Stack class, and AWS constructs"
                ),
            )
        )

        return scores


# Auto-register
register_evaluator("deployment", DeployConfigEvaluator)
