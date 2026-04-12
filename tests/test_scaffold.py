"""Tests for the scaffold skill pack — registration, prompt, templates."""

from __future__ import annotations

import ast
import sys

import pytest

from platform_agent.plato.skills.base import SkillPack, load_skill
from platform_agent.plato.skills import _registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the skill registry before each test."""
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


@pytest.fixture()
def scaffold_cls():
    """Import and return the ScaffoldSkill class (triggers register_skill)."""
    # Remove cached module so re-import triggers registration
    mod_key = "platform_agent.plato.skills.scaffold"
    if mod_key in sys.modules:
        del sys.modules[mod_key]
    from platform_agent.plato.skills.scaffold import ScaffoldSkill
    return ScaffoldSkill


@pytest.fixture()
def templates():
    """Import and return template module."""
    from platform_agent.plato.skills.scaffold.templates import TEMPLATES
    return TEMPLATES


@pytest.fixture()
def template_descriptions():
    from platform_agent.plato.skills.scaffold.templates import TEMPLATE_DESCRIPTIONS
    return TEMPLATE_DESCRIPTIONS


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


def test_scaffold_registers_correctly(scaffold_cls) -> None:
    """ScaffoldSkill should be in the registry after import."""
    assert "scaffold" in _registry
    assert _registry["scaffold"] is scaffold_cls


def test_scaffold_is_skillpack_subclass(scaffold_cls) -> None:
    assert issubclass(scaffold_cls, SkillPack)


def test_scaffold_loads_via_load_skill(scaffold_cls) -> None:
    skill = load_skill(scaffold_cls)
    assert skill.name == "scaffold"
    assert isinstance(skill, SkillPack)


# ---------------------------------------------------------------------------
# System prompt extension tests
# ---------------------------------------------------------------------------


def test_system_prompt_contains_template_descriptions(scaffold_cls) -> None:
    """The system prompt should mention each template type."""
    skill = load_skill(scaffold_cls)
    prompt = skill.system_prompt_extension
    assert "basic-agent" in prompt
    assert "multi-agent" in prompt
    assert "rag-agent" in prompt
    assert "tool-agent" in prompt


def test_system_prompt_contains_platform_checks(scaffold_cls) -> None:
    """The system prompt should reference key platform readiness checks."""
    skill = load_skill(scaffold_cls)
    prompt = skill.system_prompt_extension
    # Blocker checks
    assert "C1" in prompt
    assert "C2" in prompt
    # Warning checks
    assert "C4" in prompt
    assert "HEALTHCHECK" in prompt


def test_system_prompt_contains_file_patterns(scaffold_cls) -> None:
    """The system prompt should describe the key files to generate."""
    skill = load_skill(scaffold_cls)
    prompt = skill.system_prompt_extension
    assert "pyproject.toml" in prompt
    assert "Dockerfile" in prompt
    assert "agent.py" in prompt
    assert "health.py" in prompt


def test_scaffold_tools(scaffold_cls) -> None:
    """Scaffold skill should expose Write and Bash tools for file generation."""
    skill = load_skill(scaffold_cls)
    assert "Write" in skill.tools
    assert "Bash" in skill.tools
    assert "Read" in skill.tools


# ---------------------------------------------------------------------------
# Template existence and structure tests
# ---------------------------------------------------------------------------


def test_all_template_types_exist(templates) -> None:
    """All four template types should be defined."""
    assert "basic-agent" in templates
    assert "multi-agent" in templates
    assert "rag-agent" in templates
    assert "tool-agent" in templates


def test_basic_template_has_required_files(templates) -> None:
    """The basic-agent template should contain all required files."""
    basic = templates["basic-agent"]
    required_files = [
        "pyproject.toml",
        "Dockerfile",
        "src/{project_name}/agent.py",
        "src/{project_name}/health.py",
        "tests/test_agent.py",
        "README.md",
        ".gitignore",
    ]
    for f in required_files:
        assert f in basic, f"Missing file in basic-agent template: {f}"


def test_multi_template_extends_basic(templates) -> None:
    """The multi-agent template should contain basic files plus orchestrator/skills."""
    multi = templates["multi-agent"]
    # Should have basic files
    assert "pyproject.toml" in multi
    assert "Dockerfile" in multi
    # Should have multi-agent additions
    assert "src/{project_name}/orchestrator.py" in multi
    assert "src/{project_name}/skills/__init__.py" in multi
    assert "src/{project_name}/skills/example_skill.py" in multi


def test_template_descriptions_match_templates(templates, template_descriptions) -> None:
    """Every template should have a corresponding description."""
    for name in templates:
        assert name in template_descriptions, f"Missing description for template: {name}"


# ---------------------------------------------------------------------------
# Template content validation
# ---------------------------------------------------------------------------


def test_template_python_files_are_valid(templates) -> None:
    """All .py template files should be syntactically valid Python after substitution."""
    for template_name, files in templates.items():
        for path, content in files.items():
            if not path.endswith(".py"):
                continue
            # Substitute placeholder so the code is parseable
            rendered = content.format(project_name="test_project")
            try:
                ast.parse(rendered, filename=f"{template_name}/{path}")
            except SyntaxError as e:
                pytest.fail(
                    f"Syntax error in {template_name}/{path}: {e}"
                )


def test_template_pyproject_has_claude_agent_sdk(templates) -> None:
    """Template pyproject.toml should list claude-agent-sdk as a dependency."""
    for template_name, files in templates.items():
        toml_content = files.get("pyproject.toml", "")
        assert "claude-agent-sdk" in toml_content, (
            f"{template_name} pyproject.toml missing claude-agent-sdk dependency"
        )


def test_template_pyproject_has_pinned_versions(templates) -> None:
    """Template pyproject.toml should pin dependency version ranges."""
    for template_name, files in templates.items():
        toml_content = files.get("pyproject.toml", "")
        # Check that at least one dependency has a version constraint
        assert ">=" in toml_content or "==" in toml_content, (
            f"{template_name} pyproject.toml has no pinned dependency versions"
        )


def test_template_dockerfile_has_healthcheck(templates) -> None:
    """Template Dockerfile should include a HEALTHCHECK directive."""
    for template_name, files in templates.items():
        dockerfile = files.get("Dockerfile", "")
        assert "HEALTHCHECK" in dockerfile, (
            f"{template_name} Dockerfile missing HEALTHCHECK directive"
        )


def test_template_dockerfile_uses_slim_base(templates) -> None:
    """Template Dockerfile should use python:3.11-slim base image."""
    for template_name, files in templates.items():
        dockerfile = files.get("Dockerfile", "")
        assert "python:3.11-slim" in dockerfile, (
            f"{template_name} Dockerfile not using python:3.11-slim"
        )


def test_template_dockerfile_exposes_port(templates) -> None:
    """Template Dockerfile should EXPOSE 8080."""
    for template_name, files in templates.items():
        dockerfile = files.get("Dockerfile", "")
        assert "EXPOSE 8080" in dockerfile, (
            f"{template_name} Dockerfile missing EXPOSE 8080"
        )


def test_template_agent_has_health_endpoint(templates) -> None:
    """Template agent.py should define a /health endpoint."""
    for template_name, files in templates.items():
        agent_content = files.get("src/{project_name}/agent.py", "")
        assert "/health" in agent_content, (
            f"{template_name} agent.py missing /health endpoint"
        )


def test_template_agent_has_sigterm_handler(templates) -> None:
    """Template agent.py should handle SIGTERM for graceful shutdown."""
    for template_name, files in templates.items():
        agent_content = files.get("src/{project_name}/agent.py", "")
        assert "SIGTERM" in agent_content, (
            f"{template_name} agent.py missing SIGTERM handler"
        )


def test_template_agent_logs_to_stdout(templates) -> None:
    """Template agent.py should log to stdout."""
    for template_name, files in templates.items():
        agent_content = files.get("src/{project_name}/agent.py", "")
        assert "sys.stdout" in agent_content, (
            f"{template_name} agent.py not logging to stdout"
        )


def test_template_gitignore_excludes_env(templates) -> None:
    """Template .gitignore should exclude .env files."""
    for template_name, files in templates.items():
        gitignore = files.get(".gitignore", "")
        assert ".env" in gitignore, (
            f"{template_name} .gitignore missing .env exclusion"
        )


def test_template_placeholder_substitution(templates) -> None:
    """All templates should use {project_name} placeholder that can be formatted."""
    for template_name, files in templates.items():
        for path, content in files.items():
            rendered_path = path.format(project_name="my_agent")
            assert "{project_name}" not in rendered_path
            rendered_content = content.format(project_name="my_agent")
            assert "{project_name}" not in rendered_content, (
                f"Unresolved placeholder in {template_name}/{path}"
            )
