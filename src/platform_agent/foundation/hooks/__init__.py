"""Hook middleware for the Strands Foundation Agent.

Provides HookProvider implementations for soul system, memory, guardrails,
audit logging, tool policy enforcement, compaction, telemetry, model metrics,
memory extraction, and memory consolidation.

Note: MemorySyncHook and seed script were removed in the memory simplification
refactor. Platform files (SOUL.md, IDENTITY.md) are baked into the container
image. User memory is handled entirely by AgentCore Memory (API-level namespace
isolation), not workspace files.
"""

# HookBase must be imported first — hook modules import it from base.py,
# so it must be available in the module namespace before hook imports.
from platform_agent.foundation.hooks.base import HookBase

from platform_agent.foundation.hooks.soul_hook import SoulSystemHook
from platform_agent.foundation.hooks.memory_hook import MemoryHook
from platform_agent.foundation.hooks.guardrails_hook import GuardrailsHook
from platform_agent.foundation.hooks.audit_hook import AuditHook
from platform_agent.foundation.hooks.telemetry_hook import TelemetryHook
from platform_agent.foundation.hooks.model_metrics_hook import ModelMetricsHook
from platform_agent.foundation.hooks.tool_policy_hook import ToolPolicyHook
from platform_agent.foundation.hooks.compaction_hook import CompactionHook
from platform_agent.foundation.hooks.memory_extraction_hook import MemoryExtractionHook
from platform_agent.foundation.hooks.consolidation_hook import ConsolidationHook
from platform_agent.foundation.hooks.aidlc_telemetry_hook import AIDLCTelemetryHook
from platform_agent.foundation.hooks.business_metrics_hook import BusinessMetricsHook
from platform_agent.foundation.hooks.hallucination_detector_hook import HallucinationDetectorHook
from platform_agent.foundation.hooks.otel_span_hook import OTELSpanHook
from platform_agent.foundation.hooks.session_recording_hook import SessionRecordingHook
from platform_agent.foundation.hooks.approval_hook import ApprovalHook, ApprovalConfig

__all__ = [
    "HookBase",
    "SoulSystemHook",
    "MemoryHook",
    "GuardrailsHook",
    "AuditHook",
    "TelemetryHook",
    "ModelMetricsHook",
    "ToolPolicyHook",
    "ApprovalHook",
    "ApprovalConfig",
    "CompactionHook",
    "MemoryExtractionHook",
    "ConsolidationHook",
    "AIDLCTelemetryHook",
    "BusinessMetricsHook",
    "HallucinationDetectorHook",
    "OTELSpanHook",
    "SessionRecordingHook",
]
