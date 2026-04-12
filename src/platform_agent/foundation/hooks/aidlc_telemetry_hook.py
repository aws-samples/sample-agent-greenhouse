"""AIDLCTelemetryHook — tracks AIDLC workflow lifecycle metrics.

Subscribes to AIDLCWorkflow events (not Strands hook events). This is a
standalone observer that registers with the workflow engine via
``workflow.on_event(hook.handle_event)``.

Captures: stage transitions, durations, approval wait times, drop-offs,
rework cycles, and overall workflow timing.  Emits CloudWatch EMF metrics
under the ``Plato/AIDLC`` namespace.

Traces to: observability-design.md §4 (Layer B)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from platform_agent.plato.aidlc.stages import StageID
from platform_agent.foundation.hooks.base import HookBase

logger = logging.getLogger(__name__)


class AIDLCTelemetryHook(HookBase):
    """Observer that tracks AIDLC workflow events for telemetry.

    Not a Strands ``HookProvider`` — registers directly with the workflow
    engine via ``workflow.on_event(hook.handle_event)``.

    Attributes:
        auto_emit: If True, automatically emit CloudWatch EMF on
            workflow completion.
    """

    # Canonical stage order for funnel data — derived from StageID enum.
    _STAGE_ORDER: list[str] = [s.value for s in StageID]

    def __init__(self, auto_emit: bool = True) -> None:
        self.auto_emit = auto_emit

        # Workflow-level timing
        self.workflow_start_time: float | None = None
        self.workflow_end_time: float | None = None
        self._complexity: str | None = None

        # Per-stage tracking
        self.stage_transitions: list[dict[str, Any]] = []
        self.stage_durations: dict[str, float] = {}
        self.approval_wait_times: dict[str, float] = {}
        self.drop_offs: list[dict[str, Any]] = []
        self.rework_count: dict[str, int] = {}

        # Internal bookkeeping — tracks in-progress and submitted timestamps.
        self._stage_started_at: dict[str, float] = {}
        self._stage_submitted_at: dict[str, float] = {}
        self._completed_stages: set[str] = set()
        self._last_stage: str | None = None

    # ------------------------------------------------------------------
    # Main callback
    # ------------------------------------------------------------------

    def handle_event(self, event_type: str, data: dict) -> None:
        """Dispatch a workflow event to the appropriate handler.

        Args:
            event_type: Dotted event name emitted by AIDLCWorkflow.
            data: Event payload dict.
        """
        handler = {
            "aidlc.workflow_started": self._on_workflow_started,
            "aidlc.stage_submitted": self._on_stage_submitted,
            "aidlc.stage_approved": self._on_stage_approved,
            "aidlc.stage_rejected": self._on_stage_rejected,
            "aidlc.stage_skipped": self._on_stage_skipped,
            "aidlc.workflow_completed": self._on_workflow_completed,
        }.get(event_type)

        if handler is not None:
            handler(data)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_workflow_started(self, data: dict) -> None:
        self.workflow_start_time = time.time()
        self._complexity = data.get("complexity")
        # The first stage is implicitly started when the workflow starts.
        first_stage = self._STAGE_ORDER[0] if self._STAGE_ORDER else None
        if first_stage:
            self._stage_started_at[first_stage] = self.workflow_start_time
            self._last_stage = first_stage

    def _on_stage_submitted(self, data: dict) -> None:
        stage_id = data.get("stage_id", "")
        now = time.time()
        self._stage_submitted_at[stage_id] = now

        if self._last_stage and self._last_stage != stage_id:
            self.stage_transitions.append({
                "from_stage": self._last_stage,
                "to_stage": stage_id,
                "timestamp": now,
            })

    def _on_stage_approved(self, data: dict) -> None:
        stage_id = data.get("stage_id", "")
        now = time.time()

        # Duration: time from IN_PROGRESS start → APPROVED
        started = self._stage_started_at.get(stage_id)
        if started is not None:
            self.stage_durations[stage_id] = now - started

        # Approval wait: time from AWAITING_APPROVAL → APPROVED
        submitted = self._stage_submitted_at.get(stage_id)
        if submitted is not None:
            self.approval_wait_times[stage_id] = now - submitted

        self._completed_stages.add(stage_id)

        # Record transition — the workflow engine will advance to the
        # next stage after approve, so record the outgoing transition.
        self._record_stage_advance(stage_id, now)

    def _on_stage_rejected(self, data: dict) -> None:
        stage_id = data.get("stage_id", "")
        self.rework_count[stage_id] = self.rework_count.get(stage_id, 0) + 1

        # Re-start the clock for this stage (rework begins)
        self._stage_started_at[stage_id] = time.time()
        # Clear submitted timestamp so wait time is recalculated on next submit
        self._stage_submitted_at.pop(stage_id, None)

    def _on_stage_skipped(self, data: dict) -> None:
        stage_id = data.get("stage_id", "")
        now = time.time()
        self._completed_stages.add(stage_id)
        self._record_stage_advance(stage_id, now)

    def _on_workflow_completed(self, data: dict) -> None:
        self.workflow_end_time = time.time()
        if self.auto_emit:
            self.emit_cloudwatch_emf()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record_stage_advance(self, from_stage: str, timestamp: float) -> None:
        """Record that we're moving past *from_stage*."""
        try:
            idx = self._STAGE_ORDER.index(from_stage)
        except ValueError:
            return
        if idx + 1 < len(self._STAGE_ORDER):
            next_stage = self._STAGE_ORDER[idx + 1]
            self.stage_transitions.append({
                "from_stage": from_stage,
                "to_stage": next_stage,
                "timestamp": timestamp,
            })
            # Mark the next stage as started for duration tracking
            self._stage_started_at[next_stage] = timestamp
            self._last_stage = next_stage

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def get_aidlc_metrics(self) -> dict[str, Any]:
        """Return a summary dict of all tracked AIDLC metrics.

        Returns:
            Dict with keys: workflow_start_time, workflow_end_time,
            stage_durations, approval_wait_times, rework_count,
            drop_offs, stage_transitions, completed_stages.
        """
        return {
            "workflow_start_time": self.workflow_start_time,
            "workflow_end_time": self.workflow_end_time,
            "complexity": self._complexity,
            "stage_durations": dict(self.stage_durations),
            "approval_wait_times": dict(self.approval_wait_times),
            "rework_count": dict(self.rework_count),
            "drop_offs": list(self.drop_offs),
            "stage_transitions": list(self.stage_transitions),
            "completed_stages": sorted(self._completed_stages),
        }

    def get_funnel_data(self) -> list[dict[str, Any]]:
        """Return ordered stages with completion counts for funnel viz.

        Returns:
            List of dicts with ``stage_id`` and ``completed`` (bool).
        """
        return [
            {
                "stage_id": stage_id,
                "completed": stage_id in self._completed_stages,
            }
            for stage_id in self._STAGE_ORDER
        ]

    def emit_cloudwatch_emf(self) -> None:
        """Emit CloudWatch Embedded Metric Format JSON to stdout.

        Namespace: ``Plato/AIDLC``, Dimensions: ``StageName``, ``Complexity``.
        """
        complexity = self._complexity or "unknown"

        # Emit per-stage metrics
        for stage_id in self._STAGE_ORDER:
            duration = self.stage_durations.get(stage_id)
            wait_time = self.approval_wait_times.get(stage_id)
            rework = self.rework_count.get(stage_id, 0)

            metrics_list = []
            emf_log: dict[str, Any] = {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "Plato/AIDLC",
                            "Dimensions": [["StageName", "Complexity"]],
                            "Metrics": metrics_list,
                        }
                    ],
                },
                "StageName": stage_id,
                "Complexity": complexity,
            }

            if duration is not None:
                metrics_list.append({"Name": "AIDLCStageDuration", "Unit": "Milliseconds"})
                emf_log["AIDLCStageDuration"] = duration * 1000  # seconds → ms

            if wait_time is not None:
                metrics_list.append({"Name": "AIDLCApprovalWaitTime", "Unit": "Milliseconds"})
                emf_log["AIDLCApprovalWaitTime"] = wait_time * 1000  # seconds → ms

            metrics_list.append({"Name": "AIDLCReworkCount", "Unit": "Count"})
            emf_log["AIDLCReworkCount"] = rework

            if metrics_list:
                print(json.dumps(emf_log))

        # Emit workflow-level completion metric
        if self.workflow_end_time is not None:
            completion_emf: dict[str, Any] = {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "Plato/AIDLC",
                            "Dimensions": [["Complexity"]],
                            "Metrics": [
                                {"Name": "AIDLCWorkflowCompleted", "Unit": "Count"},
                            ],
                        }
                    ],
                },
                "Complexity": complexity,
                "AIDLCWorkflowCompleted": 1,
            }
            print(json.dumps(completion_emf))

    def clear(self) -> None:
        """Reset all tracked state."""
        self.workflow_start_time = None
        self.workflow_end_time = None
        self._complexity = None
        self.stage_transitions.clear()
        self.stage_durations.clear()
        self.approval_wait_times.clear()
        self.drop_offs.clear()
        self.rework_count.clear()
        self._stage_started_at.clear()
        self._stage_submitted_at.clear()
        self._completed_stages.clear()
        self._last_stage = None
