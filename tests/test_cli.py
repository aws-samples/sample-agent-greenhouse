"""Tests for the CLI entry point.

Tests CLI command structure, help text, skill loading, and the
_run_agent_with_skill helper. Does not test actual agent execution
(mocked via conftest).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from platform_agent.cli import cli
from platform_agent.plato.skills import discover_skills, list_skills


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


# -- CLI structure tests -------------------------------------------------------


class TestCLIStructure:
    def test_cli_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Plato" in result.output

    def test_cli_has_all_commands(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert "chat" in result.output
        assert "readiness" in result.output
        assert "review" in result.output
        assert "scaffold" in result.output
        assert "deploy-config" in result.output
        assert "orchestrate" in result.output
        assert "list-skills" in result.output

    def test_readiness_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["readiness", "--help"])
        assert result.exit_code == 0
        assert "readiness" in result.output.lower() or "C1-C12" in result.output

    def test_review_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["review", "--help"])
        assert result.exit_code == 0
        assert "security" in result.output.lower()

    def test_scaffold_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["scaffold", "--help"])
        assert result.exit_code == 0
        assert "basic-agent" in result.output

    def test_deploy_config_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["deploy-config", "--help"])
        assert result.exit_code == 0
        assert "agentcore" in result.output

    def test_orchestrate_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["orchestrate", "--help"])
        assert result.exit_code == 0
        assert "orchestrator" in result.output.lower()


# -- list-skills command -------------------------------------------------------


class TestListSkills:
    def test_list_skills_shows_all_four(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["list-skills"])
        assert result.exit_code == 0
        assert "design-advisor" in result.output
        assert "code-review" in result.output
        assert "scaffold" in result.output
        assert "deployment-config" in result.output

    def test_list_skills_shows_versions(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["list-skills"])
        assert "0.1.0" in result.output

    def test_list_skills_shows_descriptions(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["list-skills"])
        # Each skill should have some description text
        assert "security" in result.output.lower() or "review" in result.output.lower()


# -- review command options ---------------------------------------------------


class TestReviewOptions:
    def test_review_focus_choices(self, runner: CliRunner) -> None:
        """Verify --focus accepts expected values."""
        for focus in ["security", "quality", "patterns", "all"]:
            result = runner.invoke(cli, ["review", "--help"])
            assert focus in result.output

    def test_review_verbose_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["review", "--help"])
        assert "--verbose" in result.output or "-v" in result.output


# -- scaffold command options -------------------------------------------------


class TestScaffoldOptions:
    def test_scaffold_template_choices(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["scaffold", "--help"])
        for tpl in ["basic-agent", "multi-agent", "rag-agent", "tool-agent"]:
            assert tpl in result.output

    def test_scaffold_output_option(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["scaffold", "--help"])
        assert "--output" in result.output or "-o" in result.output


# -- deploy-config command options --------------------------------------------


class TestDeployConfigOptions:
    def test_deploy_target_choices(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["deploy-config", "--help"])
        for target in ["agentcore", "ecs", "lambda"]:
            assert target in result.output


# -- _run_agent_with_skill helper ---------------------------------------------


class TestRunAgentWithSkill:
    def test_discovers_and_loads_skill(self) -> None:
        """Verify the helper can find all registered skills."""
        discover_skills()
        names = list_skills()
        assert "design-advisor" in names
        assert "scaffold" in names
        assert "deployment-config" in names
        assert "code-review" in names
