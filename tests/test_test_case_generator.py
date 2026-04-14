"""Tests for the test case generator skill.

Covers AC extraction, test case generation, TC format compliance,
1:1 AC-to-TC mapping, and test type heuristics.

Traces to: spec SS2.3 (test_case_generator), AC-8 (Every AC has a TC)
"""

from __future__ import annotations

import json
import re

import pytest

from platform_agent.plato.skills.test_case_generator import (
    TCGeneratorSkill,
    register_skill,
)
from platform_agent.plato.skills.test_case_generator.generator import (
    extract_acceptance_criteria,
    generate_test_cases,
    _classify_test_type,
)
from platform_agent.plato.skills.test_case_generator.tools import (
    TEST_CASE_GENERATOR_TOOLS,
    generate_test_cases_from_spec,
)
from platform_agent.plato.skills.base import SkillPack, load_skill


# ---------------------------------------------------------------------------
# Sample spec content
# ---------------------------------------------------------------------------

SAMPLE_SPEC = """\
# Test Project — Specification

## 3.1 Feature A

**Acceptance Criteria:**
- AC-001: User can submit a ticket via API
- AC-002: Refund limit enforced at $500

## 3.2 Feature B

**Acceptance Criteria:**
- AC-003: Audit log captures every action
- AC-004: Dashboard shows real-time metrics
"""

SAMPLE_SPEC_BOLD = """\
# Spec with Bold ACs

## 2.1 Auth

**Acceptance Criteria:**
- **AC-010:** Users can log in with SSO
- **AC-011**: Password reset sends email notification
"""

SAMPLE_SPEC_DEPLOY = """\
# Deployment Spec

## 4.1 Infrastructure

**Acceptance Criteria:**
- AC-100: Agent deploys to AgentCore via Slack channel
- AC-101: Database migration runs on startup
- AC-102: Health check endpoint returns 200
- AC-103: User login flow works end-to-end
"""

SAMPLE_SPEC_SINGLE = """\
# Minimal Spec

## 1.1 Core

- AC-001: The system processes input correctly
"""

EMPTY_SPEC = ""
NO_AC_SPEC = "# Project\n\nSome text without any acceptance criteria."


# ---------------------------------------------------------------------------
# Skill registration and metadata
# ---------------------------------------------------------------------------


class TestSkillRegistration:
    """Tests for test case generator skill registration and metadata."""

    def test_skill_is_skillpack_subclass(self) -> None:
        """TCGeneratorSkill is a SkillPack subclass (renamed to avoid pytest collection)."""
        assert issubclass(TCGeneratorSkill, SkillPack)

    def test_skill_name(self) -> None:
        """Skill name is 'test_case_generator'."""
        skill = TCGeneratorSkill()
        assert skill.name == "test_case_generator"

    def test_skill_description(self) -> None:
        """Skill has a non-empty description."""
        skill = TCGeneratorSkill()
        assert len(skill.description) > 0
        assert "test case" in skill.description.lower()

    def test_skill_has_system_prompt(self) -> None:
        """Skill has system_prompt_extension cleared (SKILL.md is sole source)."""
        skill = TCGeneratorSkill()
        # system_prompt_extension is now empty — SKILL.md is the sole prompt source
        assert skill.system_prompt_extension == ""

    def test_skill_tools_list(self) -> None:
        """Skill references the generate tool name."""
        skill = TCGeneratorSkill()
        assert "generate_test_cases_from_spec" in skill.tools

    def test_load_skill(self) -> None:
        """load_skill creates a configured instance."""
        skill = load_skill(TCGeneratorSkill)
        assert skill.name == "test_case_generator"

    def test_skill_registered_in_registry(self) -> None:
        """Skill is available via the registry."""
        from platform_agent.plato.skills import get_skill
        cls = get_skill("test_case_generator")
        assert cls is TCGeneratorSkill

    def test_tools_list_has_all_tools(self) -> None:
        """TEST_CASE_GENERATOR_TOOLS contains the tool function."""
        assert len(TEST_CASE_GENERATOR_TOOLS) == 1


# ---------------------------------------------------------------------------
# AC extraction from spec markdown
# ---------------------------------------------------------------------------


class TestACExtraction:
    """Tests for acceptance criteria extraction from spec content."""

    def test_extracts_all_acs(self) -> None:
        """Extracts all AC-xxx entries from spec content."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC)
        ac_ids = [c["id"] for c in criteria]
        assert ac_ids == ["AC-001", "AC-002", "AC-003", "AC-004"]

    def test_extracts_descriptions(self) -> None:
        """Extracted ACs include their full descriptions."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC)
        assert criteria[0]["description"] == "User can submit a ticket via API"
        assert criteria[1]["description"] == "Refund limit enforced at $500"

    def test_extracts_sections(self) -> None:
        """Extracted ACs include their section references."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC)
        assert criteria[0]["section"] == "3.1"
        assert criteria[2]["section"] == "3.2"

    def test_handles_bold_ac_format(self) -> None:
        """Extracts ACs formatted with bold markdown (**AC-xxx:**)."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC_BOLD)
        assert len(criteria) == 2
        assert criteria[0]["id"] == "AC-010"
        assert criteria[1]["id"] == "AC-011"

    def test_empty_spec_returns_empty(self) -> None:
        """Empty spec returns no criteria."""
        assert extract_acceptance_criteria(EMPTY_SPEC) == []

    def test_spec_without_acs_returns_empty(self) -> None:
        """Spec without AC-xxx patterns returns no criteria."""
        assert extract_acceptance_criteria(NO_AC_SPEC) == []

    def test_single_ac_extraction(self) -> None:
        """Correctly extracts a single AC from minimal spec."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC_SINGLE)
        assert len(criteria) == 1
        assert criteria[0]["id"] == "AC-001"

    def test_no_duplicate_acs(self) -> None:
        """Duplicate AC-IDs are deduplicated."""
        dupe_spec = (
            "# Spec\n\n## 1.1 A\n\n- AC-001: First\n\n"
            "## 1.2 B\n\n- AC-001: Duplicate\n"
        )
        criteria = extract_acceptance_criteria(dupe_spec)
        assert len(criteria) == 1


# ---------------------------------------------------------------------------
# Test case generation
# ---------------------------------------------------------------------------


class TestTestCaseGeneration:
    """Tests for test case generation from spec content."""

    def test_generates_one_tc_per_ac(self) -> None:
        """One test case is generated per acceptance criterion (AC-8).

        Traces to: AC-8 (Every AC has a corresponding test case)
        """
        criteria = extract_acceptance_criteria(SAMPLE_SPEC)
        md = generate_test_cases(SAMPLE_SPEC)
        for ac in criteria:
            ac_num = ac["id"].replace("AC-", "")
            tc_id = f"TC-{ac_num}"
            assert tc_id in md, f"Missing {tc_id} for {ac['id']}"
            assert f"traces to {ac['id']}" in md

    def test_tc_count_matches_ac_count(self) -> None:
        """Number of TCs equals number of ACs."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC)
        md = generate_test_cases(SAMPLE_SPEC)
        tc_count = md.count("## TC-")
        assert tc_count == len(criteria)

    def test_empty_spec_produces_no_tcs(self) -> None:
        """Empty spec produces a message, not test cases."""
        md = generate_test_cases(EMPTY_SPEC)
        assert "No acceptance criteria" in md

    def test_no_ac_spec_produces_no_tcs(self) -> None:
        """Spec without ACs produces a message, not test cases."""
        md = generate_test_cases(NO_AC_SPEC)
        assert "No acceptance criteria" in md


# ---------------------------------------------------------------------------
# TC format compliance
# ---------------------------------------------------------------------------


class TestTCFormatCompliance:
    """Tests for test case format compliance.

    Each TC must have: Description, Setup, Steps, Expected, Type.
    """

    def test_all_required_fields_present(self) -> None:
        """Every TC includes all required fields."""
        md = generate_test_cases(SAMPLE_SPEC)
        required_fields = [
            "**Description:**",
            "**Setup:**",
            "**Steps:**",
            "**Expected:**",
            "**Type:**",
        ]
        for field in required_fields:
            assert field in md, f"Missing field: {field}"

    def test_tc_header_format(self) -> None:
        """TC headers follow the '## TC-NNN (traces to AC-NNN)' format."""
        md = generate_test_cases(SAMPLE_SPEC)
        pattern = re.compile(r"## TC-\d+ \(traces to AC-\d+\)")
        matches = pattern.findall(md)
        criteria = extract_acceptance_criteria(SAMPLE_SPEC)
        assert len(matches) == len(criteria)

    def test_type_field_is_valid(self) -> None:
        """Type field contains only valid values (unit, integration, e2e)."""
        md = generate_test_cases(SAMPLE_SPEC)
        type_pattern = re.compile(r"\*\*Type:\*\*\s+(unit|integration|e2e)")
        matches = type_pattern.findall(md)
        criteria = extract_acceptance_criteria(SAMPLE_SPEC)
        assert len(matches) == len(criteria)

    def test_steps_are_numbered(self) -> None:
        """Steps section contains numbered items."""
        md = generate_test_cases(SAMPLE_SPEC)
        assert re.search(r"1\.", md)
        assert re.search(r"2\.", md)
        assert re.search(r"3\.", md)

    def test_each_tc_has_all_fields(self) -> None:
        """Each individual TC block has all required fields."""
        md = generate_test_cases(SAMPLE_SPEC)
        # Split by TC headers, keeping delimiters to pair with content
        tc_pattern = re.compile(r"(## TC-\d+ \(traces to AC-\d+\))")
        parts = tc_pattern.split(md)
        # Pair headers with their content: parts[1]=header, parts[2]=content, ...
        tc_blocks = [parts[i + 1] for i in range(1, len(parts) - 1, 2)]
        assert len(tc_blocks) > 0, "No TC blocks found"
        for block in tc_blocks:
            assert "**Description:**" in block
            assert "**Setup:**" in block
            assert "**Steps:**" in block
            assert "**Expected:**" in block
            assert "**Type:**" in block


# ---------------------------------------------------------------------------
# 1:1 AC-to-TC mapping (AC-8)
# ---------------------------------------------------------------------------


class TestACTCMapping:
    """Tests for 1:1 mapping between ACs and TCs.

    Traces to: AC-8 (Every AC has a corresponding test case)
    """

    def test_every_ac_has_a_tc(self) -> None:
        """Every AC-ID in the spec has a corresponding TC-ID in output."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC)
        md = generate_test_cases(SAMPLE_SPEC)
        for ac in criteria:
            ac_num = ac["id"].replace("AC-", "")
            tc_id = f"TC-{ac_num}"
            assert tc_id in md, f"AC {ac['id']} missing corresponding {tc_id}"

    def test_tc_ids_mirror_ac_ids(self) -> None:
        """TC numbering mirrors AC numbering (AC-001 → TC-001)."""
        md = generate_test_cases(SAMPLE_SPEC)
        tc_pattern = re.compile(r"TC-(\d+) \(traces to AC-(\d+)\)")
        for match in tc_pattern.finditer(md):
            tc_num = match.group(1)
            ac_num = match.group(2)
            assert tc_num == ac_num, f"TC-{tc_num} does not mirror AC-{ac_num}"

    def test_bold_format_acs_get_tcs(self) -> None:
        """ACs in bold format (**AC-xxx:**) also get corresponding TCs."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC_BOLD)
        md = generate_test_cases(SAMPLE_SPEC_BOLD)
        for ac in criteria:
            ac_num = ac["id"].replace("AC-", "")
            assert f"TC-{ac_num}" in md

    def test_deploy_spec_mapping(self) -> None:
        """All ACs in deploy spec get TCs."""
        criteria = extract_acceptance_criteria(SAMPLE_SPEC_DEPLOY)
        md = generate_test_cases(SAMPLE_SPEC_DEPLOY)
        assert len(criteria) == 4
        for ac in criteria:
            ac_num = ac["id"].replace("AC-", "")
            assert f"TC-{ac_num}" in md


# ---------------------------------------------------------------------------
# Test type heuristics (unit/integration/e2e classification)
# ---------------------------------------------------------------------------


class TestTypeHeuristics:
    """Tests for test type classification heuristics."""

    def test_deploy_keyword_is_e2e(self) -> None:
        """Description with 'deploy' classifies as e2e."""
        assert _classify_test_type("Agent deploys to production") == "e2e"

    def test_channel_keyword_is_e2e(self) -> None:
        """Description with 'channel' classifies as e2e."""
        assert _classify_test_type("Agent operates on Slack channel") == "e2e"

    def test_login_keyword_is_e2e(self) -> None:
        """Description with 'login' classifies as e2e."""
        assert _classify_test_type("User login flow works end-to-end") == "e2e"

    def test_api_keyword_is_integration(self) -> None:
        """Description with 'API' classifies as integration."""
        assert _classify_test_type("Connects to external API") == "integration"

    def test_database_keyword_is_integration(self) -> None:
        """Description with 'database' classifies as integration."""
        assert _classify_test_type("Database migration runs on startup") == "integration"

    def test_service_keyword_is_integration(self) -> None:
        """Description with 'service' classifies as integration."""
        assert _classify_test_type("Communicates with auth service") == "integration"

    def test_default_is_unit(self) -> None:
        """Description without special keywords defaults to unit."""
        assert _classify_test_type("Refund limit enforced at $500") == "unit"

    def test_generic_description_is_unit(self) -> None:
        """Generic description defaults to unit."""
        assert _classify_test_type("The system processes input correctly") == "unit"

    def test_e2e_takes_priority_over_integration(self) -> None:
        """When both e2e and integration keywords present, e2e wins."""
        assert _classify_test_type("Deploy API service to channel") == "e2e"

    def test_case_insensitive(self) -> None:
        """Classification is case-insensitive."""
        assert _classify_test_type("DEPLOY to production") == "e2e"
        assert _classify_test_type("DATABASE query") == "integration"

    def test_deploy_spec_types(self) -> None:
        """Deploy spec produces correct type mix."""
        md = generate_test_cases(SAMPLE_SPEC_DEPLOY)
        # AC-100: deploys via Slack channel → e2e
        assert "**Type:** e2e" in md
        # AC-101: database migration → integration
        assert "**Type:** integration" in md
