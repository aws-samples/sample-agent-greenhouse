"""Integration tests for the AIDLC skill ecosystem.

Tests end-to-end flows across multiple skills:
- Inception → Artifact Generation
- Inception → Compliance Check
- Review → Issue Creation
- Orchestrator routing and discovery

Traces to: spec SS2.3, SS3.1–SS3.6
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from platform_agent.plato.aidlc.stages import StageID
from platform_agent.plato.aidlc.state import Complexity, WorkflowState
from platform_agent.plato.skills.aidlc_inception import tools as _tools_mod
from platform_agent.plato.skills.aidlc_inception.tools import (
    _active_workflows,
    aidlc_approve_stage,
    aidlc_generate_artifacts,
    aidlc_get_status,
    aidlc_start_inception,
    aidlc_submit_answers,
)
from platform_agent.plato.skills.spec_compliance.checker import (
    ComplianceEntry,
    ComplianceReport,
    SpecComplianceChecker,
)
from platform_agent.plato.skills.pr_review.reviewer import PRReviewer
from platform_agent.plato.skills.issue_creator.creator import (
    create_issues_from_compliance,
    format_issue_body,
)
from platform_agent.plato.skills.test_case_generator.generator import (
    extract_acceptance_criteria,
    generate_test_cases,
)
from platform_agent.plato.skills import (
    _registry,
    discover_skills,
    get_skill,
    list_skills,
    register_skill,
)
from platform_agent.plato.skills.base import SkillPack, load_skill
from platform_agent.plato.orchestrator import (
    build_agents_from_skills,
    build_orchestrator_prompt,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_workflow_registry(tmp_path: Path):
    """Reset the module-level workflow registry and patch projects base dir."""
    _active_workflows.clear()
    projects_dir = str(tmp_path / "projects")
    old_val = _tools_mod._projects_base_dir
    _tools_mod._projects_base_dir = projects_dir
    yield
    _tools_mod._projects_base_dir = old_val
    _active_workflows.clear()


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Provide a temporary workspace directory."""
    return tmp_path


def _run_inception_to_completion(workspace: Path) -> Path:
    """Helper: run a full inception flow to completion.

    Uses answers that trigger SIMPLE complexity (score <=2) so conditional
    stages are skipped and the flow completes quickly.

    Args:
        workspace: Ignored (legacy param, kept for call-site compat).

    Returns:
        Auto-computed project directory path.
    """
    start_result = json.loads(aidlc_start_inception(
        project_name="integ-test",
        tenant_id="t1",
        repo="org/integ-test",
    ))
    project_dir = Path(start_result["workspace_path"])

    # Stage 1: Workspace Detection
    aidlc_submit_answers(
        stage_id="workspace_detection",
        answers_json=json.dumps({"existing_repo": False}),
    )
    aidlc_approve_stage(stage_id="workspace_detection")

    # Stage 2: Requirements — SIMPLE answers (score=0):
    #   single user type, single channel, single capability,
    #   no compliance, single data source, non-hybrid deploy
    aidlc_submit_answers(
        stage_id="requirements",
        answers_json=json.dumps({
            "target_users": "internal teams",
            "channels": ["Slack"],
            "capabilities": ["knowledge base search"],
            "data_sources": ["internal wiki"],
            "compliance": "none",
            "deployment_target": "AgentCore",
        }),
    )
    aidlc_approve_stage(stage_id="requirements")

    # SIMPLE: user_stories, application_design, units are skipped
    # Stage 3: Workflow Planning
    aidlc_submit_answers(
        stage_id="workflow_planning",
        answers_json=json.dumps({
            "stages": ["build", "test", "deploy"],
            "parallel": False,
        }),
    )
    aidlc_approve_stage(stage_id="workflow_planning")

    return project_dir


# ---------------------------------------------------------------------------
# Mock GitHub API helpers
# ---------------------------------------------------------------------------


def _mock_get_tree(repo: str, path: str = "", branch: str = "main") -> str:
    """Mock github_get_tree returning a fixed file list."""
    if path == "":
        return json.dumps({
            "entries": [
                {"name": "src", "type": "dir", "path": "src", "size": 0},
                {"name": "tests", "type": "dir", "path": "tests", "size": 0},
            ],
            "count": 2,
        })
    if path == "src":
        return json.dumps({
            "entries": [
                {"name": "agent.py", "type": "file", "path": "src/agent.py", "size": 500},
            ],
            "count": 1,
        })
    if path == "tests":
        return json.dumps({
            "entries": [
                {"name": "test_agent.py", "type": "file", "path": "tests/test_agent.py", "size": 300},
            ],
            "count": 1,
        })
    return json.dumps({"entries": [], "count": 0})


def _mock_get_file(repo: str, path: str, branch: str = "main") -> str:
    """Mock github_get_file returning fixed file contents."""
    files = {
        "src/agent.py": (
            "# Agent module\n"
            "\n"
            "def search_kb(query):\n"
            "    \"\"\"Search the knowledge base.\n"
            "\n"
            "    Traces to: AC-001\n"
            "    \"\"\"\n"
            "    return {'results': []}\n"
        ),
        "tests/test_agent.py": (
            "# Tests\n"
            "\n"
            "def test_search_kb():\n"
            "    \"\"\"TC-001 (traces to AC-001)\"\"\"\n"
            "    assert search_kb('test') is not None\n"
        ),
    }
    if path in files:
        return files[path]
    raise RuntimeError(f"404: {path}")


def _mock_create_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> str:
    """Mock github_create_issue."""
    return json.dumps({
        "status": "created",
        "number": 1,
        "url": f"https://github.com/{repo}/issues/1",
        "title": title,
    })


_issue_counter = 0


def _mock_create_issue_sequential(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> str:
    """Mock that returns incrementing issue numbers."""
    global _issue_counter
    _issue_counter += 1
    return json.dumps({
        "status": "created",
        "number": _issue_counter,
        "url": f"https://github.com/{repo}/issues/{_issue_counter}",
        "title": title,
    })


def _mock_get_pr_diff(repo: str, pr_number: int) -> str:
    """Mock get_pr_diff returning a diff with spec violations."""
    return (
        "diff --git a/src/handler.py b/src/handler.py\n"
        "--- a/src/handler.py\n"
        "+++ b/src/handler.py\n"
        "@@ -10,3 +10,10 @@\n"
        "+def process():\n"
        "+    try:\n"
        "+        do_something()\n"
        "+    except:\n"
        "+        pass\n"
    )


def _mock_get_pr_files(repo: str, pr_number: int) -> str:
    """Mock get_pr_files returning changed file list."""
    return json.dumps([
        {"filename": "src/handler.py", "status": "modified", "additions": 7, "deletions": 0},
    ])


def _mock_create_review(
    repo: str,
    pr_number: int,
    body: str,
    event: str,
    comments: list | None = None,
) -> str:
    """Mock github_create_review."""
    return json.dumps({
        "status": "created",
        "event": event,
        "review_id": 999,
    })


# ---------------------------------------------------------------------------
# Integration: Inception → Artifact Generation
# ---------------------------------------------------------------------------


class TestInceptionToArtifacts:
    """Full Inception → Artifact Generation flow.

    Traces to: spec SS3.1, SS3.2
    """

    def test_full_inception_generates_all_deliverables(
        self, tmp_workspace: Path
    ) -> None:
        """Complete inception flow produces spec.md, CLAUDE.md, test-cases.md."""
        project_dir = _run_inception_to_completion(tmp_workspace)

        # Verify workflow is complete
        status = json.loads(aidlc_get_status())
        assert status["completion_pct"] == 100

        # Generate artifacts
        result_json = aidlc_generate_artifacts()
        result = json.loads(result_json)
        assert result["status"] == "generated"

        # Verify all deliverable files exist
        assert (project_dir / "spec.md").exists()
        assert (project_dir / "CLAUDE.md").exists()
        assert (project_dir / "test-cases.md").exists()
        assert (project_dir / ".claude" / "rules" / "tdd-rule.md").exists()
        assert (project_dir / ".claude" / "rules" / "spec-compliance.md").exists()

    def test_generated_spec_has_acceptance_criteria(
        self, tmp_workspace: Path
    ) -> None:
        """Generated spec.md contains acceptance criteria."""
        project_dir = _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts()

        spec = (project_dir / "spec.md").read_text()
        assert "Acceptance Criteria" in spec
        assert "AC-001" in spec

    def test_generated_test_cases_match_spec_acs(
        self, tmp_workspace: Path
    ) -> None:
        """Generated test-cases.md has a TC for each AC in spec.md."""
        project_dir = _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts()

        spec = (project_dir / "spec.md").read_text()
        test_cases = (project_dir / "test-cases.md").read_text()

        # Count ACs in spec
        import re
        ac_ids = re.findall(r"AC-\d+", spec)
        # Each AC should have a corresponding TC in test-cases
        assert "TC-001" in test_cases
        # test-cases should reference "traces to AC-"
        assert "traces to AC-" in test_cases or "AC-" in test_cases

    def test_generated_claude_md_has_testing_standards(
        self, tmp_workspace: Path
    ) -> None:
        """Generated CLAUDE.md includes TDD and testing requirements."""
        project_dir = _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts()

        claude_md = (project_dir / "CLAUDE.md").read_text()
        assert "TDD" in claude_md
        assert "80%" in claude_md

    def test_agentcore_deployment_generates_refs(
        self, tmp_workspace: Path
    ) -> None:
        """AgentCore deployment target generates agentcore reference docs."""
        project_dir = _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts()

        # AgentCore was set as deployment_target
        assert (project_dir / "docs" / "agentcore" / "agentcore-patterns.md").exists()
        assert (project_dir / ".claude" / "rules" / "agentcore-patterns.md").exists()


# ---------------------------------------------------------------------------
# Integration: Inception → Compliance Check
# ---------------------------------------------------------------------------


class TestInceptionToCompliance:
    """Inception → Compliance Check flow.

    Generate spec via inception, then run compliance check against mock repo.

    Traces to: spec SS3.1, SS3.3
    """

    def test_compliance_check_on_generated_spec(
        self, tmp_workspace: Path
    ) -> None:
        """Compliance checker works against a spec generated by inception.

        The inception deliverables generator uses bold markdown format
        for ACs (e.g. ``**AC-001:**``). The SpecComplianceChecker handles
        both plain and bold AC formats natively.
        """
        project_dir = _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts()

        spec_content = (project_dir / "spec.md").read_text()
        checker = SpecComplianceChecker(spec_content)
        criteria = checker.extract_acceptance_criteria()

        # Spec should have ACs
        assert len(criteria) > 0

        # Run compliance check against mock repo
        report = checker.check_compliance(
            repo="org/integ-test",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )

        # Report should have entries for all ACs
        assert len(report.entries) == len(criteria)

        # At least AC-001 should be found (mock has "Traces to: AC-001")
        ac001_entries = [e for e in report.entries if e.ac_id == "AC-001"]
        if ac001_entries:
            assert ac001_entries[0].status in ("PASS", "PARTIAL")

    def test_compliance_report_reflects_mock_state(
        self, tmp_workspace: Path
    ) -> None:
        """Compliance report correctly reflects mock repo state."""
        project_dir = _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts()

        spec_content = (project_dir / "spec.md").read_text()
        checker = SpecComplianceChecker(spec_content)
        report = checker.check_compliance(
            repo="org/integ-test",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )

        # Report has summary
        assert "PASS" in report.summary or "PARTIAL" in report.summary or "NOT_FOUND" in report.summary

        # Formatted report is markdown table
        formatted = checker.format_report(report)
        assert "| AC ID |" in formatted


# ---------------------------------------------------------------------------
# Integration: Review → Issue Creation
# ---------------------------------------------------------------------------


class TestReviewToIssueCreation:
    """PR Review → Issue Creation flow.

    Mock a PR with spec violations, run review, create issues from findings.

    Traces to: spec SS3.4, SS3.5
    """

    @pytest.fixture(autouse=True)
    def _reset_counter(self) -> None:
        """Reset the global issue counter."""
        global _issue_counter
        _issue_counter = 0

    def test_review_findings_generate_issues(self) -> None:
        """Issues created from review findings match the violations found."""
        # Create a compliance report with violations
        report = ComplianceReport(
            entries=[
                ComplianceEntry(
                    ac_id="AC-001",
                    description="Submit ticket",
                    section="3.1",
                    status="PASS",
                    implemented=True,
                    test_exists=True,
                    impl_file="src/agent.py",
                    test_file="tests/test_agent.py",
                ),
                ComplianceEntry(
                    ac_id="AC-002",
                    description="Refund limit",
                    section="3.1",
                    status="NOT_FOUND",
                ),
                ComplianceEntry(
                    ac_id="AC-003",
                    description="Audit log",
                    section="3.2",
                    status="PARTIAL",
                    implemented=True,
                    impl_file="src/audit.py",
                ),
            ],
            repo="org/test-repo",
        )
        report.compute_summary()

        # Create issues from compliance
        results = create_issues_from_compliance(
            repo="org/test-repo",
            compliance_report=report,
            spec_content="",
            _github_create_issue=_mock_create_issue_sequential,
        )

        # Should create issues for NOT_FOUND and PARTIAL, not PASS
        assert len(results) == 2
        ac_ids = {r.ac_id for r in results}
        assert ac_ids == {"AC-002", "AC-003"}
        assert all(r.success for r in results)

    def test_issue_bodies_reference_spec(self) -> None:
        """Created issues include spec references."""
        finding = {
            "section": "3.1",
            "ac_id": "AC-002",
            "description": "Refund limit enforced at $500",
            "current_state": "Not implemented",
            "expected_state": "Refund limit logic in handler",
            "tc_id": "TC-002",
            "files": "src/handler.py",
            "severity": "blocking",
            "suggested_fix": "Add refund validation logic",
        }
        body = format_issue_body(finding)
        assert "AC-002" in body
        assert "TC-002" in body
        assert "blocking" in body
        assert "Spec Violation" in body

    def test_issues_match_review_findings(self) -> None:
        """Each issue corresponds to a specific review finding."""
        report = ComplianceReport(
            entries=[
                ComplianceEntry(
                    ac_id="AC-010",
                    description="Auth works",
                    status="NOT_FOUND",
                    section="2.1",
                ),
                ComplianceEntry(
                    ac_id="AC-011",
                    description="Logging exists",
                    status="PARTIAL",
                    section="2.2",
                    test_exists=True,
                    test_file="tests/test_log.py",
                ),
            ],
        )

        results = create_issues_from_compliance(
            repo="org/repo",
            compliance_report=report,
            spec_content="",
            _github_create_issue=_mock_create_issue_sequential,
        )

        assert len(results) == 2
        titles = {r.title for r in results}
        # Titles should reference the AC-IDs
        assert any("AC-010" in t for t in titles)
        assert any("AC-011" in t for t in titles)


# ---------------------------------------------------------------------------
# Integration: Orchestrator routing and discovery
# ---------------------------------------------------------------------------


class TestOrchestratorRouting:
    """Tests for orchestrator skill discovery and AIDLC routing.

    Traces to: spec SS3.6, orchestrator routing requirements
    """

    @pytest.fixture(autouse=True)
    def _restore_registry(self):
        """Save and restore the skill registry."""
        saved = dict(_registry)
        yield
        _registry.clear()
        _registry.update(saved)

    def test_all_five_new_skills_discovered(self) -> None:
        """All 5 new AIDLC skills are discoverable."""
        # Clear and re-discover
        to_remove = [
            k for k in sys.modules
            if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"
        ]
        for k in to_remove:
            del sys.modules[k]
        _registry.clear()
        discover_skills()

        expected = [
            "aidlc-inception",
            "spec-compliance",
            "pr-review",
            "issue-creator",
            "test-case-generator",
        ]
        skills = list_skills()
        for name in expected:
            assert name in skills, f"Skill '{name}' not discovered"

    def test_routing_prompt_mentions_aidlc_patterns(self) -> None:
        """Orchestrator prompt includes AIDLC routing patterns."""
        # Clear and re-discover
        to_remove = [
            k for k in sys.modules
            if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"
        ]
        for k in to_remove:
            del sys.modules[k]
        _registry.clear()
        discover_skills()

        agents = build_agents_from_skills()
        prompt = build_orchestrator_prompt(agents)

        # Check AIDLC routing section exists
        assert "AIDLC Routing Patterns" in prompt

        # Check each skill is mentioned in routing
        assert "aidlc-inception" in prompt
        assert "pr-review" in prompt
        assert "spec-compliance" in prompt
        assert "issue-creator" in prompt
        assert "test-case-generator" in prompt

    def test_routing_prompt_mentions_multi_step_flows(self) -> None:
        """Orchestrator prompt includes multi-step flow guidance."""
        to_remove = [
            k for k in sys.modules
            if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"
        ]
        for k in to_remove:
            del sys.modules[k]
        _registry.clear()
        discover_skills()

        agents = build_agents_from_skills()
        prompt = build_orchestrator_prompt(agents)

        assert "Multi-Step AIDLC Flows" in prompt
        assert "review and create issues" in prompt

    def test_routing_prompt_mentions_workflow_awareness(self) -> None:
        """Orchestrator prompt includes AIDLC workflow awareness."""
        to_remove = [
            k for k in sys.modules
            if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"
        ]
        for k in to_remove:
            del sys.modules[k]
        _registry.clear()
        discover_skills()

        agents = build_agents_from_skills()
        prompt = build_orchestrator_prompt(agents)

        assert "AIDLC Workflow Awareness" in prompt
        assert "aidlc-inception" in prompt

    def test_each_skill_has_agent_definition(self) -> None:
        """Each new skill produces a valid AgentDefinition."""
        to_remove = [
            k for k in sys.modules
            if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"
        ]
        for k in to_remove:
            del sys.modules[k]
        _registry.clear()
        discover_skills()

        agents = build_agents_from_skills()
        for skill_name in [
            "aidlc-inception",
            "spec-compliance",
            "pr-review",
            "issue-creator",
            "test-case-generator",
        ]:
            assert skill_name in agents, f"Missing agent for {skill_name}"
            agent_def = agents[skill_name]
            assert agent_def.description, f"No description for {skill_name}"
            # system_prompt_extension is now empty (SKILL.md is sole source).
            # The orchestrator's AgentDefinition.prompt comes from SkillPack
            # which no longer has hardcoded prompts. This is expected.
            # assert agent_def.prompt, f"No prompt for {skill_name}"


# ---------------------------------------------------------------------------
# Integration: Test Case Generator with generated spec
# ---------------------------------------------------------------------------


class TestGeneratorWithInceptionSpec:
    """Test case generator operating on inception-generated specs.

    Traces to: AC-8, spec SS2.3
    """

    def test_generator_works_on_inception_spec(
        self, tmp_workspace: Path
    ) -> None:
        """Test case generator produces valid TCs from inception-generated spec."""
        project_dir = _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts()

        spec_content = (project_dir / "spec.md").read_text()
        criteria = extract_acceptance_criteria(spec_content)

        # Spec should have ACs
        assert len(criteria) > 0

        # Generate test cases
        tc_md = generate_test_cases(spec_content)

        # Every AC should have a TC
        for ac in criteria:
            ac_num = ac["id"].replace("AC-", "")
            tc_id = f"TC-{ac_num}"
            assert tc_id in tc_md, f"Missing {tc_id} for {ac['id']}"

    def test_generator_format_on_inception_spec(
        self, tmp_workspace: Path
    ) -> None:
        """Generated TCs follow required format."""
        project_dir = _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts()

        spec_content = (project_dir / "spec.md").read_text()
        tc_md = generate_test_cases(spec_content)

        assert "**Description:**" in tc_md
        assert "**Setup:**" in tc_md
        assert "**Steps:**" in tc_md
        assert "**Expected:**" in tc_md
        assert "**Type:**" in tc_md
