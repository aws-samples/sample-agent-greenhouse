"""AIDLC Inception deliverable generators.

Compiles final deliverables from completed Inception artifacts:
spec.md, CLAUDE.md, test-cases.md, and optional AgentCore references.

Traces to: spec §3.2 (Artifact Generation)
           AC-6 (All four artifact types generated)
           AC-7 (CLAUDE.md includes .claude/rules/ enforcement files)
           AC-8 (Every AC in spec.md has a corresponding test case)
           AC-9 (AgentCore references when deployment target is AgentCore)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from platform_agent.plato.aidlc.state import WorkflowState

logger = logging.getLogger(__name__)


def _read_artifact(aidlc_docs_dir: Path, filename: str) -> str:
    """Read an artifact file from aidlc-docs/, returning empty string if missing.

    Args:
        aidlc_docs_dir: Path to the aidlc-docs directory.
        filename: Name of the artifact file to read.

    Returns:
        File content as string, or empty string if file does not exist.
    """
    path = aidlc_docs_dir / filename
    if path.exists():
        return path.read_text()
    return ""


def _extract_section(content: str, heading: str) -> str:
    """Extract content under a specific markdown heading.

    Extracts everything from the heading line until the next heading of
    the same or higher level, or end of file.

    Args:
        content: Full markdown content.
        heading: The heading text to search for (without # prefix).

    Returns:
        The content under the heading, or empty string if not found.
    """
    lines = content.splitlines()
    collecting = False
    heading_level = 0
    collected: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            title = stripped.lstrip("#").strip()
            if title.lower() == heading.lower():
                collecting = True
                heading_level = level
                continue
            elif collecting and level <= heading_level:
                break
        if collecting:
            collected.append(line)

    return "\n".join(collected).strip()


def _get_requirements_data(state: WorkflowState) -> dict[str, Any]:
    """Extract requirements data from audit entries.

    Args:
        state: The completed workflow state.

    Returns:
        Dict of requirements answers, or empty dict if not found.
    """
    for entry in state.audit_entries:
        if entry.get("stage_id") == "requirements":
            user_input = entry.get("user_input", {})
            if isinstance(user_input, dict):
                return user_input
    return {}


def _get_deployment_target(state: WorkflowState) -> str:
    """Determine the deployment target from requirements.

    Args:
        state: The completed workflow state.

    Returns:
        Deployment target string (e.g. "AgentCore", "Self-hosted", "Hybrid").
    """
    req_data = _get_requirements_data(state)
    return req_data.get("deployment_target", "")


def generate_spec(state: WorkflowState, aidlc_docs_dir: Path) -> str:
    """Generate a unified spec.md from all Inception artifacts.

    Reads all aidlc-docs/*.md artifacts and compiles them into a single
    specification document with acceptance criteria.

    Args:
        state: The completed workflow state.
        aidlc_docs_dir: Path to the aidlc-docs directory.

    Returns:
        Compiled spec.md content as a string.

    Traces to: AC-6 (All artifact types generated)
    """
    spec = f"# {state.project_name} — Specification\n\n"
    spec += f"**Repository:** {state.repo}  \n"
    spec += f"**Complexity:** {state.complexity.value}  \n\n"
    spec += "---\n\n"

    # Section 1: Overview (from workspace analysis)
    workspace = _read_artifact(aidlc_docs_dir, "workspace-analysis.md")
    spec += "## 1. Overview\n\n"
    if workspace:
        # Strip the original heading and include content
        content = workspace.split("\n", 1)[-1].strip() if "\n" in workspace else workspace
        spec += content + "\n\n"
    else:
        spec += "No workspace analysis available.\n\n"

    # Section 2: Requirements
    requirements = _read_artifact(aidlc_docs_dir, "requirements.md")
    spec += "## 2. Requirements\n\n"
    if requirements:
        # Include requirements content, stripping top-level heading and metadata
        for section_name in [
            "Target Users", "Channels", "Core Capabilities",
            "Data Sources", "Compliance Requirements", "Deployment Target",
        ]:
            section = _extract_section(requirements, section_name)
            if section:
                spec += f"### {section_name}\n\n{section}\n\n"
    else:
        spec += "No requirements document available.\n\n"

    # Section 3: User Stories (if present)
    user_stories = _read_artifact(aidlc_docs_dir, "user-stories.md")
    if user_stories:
        spec += "## 3. User Stories\n\n"
        for section_name in ["Actors", "User Journeys", "Edge Cases"]:
            section = _extract_section(user_stories, section_name)
            if section:
                spec += f"### {section_name}\n\n{section}\n\n"

    # Section 4: Architecture (from application design)
    app_design = _read_artifact(aidlc_docs_dir, "application-design.md")
    spec += "## 4. Architecture\n\n"
    if app_design:
        for section_name in ["Components", "APIs", "Data Flow", "Integration Points"]:
            section = _extract_section(app_design, section_name)
            if section:
                spec += f"### {section_name}\n\n{section}\n\n"
    else:
        spec += "Architecture to be defined during construction.\n\n"

    # Section 5: Workflow Plan
    workflow_plan = _read_artifact(aidlc_docs_dir, "workflow-plan.md")
    if workflow_plan:
        spec += "## 5. Workflow Plan\n\n"
        for section_name in ["Construction Stages", "Execution Strategy"]:
            section = _extract_section(workflow_plan, section_name)
            if section:
                spec += f"### {section_name}\n\n{section}\n\n"

    # Section 6: Work Units (if present)
    units = _read_artifact(aidlc_docs_dir, "units.md")
    if units:
        spec += "## 6. Work Units\n\n"
        for section_name in ["Work Units", "Dependencies", "Delivery Order"]:
            section = _extract_section(units, section_name)
            if section:
                spec += f"### {section_name}\n\n{section}\n\n"

    # Section 7: Acceptance Criteria
    spec += "## 7. Acceptance Criteria\n\n"
    ac_num = 1
    req_data = _get_requirements_data(state)

    # Generate ACs from requirements
    capabilities = req_data.get("capabilities", [])
    if isinstance(capabilities, list):
        for cap in capabilities:
            spec += f"- **AC-{ac_num:03d}:** Agent supports {cap}\n"
            ac_num += 1

    channels = req_data.get("channels", [])
    if isinstance(channels, list):
        for ch in channels:
            spec += f"- **AC-{ac_num:03d}:** Agent operates on {ch} channel\n"
            ac_num += 1

    compliance = req_data.get("compliance", "none")
    if isinstance(compliance, str) and compliance.lower() not in ("none", ""):
        spec += f"- **AC-{ac_num:03d}:** Agent meets compliance requirement: {compliance}\n"
        ac_num += 1

    deploy = req_data.get("deployment_target", "")
    if deploy:
        spec += f"- **AC-{ac_num:03d}:** Agent deploys to {deploy}\n"
        ac_num += 1

    # Standard ACs
    spec += f"- **AC-{ac_num:03d}:** All tests pass with 80%+ coverage\n"
    ac_num += 1
    spec += f"- **AC-{ac_num:03d}:** No hardcoded secrets in codebase\n"
    ac_num += 1

    spec += "\n"

    # Section 8: Risks
    spec += "## 8. Risks\n\n"
    spec += "| Risk | Impact | Mitigation |\n"
    spec += "|------|--------|------------|\n"
    spec += "| Scope creep | Delayed delivery | Strict AC-based scope |\n"
    spec += "| API rate limits | Feature degradation | Retry with backoff |\n"
    spec += "| Test coverage gaps | Regressions | TDD enforcement |\n"

    return spec


def generate_claude_md(state: WorkflowState) -> str:
    """Generate a project-specific CLAUDE.md from Inception decisions.

    Includes tech stack, architecture constraints, testing standards,
    and references to .claude/rules/ enforcement files.

    Args:
        state: The completed workflow state.

    Returns:
        CLAUDE.md content as a string.

    Traces to: AC-7 (CLAUDE.md includes .claude/rules/ enforcement files)
    """
    req_data = _get_requirements_data(state)
    deploy_target = _get_deployment_target(state)

    md = f"# CLAUDE.md — {state.project_name}\n\n"
    md += "> Auto-generated by AIDLC Inception. Do not edit manually.\n\n"

    # Project overview
    md += "## Project Overview\n\n"
    md += f"**Repository:** {state.repo}  \n"
    md += f"**Complexity:** {state.complexity.value}  \n"
    if deploy_target:
        md += f"**Deployment Target:** {deploy_target}  \n"
    md += "\n"

    # Tech stack (derived from decisions and requirements)
    md += "## Tech Stack\n\n"
    md += "- **Language:** Python 3.11+\n"
    md += "- **Testing:** pytest + pytest-asyncio\n"
    channels = req_data.get("channels", [])
    if isinstance(channels, list):
        for ch in channels:
            if ch.lower() == "slack":
                md += "- **Messaging:** Slack integration\n"
            elif ch.lower() == "api":
                md += "- **API:** REST API endpoints\n"
            elif ch.lower() == "web":
                md += "- **Frontend:** Web interface\n"
    if deploy_target and "agentcore" in deploy_target.lower():
        md += "- **Runtime:** Amazon Bedrock AgentCore\n"
        md += "- **Agent Framework:** Strands Agents SDK\n"
    md += "\n"

    # Architecture constraints
    md += "## Architecture Constraints\n\n"
    compliance = req_data.get("compliance", "none")
    if isinstance(compliance, str) and compliance.lower() not in ("none", ""):
        md += f"- Compliance: {compliance}\n"
    if deploy_target and "agentcore" in deploy_target.lower():
        md += "- Container must start within 60 seconds\n"
        md += "- No local filesystem persistence — use external state stores\n"
        md += "- Environment variables for all configuration\n"
    md += "- No hardcoded secrets\n"
    md += "- All user inputs validated\n"
    md += "\n"

    # Testing standards
    md += "## Testing Standards\n\n"
    md += "- **TDD Required:** Write failing test FIRST, then implement\n"
    md += "- Minimum coverage: 80%\n"
    md += "- Use pytest fixtures, not test setup/teardown methods\n"
    md += "- Mock external services in unit tests\n"
    md += "- Test file naming: `tests/test_{module_name}.py`\n\n"

    # Coding standards
    md += "## Coding Standards\n\n"
    md += "- PEP 8, max line length 120\n"
    md += "- Type hints on all function signatures\n"
    md += "- Docstrings on all public functions (Google style)\n"
    md += "- Use `pathlib.Path` over `os.path`\n"
    md += "- No bare `except:` — always catch specific exceptions\n"
    md += "- Use `logging` module, not `print()`\n\n"

    # Rules references
    md += "## Enforcement Rules\n\n"
    md += "The following `.claude/rules/` files enforce these standards:\n\n"
    md += "- `.claude/rules/tdd-rule.md` — Write failing tests before implementation\n"
    md += "- `.claude/rules/spec-compliance.md` — All code must trace to spec.md AC\n"
    if deploy_target and "agentcore" in deploy_target.lower():
        md += "- `.claude/rules/agentcore-patterns.md` — AgentCore deployment patterns\n"
    md += "\n"

    # Decisions log
    if state.decisions:
        md += "## Key Decisions\n\n"
        for decision in state.decisions:
            md += f"- **{decision.get('decision', '')}**: {decision.get('rationale', '')}\n"
        md += "\n"

    return md


def generate_test_cases(state: WorkflowState) -> str:
    """Generate test-cases.md with one test case per acceptance criterion.

    Args:
        state: The completed workflow state.

    Returns:
        test-cases.md content as a string.

    Traces to: AC-8 (Every AC in spec.md has a corresponding test case)
    """
    req_data = _get_requirements_data(state)

    md = f"# Test Cases — {state.project_name}\n\n"
    md += "> Auto-generated by AIDLC Inception. One test case per acceptance criterion.\n\n"
    md += "---\n\n"

    tc_num = 1
    ac_num = 1

    # Test cases from capabilities
    capabilities = req_data.get("capabilities", [])
    if isinstance(capabilities, list):
        for cap in capabilities:
            md += f"## TC-{tc_num:03d} (traces to AC-{ac_num:03d})\n\n"
            md += f"**Description:** Verify agent supports {cap}\n\n"
            md += "**Setup:** Agent is initialised with required configuration\n\n"
            md += "**Steps:**\n\n"
            md += f"1. Invoke the agent with a request related to {cap}\n"
            md += "2. Observe the agent's response\n\n"
            md += f"**Expected:** Agent correctly handles {cap} request\n\n"
            md += "**Type:** integration\n\n"
            md += "---\n\n"
            tc_num += 1
            ac_num += 1

    # Test cases from channels
    channels = req_data.get("channels", [])
    if isinstance(channels, list):
        for ch in channels:
            md += f"## TC-{tc_num:03d} (traces to AC-{ac_num:03d})\n\n"
            md += f"**Description:** Verify agent operates on {ch} channel\n\n"
            md += f"**Setup:** {ch} channel is configured and accessible\n\n"
            md += "**Steps:**\n\n"
            md += f"1. Send a message via {ch} channel\n"
            md += "2. Verify agent receives and processes the message\n"
            md += "3. Verify agent responds via the same channel\n\n"
            md += f"**Expected:** Agent sends and receives messages on {ch}\n\n"
            md += "**Type:** e2e\n\n"
            md += "---\n\n"
            tc_num += 1
            ac_num += 1

    # Test case for compliance
    compliance = req_data.get("compliance", "none")
    if isinstance(compliance, str) and compliance.lower() not in ("none", ""):
        md += f"## TC-{tc_num:03d} (traces to AC-{ac_num:03d})\n\n"
        md += f"**Description:** Verify compliance with {compliance}\n\n"
        md += "**Setup:** Agent is running in a controlled test environment\n\n"
        md += "**Steps:**\n\n"
        md += f"1. Exercise agent functionality that touches {compliance} requirements\n"
        md += "2. Audit logs and data handling for compliance\n\n"
        md += f"**Expected:** Agent meets {compliance} requirements\n\n"
        md += "**Type:** integration\n\n"
        md += "---\n\n"
        tc_num += 1
        ac_num += 1

    # Test case for deployment
    deploy = req_data.get("deployment_target", "")
    if deploy:
        md += f"## TC-{tc_num:03d} (traces to AC-{ac_num:03d})\n\n"
        md += f"**Description:** Verify agent deploys to {deploy}\n\n"
        md += f"**Setup:** {deploy} environment is configured\n\n"
        md += "**Steps:**\n\n"
        md += f"1. Deploy agent to {deploy}\n"
        md += "2. Verify health check endpoint responds\n"
        md += "3. Send a test request and verify response\n\n"
        md += f"**Expected:** Agent runs successfully on {deploy}\n\n"
        md += "**Type:** e2e\n\n"
        md += "---\n\n"
        tc_num += 1
        ac_num += 1

    # Standard test cases
    md += f"## TC-{tc_num:03d} (traces to AC-{ac_num:03d})\n\n"
    md += "**Description:** Verify test coverage meets 80% threshold\n\n"
    md += "**Setup:** Test suite is configured with coverage reporting\n\n"
    md += "**Steps:**\n\n"
    md += "1. Run full test suite with coverage\n"
    md += "2. Check coverage report\n\n"
    md += "**Expected:** Coverage is 80% or higher\n\n"
    md += "**Type:** unit\n\n"
    md += "---\n\n"
    tc_num += 1
    ac_num += 1

    md += f"## TC-{tc_num:03d} (traces to AC-{ac_num:03d})\n\n"
    md += "**Description:** Verify no hardcoded secrets in codebase\n\n"
    md += "**Setup:** Codebase is available for scanning\n\n"
    md += "**Steps:**\n\n"
    md += "1. Run secret scanning tool across all source files\n"
    md += "2. Check for API keys, passwords, tokens in source\n\n"
    md += "**Expected:** No hardcoded secrets found\n\n"
    md += "**Type:** unit\n\n"

    return md


def generate_agentcore_refs(state: WorkflowState) -> str | None:
    """Generate AgentCore reference documentation if deployment target is AgentCore.

    Args:
        state: The completed workflow state.

    Returns:
        AgentCore patterns documentation as a string, or None if
        the deployment target is not AgentCore.

    Traces to: AC-9 (AgentCore references when deployment target is AgentCore)
    """
    deploy_target = _get_deployment_target(state)
    if not deploy_target or "agentcore" not in deploy_target.lower():
        return None

    md = f"# AgentCore Patterns — {state.project_name}\n\n"
    md += "> Reference documentation for deploying to Amazon Bedrock AgentCore.\n\n"
    md += "---\n\n"

    md += "## Deployment Configuration\n\n"
    md += "```yaml\n"
    md += "# .bedrock_agentcore.yaml\n"
    md += "runtime: python3.11\n"
    md += "memory: 2048\n"
    md += "timeout: 60\n"
    md += "health_check:\n"
    md += "  path: /health\n"
    md += "  interval: 30\n"
    md += "```\n\n"

    md += "## Memory Integration\n\n"
    md += "Use AgentCore Memory for cross-session state persistence:\n\n"
    md += "```python\n"
    md += "from bedrock_agentcore.memory import MemoryClient\n\n"
    md += "memory = MemoryClient()\n"
    md += "memory.store(session_id, key, value)\n"
    md += "value = memory.retrieve(session_id, key)\n"
    md += "```\n\n"

    md += "## IAM Best Practices\n\n"
    md += "- Follow least-privilege principle\n"
    md += "- Use IAM roles, not access keys\n"
    md += "- Scope permissions to specific resources\n"
    md += "- Rotate credentials regularly\n\n"

    md += "## Cedar Policy Templates\n\n"
    md += "```cedar\n"
    md += "permit(\n"
    md += "  principal,\n"
    md += "  action == Action::\"invoke\",\n"
    md += "  resource\n"
    md += ") when {\n"
    md += "  principal.tenant == resource.tenant\n"
    md += "};\n"
    md += "```\n\n"

    md += "## Health Check Endpoint\n\n"
    md += "Every AgentCore agent must expose a health check:\n\n"
    md += "```python\n"
    md += "@app.get(\"/health\")\n"
    md += "def health():\n"
    md += "    return {\"status\": \"healthy\"}\n"
    md += "```\n"

    return md
