"""Tests for spec completeness scoring utility.

Tests:
1. Full spec → score 100
2. Partial spec → score 60
3. Empty spec → score 0
4. AC count detection
5. Case insensitive header matching
6. Variant headers (acceptance-criteria, etc.)
"""

from __future__ import annotations

import pytest

from platform_agent.plato.aidlc.spec_scoring import score_spec, SPEC_REQUIRED_SECTIONS


class TestFullSpec:
    """Test fully complete spec scoring."""

    def test_full_spec(self):
        """All sections present → score 100."""
        spec = """\
# My Project Spec

## Overview

This project implements a new authentication system.

## Acceptance Criteria

- AC-001: User can log in with email/password
- AC-002: User can log in with SSO
- AC-003: Failed login shows error message

## Architecture

The system uses a microservices architecture with separate auth and user services.

## Non-Functional Requirements

- Response time < 200ms for auth endpoints
- 99.9% uptime SLA

## Risks

- SSO provider downtime could block logins
- Token storage security must be validated
"""
        result = score_spec(spec)
        assert result["score"] == 100.0
        assert len(result["sections_found"]) == 5
        assert len(result["sections_missing"]) == 0
        assert result["ac_count"] == 3


class TestPartialSpec:
    """Test partially complete spec scoring."""

    def test_partial_spec(self):
        """3 of 5 sections → score 60."""
        spec = """\
## Overview

A feature for user notifications.

## Acceptance Criteria

- AC-001: Users receive email notifications
- AC-002: Users can configure preferences

## Architecture

Event-driven with SNS and SQS.
"""
        result = score_spec(spec)
        assert result["score"] == pytest.approx(60.0)
        assert len(result["sections_found"]) == 3
        assert "non_functional" in result["sections_missing"]
        assert "risks" in result["sections_missing"]


class TestEmptySpec:
    """Test empty spec scoring."""

    def test_empty_spec(self):
        """No sections → score 0."""
        result = score_spec("")
        assert result["score"] == 0.0
        assert result["sections_found"] == []
        assert len(result["sections_missing"]) == 5
        assert result["ac_count"] == 0

    def test_whitespace_only_spec(self):
        """Whitespace only → score 0."""
        result = score_spec("   \n\n  \t  ")
        assert result["score"] == 0.0

    def test_none_like_empty(self):
        """None-like empty string → score 0."""
        result = score_spec("")
        assert result["score"] == 0.0


class TestACCount:
    """Test acceptance criteria counting."""

    def test_ac_count(self):
        """Counts AC-xxx entries."""
        spec = """\
## Acceptance Criteria

- AC-001: First criterion
- AC-002: Second criterion
- AC-003: Third criterion
- AC-004: Fourth criterion
- AC-005: Fifth criterion
"""
        result = score_spec(spec)
        assert result["ac_count"] == 5

    def test_ac_count_zero(self):
        """No AC entries → count 0."""
        spec = "## Overview\n\nNo acceptance criteria here."
        result = score_spec(spec)
        assert result["ac_count"] == 0

    def test_ac_mixed_case(self):
        """AC-xxx and ac-xxx both counted."""
        spec = "AC-001 and ac-002 and AC-100"
        result = score_spec(spec)
        assert result["ac_count"] == 3


class TestCaseInsensitive:
    """Test case-insensitive header matching."""

    def test_case_insensitive(self):
        """## OVERVIEW matches as overview section."""
        spec = """\
## OVERVIEW

All caps header should match.
"""
        result = score_spec(spec)
        assert "overview" in result["sections_found"]

    def test_mixed_case(self):
        """## Acceptance Criteria matches."""
        spec = """\
## Acceptance Criteria

Mixed case.
"""
        result = score_spec(spec)
        assert "acceptance_criteria" in result["sections_found"]


class TestVariantHeaders:
    """Test that variant header names are matched."""

    def test_acceptance_criteria_variant(self):
        """acceptance-criteria (hyphenated) matches."""
        spec = "## Acceptance-Criteria\n\nContent here."
        result = score_spec(spec)
        assert "acceptance_criteria" in result["sections_found"]

    def test_project_description_variant(self):
        """Project Description matches as overview."""
        spec = "## Project Description\n\nContent here."
        result = score_spec(spec)
        assert "overview" in result["sections_found"]

    def test_nfr_variant(self):
        """NFR matches as non_functional."""
        spec = "## NFR\n\nContent here."
        result = score_spec(spec)
        assert "non_functional" in result["sections_found"]

    def test_risk_assessment_variant(self):
        """Risk Assessment matches as risks."""
        spec = "## Risk Assessment\n\nContent here."
        result = score_spec(spec)
        assert "risks" in result["sections_found"]

    def test_component_design_variant(self):
        """Component Design matches as architecture."""
        spec = "## Component Design\n\nContent here."
        result = score_spec(spec)
        assert "architecture" in result["sections_found"]

    def test_h3_headers(self):
        """### headers also match."""
        spec = "### Overview\n\nContent."
        result = score_spec(spec)
        assert "overview" in result["sections_found"]


class TestReturnStructure:
    """Test that return structure is always consistent."""

    def test_total_sections_always_five(self):
        """total_sections is always 5."""
        result = score_spec("anything")
        assert result["total_sections"] == 5

    def test_sections_found_plus_missing_equals_total(self):
        """sections_found + sections_missing = total."""
        spec = "## Overview\n\n## Risks\n\n"
        result = score_spec(spec)
        assert len(result["sections_found"]) + len(result["sections_missing"]) == 5
