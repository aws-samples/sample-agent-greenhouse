"""Plato domain harness factory — returns config matching plato_harness.yaml."""

from pathlib import Path

from platform_agent.foundation.harness import (
    DomainHarness,
    EvalRule,
    HookConfig,
    MemoryConfig,
    PersonaConfig,
    PolicyConfig,
    SkillRef,
)


def create_plato_harness() -> DomainHarness:
    """Return the complete Plato domain harness matching plato_harness.yaml."""
    # Domain skills directory — resolved relative to plato/skills/ package
    import platform_agent.plato.skills as _ps
    plato_skills_dir = str(Path(_ps.__file__).parent)

    return DomainHarness(
        name="plato",
        description=(
            "Platform agent for Amazon Bedrock AgentCore"
            " \u2014 helps developers build, review, and deploy agent applications"
        ),
        version="1.0.0",
        skill_directories=[plato_skills_dir],
        skills=[
            SkillRef(
                name="aidlc_inception",
                description="Guided AIDLC inception workflow",
                tools=[
                    "aidlc_start_inception",
                    "aidlc_get_questions",
                    "aidlc_submit_answers",
                    "aidlc_approve_stage",
                    "aidlc_reject_stage",
                    "aidlc_get_status",
                    "aidlc_generate_artifacts",
                ],
            ),
            SkillRef(
                name="code_review",
                description="Security and quality code reviewer",
                tools=["Read", "Glob", "Grep"],
            ),
            SkillRef(
                name="debug",
                description="Debug and troubleshooting skill",
                tools=["Read", "Glob", "Grep", "Bash"],
            ),
            SkillRef(
                name="deployment_config",
                description="Deployment configuration generator",
                tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
            ),
            SkillRef(
                name="design_advisor",
                description="Architecture and platform readiness assessor",
                tools=["Read", "Glob", "Grep"],
            ),
            SkillRef(
                name="fleet_ops",
                description="Fleet operations management",
                tools=["Read", "Glob", "Grep", "Bash"],
            ),
            SkillRef(
                name="governance",
                description="Governance and compliance checks",
                tools=["Read", "Glob", "Grep"],
            ),
            SkillRef(
                name="issue_creator",
                description="Structured GitHub issue creator",
                tools=["create_spec_violation_issue", "create_issues_from_review"],
            ),
            SkillRef(
                name="knowledge",
                description="Knowledge base and reference lookup",
                tools=["Read", "Glob", "Grep"],
            ),
            SkillRef(
                name="monitoring",
                description="Monitoring and alerting setup",
                tools=["Read", "Glob", "Grep", "Bash"],
            ),
            SkillRef(
                name="observability",
                description="Observability instrumentation guidance",
                tools=["Read", "Glob", "Grep", "Bash"],
            ),
            SkillRef(
                name="onboarding",
                description="Developer onboarding guidance",
                tools=["Read", "Write", "Glob", "Grep"],
            ),
            SkillRef(
                name="pr_review",
                description="PR review with spec tracing",
                tools=["review_pull_request"],
            ),
            SkillRef(
                name="scaffold",
                description="Project skeleton generator",
                tools=["Read", "Write", "Edit", "Bash", "Glob"],
            ),
            SkillRef(
                name="spec_compliance",
                description="Spec compliance checker",
                tools=["check_spec_compliance", "check_single_ac"],
            ),
            SkillRef(
                name="test_case_generator",
                description="Spec-to-test-case generator (1:1 AC-to-TC)",
                tools=["generate_test_cases_from_spec"],
            ),
        ],
        tools=["github_tool", "claude_code_tool"],
        mcp_servers={
            "bedrock-agentcore": {
                "command": "awslabs.amazon-bedrock-agentcore-mcp-server",
                "args": [],
                "env": {
                    "FASTMCP_LOG_LEVEL": "WARNING",
                },
            },
            "aws-documentation": {
                "command": "awslabs.aws-documentation-mcp-server",
                "args": [],
                "env": {
                    "FASTMCP_LOG_LEVEL": "WARNING",
                },
            },
        },
        policies=PolicyConfig(
            tool_allowlist=[],
            tool_denylist=[],
            cedar_policies=[],
            max_tool_calls_per_turn=None,
        ),
        memory_config=MemoryConfig(
            namespace_template="/plato/{actorId}/",
            persist_types=[
                "inception_spec",
                "compliance_report",
                "review_findings",
                "design_assessment",
                "deployment_config",
            ],
            ttl_days=90,
            extraction_enabled=False,
            consolidation_enabled=False,
        ),
        eval_criteria=[
            EvalRule(
                name="spec_quality",
                description="AIDLC spec scoring rubric",
                threshold=0.8,
                scorer="spec_scoring.ScoreSpec",
            ),
            EvalRule(
                name="code_review_coverage",
                description="Code review must check security, quality, and readiness",
                threshold=0.9,
                scorer="evaluator.code_review.CodeReviewEvaluator",
            ),
            EvalRule(
                name="readiness_checklist",
                description="Platform readiness C1-C12 checklist",
                threshold=12,
                scorer="evaluator.design.DesignEvaluator",
            ),
        ],
        hooks=[
            # Foundation always-on
            HookConfig(hook="SoulSystemHook", category="foundation", params={}),
            HookConfig(hook="AuditHook", category="foundation", params={}),
            HookConfig(hook="TelemetryHook", category="foundation", params={}),
            HookConfig(hook="GuardrailsHook", category="foundation", params={}),
            # Domain hooks
            HookConfig(hook="MemoryHook", category="domain", params={}),
            HookConfig(hook="ModelMetricsHook", category="domain", params={}),
            HookConfig(
                hook="ToolPolicyHook",
                category="domain",
                params={"allowlist": [], "denylist": []},
            ),
            HookConfig(
                hook="ApprovalHook",
                category="domain",
                params={
                    "tools_requiring_approval": [],
                    "default_action": "block",
                },
            ),
            HookConfig(hook="BusinessMetricsHook", category="domain", params={}),
            HookConfig(hook="HallucinationDetectorHook", category="domain", params={}),
            # OTELSpanHook deprecated — Strands SDK native OTEL tracing replaces it
            # HookConfig(hook="OTELSpanHook", category="domain", params={}),
            HookConfig(hook="SessionRecordingHook", category="domain", params={}),
            # Optional hooks
            HookConfig(
                hook="MemoryExtractionHook",
                category="optional",
                enabled_by="memory_config.extraction_enabled",
                params={},
            ),
            HookConfig(
                hook="ConsolidationHook",
                category="optional",
                enabled_by="memory_config.consolidation_enabled",
                params={},
            ),
        ],
        persona=PersonaConfig(
            tone="technical",
            communication_style="concise but thorough",
            role="platform agent \u2014 architect, advisor, governance enforcer",
            constraints=[
                "NOT a coding agent \u2014 does not write application code",
                "Reviews, assesses, scaffolds, and configures \u2014 does not run user agents",
            ],
        ),
        workspace_context_enabled=True,
    )
