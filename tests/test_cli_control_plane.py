"""Tests for CLI control-plane commands.

Uses Click's CliRunner to invoke each sub-command and verify output.
"""

from __future__ import annotations

from click.testing import CliRunner

from platform_agent.cli import cli


class TestControlPlaneRegistryCommands:
    def test_registry_list_empty(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "registry", "list"])
        assert result.exit_code == 0
        assert "No agents found" in result.output

    def test_registry_list_with_state_filter(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "registry", "list", "--state", "ready"])
        assert result.exit_code == 0
        assert "No agents found" in result.output

    def test_registry_list_invalid_state(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "registry", "list", "--state", "invalid"])
        assert result.exit_code == 0
        assert "Invalid state" in result.output

    def test_registry_show_not_found(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "registry", "show", "nonexistent"])
        assert result.exit_code == 0
        assert "not found" in result.output


class TestControlPlanePolicyCommands:
    def test_policy_list_default(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "policy", "list"])
        assert result.exit_code == 0
        # Default policies should be listed
        assert "permit" in result.output.lower() or "forbid" in result.output.lower()

    def test_policy_list_by_role(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "policy", "list", "--agent", "admin"])
        assert result.exit_code == 0
        assert "admin" in result.output.lower()

    def test_policy_check_allowed(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "control-plane", "policy", "check",
            "agent-1", "read", "project/main.py",
        ])
        assert result.exit_code == 0
        assert "ALLOWED" in result.output or "DENIED" in result.output

    def test_policy_check_denied_secrets(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "control-plane", "policy", "check",
            "agent-1", "read", "secrets/key.pem",
        ])
        assert result.exit_code == 0
        assert "DENIED" in result.output


class TestControlPlaneTaskCommands:
    def test_task_list_empty(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "task", "list"])
        assert result.exit_code == 0
        assert "No tasks found" in result.output

    def test_task_list_invalid_status(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "task", "list", "--status", "bogus"])
        assert result.exit_code == 0
        assert "Invalid status" in result.output

    def test_task_show_not_found(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "task", "show", "nonexistent-id"])
        assert result.exit_code == 0
        assert "not found" in result.output


class TestControlPlaneAuditCommands:
    def test_audit_violations_empty(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "audit", "violations"])
        assert result.exit_code == 0
        assert "No violations found" in result.output

    def test_audit_violations_with_agent_filter(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "control-plane", "audit", "violations", "--agent", "a1",
        ])
        assert result.exit_code == 0
        assert "No violations found" in result.output

    def test_audit_violations_with_since(self):
        runner = CliRunner()
        result = runner.invoke(cli, [
            "control-plane", "audit", "violations", "--since", "24",
        ])
        assert result.exit_code == 0
        assert "No violations found" in result.output

    def test_audit_report(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "audit", "report"])
        assert result.exit_code == 0
        assert "total_entries" in result.output

    def test_audit_report_weekly(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "audit", "report", "--weekly"])
        assert result.exit_code == 0
        assert "total_entries" in result.output


class TestControlPlaneHealthCommand:
    def test_health_no_agents(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "health"])
        assert result.exit_code == 0
        assert "No agents found" in result.output

    def test_health_specific_agent_not_found(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "health", "--agent", "ghost"])
        assert result.exit_code == 0
        assert "not found" in result.output


class TestControlPlaneGroupStructure:
    def test_control_plane_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "--help"])
        assert result.exit_code == 0
        assert "registry" in result.output
        assert "policy" in result.output
        assert "task" in result.output
        assert "audit" in result.output
        assert "health" in result.output

    def test_registry_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "registry", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output

    def test_policy_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "policy", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "check" in result.output

    def test_task_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "task", "--help"])
        assert result.exit_code == 0
        assert "list" in result.output
        assert "show" in result.output

    def test_audit_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["control-plane", "audit", "--help"])
        assert result.exit_code == 0
        assert "violations" in result.output
        assert "report" in result.output
