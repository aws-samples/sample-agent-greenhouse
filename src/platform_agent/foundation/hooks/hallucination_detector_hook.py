"""HallucinationDetectorHook — captures data for offline hallucination analysis.

IMPORTANT: This hook ONLY COLLECTS data. Zero network I/O. No DDB writes,
no API calls. It stores captured data in-memory for later offline analysis
(by an async Lambda or batch job).

Uses Strands HookProvider API for proper lifecycle integration.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

from platform_agent.foundation.hooks.base import HookBase

try:
    from strands.hooks import HookRegistry
    from strands.hooks.events import AfterToolCallEvent

    _HAS_STRANDS_HOOKS = True
except ImportError:
    _HAS_STRANDS_HOOKS = False



# Tools whose output we capture.
_REVIEW_TOOL = "create_pull_request_review"
_FILE_TREE_TOOL = "github_get_tree"

# Regex patterns for extracting structured data from output.
_AC_PATTERN = re.compile(r"AC-\d+", re.IGNORECASE)
_FILE_REF_PATTERN = re.compile(r"(?:src|lib|tests?|app)/[\w/.-]+\.\w+")

# Maximum length for captured output text.
_MAX_OUTPUT_LENGTH = 2000


class CapturedOutput:
    """A single captured tool call output for later analysis."""

    __slots__ = ("session_id", "tool_name", "output_text", "file_refs", "ac_ids", "timestamp")

    def __init__(
        self,
        *,
        session_id: str,
        tool_name: str,
        output_text: str,
        file_refs: list[str],
        ac_ids: list[str],
        timestamp: float,
    ) -> None:
        self.session_id = session_id
        self.tool_name = tool_name
        self.output_text = output_text
        self.file_refs = file_refs
        self.ac_ids = ac_ids
        self.timestamp = timestamp

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "output_text": self.output_text,
            "file_refs": self.file_refs,
            "ac_ids": self.ac_ids,
            "timestamp": self.timestamp,
        }


class HallucinationDetectorHook(HookBase):
    """Hook that captures tool call outputs for offline hallucination analysis.

    Zero network I/O. All data stored in-memory for retrieval by an external
    process (async Lambda, batch job) that persists to DDB/S3 and runs
    cross-reference analysis.

    Captures:
    - Review text + referenced file paths (from create_pull_request_review)
    - File tree results (from github_get_tree)
    - AC/TC IDs for consistency checking
    - Spec compliance findings

    Implements strands.hooks.HookProvider for native integration.
    """

    def __init__(self, *, session_id: str | None = None) -> None:
        self.session_id = session_id or "unknown"
        self._captured: list[CapturedOutput] = []
        self._file_trees: list[set[str]] = []
        self._spec_ac_ids: set[str] = set()

    def register_hooks(self, registry) -> None:
        """Register callbacks with the Strands HookRegistry."""
        if _HAS_STRANDS_HOOKS:
            registry.add_callback(AfterToolCallEvent, self.on_after_tool_call)

    def on_after_tool_call(self, event) -> None:
        """Capture relevant tool call outputs for later analysis.

        Args:
            event: AfterToolCallEvent from Strands.
        """
        try:
            tool_use = getattr(event, "tool_use", {})
            tool_name = (
                tool_use.get("name", "unknown")
                if isinstance(tool_use, dict)
                else "unknown"
            )

            # Only capture from relevant tools.
            if not self._is_relevant_tool(tool_name):
                return

            tool_result = str(getattr(event, "tool_result", ""))
            output_text = tool_result[:_MAX_OUTPUT_LENGTH]

            # Extract file references from output.
            file_refs = _FILE_REF_PATTERN.findall(tool_result)

            # Extract AC IDs from output.
            ac_ids = _AC_PATTERN.findall(tool_result)

            captured = CapturedOutput(
                session_id=self.session_id,
                tool_name=tool_name,
                output_text=output_text,
                file_refs=file_refs,
                ac_ids=ac_ids,
                timestamp=time.time(),
            )
            self._captured.append(captured)

            # Track file trees separately for cross-reference checks.
            if tool_name == _FILE_TREE_TOOL:
                self._file_trees.append(set(file_refs))

            # Track spec AC IDs from submit_answers (spec-generating stages).
            tool_input = (
                tool_use.get("input", {})
                if isinstance(tool_use, dict)
                else {}
            )
            if isinstance(tool_input, dict):
                stage_id = tool_input.get("stage_id", "")
                if stage_id in ("requirements", "user_stories"):
                    self._spec_ac_ids.update(ac_ids)

        except Exception:
            logger.debug(
                "HallucinationDetectorHook: error in on_after_tool_call",
                exc_info=True,
            )

    def get_captured_data(self) -> list[dict[str, Any]]:
        """Return all captured outputs as a list of dicts.

        Returns:
            List of captured output dictionaries.
        """
        return [c.to_dict() for c in self._captured]

    def get_consistency_report(self) -> dict[str, Any]:
        """Run basic local consistency checks (no network I/O).

        Returns:
            Dictionary with cross_reference_issues and ac_consistency_issues.
        """
        cross_reference_issues: list[dict[str, Any]] = []
        ac_consistency_issues: list[dict[str, Any]] = []

        # Build the full set of known files from all captured file trees.
        known_files: set[str] = set()
        for tree in self._file_trees:
            known_files.update(tree)

        # Cross-reference check: file paths in reviews not in captured trees.
        for captured in self._captured:
            if captured.tool_name == _REVIEW_TOOL and known_files:
                for file_ref in captured.file_refs:
                    if file_ref not in known_files:
                        cross_reference_issues.append({
                            "session_id": captured.session_id,
                            "tool_name": captured.tool_name,
                            "missing_file": file_ref,
                            "timestamp": captured.timestamp,
                        })

        # AC consistency check: AC IDs in test cases not in spec ACs.
        if self._spec_ac_ids:
            for captured in self._captured:
                if captured.tool_name not in (_REVIEW_TOOL, _FILE_TREE_TOOL):
                    for ac_id in captured.ac_ids:
                        if ac_id not in self._spec_ac_ids:
                            ac_consistency_issues.append({
                                "session_id": captured.session_id,
                                "tool_name": captured.tool_name,
                                "unmatched_ac_id": ac_id,
                                "timestamp": captured.timestamp,
                            })

        return {
            "cross_reference_issues": cross_reference_issues,
            "ac_consistency_issues": ac_consistency_issues,
        }

    def clear(self) -> None:
        """Clear all captured data."""
        self._captured.clear()
        self._file_trees.clear()
        self._spec_ac_ids.clear()

    @staticmethod
    def _is_relevant_tool(tool_name: str) -> bool:
        """Check if a tool call should be captured."""
        return tool_name in (
            _REVIEW_TOOL,
            _FILE_TREE_TOOL,
            "aidlc_submit_answers",
            "check_spec_compliance",
        )
