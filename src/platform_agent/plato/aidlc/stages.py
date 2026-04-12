"""AIDLC stage definitions.

Defines the ordered stages of the AIDLC Inception workflow, their metadata,
and lookup utilities.

Traces to: spec §3.1 (AIDLC Inception Skill stages), §6.1 (Workflow Engine)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StageID(str, Enum):
    """Identifier for each AIDLC Inception stage.

    The value is a human-readable slug used in serialisation.
    """

    WORKSPACE_DETECTION = "workspace_detection"
    REQUIREMENTS = "requirements"
    USER_STORIES = "user_stories"
    WORKFLOW_PLANNING = "workflow_planning"
    APP_DESIGN = "app_design"
    UNITS = "units"


@dataclass(frozen=True)
class Stage:
    """Immutable definition of an AIDLC stage.

    Attributes:
        id: Unique stage identifier.
        name: Human-readable stage name.
        description: What happens in this stage.
        is_conditional: Whether the stage can be skipped based on complexity.
        output_artifact: Relative path (under aidlc-docs/) for the stage artifact.
        gate_prompt: Approval gate prompt shown to the developer.
    """

    id: StageID
    name: str
    description: str
    is_conditional: bool
    output_artifact: str
    gate_prompt: str


STAGE_DEFINITIONS: list[Stage] = [
    Stage(
        id=StageID.WORKSPACE_DETECTION,
        name="Workspace Detection",
        description=(
            "Detect whether the developer has an existing repository or is "
            "starting fresh. Determine brownfield vs greenfield."
        ),
        is_conditional=False,
        output_artifact="workspace-analysis.md",
        gate_prompt="Please confirm the workspace analysis is correct.",
    ),
    Stage(
        id=StageID.REQUIREMENTS,
        name="Requirements Analysis",
        description=(
            "Gather structured requirements: target users, channels, "
            "capabilities, data sources, compliance, and deployment target."
        ),
        is_conditional=False,
        output_artifact="requirements.md",
        gate_prompt="Please approve the requirements document.",
    ),
    Stage(
        id=StageID.USER_STORIES,
        name="User Stories",
        description=(
            "Define actor types, user journeys, and edge cases. "
            "Conditional — skipped for simple single-purpose agents."
        ),
        is_conditional=True,
        output_artifact="user-stories.md",
        gate_prompt="Please approve the user stories.",
    ),
    Stage(
        id=StageID.WORKFLOW_PLANNING,
        name="Workflow Planning",
        description=(
            "Determine construction stages, sequencing, and estimated effort. "
            "Create change sequence for brownfield projects."
        ),
        is_conditional=False,
        output_artifact="workflow-plan.md",
        gate_prompt="Please approve the workflow plan.",
    ),
    Stage(
        id=StageID.APP_DESIGN,
        name="Application Design",
        description=(
            "Define components, APIs, data flow, and integration points. "
            "Conditional — skipped for simple projects."
        ),
        is_conditional=True,
        output_artifact="application-design.md",
        gate_prompt="Please approve the application design.",
    ),
    Stage(
        id=StageID.UNITS,
        name="Units Generation",
        description=(
            "Decompose into parallel work units with dependencies and "
            "delivery order. Conditional — skipped for simple projects."
        ),
        is_conditional=True,
        output_artifact="units.md",
        gate_prompt="Please approve the work units.",
    ),
]

_STAGE_INDEX: dict[StageID, Stage] = {s.id: s for s in STAGE_DEFINITIONS}


def get_stage(stage_id: StageID) -> Stage:
    """Look up a stage definition by ID.

    Args:
        stage_id: The stage to look up.

    Returns:
        The Stage definition.

    Raises:
        KeyError: If the stage_id is not found.
    """
    try:
        return _STAGE_INDEX[stage_id]
    except KeyError:
        raise KeyError(f"Unknown stage: {stage_id}") from None
