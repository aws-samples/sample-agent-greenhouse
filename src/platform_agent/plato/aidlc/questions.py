"""AIDLC structured question generator.

Produces stage-specific questions that adapt depth to project complexity.
Questions follow the AIDLC question-format-guide: structured, multiple-choice
where possible, with complexity-driven depth.

Traces to: AC-4 (Stage depth adapts based on complexity assessment),
           spec §3.1 (structured questions per stage)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from platform_agent.plato.aidlc.stages import StageID
from platform_agent.plato.aidlc.state import Complexity


class QuestionType(str, Enum):
    """Type of structured question."""

    MULTIPLE_CHOICE = "multiple_choice"
    FREE_TEXT = "free_text"
    YES_NO = "yes_no"


@dataclass(frozen=True)
class Question:
    """A structured question for an AIDLC stage.

    Attributes:
        id: Unique question identifier (e.g. "req-001").
        text: The question text shown to the developer.
        question_type: How the question should be answered.
        options: Available options for MULTIPLE_CHOICE questions.
        required: Whether the question must be answered.
    """

    id: str
    text: str
    question_type: QuestionType
    options: list[str] | None = None
    required: bool = True


# ---------------------------------------------------------------------------
# Question banks per stage
# ---------------------------------------------------------------------------

_WORKSPACE_QUESTIONS: list[Question] = [
    Question(
        id="ws-001",
        text="Do you have an existing repository for this project?",
        question_type=QuestionType.YES_NO,
    ),
    Question(
        id="ws-002",
        text="If yes, what is the repository URL?",
        question_type=QuestionType.FREE_TEXT,
        required=False,
    ),
    Question(
        id="ws-003",
        text="Is this a brownfield (modifying existing code) or greenfield (starting fresh) project?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["Brownfield", "Greenfield"],
    ),
]

_REQUIREMENTS_BASE: list[Question] = [
    Question(
        id="req-001",
        text="Who are the target users of this agent?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["External customers", "Internal teams", "Both"],
    ),
    Question(
        id="req-002",
        text="Which channels will the agent operate on?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["Slack", "API", "Web", "Multi-channel"],
    ),
    Question(
        id="req-003",
        text="What are the core capabilities of the agent?",
        question_type=QuestionType.FREE_TEXT,
    ),
    Question(
        id="req-004",
        text="What data sources will the agent need access to?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["Knowledge base", "CRM", "APIs", "Databases", "Multiple"],
    ),
    Question(
        id="req-005",
        text="Are there compliance requirements?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["None", "PII handling", "Audit trail", "Industry-specific (SOC2, HIPAA, etc.)"],
    ),
    Question(
        id="req-006",
        text="What is the deployment target?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["AgentCore", "Self-hosted", "Hybrid"],
    ),
]

_REQUIREMENTS_COMPLEX_EXTRA: list[Question] = [
    Question(
        id="req-007",
        text="Describe any regulatory or compliance frameworks that apply.",
        question_type=QuestionType.FREE_TEXT,
    ),
    Question(
        id="req-008",
        text="What is the expected volume of interactions per day?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["< 100", "100 - 1,000", "1,000 - 10,000", "> 10,000"],
    ),
    Question(
        id="req-009",
        text="Are there existing systems this agent must integrate with?",
        question_type=QuestionType.FREE_TEXT,
    ),
]

_USER_STORIES_BASE: list[Question] = [
    Question(
        id="us-001",
        text="What actor types interact with the agent?",
        question_type=QuestionType.FREE_TEXT,
    ),
    Question(
        id="us-002",
        text="Describe the primary user journeys.",
        question_type=QuestionType.FREE_TEXT,
    ),
]

_USER_STORIES_COMPLEX_EXTRA: list[Question] = [
    Question(
        id="us-003",
        text="What edge cases or failure scenarios should be handled?",
        question_type=QuestionType.FREE_TEXT,
    ),
    Question(
        id="us-004",
        text="Are there different permission levels for different actors?",
        question_type=QuestionType.YES_NO,
    ),
]

_WORKFLOW_PLANNING_BASE: list[Question] = [
    Question(
        id="wp-001",
        text="What construction stages are needed?",
        question_type=QuestionType.FREE_TEXT,
    ),
    Question(
        id="wp-002",
        text="Can any stages run in parallel, or must they be sequential?",
        question_type=QuestionType.MULTIPLE_CHOICE,
        options=["Parallel where possible", "Strictly sequential"],
    ),
]

_WORKFLOW_PLANNING_COMPLEX_EXTRA: list[Question] = [
    Question(
        id="wp-003",
        text="What is the estimated effort for each stage?",
        question_type=QuestionType.FREE_TEXT,
    ),
]

_APP_DESIGN_BASE: list[Question] = [
    Question(
        id="ad-001",
        text="What components make up the application?",
        question_type=QuestionType.FREE_TEXT,
    ),
    Question(
        id="ad-002",
        text="Are there external APIs the agent needs to call?",
        question_type=QuestionType.FREE_TEXT,
    ),
]

_APP_DESIGN_COMPLEX_EXTRA: list[Question] = [
    Question(
        id="ad-003",
        text="Describe the data flow between components.",
        question_type=QuestionType.FREE_TEXT,
    ),
    Question(
        id="ad-004",
        text="What integration points exist with external systems?",
        question_type=QuestionType.FREE_TEXT,
    ),
]

_UNITS_BASE: list[Question] = [
    Question(
        id="un-001",
        text="How should the work be decomposed into units?",
        question_type=QuestionType.FREE_TEXT,
    ),
    Question(
        id="un-002",
        text="What are the dependencies between units?",
        question_type=QuestionType.FREE_TEXT,
    ),
]

_UNITS_COMPLEX_EXTRA: list[Question] = [
    Question(
        id="un-003",
        text="What is the recommended delivery order for the units?",
        question_type=QuestionType.FREE_TEXT,
    ),
]

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_QUESTION_BANKS: dict[StageID, tuple[list[Question], list[Question]]] = {
    StageID.WORKSPACE_DETECTION: (_WORKSPACE_QUESTIONS, []),
    StageID.REQUIREMENTS: (_REQUIREMENTS_BASE, _REQUIREMENTS_COMPLEX_EXTRA),
    StageID.USER_STORIES: (_USER_STORIES_BASE, _USER_STORIES_COMPLEX_EXTRA),
    StageID.WORKFLOW_PLANNING: (_WORKFLOW_PLANNING_BASE, _WORKFLOW_PLANNING_COMPLEX_EXTRA),
    StageID.APP_DESIGN: (_APP_DESIGN_BASE, _APP_DESIGN_COMPLEX_EXTRA),
    StageID.UNITS: (_UNITS_BASE, _UNITS_COMPLEX_EXTRA),
}


def get_questions_for_stage(stage_id: StageID, complexity: Complexity) -> list[Question]:
    """Return the list of questions for a given stage and complexity level.

    SIMPLE complexity returns only the base questions.
    STANDARD returns base questions.
    COMPLEX returns base + extra deep-dive questions.

    Args:
        stage_id: The stage to get questions for.
        complexity: Current project complexity assessment.

    Returns:
        Ordered list of Question objects.

    Traces to: AC-4 (Stage depth adapts based on complexity assessment)
    """
    base, extra = _QUESTION_BANKS.get(stage_id, ([], []))
    if complexity == Complexity.COMPLEX:
        return list(base) + list(extra)
    return list(base)
