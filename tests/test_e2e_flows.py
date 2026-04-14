"""End-to-end tests for AIDLC skill chaining flows.

Validates full AIDLC pipelines end-to-end: inception → artifacts,
inception → compliance → issues, PR review → issues, spec → test cases,
orchestrator routing, CLI registration, and regression of existing skills.

Mock-based: tests skill CHAINING, not individual skills (those are already
tested in test_aidlc_inception_skill.py, test_spec_compliance.py, etc.).

Traces to: spec TC-030 through TC-036
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from platform_agent.plato.aidlc.stages import StageID
from platform_agent.plato.aidlc.state import Complexity, WorkflowState
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
def _clean_workflow_registry():
    """Reset the module-level workflow registry between tests."""
    _active_workflows.clear()
    yield
    _active_workflows.clear()


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Provide a temporary workspace directory."""
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_inception_to_completion(workspace: Path) -> None:
    """Run a full inception flow to completion.

    Uses answers that trigger SIMPLE complexity (score <=2) so conditional
    stages are skipped and the flow completes quickly.
    """
    aidlc_start_inception(
        project_name="e2e-test",
        tenant_id="t1",
        repo="org/e2e-test",
        workspace_path=str(workspace),
    )

    # Stage 1: Workspace Detection
    aidlc_submit_answers(
        stage_id="workspace_detection",
        answers_json=json.dumps({"existing_repo": False}),
    )
    aidlc_approve_stage(stage_id="workspace_detection")

    # Stage 2: Requirements — SIMPLE answers (score=0)
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


_issue_counter = 0


def _mock_create_issue(
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> str:
    """Mock github_create_issue with incrementing issue numbers."""
    global _issue_counter
    _issue_counter += 1
    return json.dumps({
        "status": "created",
        "number": _issue_counter,
        "url": f"https://github.com/{repo}/issues/{_issue_counter}",
        "title": title,
    })


def _mock_get_pr_diff(repo: str, pr_number: int) -> str:
    """Mock get_pr_diff returning a diff with code issues."""
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
    return json.dumps({
        "files": [
            {"filename": "src/handler.py", "status": "modified", "additions": 7, "deletions": 0},
        ],
    })


# ---------------------------------------------------------------------------
# TC-030: Full Inception → Artifact Generation
# ---------------------------------------------------------------------------


class TestFullInceptionToArtifacts:
    """Simulate complete inception → artifact generation.

    Traces to: TC-030
    """

    def test_full_inception_to_artifacts(self, tmp_workspace: Path) -> None:
        """Complete inception generates spec.md, CLAUDE.md, test-cases.md."""
        _run_inception_to_completion(tmp_workspace)

        # Verify workflow is complete
        status = json.loads(aidlc_get_status())
        assert status["completion_pct"] == 100

        # Generate artifacts
        result_json = aidlc_generate_artifacts(workspace_path=str(tmp_workspace))
        result = json.loads(result_json)
        assert result["status"] == "generated"

        # Verify all deliverable files exist
        assert (tmp_workspace / "spec.md").exists()
        assert (tmp_workspace / "CLAUDE.md").exists()
        assert (tmp_workspace / "test-cases.md").exists()

        # Verify spec has acceptance criteria
        spec = (tmp_workspace / "spec.md").read_text()
        assert "Acceptance Criteria" in spec
        assert "AC-001" in spec

        # Verify CLAUDE.md has testing standards
        claude_md = (tmp_workspace / "CLAUDE.md").read_text()
        assert "TDD" in claude_md
        assert "80%" in claude_md

        # Verify test-cases has TCs that match ACs
        test_cases = (tmp_workspace / "test-cases.md").read_text()
        assert "TC-001" in test_cases

        # Verify ACs in spec match TCs in test-cases
        ac_ids = re.findall(r"AC-(\d+)", spec)
        for ac_num in ac_ids:
            tc_id = f"TC-{ac_num}"
            assert tc_id in test_cases, f"Missing {tc_id} for AC-{ac_num}"


# ---------------------------------------------------------------------------
# TC-031: Inception → Compliance → Issues
# ---------------------------------------------------------------------------


class TestInceptionToComplianceToIssues:
    """Full pipeline: inception → compliance → issue creation.

    Traces to: TC-031
    """

    @pytest.fixture(autouse=True)
    def _reset_counter(self) -> None:
        global _issue_counter
        _issue_counter = 0

    def test_inception_to_compliance_to_issues(
        self, tmp_workspace: Path
    ) -> None:
        """Generate spec, run compliance, create issues from failures."""
        # Step 1: Run inception and generate artifacts
        _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts(workspace_path=str(tmp_workspace))

        # Step 2: Run compliance checker on mock codebase
        spec_content = (tmp_workspace / "spec.md").read_text()
        checker = SpecComplianceChecker(spec_content)
        criteria = checker.extract_acceptance_criteria()
        assert len(criteria) > 0

        report = checker.check_compliance(
            repo="org/e2e-test",
            branch="main",
            _github_get_tree=_mock_get_tree,
            _github_get_file=_mock_get_file,
        )

        # Report should have entries for all ACs
        assert len(report.entries) == len(criteria)

        # Step 3: Create issues from compliance failures
        failing = [
            e for e in report.entries
            if e.status in ("PARTIAL", "NOT_FOUND")
        ]

        if failing:
            results = create_issues_from_compliance(
                repo="org/e2e-test",
                compliance_report=report,
                spec_content=spec_content,
                _github_create_issue=_mock_create_issue,
            )

            # Verify issues created for failures
            assert len(results) == len(failing)
            assert all(r.success for r in results)

            # Verify issues have correct AC references
            for r in results:
                assert r.ac_id.startswith("AC-")

            # Verify severity categorization
            for r in results:
                assert r.issue_number > 0


# ---------------------------------------------------------------------------
# TC-032: PR Review → Issue Creation
# ---------------------------------------------------------------------------


class TestPRReviewToIssueCreation:
    """Review → Issues flow: run review, create issues from findings.

    Traces to: TC-032
    """

    @pytest.fixture(autouse=True)
    def _reset_counter(self) -> None:
        global _issue_counter
        _issue_counter = 0

    def test_pr_review_to_issue_creation(self) -> None:
        """Run PR review with mock diff, feed findings to issue creator."""
        # Step 1: Run PR review with mock diff
        reviewer = PRReviewer(
            github_get_pr_diff=_mock_get_pr_diff,
            github_list_pr_files=_mock_get_pr_files,
            github_get_file=_mock_get_file,
        )
        review_result = reviewer.review_pr(
            repo="org/e2e-test",
            pr_number=42,
        )

        # Review should find issues (bare except in mock diff)
        assert len(review_result.code_issues) > 0

        # Step 2: Build compliance report from review findings
        # Create compliance entries from code issues for issue creation
        entries = []
        for i, issue in enumerate(review_result.code_issues, start=1):
            entries.append(ComplianceEntry(
                ac_id=f"AC-{i:03d}",
                description=issue.description,
                section="review",
                status="NOT_FOUND" if issue.severity == "blocking" else "PARTIAL",
                impl_file=issue.file,
            ))

        report = ComplianceReport(entries=entries, repo="org/e2e-test")
        report.compute_summary()

        # Step 3: Create issues from review findings
        results = create_issues_from_compliance(
            repo="org/e2e-test",
            compliance_report=report,
            spec_content="",
            _github_create_issue=_mock_create_issue,
        )

        # Verify issues created with correct references
        assert len(results) > 0
        assert all(r.success for r in results)
        assert all(r.issue_number > 0 for r in results)


# ---------------------------------------------------------------------------
# TC-033: Test Gen Matches Spec ACs (1:1)
# ---------------------------------------------------------------------------


class TestTestGenMatchesSpecACs:
    """Spec → Test Case 1:1 mapping verification.

    Traces to: TC-033
    """

    def test_test_gen_matches_spec_acs(self, tmp_workspace: Path) -> None:
        """Every AC in generated spec has exactly one TC."""
        # Step 1: Run inception and generate spec
        _run_inception_to_completion(tmp_workspace)
        aidlc_generate_artifacts(workspace_path=str(tmp_workspace))

        spec_content = (tmp_workspace / "spec.md").read_text()

        # Step 2: Extract ACs from spec
        criteria = extract_acceptance_criteria(spec_content)
        assert len(criteria) > 0

        # Step 3: Generate test cases from spec
        tc_md = generate_test_cases(spec_content)

        # Step 4: Verify every AC has exactly one TC (1:1)
        for ac in criteria:
            ac_num = ac["id"].replace("AC-", "")
            tc_id = f"TC-{ac_num}"
            assert tc_id in tc_md, f"Missing {tc_id} for {ac['id']}"

        # Verify TC count matches AC count
        tc_ids = re.findall(r"TC-(\d+)", tc_md)
        unique_tcs = set(tc_ids)
        assert len(unique_tcs) == len(criteria), (
            f"TC count ({len(unique_tcs)}) != AC count ({len(criteria)})"
        )


# ---------------------------------------------------------------------------
# TC-034: Orchestrator Routes Correctly
# ---------------------------------------------------------------------------


class TestOrchestratorRoutesCorrectly:
    """Orchestrator routing validation.

    Traces to: TC-034
    """

    @pytest.fixture(autouse=True)
    def _restore_registry(self):
        saved = dict(_registry)
        yield
        _registry.clear()
        _registry.update(saved)

    def test_orchestrator_routes_correctly(self) -> None:
        """All 5 AIDLC skills discovered, prompt has routing + NDU principle."""
        # Clear and re-discover
        to_remove = [
            k for k in sys.modules
            if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"
        ]
        for k in to_remove:
            del sys.modules[k]
        _registry.clear()
        discover_skills()

        # Verify all 5 AIDLC skills are discovered
        skills = list_skills()
        expected_aidlc = [
            "aidlc-inception",
            "spec-compliance",
            "pr-review",
            "issue-creator",
            "test-case-generator",
        ]
        for name in expected_aidlc:
            assert name in skills, f"Skill '{name}' not discovered"

        # Build agents from skills
        agents = build_agents_from_skills()
        prompt = build_orchestrator_prompt(agents)

        # Verify orchestrator prompt contains routing patterns
        assert "AIDLC Routing Patterns" in prompt
        for name in expected_aidlc:
            assert name in prompt, f"Skill '{name}' not in orchestrator prompt"

        # Verify Never Delegate Understanding principle
        assert "NEVER DELEGATE UNDERSTANDING" in prompt


# ---------------------------------------------------------------------------
# TC-035: CLI Commands Exist
# ---------------------------------------------------------------------------


class TestCLICommandsExist:
    """CLI integration smoke test.

    Traces to: TC-035
    """

    def test_cli_commands_exist(self) -> None:
        """inception, compliance, test-gen commands are registered with correct params."""
        click = pytest.importorskip("click")
        from platform_agent.cli import cli

        # Get all registered command names
        command_names = list(cli.commands.keys())

        # Verify new commands exist
        assert "inception" in command_names
        assert "compliance" in command_names
        assert "test-gen" in command_names

        # Verify inception has correct parameters
        inception_cmd = cli.commands["inception"]
        param_names = [p.name for p in inception_cmd.params]
        assert "repo" in param_names
        assert "complexity" in param_names
        assert "verbose" in param_names

        # Verify compliance has correct parameters
        compliance_cmd = cli.commands["compliance"]
        param_names = [p.name for p in compliance_cmd.params]
        assert "repo" in param_names
        assert "spec_path" in param_names
        assert "branch" in param_names
        assert "verbose" in param_names

        # Verify test-gen has correct parameters
        test_gen_cmd = cli.commands["test-gen"]
        param_names = [p.name for p in test_gen_cmd.params]
        assert "repo" in param_names
        assert "spec_path" in param_names
        assert "branch" in param_names
        assert "verbose" in param_names


# ---------------------------------------------------------------------------
# TC-036: Regression — Existing Skills Still Work
# ---------------------------------------------------------------------------


class TestRegressionExistingSkills:
    """Existing skills still work after Sprint 1-4 additions.

    Traces to: TC-036
    """

    @pytest.fixture(autouse=True)
    def _restore_registry(self):
        saved = dict(_registry)
        yield
        _registry.clear()
        _registry.update(saved)

    def test_regression_existing_skills(self) -> None:
        """design_advisor, code_review, scaffold, deployment_config all load."""
        # Clear and re-discover
        to_remove = [
            k for k in sys.modules
            if k.startswith("platform_agent.plato.skills.") and k != "platform_agent.plato.skills.base"
        ]
        for k in to_remove:
            del sys.modules[k]
        _registry.clear()
        discover_skills()

        existing_skills = [
            "design-advisor",
            "code-review",
            "scaffold",
            "deployment-config",
        ]

        for skill_name in existing_skills:
            # Verify skill is registered
            assert skill_name in list_skills(), f"'{skill_name}' not found"

            # Verify skill loads correctly
            skill_cls = get_skill(skill_name)
            skill = load_skill(skill_cls)

            # Verify expected properties
            assert skill.name == skill_name
            assert skill.description, f"No description for {skill_name}"
            assert skill.version, f"No version for {skill_name}"
            assert len(skill.tools) > 0, f"No tools for {skill_name}"

        # Verify FoundationAgent can load them
        from platform_agent._legacy_foundation import FoundationAgent

        agent = FoundationAgent()
        for skill_name in existing_skills:
            skill_cls = get_skill(skill_name)
            skill = load_skill(skill_cls)
            agent.load_skill(skill)

        assert len(agent.skills) == len(existing_skills)
        loaded_names = [s.name for s in agent.skills]
        for name in existing_skills:
            assert name in loaded_names
