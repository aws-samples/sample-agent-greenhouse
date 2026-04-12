"""Deprecated — use platform_agent.plato.orchestrator instead.

Backward-compatibility shim. All real code lives in platform_agent.plato.orchestrator.
"""
import sys
import importlib
import warnings

warnings.warn(
    "platform_agent.orchestrator is deprecated; use platform_agent.plato.orchestrator instead.",
    DeprecationWarning,
    stacklevel=2,
)

importlib.import_module("platform_agent.plato.orchestrator")
sys.modules[__name__] = sys.modules["platform_agent.plato.orchestrator"]
