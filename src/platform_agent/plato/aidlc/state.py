"""AIDLC workflow state persistence.

Provides dataclasses for tracking stage and workflow state, plus
file-based JSON serialisation to ``aidlc-docs/aidlc-state.json``.

Traces to: AC-21 (State persists across sessions),
           AC-3 (Audit log captures every human input verbatim)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from platform_agent.plato.aidlc.stages import StageID

logger = logging.getLogger(__name__)


class StageStatus(str, Enum):
    """Status of an individual AIDLC stage."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SKIPPED = "skipped"


class Complexity(str, Enum):
    """Project complexity level — drives conditional stage inclusion."""

    SIMPLE = "simple"
    STANDARD = "standard"
    COMPLEX = "complex"


@dataclass
class StageState:
    """Mutable state for a single AIDLC stage.

    Attributes:
        stage_id: Which stage this state belongs to.
        status: Current status of the stage.
        started_at: ISO timestamp when the stage entered IN_PROGRESS.
        completed_at: ISO timestamp when the stage was APPROVED or SKIPPED.
        output_path: Relative path to the generated artifact (under aidlc-docs/).
        approval_note: Optional note from the approver.
    """

    stage_id: StageID
    status: StageStatus = StageStatus.PENDING
    started_at: str | None = None
    completed_at: str | None = None
    output_path: str | None = None
    approval_note: str = ""


@dataclass
class WorkflowState:
    """Full workflow state for an AIDLC Inception session.

    Attributes:
        project_name: Name of the project being incepted.
        tenant_id: Multi-tenant identifier.
        repo: GitHub repository (org/repo format).
        created_at: ISO timestamp of workflow creation.
        current_stage_id: The stage currently being executed (or None if complete).
        stages: Per-stage state, keyed by StageID.
        complexity: Assessed project complexity.
        decisions: Logged decisions with rationale.
        audit_entries: Timestamped audit log of all user inputs.
    """

    project_name: str
    tenant_id: str
    repo: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current_stage_id: StageID | None = None
    stages: dict[StageID, StageState] = field(default_factory=dict)
    complexity: Complexity = Complexity.STANDARD
    decisions: list[dict[str, Any]] = field(default_factory=list)
    audit_entries: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

_STATE_DIR = "aidlc-docs"
_STATE_FILE = "aidlc-state.json"


def _state_to_dict(state: WorkflowState) -> dict[str, Any]:
    """Convert WorkflowState to a JSON-serialisable dict."""
    stages_dict: dict[str, Any] = {}
    for sid, ss in state.stages.items():
        stages_dict[sid.value] = {
            "stage_id": ss.stage_id.value,
            "status": ss.status.value,
            "started_at": ss.started_at,
            "completed_at": ss.completed_at,
            "output_path": ss.output_path,
            "approval_note": ss.approval_note,
        }

    return {
        "project_name": state.project_name,
        "tenant_id": state.tenant_id,
        "repo": state.repo,
        "created_at": state.created_at,
        "current_stage_id": state.current_stage_id.value if state.current_stage_id else None,
        "stages": stages_dict,
        "complexity": state.complexity.value,
        "decisions": state.decisions,
        "audit_entries": state.audit_entries,
    }


def _dict_to_state(data: dict[str, Any]) -> WorkflowState:
    """Reconstruct a WorkflowState from a deserialised dict."""
    stages: dict[StageID, StageState] = {}
    for key, val in data.get("stages", {}).items():
        sid = StageID(key)
        stages[sid] = StageState(
            stage_id=sid,
            status=StageStatus(val["status"]),
            started_at=val.get("started_at"),
            completed_at=val.get("completed_at"),
            output_path=val.get("output_path"),
            approval_note=val.get("approval_note", ""),
        )

    current = data.get("current_stage_id")
    return WorkflowState(
        project_name=data["project_name"],
        tenant_id=data["tenant_id"],
        repo=data["repo"],
        created_at=data.get("created_at", ""),
        current_stage_id=StageID(current) if current else None,
        stages=stages,
        complexity=Complexity(data.get("complexity", "standard")),
        decisions=data.get("decisions", []),
        audit_entries=data.get("audit_entries", []),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def save_state(state: WorkflowState, base_dir: Path) -> Path:
    """Persist workflow state to ``aidlc-docs/aidlc-state.json``.

    Args:
        state: The workflow state to persist.
        base_dir: Project workspace root directory.

    Returns:
        Path to the written state file.

    Traces to: AC-21 (State persists across sessions)
    """
    docs_dir = base_dir / _STATE_DIR
    docs_dir.mkdir(parents=True, exist_ok=True)
    state_path = docs_dir / _STATE_FILE
    state_path.write_text(json.dumps(_state_to_dict(state), indent=2, default=str))
    logger.info("Saved AIDLC state to %s", state_path)
    return state_path


def load_state(base_dir: Path) -> WorkflowState:
    """Load workflow state from ``aidlc-docs/aidlc-state.json``.

    Args:
        base_dir: Project workspace root directory.

    Returns:
        The restored WorkflowState.

    Raises:
        FileNotFoundError: If the state file does not exist.

    Traces to: AC-22 (Workflow resumes from last approved stage on reconnect)
    """
    state_path = base_dir / _STATE_DIR / _STATE_FILE
    if not state_path.exists():
        raise FileNotFoundError(f"No AIDLC state file at {state_path}")
    data = json.loads(state_path.read_text())
    logger.info("Loaded AIDLC state from %s", state_path)
    return _dict_to_state(data)


def append_audit(
    state: WorkflowState,
    user_input: Any,
    stage_id: StageID,
) -> None:
    """Append a timestamped audit entry capturing user input verbatim.

    Args:
        state: The current workflow state (mutated in place).
        user_input: The raw user input to log.
        stage_id: Which stage the input relates to.

    Traces to: AC-3 (Audit log captures every human input verbatim)
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage_id": stage_id.value,
        "user_input": user_input,
    }
    state.audit_entries.append(entry)
