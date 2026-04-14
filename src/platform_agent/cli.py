"""CLI entry point for Platform as Agent.

Subcommands:
    chat            Interactive conversation with the platform agent
    review          Review an agent codebase for quality and security
    readiness       Check platform readiness of an agent app
    scaffold        Generate a new agent project from a description
    deploy-config   Generate deployment configuration for a repo
    inception       Start AIDLC Inception workflow
    compliance      Run spec compliance check
    test-gen        Generate test cases from spec
    orchestrate     Route a request through the orchestrator (multi-skill)
    evaluate        Evaluate specialist output with reflect-refine loop
    memory          Manage the agent memory store
    handoff         Manage human handoff/escalation requests
"""

from __future__ import annotations

import asyncio
import time

import click


def _run_agent_with_skill(
    skill_name: str,
    prompt: str,
    cwd: str = ".",
    verbose: bool = False,
) -> str:
    """Load a specific skill onto a FoundationAgent and run a prompt.

    This is the preferred pattern for CLI commands — each command loads
    the exact skill it needs, giving the agent focused expertise.

    Args:
        skill_name: Name of the registered skill to load.
        prompt: The task prompt.
        cwd: Working directory for file operations.
        verbose: If True, print timing and config info.

    Returns:
        The agent's response text.
    """
    from platform_agent.foundation import FoundationAgent
    from platform_agent.plato.skills import discover_skills, get_skill
    from platform_agent.plato.skills.base import load_skill

    discover_skills()
    skill_cls = get_skill(skill_name)
    skill = load_skill(skill_cls)

    agent = FoundationAgent(cwd=cwd)
    agent.load_skill(skill)

    if verbose:
        click.echo(f"[plato] Runtime: {agent.runtime}", err=True)
        click.echo(f"[plato] Skill: {skill.name} v{skill.version}", err=True)
        click.echo(f"[plato] Tools: {agent._build_tools()}", err=True)
        click.echo(f"[plato] Working dir: {cwd}", err=True)
        start = time.time()

    result = asyncio.run(agent.run(prompt))

    if verbose:
        elapsed = time.time() - start
        click.echo(f"[plato] Completed in {elapsed:.1f}s", err=True)

    return result


@click.group()
@click.version_option(package_name="platform-as-agent")
def cli():
    """Plato - Platform as Agent CLI.

    An intelligent multi-agent system that assists developers throughout
    the agent deployment lifecycle.
    """


# -- chat: interactive session with optional skills ----------------------------


@cli.command()
@click.option("--cwd", default=".", help="Working directory for the agent.")
@click.option("--skill", multiple=True, help="Skills to load (repeatable).")
def chat(cwd: str, skill: tuple[str, ...]):
    """Start an interactive chat session with the platform agent."""
    from platform_agent._legacy_foundation import FoundationAgent
    from platform_agent.plato.skills import discover_skills, get_skill
    from platform_agent.plato.skills.base import load_skill

    discover_skills()

    agent = FoundationAgent(cwd=cwd)
    for skill_name in skill:
        skill_cls = get_skill(skill_name)
        agent.load_skill(load_skill(skill_cls))

    loaded = [s.name for s in agent.skills]
    click.echo("Plato - Platform Agent")
    if loaded:
        click.echo(f"Skills: {', '.join(loaded)}")
    click.echo("Type 'exit' to quit")
    click.echo("-" * 48)

    while True:
        try:
            prompt = click.prompt("you", prompt_suffix="> ")
        except (EOFError, KeyboardInterrupt):
            click.echo("\nGoodbye.")
            break

        if prompt.strip().lower() in ("exit", "quit"):
            click.echo("Goodbye.")
            break

        result = asyncio.run(agent.run(prompt))
        click.echo(f"\nplato> {result}\n")


# -- readiness: platform readiness check using design_advisor ------------------


@cli.command()
@click.argument("repo", default=".")
@click.option("--verbose", "-v", is_flag=True, help="Show timing and config info.")
def readiness(repo: str, verbose: bool):
    """Check platform deployment readiness of an agent application.

    Runs the 12-item platform readiness checklist (C1-C12) against the
    target repository and reports READY / NEEDS WORK / NOT READY.
    """
    prompt = (
        f"Perform a complete platform readiness assessment of the agent application at {repo}. "
        "Run all 12 checks (C1-C12) and provide the full report with "
        "evidence, recommendations, and overall assessment."
    )
    result = _run_agent_with_skill("design-advisor", prompt, cwd=repo, verbose=verbose)
    click.echo(result)


# -- review: code quality and security review using code_review ----------------


@cli.command()
@click.argument("repo", default=".")
@click.option(
    "--focus",
    type=click.Choice(["security", "quality", "patterns", "all"]),
    default="all",
    help="Focus area for the review.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show timing and config info.")
def review(repo: str, focus: str, verbose: bool):
    """Review an agent codebase for quality, security, and best practices.

    Checks for prompt injection, credential exposure, error handling,
    agent SDK usage patterns, and code structure.
    """
    focus_desc = {
        "security": "Focus on security: prompt injection, credential exposure, unsafe execution.",
        "quality": "Focus on code quality: error handling, structure, testing.",
        "patterns": "Focus on agent patterns: SDK usage, tool design, memory management.",
        "all": "Perform a comprehensive review covering security, quality, and patterns.",
    }
    prompt = (
        f"Review the agent codebase at {repo}. {focus_desc[focus]} "
        "Provide specific file and line references for each finding."
    )
    result = _run_agent_with_skill("code-review", prompt, cwd=repo, verbose=verbose)
    click.echo(result)


# -- scaffold: project generation using scaffold skill -------------------------


@cli.command()
@click.argument("description")
@click.option("--output", "-o", default=".", help="Output directory for the scaffold.")
@click.option(
    "--template",
    type=click.Choice(["basic-agent", "multi-agent", "rag-agent", "tool-agent"]),
    default="basic-agent",
    help="Project template to use.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show timing and config info.")
def scaffold(description: str, output: str, template: str, verbose: bool):
    """Generate a new agent project skeleton from a description.

    Creates a complete, runnable project following platform best practices
    including Dockerfile, health check, env-based config, and tests.
    """
    prompt = (
        f"Scaffold a new agent project in {output} using the '{template}' template. "
        f"Project description: {description}. "
        "Generate all required files: pyproject.toml, Dockerfile, agent code, "
        "health check, tests, README, and .gitignore. "
        "Ensure the generated project would pass a platform readiness check (READY rating)."
    )
    result = _run_agent_with_skill("scaffold", prompt, cwd=output, verbose=verbose)
    click.echo(result)


# -- deploy-config: deployment configuration using deployment_config skill -----


@cli.command("deploy-config")
@click.argument("repo", default=".")
@click.option(
    "--target",
    type=click.Choice(["agentcore", "ecs", "lambda"]),
    default="agentcore",
    help="Deployment target platform.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show timing and config info.")
def deploy_config(repo: str, target: str, verbose: bool):
    """Generate deployment configuration for an agent repository.

    Produces IAM policies, Dockerfile, buildspec.yml, CDK stack,
    runtime config, and env var templates for the target platform.
    """
    prompt = (
        f"Generate deployment configuration for the agent project at {repo}. "
        f"Target platform: {target}. "
        "Generate: IAM policy (least-privilege), Dockerfile (if missing), "
        "buildspec.yml, CDK stack, runtime config, and .env template. "
        "First check platform readiness — if there are blockers, report them "
        "before generating configs."
    )
    result = _run_agent_with_skill("deployment-config", prompt, cwd=repo, verbose=verbose)
    click.echo(result)


# -- inception: AIDLC Inception workflow using aidlc_inception skill ----------


@cli.command()
@click.argument("repo")
@click.option(
    "--complexity",
    type=click.Choice(["simple", "moderate", "complex"]),
    default="moderate",
    help="Project complexity level.",
)
@click.option("--verbose", "-v", is_flag=True, help="Show timing and config info.")
def inception(repo: str, complexity: str, verbose: bool):
    """Start an AIDLC Inception workflow for an agent project.

    Guides the team through structured inception stages: workspace detection,
    requirements gathering, user stories, architecture, and workflow planning.
    Generates spec.md, CLAUDE.md, and test-cases.md as deliverables.
    """
    prompt = (
        f"Start an AIDLC Inception workflow for the repository {repo}. "
        f"Project complexity is {complexity}. "
        "Guide the team through all inception stages and generate deliverables."
    )
    result = _run_agent_with_skill("aidlc-inception", prompt, cwd=repo, verbose=verbose)
    click.echo(result)


# -- compliance: spec compliance check using spec_compliance skill -----------


@cli.command()
@click.argument("repo")
@click.option("--spec-path", default="spec.md", help="Path to the spec file.")
@click.option("--branch", default="main", help="Git branch to check.")
@click.option("--verbose", "-v", is_flag=True, help="Show timing and config info.")
def compliance(repo: str, spec_path: str, branch: str, verbose: bool):
    """Run spec compliance check against a repository.

    Verifies that the codebase implements all acceptance criteria from spec.md,
    checking for implementation evidence and test coverage.
    """
    prompt = (
        f"Run a spec compliance check on the repository {repo}. "
        f"Spec file is at {spec_path} on branch {branch}. "
        "Check all acceptance criteria for implementation evidence and test coverage. "
        "Provide a detailed compliance report."
    )
    result = _run_agent_with_skill("spec-compliance", prompt, cwd=repo, verbose=verbose)
    click.echo(result)


# -- test-gen: test case generation using test_case_generator skill ----------


@cli.command("test-gen")
@click.argument("repo")
@click.option("--spec-path", default="spec.md", help="Path to the spec file.")
@click.option("--branch", default="main", help="Git branch to read spec from.")
@click.option("--verbose", "-v", is_flag=True, help="Show timing and config info.")
def test_gen(repo: str, spec_path: str, branch: str, verbose: bool):
    """Generate test cases from spec.md acceptance criteria.

    Creates structured test cases with 1:1 AC-to-TC traceability.
    Each acceptance criterion gets exactly one test case with setup,
    steps, expected results, and test type classification.
    """
    prompt = (
        f"Generate test cases from the spec at {spec_path} in repository {repo} "
        f"on branch {branch}. "
        "Create one test case per acceptance criterion with full traceability. "
        "Output structured test-cases.md content."
    )
    result = _run_agent_with_skill("test-case-generator", prompt, cwd=repo, verbose=verbose)
    click.echo(result)


def _detect_evaluator(request: str) -> str | None:
    """Auto-detect which evaluator to use based on request keywords.

    Args:
        request: The user's request string.

    Returns:
        Evaluator name or None if no match.
    """
    request_lower = request.lower()
    if any(k in request_lower for k in ["readiness", "ready", "c1-c12", "platform check"]):
        return "design"
    if any(k in request_lower for k in ["review", "security", "code quality", "audit"]):
        return "code_review"
    # Check deployment before scaffold since "deploy" keywords are more specific
    if any(k in request_lower for k in ["deploy", "deployment", "iam", "infrastructure"]):
        return "deployment"
    if any(k in request_lower for k in ["scaffold", "generate", "create project", "skeleton"]):
        return "scaffold"
    return None


# -- orchestrate: multi-skill routing via orchestrator -------------------------


@cli.command()
@click.argument("request")
@click.option("--cwd", default=".", help="Working directory for file operations.")
@click.option("--evaluate", is_flag=True, help="Run evaluator quality gate on specialist output.")
@click.option("--max-iterations", "-n", default=3, help="Max reflect-refine iterations (with --evaluate).")
@click.option("--verbose", "-v", is_flag=True, help="Show timing and config info.")
def orchestrate(request: str, cwd: str, evaluate: bool, max_iterations: int, verbose: bool):
    """Route a complex request through the multi-skill orchestrator.

    Use this when a request spans multiple concerns (e.g., "review this
    repo and generate deployment configs"). The orchestrator delegates
    to the appropriate specialist agents.

    With --evaluate, specialist output goes through evaluator quality gates
    with reflect-refine loops before returning.
    """
    from platform_agent.plato.orchestrator import run_orchestrator

    if verbose:
        click.echo("[plato] Mode: orchestrator (multi-skill)", err=True)
        click.echo(f"[plato] Working dir: {cwd}", err=True)
        if evaluate:
            click.echo(f"[plato] Evaluator: enabled (max {max_iterations} iterations)", err=True)
        start = time.time()

    result = asyncio.run(run_orchestrator(request, cwd=cwd))

    # Optional evaluator pass on the result
    if evaluate:
        from platform_agent.plato.evaluator import discover_evaluators, get_evaluator

        discover_evaluators()

        # Auto-detect which evaluator to use based on request keywords
        evaluator_name = _detect_evaluator(request)
        if evaluator_name:
            if verbose:
                click.echo(f"[plato] Auto-selected evaluator: {evaluator_name}", err=True)

            evaluator_cls = get_evaluator(evaluator_name)
            evaluator = evaluator_cls()

            # Evaluate the orchestrator output using heuristics
            eval_result = asyncio.run(
                evaluator.evaluate_once(result, request, 1)
            )
            click.echo(f"\n{'='*60}")
            click.echo(f"Evaluator: {evaluator.name} | Score: {eval_result.overall_score:.0%} | "
                        f"{'✅ PASSED' if eval_result.passed else '⚠️ NEEDS IMPROVEMENT'}")
            click.echo(f"{'='*60}")

            for score in eval_result.item_scores:
                status = "✅" if score.passed else "❌"
                click.echo(f"  {status} {score.rubric_item_id}: {score.score:.0%}")
                if score.feedback:
                    click.echo(f"     → {score.feedback}")
        else:
            click.echo("\n[plato] Could not auto-detect evaluator for this request.", err=True)

    if verbose:
        elapsed = time.time() - start
        click.echo(f"\n[plato] Completed in {elapsed:.1f}s", err=True)

    click.echo(result)


# -- list-skills: show available skills ----------------------------------------


@cli.command("list-skills")
def list_skills_cmd():
    """List all available skill packs."""
    from platform_agent.plato.skills import discover_skills, list_skills, get_skill
    from platform_agent.plato.skills.base import load_skill

    discover_skills()
    names = list_skills()

    if not names:
        click.echo("No skills found.")
        return

    click.echo(f"Available skills ({len(names)}):\n")
    for name in sorted(names):
        skill_cls = get_skill(name)
        skill = load_skill(skill_cls)
        click.echo(f"  {skill.name:20s} v{skill.version:6s}  {skill.description}")


# -- evaluate: quality gate with reflect-refine loop --------------------------


@cli.command()
@click.argument("skill", type=click.Choice(["readiness", "review", "scaffold", "deploy-config"]))
@click.argument("repo", default=".")
@click.option("--max-iterations", "-n", default=3, help="Max reflect-refine iterations.")
@click.option(
    "--focus",
    type=click.Choice(["security", "quality", "patterns", "all"]),
    default="all",
    help="Focus area (for review evaluations).",
)
@click.option("--verbose", "-v", is_flag=True, help="Show timing and iteration details.")
def evaluate(skill: str, repo: str, max_iterations: int, focus: str, verbose: bool):
    """Evaluate specialist output with reflect-refine quality gates.

    Runs a specialist agent, then evaluates its output against a rubric.
    If the output doesn't pass, the specialist revises based on feedback.
    Repeats up to --max-iterations times.

    SKILL is which specialist to evaluate: readiness, review, scaffold, deploy-config.
    """
    from platform_agent.plato.evaluator import get_evaluator
    from platform_agent._legacy_foundation import FoundationAgent
    from platform_agent.plato.skills import discover_skills, get_skill
    from platform_agent.plato.skills.base import load_skill

    # Map CLI skill names to internal names
    skill_map = {
        "readiness": ("design_advisor", "design"),
        "review": ("code_review", "code_review"),
        "scaffold": ("scaffold", "scaffold"),
        "deploy-config": ("deployment_config", "deployment"),
    }

    specialist_skill_name, evaluator_name = skill_map[skill]

    if verbose:
        click.echo(f"[plato] Evaluating: {skill}", err=True)
        click.echo(f"[plato] Specialist: {specialist_skill_name}", err=True)
        click.echo(f"[plato] Evaluator: {evaluator_name}", err=True)
        click.echo(f"[plato] Max iterations: {max_iterations}", err=True)
        start = time.time()

    # Set up specialist
    discover_skills()
    skill_cls = get_skill(specialist_skill_name)
    skill_pack = load_skill(skill_cls)

    specialist = FoundationAgent(cwd=repo)
    specialist.load_skill(skill_pack)

    # Build specialist prompt
    prompts = {
        "readiness": (
            f"Perform a complete platform readiness assessment of the agent "
            f"application at {repo}. Run all 12 checks (C1-C12) and provide "
            f"the full report with evidence, recommendations, and overall assessment."
        ),
        "review": (
            f"Review the agent codebase at {repo}. "
            f"{'Focus on security.' if focus == 'security' else ''}"
            f"{'Focus on code quality.' if focus == 'quality' else ''}"
            f"{'Focus on agent patterns.' if focus == 'patterns' else ''}"
            f"{'Comprehensive review.' if focus == 'all' else ''} "
            f"Provide specific file and line references."
        ),
        "scaffold": (
            f"Scaffold a new agent project in {repo}. Generate all required "
            f"files following platform best practices."
        ),
        "deploy-config": (
            f"Generate deployment configuration for the agent project at {repo}. "
            f"Generate IAM policy, Dockerfile, buildspec, CDK stack, runtime config."
        ),
    }

    # Set up evaluator
    evaluator_cls = get_evaluator(evaluator_name)
    evaluator = evaluator_cls()

    # Optional: create a separate FoundationAgent for evaluation
    # For now, use heuristic evaluation (no extra LLM call)
    evaluator_agent = None

    # Run reflect-refine loop
    session = asyncio.run(
        evaluator.evaluate_with_refinement(
            specialist=specialist,
            original_request=prompts[skill],
            evaluator_agent=evaluator_agent,
            max_iterations=max_iterations,
        )
    )

    # Output report
    report = evaluator.format_session_report(session)
    click.echo(report)

    if verbose:
        elapsed = time.time() - start
        click.echo(f"\n[plato] Completed in {elapsed:.1f}s", err=True)
        click.echo(f"[plato] Status: {session.final_status}", err=True)
        click.echo(f"[plato] Iterations: {session.iteration_count}", err=True)
        if session.improved:
            click.echo(
                f"[plato] Score improved: "
                f"{session.iterations[0].evaluation.overall_score:.0%} → "
                f"{session.latest_score:.0%}",
                err=True,
            )


# -- list-evaluators: show available evaluators --------------------------------


@cli.command("list-evaluators")
def list_evaluators_cmd():
    """List all available evaluator agents."""
    from platform_agent.plato.evaluator import discover_evaluators, list_evaluators, get_evaluator

    discover_evaluators()
    names = list_evaluators()

    if not names:
        click.echo("No evaluators found.")
        return

    click.echo(f"Available evaluators ({len(names)}):\n")
    for name in names:
        cls = get_evaluator(name)
        evaluator = cls()
        click.echo(
            f"  {evaluator.name:20s} v{evaluator.rubric.version:6s}  "
            f"{evaluator.description} ({len(evaluator.rubric.items)} rubric items)"
        )


# -- memory: manage the agent memory store ------------------------------------


@cli.group()
def memory():
    """Manage the agent memory store."""
    pass


@memory.command("list")
@click.argument("namespace", default="interactions")
@click.option("--backend", type=click.Choice(["local", "agentcore"]), default=None)
def memory_list(namespace: str, backend: str | None):
    """List all memory entries in a namespace."""
    from platform_agent.memory import create_memory_store

    store = create_memory_store(backend=backend)
    keys = asyncio.run(store.list(namespace))
    if not keys:
        click.echo(f"No entries in namespace '{namespace}'.")
        return
    click.echo(f"Entries in '{namespace}' ({len(keys)}):")
    for key in keys:
        click.echo(f"  {key}")


@memory.command("get")
@click.argument("namespace")
@click.argument("key")
@click.option("--backend", type=click.Choice(["local", "agentcore"]), default=None)
def memory_get(namespace: str, key: str, backend: str | None):
    """Get a specific memory entry."""
    import json

    from platform_agent.memory import create_memory_store

    store = create_memory_store(backend=backend)
    result = asyncio.run(store.get(namespace, key))
    if result is None:
        click.echo(f"No entry found: {namespace}/{key}")
        return
    click.echo(json.dumps(result, indent=2))


@memory.command("search")
@click.argument("namespace")
@click.argument("query")
@click.option("--limit", "-n", default=5)
@click.option("--backend", type=click.Choice(["local", "agentcore"]), default=None)
def memory_search(namespace: str, query: str, limit: int, backend: str | None):
    """Search memory entries in a namespace."""
    import json

    from platform_agent.memory import create_memory_store

    store = create_memory_store(backend=backend)
    results = asyncio.run(store.search(namespace, query, limit=limit))
    if not results:
        click.echo(f"No results for '{query}' in '{namespace}'.")
        return
    click.echo(f"Results ({len(results)}):")
    for r in results:
        click.echo(json.dumps(r, indent=2))


@memory.command("delete")
@click.argument("namespace")
@click.argument("key")
@click.option("--backend", type=click.Choice(["local", "agentcore"]), default=None)
def memory_delete(namespace: str, key: str, backend: str | None):
    """Delete a memory entry."""
    from platform_agent.memory import create_memory_store

    store = create_memory_store(backend=backend)
    deleted = asyncio.run(store.delete(namespace, key))
    if deleted:
        click.echo(f"Deleted: {namespace}/{key}")
    else:
        click.echo(f"Not found: {namespace}/{key}")


@memory.command("status")
@click.option("--backend", type=click.Choice(["local", "agentcore"]), default=None)
def memory_status(backend: str | None):
    """Show memory store status and configuration."""
    import os

    from platform_agent.memory import create_memory_store

    actual_backend = backend or os.environ.get("PLATO_MEMORY_BACKEND", "local")
    click.echo(f"Backend: {actual_backend}")
    if actual_backend == "agentcore":
        memory_id = os.environ.get("AGENTCORE_MEMORY_ID", "(not set)")
        click.echo(f"Memory ID: {memory_id}")
    try:
        store = create_memory_store(backend=backend)
        click.echo(f"Store type: {type(store).__name__}")
        click.echo("Status: ✅ Connected")
    except Exception as e:
        click.echo(f"Status: ❌ Error: {e}")


# -- handoff: manage human handoff/escalation requests -----------------------


@cli.group()
def handoff():
    """Manage human handoff/escalation requests."""
    pass


@handoff.command("list")
def handoff_list():
    """List pending handoff requests."""
    from platform_agent.foundation.handoff import HandoffAgent

    agent = HandoffAgent()
    pending = agent.pending_requests
    if not pending:
        click.echo("No pending handoff requests.")
        return
    for req in pending:
        click.echo(
            f"  [{req.priority.value.upper()}] {req.request_id} "
            f"— {req.source_agent}: {req.reason}"
        )


@handoff.command("show")
@click.argument("request_id")
def handoff_show(request_id: str):
    """Show details of a handoff request."""
    from platform_agent.foundation.handoff import HandoffAgent

    agent = HandoffAgent()
    req = agent.get_request(request_id)
    if req is None:
        click.echo(f"No handoff request found: {request_id}")
        return
    click.echo(agent.format_handoff_report(req))


@handoff.command("resolve")
@click.argument("request_id")
@click.argument("decision", type=click.Choice(["approve", "reject", "revise", "override"]))
@click.option("--instructions", "-i", default="", help="Instructions for the agent")
@click.option("--reviewer", "-r", default="cli-user", help="Reviewer name")
def handoff_resolve(request_id: str, decision: str, instructions: str, reviewer: str):
    """Resolve a pending handoff request."""
    from platform_agent.foundation.handoff import CLIHandoffChannel

    channel = CLIHandoffChannel()
    try:
        response = channel.resolve(request_id, decision, instructions, reviewer)
        click.echo(f"✅ Resolved {request_id}: {response.decision} by {response.reviewer}")
    except KeyError:
        click.echo(f"❌ No pending request: {request_id}")


# -- control-plane: management commands for the control plane -----------------


@cli.group("control-plane")
def control_plane():
    """Control plane management commands."""


# -- control-plane registry ---------------------------------------------------


@control_plane.group()
def registry():
    """Agent registry commands."""


@registry.command("list")
@click.option("--tenant", default=None, help="Filter by tenant ID.")
@click.option("--state", default=None, help="Filter by agent state.")
def registry_list(tenant: str | None, state: str | None):
    """List registered agents."""
    import json

    from platform_agent.plato.control_plane.registry import AgentRegistry, AgentState

    reg = AgentRegistry()
    # In a real deployment this would connect to a shared store.
    # For CLI demo, we show the interface and report empty.
    agents = reg.list_agents(tenant_id=tenant)
    if state:
        try:
            target_state = AgentState(state)
            agents = [a for a in agents if a.state == target_state]
        except ValueError:
            click.echo(f"Invalid state: {state}")
            return
    if not agents:
        click.echo("No agents found.")
        return
    for a in agents:
        click.echo(json.dumps(a.to_dict(), indent=2, default=str))


@registry.command("show")
@click.argument("agent_id")
@click.option("--tenant", default="default", help="Tenant ID.")
def registry_show(agent_id: str, tenant: str):
    """Show details of a registered agent."""
    import json

    from platform_agent.plato.control_plane.registry import AgentRegistry

    reg = AgentRegistry()
    record = reg.get(tenant, agent_id)
    if record is None:
        click.echo(f"Agent '{agent_id}' not found in tenant '{tenant}'.")
        return
    click.echo(json.dumps(record.to_dict(), indent=2, default=str))


# -- control-plane policy -----------------------------------------------------


@control_plane.group()
def policy():
    """Policy management commands."""


@policy.command("list")
@click.option("--agent", "agent_id", default=None, help="Filter policies for agent role.")
def policy_list(agent_id: str | None):
    """List policies."""
    from platform_agent.plato.control_plane.policy_engine import create_agent_policies
    from platform_agent.foundation.guardrails import create_default_policies

    store = create_default_policies()
    policies = store.list_policies()

    if agent_id:
        role_policies = create_agent_policies(agent_id)
        policies = role_policies

    if not policies:
        click.echo("No policies found.")
        return

    for p in policies:
        click.echo(f"  {p.policy_id:30s}  {p.effect.value:7s}  {p.description}")


@policy.command("check")
@click.argument("agent_id")
@click.argument("action")
@click.argument("resource")
@click.option("--tenant", default="default", help="Tenant context.")
def policy_check(agent_id: str, action: str, resource: str, tenant: str):
    """Check if an action is allowed by policy."""
    from platform_agent.plato.control_plane.policy_engine import PlatformPolicyEngine
    from platform_agent.foundation.guardrails import AuthorizationRequest, create_default_policies

    store = create_default_policies()
    engine = PlatformPolicyEngine(store)

    req = AuthorizationRequest(
        principal_type="Agent",
        principal_id=agent_id,
        action=action,
        resource_type="File",
        resource_id=resource,
        context={"agent_state": "ready", "tenant_id": tenant},
    )
    decision = engine.evaluate(req)
    status = "ALLOWED" if decision.is_allowed else "DENIED"
    click.echo(f"{status}: {agent_id} {action} {resource}")
    for reason in decision.reasons:
        click.echo(f"  {reason}")


# -- control-plane task -------------------------------------------------------


@control_plane.group()
def task():
    """Task management commands."""


@task.command("list")
@click.option("--status", "status_filter", default=None, help="Filter by task status.")
@click.option("--agent", "agent_id", default=None, help="Filter by assigned agent.")
def task_list(status_filter: str | None, agent_id: str | None):
    """List tasks."""
    import json

    from platform_agent.plato.control_plane.task_manager import TaskManager, TaskStatus

    tm = TaskManager()
    status_obj = None
    if status_filter:
        try:
            status_obj = TaskStatus(status_filter)
        except ValueError:
            click.echo(f"Invalid status: {status_filter}")
            return

    tasks = tm.list_tasks(status=status_obj, assigned_to=agent_id)
    if not tasks:
        click.echo("No tasks found.")
        return
    for t in tasks:
        click.echo(json.dumps(t.to_dict(), indent=2, default=str))


@task.command("show")
@click.argument("task_id")
def task_show(task_id: str):
    """Show details of a task."""
    import json

    from platform_agent.plato.control_plane.task_manager import TaskManager

    tm = TaskManager()
    t = tm.get_task(task_id)
    if t is None:
        click.echo(f"Task '{task_id}' not found.")
        return
    click.echo(json.dumps(t.to_dict(), indent=2, default=str))


# -- control-plane audit ------------------------------------------------------


@control_plane.group()
def audit():
    """Audit log commands."""


@audit.command("violations")
@click.option("--agent", "agent_id", default=None, help="Filter by agent ID.")
@click.option("--since", "since_hours", default=None, type=float, help="Only entries from last N hours.")
def audit_violations(agent_id: str | None, since_hours: float | None):
    """Show policy violations."""
    import json
    from datetime import datetime, timezone, timedelta

    from platform_agent.plato.control_plane.audit import AuditStore

    store = AuditStore()
    violations = store.get_violations()

    if agent_id:
        violations = [v for v in violations if v.agent_id == agent_id]
    if since_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        violations = [v for v in violations if v.timestamp >= cutoff]

    if not violations:
        click.echo("No violations found.")
        return
    for v in violations:
        click.echo(json.dumps(v.to_dict(), indent=2, default=str))


@audit.command("report")
@click.option("--weekly", is_flag=True, help="Generate weekly report.")
def audit_report(weekly: bool):
    """Generate audit report."""
    import json

    from platform_agent.plato.control_plane.audit import AuditStore

    store = AuditStore()
    report = store.generate_report()
    click.echo(json.dumps(report, indent=2, default=str))


# -- control-plane health -----------------------------------------------------


@control_plane.command("health")
@click.option("--agent", "agent_id", default=None, help="Check specific agent health.")
@click.option("--tenant", default="default", help="Tenant ID.")
def health(agent_id: str | None, tenant: str):
    """Check agent health status."""
    from platform_agent.plato.control_plane.registry import AgentRegistry
    from platform_agent.plato.control_plane.lifecycle import HeartbeatManager

    reg = AgentRegistry()

    if agent_id:
        record = reg.get(tenant, agent_id)
        if record is None:
            click.echo(f"Agent '{agent_id}' not found in tenant '{tenant}'.")
            return
        hm = HeartbeatManager(reg)
        hb_ok = hm.check_heartbeat(tenant, agent_id)
        click.echo(f"Agent: {agent_id}")
        click.echo(f"State: {record.state.value}")
        click.echo(f"Heartbeat: {'OK' if hb_ok else 'STALE'}")
    else:
        agents = reg.list_agents(tenant_id=tenant)
        if not agents:
            click.echo("No agents found.")
            return
        hm = HeartbeatManager(reg)
        for a in agents:
            hb_ok = hm.check_heartbeat(a.tenant_id, a.agent_id)
            status = "OK" if hb_ok else "STALE"
            click.echo(f"  {a.agent_id:20s}  {a.state.value:12s}  heartbeat={status}")


if __name__ == "__main__":
    cli()
