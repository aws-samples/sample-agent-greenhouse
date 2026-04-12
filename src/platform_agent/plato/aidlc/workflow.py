"""AIDLC Workflow Engine — the core state machine.

Manages stage transitions, approval gates, complexity-based conditional
skipping, artifact generation, and state persistence.

State machine:
  IDLE → WORKSPACE_DETECTION → REQUIREMENTS → [USER_STORIES] →
  WORKFLOW_PLANNING → [APP_DESIGN] → [UNITS] → complete

Brackets = conditional stages, skipped if complexity is SIMPLE.
Each transition requires APPROVED status on the current stage.

Traces to: AC-2, AC-21, AC-22, AC-23, AC-24
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from platform_agent.plato.aidlc.artifacts import (
    compile_app_design,
    compile_requirements,
    compile_units,
    compile_user_stories,
    compile_workflow_plan,
)
from platform_agent.plato.aidlc.questions import get_questions_for_stage, Question
from platform_agent.plato.aidlc.stages import STAGE_DEFINITIONS, Stage, StageID, get_stage
from platform_agent.plato.aidlc.state import (
    Complexity,
    StageState,
    StageStatus,
    WorkflowState,
    append_audit,
    load_state,
    save_state,
)

logger = logging.getLogger(__name__)

# Map stage IDs to their artifact compiler functions.
_ARTIFACT_COMPILERS: dict[StageID, Any] = {
    StageID.REQUIREMENTS: compile_requirements,
    StageID.USER_STORIES: compile_user_stories,
    StageID.WORKFLOW_PLANNING: compile_workflow_plan,
    StageID.APP_DESIGN: compile_app_design,
    StageID.UNITS: compile_units,
}


class AIDLCWorkflow:
    """State machine managing AIDLC Inception workflow progression.

    Attributes:
        state: The current workflow state.
        base_dir: Project workspace root directory.
    """

    def __init__(
        self,
        project_name: str,
        tenant_id: str,
        repo: str,
        base_dir: Path,
    ) -> None:
        """Create a new AIDLC workflow.

        Args:
            project_name: Name of the project being incepted.
            tenant_id: Multi-tenant identifier.
            repo: GitHub repository (org/repo format).
            base_dir: Project workspace root directory.
        """
        self.base_dir = Path(base_dir)
        self.state = WorkflowState(
            project_name=project_name,
            tenant_id=tenant_id,
            repo=repo,
        )
        self._event_callbacks: list[Callable] = []

    # ------------------------------------------------------------------
    # Event emitter
    # ------------------------------------------------------------------

    def on_event(self, callback: Callable) -> None:
        """Register a callback to receive workflow events.

        Args:
            callback: A callable accepting (event_type: str, data: dict).
        """
        self._event_callbacks.append(callback)

    def _emit_event(self, event_type: str, data: dict) -> None:
        """Emit an event to all registered callbacks.

        Args:
            event_type: Dotted event name (e.g. "aidlc.workflow_started").
            data: Event payload dict.
        """
        for cb in self._event_callbacks:
            try:
                cb(event_type, data)
            except Exception:
                logger.debug("Event callback error", exc_info=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Initialise the workflow, setting the first stage to IN_PROGRESS.

        Traces to: AC-24 (ordered progression)
        """
        first_stage = STAGE_DEFINITIONS[0]
        now = datetime.now(timezone.utc).isoformat()
        self.state.current_stage_id = first_stage.id
        for stage_def in STAGE_DEFINITIONS:
            self.state.stages[stage_def.id] = StageState(stage_id=stage_def.id)
        self.state.stages[first_stage.id].status = StageStatus.IN_PROGRESS
        self.state.stages[first_stage.id].started_at = now
        logger.info("AIDLC workflow started — first stage: %s", first_stage.name)
        self._emit_event("aidlc.workflow_started", {
            "project": self.state.project_name,
            "complexity": self.state.complexity.value,
        })

    # ------------------------------------------------------------------
    # Stage queries
    # ------------------------------------------------------------------

    def get_current_stage(self) -> Stage | None:
        """Return the Stage definition for the current stage, or None if complete.

        Returns:
            The current Stage, or None if the workflow is complete.
        """
        if self.state.current_stage_id is None:
            return None
        return get_stage(self.state.current_stage_id)

    def get_status(self) -> dict[str, Any]:
        """Return a summary dict of workflow progress.

        Returns:
            Dict with keys: current_stage, progress (dict of stage→status),
            completion_pct (int 0-100).
        """
        progress: dict[str, str] = {}
        approved_or_skipped = 0
        total = len(STAGE_DEFINITIONS)

        for stage_def in STAGE_DEFINITIONS:
            ss = self.state.stages.get(stage_def.id)
            status = ss.status.value if ss else StageStatus.PENDING.value
            progress[stage_def.id.value] = status
            if ss and ss.status in (StageStatus.APPROVED, StageStatus.SKIPPED):
                approved_or_skipped += 1

        pct = int((approved_or_skipped / total) * 100) if total > 0 else 0

        return {
            "current_stage": self.state.current_stage_id.value if self.state.current_stage_id else None,
            "progress": progress,
            "completion_pct": pct,
        }

    def get_questions(self) -> list[Question]:
        """Return questions for the current stage.

        Delegates to the question generator with the current complexity.

        Returns:
            List of Question objects for the current stage.

        Raises:
            RuntimeError: If no current stage (workflow complete).
        """
        if self.state.current_stage_id is None:
            raise RuntimeError("Workflow is complete — no current stage.")
        return get_questions_for_stage(self.state.current_stage_id, self.state.complexity)

    # ------------------------------------------------------------------
    # Stage transitions
    # ------------------------------------------------------------------

    def submit_answers(self, stage_id: StageID, answers: dict[str, Any]) -> None:
        """Submit answers for a stage, generate its artifact, and transition to AWAITING_APPROVAL.

        Args:
            stage_id: The stage being answered.
            answers: The collected answers dict.

        Raises:
            ValueError: If the stage is not the current IN_PROGRESS stage.

        Traces to: AC-1 (artifact generation), AC-2 (gate enforcement),
                   AC-3 (audit), AC-24 (no skipping)
        """
        ss = self.state.stages.get(stage_id)
        if (
            self.state.current_stage_id != stage_id
            or ss is None
            or ss.status != StageStatus.IN_PROGRESS
        ):
            raise ValueError(
                f"Stage {stage_id.value} is not the current in-progress stage. "
                f"Current: {self.state.current_stage_id}, "
                f"Status: {ss.status.value if ss else 'unknown'}"
            )

        # Audit log — capture input verbatim (AC-3)
        append_audit(self.state, answers, stage_id)

        # If this is the Requirements stage, assess complexity
        if stage_id == StageID.REQUIREMENTS:
            self.state.complexity = self.assess_complexity(answers)
            logger.info("Complexity assessed as %s", self.state.complexity.value)

        # Generate artifact
        artifact_path = self._generate_artifact(stage_id, answers)
        ss.output_path = artifact_path

        # Transition to AWAITING_APPROVAL
        ss.status = StageStatus.AWAITING_APPROVAL
        logger.info("Stage %s → AWAITING_APPROVAL", stage_id.value)
        self._emit_event("aidlc.stage_submitted", {
            "stage_id": stage_id.value,
            "status": "awaiting_approval",
        })

    def approve_stage(self, stage_id: StageID, note: str = "") -> None:
        """Approve a stage and advance to the next one.

        Args:
            stage_id: The stage being approved.
            note: Optional approval note.

        Raises:
            ValueError: If the stage is not awaiting approval.

        Traces to: AC-2, AC-23, AC-24
        """
        ss = self.state.stages.get(stage_id)
        if ss is None or ss.status != StageStatus.AWAITING_APPROVAL:
            raise ValueError(
                f"Stage {stage_id.value} is not awaiting approval. "
                f"Status: {ss.status.value if ss else 'unknown'}"
            )

        ss.status = StageStatus.APPROVED
        ss.completed_at = datetime.now(timezone.utc).isoformat()
        ss.approval_note = note
        logger.info("Stage %s APPROVED", stage_id.value)
        self._emit_event("aidlc.stage_approved", {"stage_id": stage_id.value})

        # Advance to next stage
        self._advance_to_next_stage(stage_id)

    def reject_stage(self, stage_id: StageID, feedback: str = "") -> None:
        """Reject a stage, returning it to IN_PROGRESS for re-work.

        Args:
            stage_id: The stage being rejected.
            feedback: Reason for rejection.

        Raises:
            ValueError: If the stage is not awaiting approval.
        """
        ss = self.state.stages.get(stage_id)
        if ss is None or ss.status != StageStatus.AWAITING_APPROVAL:
            raise ValueError(
                f"Stage {stage_id.value} is not awaiting approval. "
                f"Status: {ss.status.value if ss else 'unknown'}"
            )

        ss.status = StageStatus.IN_PROGRESS
        logger.info("Stage %s REJECTED — returning to IN_PROGRESS. Feedback: %s", stage_id.value, feedback)
        self._emit_event("aidlc.stage_rejected", {"stage_id": stage_id.value})

    def skip_stage(self, stage_id: StageID, reason: str = "") -> None:
        """Skip a conditional stage.

        Args:
            stage_id: The stage to skip.
            reason: Why the stage is being skipped.

        Raises:
            ValueError: If the stage is not conditional.

        Traces to: AC-23
        """
        stage_def = get_stage(stage_id)
        if not stage_def.is_conditional:
            raise ValueError(f"Stage {stage_id.value} is not conditional and cannot be skipped.")

        ss = self.state.stages.get(stage_id)
        if ss is None:
            ss = StageState(stage_id=stage_id)
            self.state.stages[stage_id] = ss

        ss.status = StageStatus.SKIPPED
        ss.completed_at = datetime.now(timezone.utc).isoformat()
        ss.approval_note = reason
        logger.info("Stage %s SKIPPED: %s", stage_id.value, reason)
        self._emit_event("aidlc.stage_skipped", {
            "stage_id": stage_id.value,
            "reason": reason,
        })

        # Advance past skipped stage
        self._advance_to_next_stage(stage_id)

    # ------------------------------------------------------------------
    # Complexity assessment
    # ------------------------------------------------------------------

    def assess_complexity(self, answers: dict[str, Any]) -> Complexity:
        """Assess project complexity from Requirements answers.

        Scoring heuristic:
        - Multiple user types → +2
        - Multi-channel → +1 per extra channel
        - Compliance beyond "none" → +2
        - Multiple data sources → +1 per extra source
        - Hybrid deployment → +1

        Score thresholds: 0-2 SIMPLE, 3-5 STANDARD, 6+ COMPLEX.

        Args:
            answers: Requirements stage answers.

        Returns:
            The assessed Complexity level.

        Traces to: AC-4 (Stage depth adapts based on complexity assessment)
        """
        score = 0

        # User types
        target = answers.get("target_users", "")
        if isinstance(target, str) and ("both" in target.lower() or "and" in target.lower()):
            score += 2

        # Channels
        channels = answers.get("channels", [])
        if isinstance(channels, list):
            score += max(0, len(channels) - 1)

        # Compliance
        compliance = answers.get("compliance", "none")
        if isinstance(compliance, str) and compliance.lower() not in ("none", ""):
            # Count comma-separated items for extra weight
            items = [c.strip() for c in compliance.split(",") if c.strip()]
            score += min(len(items) + 1, 4)

        # Data sources
        data_sources = answers.get("data_sources", [])
        if isinstance(data_sources, list):
            score += max(0, len(data_sources) - 1)

        # Deployment
        deploy = answers.get("deployment_target", "")
        if isinstance(deploy, str) and deploy.lower() == "hybrid":
            score += 1

        # Capabilities
        capabilities = answers.get("capabilities", [])
        if isinstance(capabilities, list):
            score += max(0, len(capabilities) - 1)

        if score <= 2:
            return Complexity.SIMPLE
        elif score <= 5:
            return Complexity.STANDARD
        else:
            return Complexity.COMPLEX

    def should_skip_stage(self, stage_id: StageID) -> bool:
        """Determine if a conditional stage should be skipped.

        SIMPLE projects skip all conditional stages.
        STANDARD and COMPLEX include all stages.

        Args:
            stage_id: The stage to check.

        Returns:
            True if the stage should be skipped.

        Traces to: AC-23
        """
        stage_def = get_stage(stage_id)
        if not stage_def.is_conditional:
            return False
        return self.state.complexity == Complexity.SIMPLE

    # ------------------------------------------------------------------
    # Decision log
    # ------------------------------------------------------------------

    def record_decision(self, decision_text: str, rationale: str) -> None:
        """Append a decision to the decisions log.

        Args:
            decision_text: What was decided.
            rationale: Why this decision was made.
        """
        self.state.decisions.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision_text,
            "rationale": rationale,
        })

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> Path:
        """Persist the current workflow state to disk.

        Returns:
            Path to the written state file.

        Traces to: AC-21
        """
        return save_state(self.state, self.base_dir)

    @classmethod
    def load(cls, base_dir: Path) -> AIDLCWorkflow:
        """Restore a workflow from persisted state.

        Args:
            base_dir: Project workspace root directory.

        Returns:
            An AIDLCWorkflow instance with restored state.

        Raises:
            FileNotFoundError: If no state file exists.

        Traces to: AC-22
        """
        state = load_state(base_dir)
        instance = cls.__new__(cls)
        instance.base_dir = Path(base_dir)
        instance.state = state
        instance._event_callbacks = []
        return instance

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _advance_to_next_stage(self, completed_stage_id: StageID) -> None:
        """Move to the next stage in the ordered list, skipping conditional stages if needed.

        Args:
            completed_stage_id: The stage that was just approved/skipped.
        """
        stage_ids = [s.id for s in STAGE_DEFINITIONS]
        current_idx = stage_ids.index(completed_stage_id)

        for next_idx in range(current_idx + 1, len(stage_ids)):
            next_id = stage_ids[next_idx]
            next_def = get_stage(next_id)

            # Auto-skip conditional stages for SIMPLE projects
            if next_def.is_conditional and self.should_skip_stage(next_id):
                ss = self.state.stages.get(next_id)
                if ss is None:
                    ss = StageState(stage_id=next_id)
                    self.state.stages[next_id] = ss
                ss.status = StageStatus.SKIPPED
                ss.completed_at = datetime.now(timezone.utc).isoformat()
                ss.approval_note = "Auto-skipped: project complexity is SIMPLE"
                logger.info("Auto-skipping conditional stage %s (SIMPLE project)", next_id.value)
                continue

            # Found the next active stage
            self.state.current_stage_id = next_id
            ss = self.state.stages.get(next_id)
            if ss is None:
                ss = StageState(stage_id=next_id)
                self.state.stages[next_id] = ss
            ss.status = StageStatus.IN_PROGRESS
            ss.started_at = datetime.now(timezone.utc).isoformat()
            logger.info("Advanced to stage: %s", next_id.value)
            return

        # No more stages — workflow complete
        self.state.current_stage_id = None
        logger.info("AIDLC workflow complete — all stages processed")
        self._emit_event("aidlc.workflow_completed", {"completion_pct": 100})

    def _generate_artifact(self, stage_id: StageID, answers: dict[str, Any]) -> str | None:
        """Generate and write the artifact for a stage.

        Args:
            stage_id: The stage to generate an artifact for.
            answers: The collected answers.

        Returns:
            Relative path to the artifact (under aidlc-docs/), or None if
            no compiler exists for this stage.
        """
        stage_def = get_stage(stage_id)
        compiler = _ARTIFACT_COMPILERS.get(stage_id)

        if stage_id == StageID.WORKSPACE_DETECTION:
            # Workspace detection has a simple summary artifact
            md = self._compile_workspace_analysis(answers)
        elif compiler is not None:
            md = compiler(self.state, answers)
        else:
            return None

        # Write artifact
        docs_dir = self.base_dir / "aidlc-docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = docs_dir / stage_def.output_artifact
        artifact_path.write_text(md)
        logger.info("Wrote artifact: %s", artifact_path)

        return f"aidlc-docs/{stage_def.output_artifact}"

    @staticmethod
    def _compile_workspace_analysis(answers: dict[str, Any]) -> str:
        """Compile a simple workspace analysis markdown from answers.

        Args:
            answers: Workspace detection answers.

        Returns:
            Markdown string.
        """
        existing = answers.get("existing_repo", False)
        repo_url = answers.get("repo_url", "")
        md = "# Workspace Analysis\n\n"
        md += f"**Existing repository:** {'Yes' if existing else 'No (greenfield)'}\n"
        if repo_url:
            md += f"**Repository URL:** {repo_url}\n"
        md += f"\n**Project type:** {'Brownfield' if existing else 'Greenfield'}\n"
        return md
