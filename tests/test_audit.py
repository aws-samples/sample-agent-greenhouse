"""Tests for Audit Store."""

from __future__ import annotations

from datetime import datetime, timezone

from platform_agent.plato.control_plane.audit import (
    AuditAction,
    AuditEntry,
    AuditResult,
    AuditStore,
)


# ---------------------------------------------------------------------------
# AuditEntry tests
# ---------------------------------------------------------------------------


class TestAuditEntry:
    def test_create_defaults(self):
        entry = AuditEntry()
        assert entry.entry_id is not None
        assert entry.timestamp is not None
        assert entry.agent_id == ""
        assert entry.tenant_id == ""
        assert entry.action == ""
        assert entry.details == {}
        assert entry.result == "success"

    def test_create_with_values(self):
        entry = AuditEntry(
            agent_id="a1",
            tenant_id="t1",
            action="task_created",
            details={"task_id": "t123"},
            result="success",
        )
        assert entry.agent_id == "a1"
        assert entry.action == "task_created"

    def test_to_dict(self):
        entry = AuditEntry(
            entry_id="e1",
            agent_id="a1",
            tenant_id="t1",
            action="test",
            result="success",
        )
        d = entry.to_dict()
        assert d["entry_id"] == "e1"
        assert d["agent_id"] == "a1"
        assert d["tenant_id"] == "t1"
        assert d["action"] == "test"
        assert d["result"] == "success"
        assert "timestamp" in d

    def test_unique_ids(self):
        e1 = AuditEntry()
        e2 = AuditEntry()
        assert e1.entry_id != e2.entry_id


class TestAuditEnums:
    def test_audit_actions(self):
        assert AuditAction.AGENT_REGISTERED.value == "agent_registered"
        assert AuditAction.POLICY_VIOLATION.value == "policy_violation"
        assert AuditAction.CIRCUIT_BROKEN.value == "circuit_broken"

    def test_audit_results(self):
        assert AuditResult.SUCCESS.value == "success"
        assert AuditResult.FAILURE.value == "failure"
        assert AuditResult.DENIED.value == "denied"
        assert AuditResult.FILTERED.value == "filtered"


# ---------------------------------------------------------------------------
# AuditStore tests
# ---------------------------------------------------------------------------


class TestAuditStoreLog:
    def test_log_entry(self):
        store = AuditStore()
        entry = store.log(
            agent_id="a1",
            tenant_id="t1",
            action="test",
            result="success",
        )
        assert entry.agent_id == "a1"
        assert store.entry_count == 1

    def test_log_with_details(self):
        store = AuditStore()
        entry = store.log(
            agent_id="a1",
            action="task_created",
            details={"task_id": "t123"},
        )
        assert entry.details["task_id"] == "t123"

    def test_log_with_timestamp(self):
        store = AuditStore()
        ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
        entry = store.log(agent_id="a1", action="test", timestamp=ts)
        assert entry.timestamp == ts

    def test_log_increments_count(self):
        store = AuditStore()
        for i in range(10):
            store.log(agent_id=f"a{i}", action="test")
        assert store.entry_count == 10


class TestAuditStoreQuery:
    def _make_store(self):
        store = AuditStore()
        store.log(agent_id="a1", tenant_id="t1", action="read", result="success")
        store.log(agent_id="a1", tenant_id="t1", action="write", result="denied")
        store.log(agent_id="a2", tenant_id="t1", action="read", result="success")
        store.log(agent_id="a3", tenant_id="t2", action="read", result="success")
        return store

    def test_query_all(self):
        store = self._make_store()
        results = store.query()
        assert len(results) == 4

    def test_query_by_tenant(self):
        store = self._make_store()
        results = store.query(tenant_id="t1")
        assert len(results) == 3

    def test_query_by_agent(self):
        store = self._make_store()
        results = store.query(agent_id="a1")
        assert len(results) == 2

    def test_query_by_action(self):
        store = self._make_store()
        results = store.query(action="write")
        assert len(results) == 1

    def test_query_by_result(self):
        store = self._make_store()
        results = store.query(result="denied")
        assert len(results) == 1

    def test_query_with_limit(self):
        store = self._make_store()
        results = store.query(limit=2)
        assert len(results) == 2

    def test_query_since(self):
        store = AuditStore()
        old = datetime(2024, 1, 1, tzinfo=timezone.utc)
        new = datetime(2025, 6, 1, tzinfo=timezone.utc)
        store.log(agent_id="a1", action="old", timestamp=old)
        store.log(agent_id="a1", action="new", timestamp=new)
        cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
        results = store.query(since=cutoff)
        assert len(results) == 1
        assert results[0].action == "new"

    def test_query_until(self):
        store = AuditStore()
        old = datetime(2024, 1, 1, tzinfo=timezone.utc)
        new = datetime(2025, 6, 1, tzinfo=timezone.utc)
        store.log(agent_id="a1", action="old", timestamp=old)
        store.log(agent_id="a1", action="new", timestamp=new)
        cutoff = datetime(2025, 1, 1, tzinfo=timezone.utc)
        results = store.query(until=cutoff)
        assert len(results) == 1
        assert results[0].action == "old"

    def test_query_combined_filters(self):
        store = self._make_store()
        results = store.query(tenant_id="t1", agent_id="a1", action="read")
        assert len(results) == 1

    def test_query_no_matches(self):
        store = self._make_store()
        results = store.query(tenant_id="t999")
        assert len(results) == 0

    def test_query_returns_newest_first(self):
        store = AuditStore()
        store.log(agent_id="a1", action="first")
        store.log(agent_id="a1", action="second")
        results = store.query()
        assert results[0].action == "second"


class TestAuditStoreViolations:
    def test_get_violations(self):
        store = AuditStore()
        store.log(action="read", result="success")
        store.log(action="policy_violation", result="denied")
        store.log(action="write", result="denied")
        store.log(action="read", result="filtered")
        violations = store.get_violations()
        assert len(violations) == 3

    def test_get_violations_by_tenant(self):
        store = AuditStore()
        store.log(tenant_id="t1", action="policy_violation", result="denied")
        store.log(tenant_id="t2", action="policy_violation", result="denied")
        violations = store.get_violations(tenant_id="t1")
        assert len(violations) == 1

    def test_get_violations_limit(self):
        store = AuditStore()
        for _ in range(10):
            store.log(action="policy_violation", result="denied")
        violations = store.get_violations(limit=3)
        assert len(violations) == 3

    def test_no_violations(self):
        store = AuditStore()
        store.log(action="read", result="success")
        violations = store.get_violations()
        assert len(violations) == 0


class TestAuditStoreReport:
    def test_generate_report(self):
        store = AuditStore()
        store.log(agent_id="a1", tenant_id="t1", action="read", result="success")
        store.log(agent_id="a1", tenant_id="t1", action="write", result="success")
        store.log(agent_id="a2", tenant_id="t1", action="read", result="denied")
        report = store.generate_report(tenant_id="t1")
        assert report["total_entries"] == 3
        assert report["action_counts"]["read"] == 2
        assert report["action_counts"]["write"] == 1
        assert report["result_counts"]["success"] == 2
        assert report["result_counts"]["denied"] == 1
        assert "a1" in report["top_agents"]
        assert report["top_agents"]["a1"] == 2

    def test_generate_report_empty(self):
        store = AuditStore()
        report = store.generate_report()
        assert report["total_entries"] == 0
        assert report["action_counts"] == {}
        assert report["violation_count"] == 0

    def test_generate_report_all_tenants(self):
        store = AuditStore()
        store.log(tenant_id="t1", action="read", result="success")
        store.log(tenant_id="t2", action="write", result="success")
        report = store.generate_report()
        assert report["total_entries"] == 2


class TestAuditStoreClear:
    def test_clear(self):
        store = AuditStore()
        store.log(action="test")
        store.log(action="test")
        count = store.clear()
        assert count == 2
        assert store.entry_count == 0

    def test_clear_empty(self):
        store = AuditStore()
        count = store.clear()
        assert count == 0
