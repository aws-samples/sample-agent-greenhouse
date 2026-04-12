"""AIDLC Inception Strands tools — workflow management via LLM tool_use.

Provides tools for starting, progressing, and completing an AIDLC Inception
workflow. Each tool manages workflow state via a module-level registry,
loading from disk on first access and saving after each mutation.

Project directories are auto-computed under a shared PROJECTS_BASE_DIR
(default: /mnt/workspace/projects when AgentCore managed session storage
is mounted, otherwise /app/workspace/projects). The LLM never needs to
supply filesystem paths — only project_name, tenant_id, and repo.

Traces to: spec §3.1 (AIDLC Inception Skill)
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from platform_agent.plato.aidlc.questions import Question
from platform_agent.plato.aidlc.stages import StageID, get_stage
from platform_agent.plato.aidlc.state import StageStatus
from platform_agent.plato.aidlc.workflow import AIDLCWorkflow
from platform_agent.foundation.hooks.aidlc_telemetry_hook import AIDLCTelemetryHook

logger = logging.getLogger(__name__)

try:
    from strands import tool as strands_tool

    _HAS_STRANDS = True
except ImportError:
    _HAS_STRANDS = False
    import functools

    def strands_tool(fn):  # type: ignore[misc]
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)
        return wrapper


# ---------------------------------------------------------------------------
# Project directory resolution
# ---------------------------------------------------------------------------

# Prefer /mnt/workspace/projects (AgentCore managed session storage) when
# the mount exists; fall back to WORKSPACE_DIR/projects otherwise.
# NOTE: /mnt/workspace is only mounted at invocation time, not during
# container init.  We resolve lazily on first use.
_MNT_PROJECTS = "/mnt/workspace/projects"
_APP_PROJECTS = os.path.join(
    os.environ.get(
        "WORKSPACE_DIR",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "workspace"),
    ),
    "projects",
)

_projects_base_dir: str | None = None


def _get_projects_base_dir() -> str:
    """Lazily resolve PROJECTS_BASE_DIR.

    /mnt/workspace is only mounted during AgentCore invocations, not at
    container start / module import time. We check on first call and cache.
    """
    global _projects_base_dir
    if _projects_base_dir is None:
        _projects_base_dir = (
            _MNT_PROJECTS if os.path.isdir("/mnt/workspace") else _APP_PROJECTS
        )
        logger.info("AIDLC projects base dir: %s", _projects_base_dir)
    return _projects_base_dir


def _slugify(name: str) -> str:
    """Convert a project name into a safe directory slug.

    Examples:
        "HR QA Agent"      → "hr-qa-agent"
        "Employee KB Bot!"  → "employee-kb-bot"
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "project"


def _project_dir(project_name: str) -> Path:
    """Return the absolute project directory for a given project name."""
    return Path(_get_projects_base_dir()) / _slugify(project_name)


# ---------------------------------------------------------------------------
# Active workflow registry — keyed by (tenant_id, repo)
# ---------------------------------------------------------------------------

_active_workflows: dict[tuple[str, str], AIDLCWorkflow] = {}

# AIDLC telemetry hooks — keyed same as workflows
_aidlc_telemetry_hooks: dict[tuple[str, str], AIDLCTelemetryHook] = {}


def _get_workflow(tenant_id: str, repo: str) -> AIDLCWorkflow:
    """Retrieve the active workflow, loading from disk if necessary.

    The project directory is recovered from the in-memory registry or
    from the current context (set by aidlc_start_inception).

    Args:
        tenant_id: Multi-tenant identifier.
        repo: GitHub repository (org/repo format).

    Returns:
        The active AIDLCWorkflow instance.

    Raises:
        RuntimeError: If no workflow exists for this tenant/repo.
    """
    key = (tenant_id, repo)
    if key in _active_workflows:
        return _active_workflows[key]

    # Try loading from disk using the stored workspace path
    if _current_workspace_path is not None:
        base_dir = Path(_current_workspace_path)
        try:
            wf = AIDLCWorkflow.load(base_dir)
            _active_workflows[key] = wf
            return wf
        except FileNotFoundError:
            pass

    raise RuntimeError(
        f"No active AIDLC workflow for tenant={tenant_id}, repo={repo}. "
        "Use aidlc_start_inception to begin a new workflow."
    )


def _save_workflow(wf: AIDLCWorkflow) -> None:
    """Persist workflow state to disk.

    Args:
        wf: The workflow to save.
    """
    wf.save()


def _format_questions(questions: list[Question]) -> str:
    """Format a list of questions into a human-readable string.

    Args:
        questions: List of Question objects to format.

    Returns:
        Formatted string with numbered questions.
    """
    lines: list[str] = []
    for i, q in enumerate(questions, 1):
        line = f"{i}. [{q.id}] {q.text}"
        if q.options:
            opts = ", ".join(q.options)
            line += f"\n   Options: {opts}"
        if not q.required:
            line += " (optional)"
        line += f"\n   Type: {q.question_type.value}"
        lines.append(line)
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Current workflow context — set after start/load for tools that don't take
# tenant_id/repo params (aidlc_get_questions, aidlc_get_status)
# ---------------------------------------------------------------------------

_current_tenant_id: str | None = None
_current_repo: str | None = None
_current_workspace_path: str | None = None


def _set_current_context(tenant_id: str, repo: str, workspace_path: str) -> None:
    """Set the current workflow context for parameterless tools."""
    global _current_tenant_id, _current_repo, _current_workspace_path
    _current_tenant_id = tenant_id
    _current_repo = repo
    _current_workspace_path = workspace_path


def _get_current_workflow() -> AIDLCWorkflow:
    """Get the workflow from the current context.

    Returns:
        The active AIDLCWorkflow instance.

    Raises:
        RuntimeError: If no workflow context is set.
    """
    if _current_tenant_id is None or _current_repo is None or _current_workspace_path is None:
        raise RuntimeError(
            "No active workflow context. Use aidlc_start_inception first."
        )
    return _get_workflow(_current_tenant_id, _current_repo)


# ---------------------------------------------------------------------------
# Strands tools
# ---------------------------------------------------------------------------


@strands_tool
def aidlc_start_inception(
    project_name: str,
    tenant_id: str,
    repo: str,
) -> str:
    """Start a new AIDLC Inception workflow.

    Creates a new workflow, initialises the state machine, and returns
    the first stage's questions.  The project workspace directory is
    computed automatically — the caller does not need to supply a path.

    Args:
        project_name: Name of the project being incepted.
        tenant_id: Multi-tenant identifier.
        repo: GitHub repository (org/repo format).

    Returns:
        Formatted text with workflow status and first stage questions.
    """
    key = (tenant_id, repo)
    if key in _active_workflows:
        return json.dumps({
            "status": "error",
            "message": f"Workflow already exists for {repo}. Use aidlc_get_status to check progress.",
        })

    base_dir = _project_dir(project_name)
    base_dir.mkdir(parents=True, exist_ok=True)
    workspace_path = str(base_dir)

    wf = AIDLCWorkflow(
        project_name=project_name,
        tenant_id=tenant_id,
        repo=repo,
        base_dir=base_dir,
    )
    # Wire AIDLC telemetry observer
    telemetry = AIDLCTelemetryHook()
    wf.on_event(telemetry.handle_event)
    wf.start()
    _active_workflows[key] = wf
    _aidlc_telemetry_hooks[key] = telemetry
    _set_current_context(tenant_id, repo, workspace_path)
    _save_workflow(wf)

    # Get first stage info
    stage = wf.get_current_stage()
    questions = wf.get_questions()
    formatted_qs = _format_questions(questions)

    return json.dumps({
        "status": "started",
        "project_name": project_name,
        "workspace_path": workspace_path,
        "current_stage": stage.name if stage else None,
        "current_stage_id": stage.id.value if stage else None,
        "questions": formatted_qs,
        "message": f"AIDLC Inception started for '{project_name}'. "
                   f"Workspace: {workspace_path}. "
                   f"Current stage: {stage.name if stage else 'none'}.",
    })


@strands_tool
def aidlc_get_questions() -> str:
    """Get questions for the current AIDLC stage.

    Returns:
        Formatted questions for the current stage, or an error if
        the workflow is complete or not started.
    """
    try:
        wf = _get_current_workflow()
    except RuntimeError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    stage = wf.get_current_stage()
    if stage is None:
        return json.dumps({
            "status": "complete",
            "message": "All stages are complete. Use aidlc_generate_artifacts to produce deliverables.",
        })

    questions = wf.get_questions()
    formatted_qs = _format_questions(questions)

    return json.dumps({
        "status": "ok",
        "current_stage": stage.name,
        "current_stage_id": stage.id.value,
        "gate_prompt": stage.gate_prompt,
        "questions": formatted_qs,
    })


@strands_tool
def aidlc_submit_answers(stage_id: str, answers_json: str) -> str:
    """Submit answers for the current stage.

    Parses the answers, generates the stage artifact, and transitions
    to awaiting approval.

    Args:
        stage_id: The stage being answered (e.g. "workspace_detection").
        answers_json: JSON string containing the answers dict.

    Returns:
        Status message with artifact preview and approval prompt.
    """
    try:
        wf = _get_current_workflow()
    except RuntimeError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    try:
        sid = StageID(stage_id)
    except ValueError:
        return json.dumps({
            "status": "error",
            "message": f"Invalid stage_id: {stage_id}. "
                       f"Valid values: {[s.value for s in StageID]}",
        })

    try:
        answers = json.loads(answers_json)
    except json.JSONDecodeError as exc:
        return json.dumps({
            "status": "error",
            "message": f"Invalid JSON in answers_json: {exc}",
        })

    try:
        wf.submit_answers(sid, answers)
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    _save_workflow(wf)

    stage_state = wf.state.stages.get(sid)
    stage_def = get_stage(sid)
    artifact_path = stage_state.output_path if stage_state else None

    return json.dumps({
        "status": "awaiting_approval",
        "stage_id": stage_id,
        "stage_name": stage_def.name,
        "artifact_path": artifact_path,
        "gate_prompt": stage_def.gate_prompt,
        "message": f"Stage '{stage_def.name}' answers submitted. "
                   f"Artifact generated at {artifact_path}. "
                   "Awaiting developer approval.",
    })


@strands_tool
def aidlc_approve_stage(stage_id: str, note: str = "") -> str:
    """Approve the current stage and advance to the next one.

    Args:
        stage_id: The stage being approved.
        note: Optional approval note.

    Returns:
        Next stage questions or completion message.
    """
    try:
        wf = _get_current_workflow()
    except RuntimeError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    try:
        sid = StageID(stage_id)
    except ValueError:
        return json.dumps({
            "status": "error",
            "message": f"Invalid stage_id: {stage_id}.",
        })

    try:
        wf.approve_stage(sid, note=note)
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    _save_workflow(wf)

    # Check if there's a next stage
    next_stage = wf.get_current_stage()
    if next_stage is None:
        return json.dumps({
            "status": "all_stages_complete",
            "message": "All Inception stages are complete! "
                       "Use aidlc_generate_artifacts to produce the final deliverable package.",
        })

    questions = wf.get_questions()
    formatted_qs = _format_questions(questions)

    return json.dumps({
        "status": "advanced",
        "approved_stage": stage_id,
        "next_stage": next_stage.name,
        "next_stage_id": next_stage.id.value,
        "questions": formatted_qs,
        "message": f"Stage '{stage_id}' approved. Next stage: {next_stage.name}.",
    })


@strands_tool
def aidlc_reject_stage(stage_id: str, feedback: str = "") -> str:
    """Reject a stage and return it to in-progress for rework.

    Args:
        stage_id: The stage being rejected.
        feedback: Reason for rejection.

    Returns:
        Status message with the stage's questions for rework.
    """
    try:
        wf = _get_current_workflow()
    except RuntimeError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    try:
        sid = StageID(stage_id)
    except ValueError:
        return json.dumps({
            "status": "error",
            "message": f"Invalid stage_id: {stage_id}.",
        })

    try:
        wf.reject_stage(sid, feedback=feedback)
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    _save_workflow(wf)

    questions = wf.get_questions()
    formatted_qs = _format_questions(questions)

    return json.dumps({
        "status": "rejected",
        "stage_id": stage_id,
        "feedback": feedback,
        "questions": formatted_qs,
        "message": f"Stage '{stage_id}' rejected. Please rework and resubmit. "
                   f"Feedback: {feedback}",
    })


@strands_tool
def aidlc_get_status() -> str:
    """Get current workflow status and progress.

    Returns:
        JSON string with current stage, progress dict, and completion percentage.
    """
    try:
        wf = _get_current_workflow()
    except RuntimeError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    status = wf.get_status()
    stage = wf.get_current_stage()

    return json.dumps({
        "status": "ok",
        "project_name": wf.state.project_name,
        "current_stage": stage.name if stage else None,
        "current_stage_id": status["current_stage"],
        "progress": status["progress"],
        "completion_pct": status["completion_pct"],
        "complexity": wf.state.complexity.value,
    })


@strands_tool
def aidlc_generate_artifacts() -> str:
    """Generate final deliverable package after Inception completes.

    Produces spec.md, CLAUDE.md, test-cases.md, and optionally
    .claude/rules/*.md files from the completed Inception artifacts.
    Uses the project workspace that was set when the workflow started.

    Returns:
        JSON string listing generated files, or error if workflow is not complete.
    """
    try:
        wf = _get_current_workflow()
    except RuntimeError as exc:
        return json.dumps({"status": "error", "message": str(exc)})

    # Verify workflow is complete
    if wf.get_current_stage() is not None:
        return json.dumps({
            "status": "error",
            "message": "Workflow is not yet complete. "
                       "All stages must be approved before generating artifacts.",
        })

    from platform_agent.plato.skills.aidlc_inception.deliverables import (
        generate_agentcore_refs,
        generate_claude_md,
        generate_spec,
        generate_test_cases,
    )

    base_dir = wf.base_dir
    aidlc_docs_dir = base_dir / "aidlc-docs"
    generated_files: list[str] = []

    # spec.md
    spec_content = generate_spec(wf.state, aidlc_docs_dir)
    spec_path = base_dir / "spec.md"
    spec_path.write_text(spec_content)
    generated_files.append("spec.md")

    # CLAUDE.md
    claude_content = generate_claude_md(wf.state)
    claude_path = base_dir / "CLAUDE.md"
    claude_path.write_text(claude_content)
    generated_files.append("CLAUDE.md")

    # test-cases.md
    test_cases_content = generate_test_cases(wf.state)
    test_cases_path = base_dir / "test-cases.md"
    test_cases_path.write_text(test_cases_content)
    generated_files.append("test-cases.md")

    # .claude/rules/ files
    rules_dir = base_dir / ".claude" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    tdd_rule = (
        "# TDD Rule\n\n"
        "Write failing tests before implementation. "
        "Every new function needs at least one unit test.\n"
    )
    (rules_dir / "tdd-rule.md").write_text(tdd_rule)
    generated_files.append(".claude/rules/tdd-rule.md")

    spec_compliance_rule = (
        "# Spec Compliance Rule\n\n"
        "All code must trace to a spec.md acceptance criterion. "
        "If code cannot be linked to an AC, it is out of scope.\n"
    )
    (rules_dir / "spec-compliance.md").write_text(spec_compliance_rule)
    generated_files.append(".claude/rules/spec-compliance.md")

    # AgentCore references (conditional)
    agentcore_content = generate_agentcore_refs(wf.state)
    if agentcore_content is not None:
        agentcore_dir = base_dir / "docs" / "agentcore"
        agentcore_dir.mkdir(parents=True, exist_ok=True)
        (agentcore_dir / "agentcore-patterns.md").write_text(agentcore_content)
        generated_files.append("docs/agentcore/agentcore-patterns.md")

        agentcore_rule = (
            "# AgentCore Patterns Rule\n\n"
            "Follow AgentCore-specific patterns for deployment, memory, "
            "and IAM configuration. See docs/agentcore/ for reference.\n"
        )
        (rules_dir / "agentcore-patterns.md").write_text(agentcore_rule)
        generated_files.append(".claude/rules/agentcore-patterns.md")

    return json.dumps({
        "status": "generated",
        "files": generated_files,
        "file_count": len(generated_files),
        "workspace_path": str(base_dir),
        "message": f"Generated {len(generated_files)} deliverable files in {base_dir}.",
    })


# All AIDLC tools for easy import
AIDLC_INCEPTION_TOOLS = [
    aidlc_start_inception,
    aidlc_get_questions,
    aidlc_submit_answers,
    aidlc_approve_stage,
    aidlc_reject_stage,
    aidlc_get_status,
    aidlc_generate_artifacts,
]
