"""AIDLC artifact compilers.

Each compiler takes the workflow state and stage answers, producing a
well-structured markdown string that is written to ``aidlc-docs/``.

Traces to: AC-1 (Each stage produces a markdown artifact in aidlc-docs/)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from platform_agent.plato.aidlc.state import WorkflowState


def _header(title: str, state: WorkflowState) -> str:
    """Generate a standard markdown header block."""
    return (
        f"# {title}\n\n"
        f"**Project:** {state.project_name}  \n"
        f"**Repository:** {state.repo}  \n"
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  \n\n"
        "---\n\n"
    )


def compile_requirements(state: WorkflowState, answers: dict[str, Any]) -> str:
    """Compile the requirements document from stage answers.

    Args:
        state: Current workflow state.
        answers: Answers collected during the Requirements stage.

    Returns:
        Markdown string for ``aidlc-docs/requirements.md``.

    Traces to: AC-1
    """
    md = _header("Requirements", state)
    md += "## Target Users\n\n"
    md += f"{answers.get('target_users', 'Not specified')}\n\n"
    md += "## Channels\n\n"
    channels = answers.get("channels", [])
    if isinstance(channels, list):
        for ch in channels:
            md += f"- {ch}\n"
    else:
        md += f"- {channels}\n"
    md += "\n## Core Capabilities\n\n"
    capabilities = answers.get("capabilities", [])
    if isinstance(capabilities, list):
        for cap in capabilities:
            md += f"- {cap}\n"
    else:
        md += f"- {capabilities}\n"
    md += "\n## Data Sources\n\n"
    data_sources = answers.get("data_sources", [])
    if isinstance(data_sources, list):
        for ds in data_sources:
            md += f"- {ds}\n"
    else:
        md += f"- {data_sources}\n"
    md += "\n## Compliance Requirements\n\n"
    md += f"{answers.get('compliance', 'None')}\n\n"
    md += "## Deployment Target\n\n"
    md += f"{answers.get('deployment_target', 'Not specified')}\n"
    return md


def compile_user_stories(state: WorkflowState, answers: dict[str, Any]) -> str:
    """Compile the user stories document from stage answers.

    Args:
        state: Current workflow state.
        answers: Answers collected during the User Stories stage.

    Returns:
        Markdown string for ``aidlc-docs/user-stories.md``.

    Traces to: AC-1
    """
    md = _header("User Stories", state)
    md += "## Actors\n\n"
    actors = answers.get("actors", [])
    if isinstance(actors, list):
        for actor in actors:
            md += f"- {actor}\n"
    else:
        md += f"- {actors}\n"
    md += "\n## User Journeys\n\n"
    journeys = answers.get("journeys", [])
    if isinstance(journeys, list):
        for i, journey in enumerate(journeys, 1):
            md += f"### Journey {i}: {journey}\n\n"
            md += f"**As a** user, **I want to** {journey} **so that** I can accomplish my goal.\n\n"
    else:
        md += f"- {journeys}\n"
    md += "## Edge Cases\n\n"
    edge_cases = answers.get("edge_cases", [])
    if isinstance(edge_cases, list):
        for ec in edge_cases:
            md += f"- {ec}\n"
    else:
        md += f"{edge_cases or 'To be determined during construction.'}\n"
    return md


def compile_workflow_plan(state: WorkflowState, answers: dict[str, Any]) -> str:
    """Compile the workflow plan document from stage answers.

    Args:
        state: Current workflow state.
        answers: Answers collected during the Workflow Planning stage.

    Returns:
        Markdown string for ``aidlc-docs/workflow-plan.md``.

    Traces to: AC-1
    """
    md = _header("Workflow Plan", state)
    md += "## Construction Stages\n\n"
    stages = answers.get("stages", [])
    if isinstance(stages, list):
        for i, stage in enumerate(stages, 1):
            md += f"{i}. {stage}\n"
    else:
        md += f"1. {stages}\n"
    md += "\n## Execution Strategy\n\n"
    parallel = answers.get("parallel", False)
    md += f"**Parallel execution:** {'Yes' if parallel else 'No — sequential'}\n\n"
    effort = answers.get("estimated_effort", "")
    if effort:
        md += f"## Estimated Effort\n\n{effort}\n"
    return md


def compile_app_design(state: WorkflowState, answers: dict[str, Any]) -> str:
    """Compile the application design document from stage answers.

    Args:
        state: Current workflow state.
        answers: Answers collected during the Application Design stage.

    Returns:
        Markdown string for ``aidlc-docs/application-design.md``.

    Traces to: AC-1
    """
    md = _header("Application Design", state)
    md += "## Components\n\n"
    components = answers.get("components", [])
    if isinstance(components, list):
        for comp in components:
            md += f"- {comp}\n"
    else:
        md += f"- {components}\n"
    md += "\n## APIs\n\n"
    apis = answers.get("apis", [])
    if isinstance(apis, list):
        for api in apis:
            md += f"- {api}\n"
    else:
        md += f"- {apis}\n"
    md += "\n## Data Flow\n\n"
    data_flow = answers.get("data_flow", "To be detailed during construction.")
    md += f"{data_flow}\n\n"
    md += "## Integration Points\n\n"
    integrations = answers.get("integration_points", [])
    if isinstance(integrations, list):
        for ip in integrations:
            md += f"- {ip}\n"
    else:
        md += f"{integrations or 'None specified.'}\n"
    return md


def compile_units(state: WorkflowState, answers: dict[str, Any]) -> str:
    """Compile the units document from stage answers.

    Args:
        state: Current workflow state.
        answers: Answers collected during the Units stage.

    Returns:
        Markdown string for ``aidlc-docs/units.md``.

    Traces to: AC-1
    """
    md = _header("Units", state)
    md += "## Work Units\n\n"
    units = answers.get("units", [])
    if isinstance(units, list):
        for i, unit in enumerate(units, 1):
            md += f"### Unit {i}: {unit}\n\n"
    else:
        md += f"### Unit 1: {units}\n\n"
    md += "## Dependencies\n\n"
    deps = answers.get("dependencies", {})
    if isinstance(deps, dict) and deps:
        for unit, dep_list in deps.items():
            dep_str = ", ".join(dep_list) if isinstance(dep_list, list) else str(dep_list)
            md += f"- **{unit}** depends on: {dep_str}\n"
    else:
        md += "No inter-unit dependencies.\n"
    md += "\n## Delivery Order\n\n"
    order = answers.get("delivery_order", [])
    if isinstance(order, list) and order:
        for i, item in enumerate(order, 1):
            md += f"{i}. {item}\n"
    else:
        md += "Delivery order follows unit numbering.\n"
    return md
