"""Plato Control Plane — orchestration layer for multi-agent platforms.

Provides agent registry, task management, message routing, policy enforcement,
lifecycle management, and audit logging for multi-tenant agent deployments.
"""

from platform_agent.plato.control_plane.registry import AgentRecord, AgentRegistry
from platform_agent.plato.control_plane.policy_engine import PlatformPolicyEngine
from platform_agent.plato.control_plane.task_manager import Task, TaskManager, TaskDispatcher
from platform_agent.plato.control_plane.message_router import Message, MessageRouter
from platform_agent.plato.control_plane.lifecycle import (
    ColdStartProtocol,
    HeartbeatManager,
    GracefulShutdown,
)
from platform_agent.plato.control_plane.audit import AuditEntry, AuditStore

__all__ = [
    "AgentRecord",
    "AgentRegistry",
    "PlatformPolicyEngine",
    "Task",
    "TaskManager",
    "TaskDispatcher",
    "Message",
    "MessageRouter",
    "ColdStartProtocol",
    "HeartbeatManager",
    "GracefulShutdown",
    "AuditEntry",
    "AuditStore",
]
