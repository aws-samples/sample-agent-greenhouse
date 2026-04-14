"""Tests for Agent Registry."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from platform_agent.plato.control_plane.registry import (
    AgentRecord,
    AgentRegistry,
    AgentState,
    Capability,
    VALID_TRANSITIONS,
)


# ---------------------------------------------------------------------------
# Capability tests
# ---------------------------------------------------------------------------


class TestCapability:
    def test_create_default_confidence(self):
        cap = Capability(name="design")
        assert cap.name == "design"
        assert cap.confidence == 1.0

    def test_create_custom_confidence(self):
        cap = Capability(name="code-review", confidence=0.8)
        assert cap.confidence == 0.8

    def test_to_dict(self):
        cap = Capability(name="debug", confidence=0.75)
        d = cap.to_dict()
        assert d == {"name": "debug", "confidence": 0.75}


# ---------------------------------------------------------------------------
# AgentRecord tests
# ---------------------------------------------------------------------------


class TestAgentRecord:
    def test_create_defaults(self):
        record = AgentRecord(agent_id="a1", tenant_id="t1", role="dev")
        assert record.agent_id == "a1"
        assert record.tenant_id == "t1"
        assert record.role == "dev"
        assert record.state == AgentState.BOOT
        assert record.capabilities == []
        assert record.tools == []
        assert record.config == {}
        assert record.last_heartbeat is None
        assert record.registered_at is not None

    def test_has_capability_true(self):
        record = AgentRecord(
            agent_id="a1",
            tenant_id="t1",
            role="dev",
            capabilities=[Capability(name="code", confidence=0.9)],
        )
        assert record.has_capability("code")

    def test_has_capability_false(self):
        record = AgentRecord(agent_id="a1", tenant_id="t1", role="dev")
        assert not record.has_capability("code")

    def test_has_capability_min_confidence(self):
        record = AgentRecord(
            agent_id="a1",
            tenant_id="t1",
            role="dev",
            capabilities=[Capability(name="code", confidence=0.5)],
        )
        assert record.has_capability("code", min_confidence=0.3)
        assert not record.has_capability("code", min_confidence=0.8)

    def test_capability_confidence(self):
        record = AgentRecord(
            agent_id="a1",
            tenant_id="t1",
            role="dev",
            capabilities=[Capability(name="code", confidence=0.7)],
        )
        assert record.capability_confidence("code") == 0.7

    def test_capability_confidence_missing(self):
        record = AgentRecord(agent_id="a1", tenant_id="t1", role="dev")
        assert record.capability_confidence("code") == 0.0

    def test_to_dict(self):
        record = AgentRecord(
            agent_id="a1",
            tenant_id="t1",
            role="dev",
            capabilities=[Capability(name="code", confidence=0.9)],
            state=AgentState.READY,
            tools=["Read"],
        )
        d = record.to_dict()
        assert d["agent_id"] == "a1"
        assert d["tenant_id"] == "t1"
        assert d["state"] == "ready"
        assert d["tools"] == ["Read"]
        assert len(d["capabilities"]) == 1
        assert d["capabilities"][0]["name"] == "code"

    def test_to_dict_heartbeat(self):
        now = datetime.now(timezone.utc)
        record = AgentRecord(
            agent_id="a1", tenant_id="t1", role="dev", last_heartbeat=now
        )
        d = record.to_dict()
        assert d["last_heartbeat"] == now.isoformat()

    def test_to_dict_no_heartbeat(self):
        record = AgentRecord(agent_id="a1", tenant_id="t1", role="dev")
        d = record.to_dict()
        assert d["last_heartbeat"] is None

    def test_multiple_capabilities(self):
        record = AgentRecord(
            agent_id="a1",
            tenant_id="t1",
            role="dev",
            capabilities=[
                Capability(name="code", confidence=0.9),
                Capability(name="debug", confidence=0.7),
                Capability(name="review", confidence=0.5),
            ],
        )
        assert record.has_capability("code")
        assert record.has_capability("debug")
        assert record.has_capability("review")
        assert not record.has_capability("deploy")


# ---------------------------------------------------------------------------
# AgentState tests
# ---------------------------------------------------------------------------


class TestAgentState:
    def test_all_states_exist(self):
        states = [s.value for s in AgentState]
        assert "boot" in states
        assert "initializing" in states
        assert "ready" in states
        assert "busy" in states
        assert "degraded" in states
        assert "terminated" in states

    def test_valid_transitions_from_boot(self):
        valid = VALID_TRANSITIONS[AgentState.BOOT]
        assert AgentState.INITIALIZING in valid
        assert AgentState.TERMINATED in valid
        assert AgentState.READY not in valid

    def test_valid_transitions_from_ready(self):
        valid = VALID_TRANSITIONS[AgentState.READY]
        assert AgentState.BUSY in valid
        assert AgentState.DEGRADED in valid
        assert AgentState.TERMINATED in valid

    def test_terminated_is_terminal(self):
        valid = VALID_TRANSITIONS[AgentState.TERMINATED]
        assert len(valid) == 0

    def test_degraded_can_recover(self):
        valid = VALID_TRANSITIONS[AgentState.DEGRADED]
        assert AgentState.READY in valid

    def test_busy_can_return_ready(self):
        valid = VALID_TRANSITIONS[AgentState.BUSY]
        assert AgentState.READY in valid


# ---------------------------------------------------------------------------
# AgentRegistry tests
# ---------------------------------------------------------------------------


class TestAgentRegistryRegister:
    def test_register_auto_id(self):
        reg = AgentRegistry()
        record = reg.register(tenant_id="t1", role="dev")
        assert record.agent_id is not None
        assert record.tenant_id == "t1"
        assert record.role == "dev"

    def test_register_explicit_id(self):
        reg = AgentRegistry()
        record = reg.register(tenant_id="t1", role="dev", agent_id="my-agent")
        assert record.agent_id == "my-agent"

    def test_register_with_capabilities(self):
        reg = AgentRegistry()
        caps = [Capability(name="code", confidence=0.9)]
        record = reg.register(tenant_id="t1", role="dev", capabilities=caps)
        assert len(record.capabilities) == 1
        assert record.has_capability("code")

    def test_register_with_tools(self):
        reg = AgentRegistry()
        record = reg.register(tenant_id="t1", role="dev", tools=["Read", "Write"])
        assert record.tools == ["Read", "Write"]

    def test_register_with_config(self):
        reg = AgentRegistry()
        record = reg.register(
            tenant_id="t1", role="dev", config={"max_tokens": 1000}
        )
        assert record.config == {"max_tokens": 1000}

    def test_register_duplicate_raises(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        with pytest.raises(ValueError, match="already registered"):
            reg.register(tenant_id="t1", role="dev", agent_id="a1")

    def test_register_same_id_different_tenant(self):
        reg = AgentRegistry()
        r1 = reg.register(tenant_id="t1", role="dev", agent_id="a1")
        r2 = reg.register(tenant_id="t2", role="dev", agent_id="a1")
        assert r1.tenant_id == "t1"
        assert r2.tenant_id == "t2"

    def test_register_increments_count(self):
        reg = AgentRegistry()
        assert reg.agent_count == 0
        reg.register(tenant_id="t1", role="dev")
        assert reg.agent_count == 1
        reg.register(tenant_id="t1", role="reviewer")
        assert reg.agent_count == 2

    def test_register_state_is_boot(self):
        reg = AgentRegistry()
        record = reg.register(tenant_id="t1", role="dev")
        assert record.state == AgentState.BOOT


class TestAgentRegistryDeregister:
    def test_deregister_existing(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        assert reg.deregister("t1", "a1") is True
        assert reg.agent_count == 0

    def test_deregister_nonexistent(self):
        reg = AgentRegistry()
        assert reg.deregister("t1", "a1") is False

    def test_deregister_wrong_tenant(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        assert reg.deregister("t2", "a1") is False
        assert reg.agent_count == 1


class TestAgentRegistryGet:
    def test_get_existing(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        record = reg.get("t1", "a1")
        assert record is not None
        assert record.agent_id == "a1"

    def test_get_nonexistent(self):
        reg = AgentRegistry()
        assert reg.get("t1", "a1") is None

    def test_get_wrong_tenant(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        assert reg.get("t2", "a1") is None


class TestAgentRegistryListAgents:
    def test_list_all(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t2", role="reviewer", agent_id="a2")
        agents = reg.list_agents()
        assert len(agents) == 2

    def test_list_by_tenant(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t1", role="reviewer", agent_id="a2")
        reg.register(tenant_id="t2", role="dev", agent_id="a3")
        agents = reg.list_agents(tenant_id="t1")
        assert len(agents) == 2
        assert all(a.tenant_id == "t1" for a in agents)

    def test_list_empty(self):
        reg = AgentRegistry()
        assert reg.list_agents() == []

    def test_list_nonexistent_tenant(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev")
        assert reg.list_agents(tenant_id="t999") == []


class TestAgentRegistryUpdateState:
    def test_valid_transition(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        record = reg.update_state("t1", "a1", AgentState.INITIALIZING)
        assert record.state == AgentState.INITIALIZING

    def test_invalid_transition_raises(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        with pytest.raises(ValueError, match="Invalid transition"):
            reg.update_state("t1", "a1", AgentState.READY)

    def test_agent_not_found_raises(self):
        reg = AgentRegistry()
        with pytest.raises(KeyError):
            reg.update_state("t1", "a1", AgentState.READY)

    def test_full_lifecycle(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        reg.update_state("t1", "a1", AgentState.BUSY)
        reg.update_state("t1", "a1", AgentState.READY)
        reg.update_state("t1", "a1", AgentState.TERMINATED)
        record = reg.get("t1", "a1")
        assert record.state == AgentState.TERMINATED

    def test_cannot_transition_from_terminated(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.update_state("t1", "a1", AgentState.TERMINATED)
        with pytest.raises(ValueError, match="Invalid transition"):
            reg.update_state("t1", "a1", AgentState.READY)


class TestAgentRegistryUpdateHeartbeat:
    def test_update_heartbeat_auto(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        record = reg.update_heartbeat("t1", "a1")
        assert record.last_heartbeat is not None

    def test_update_heartbeat_explicit(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        record = reg.update_heartbeat("t1", "a1", timestamp=ts)
        assert record.last_heartbeat == ts

    def test_update_heartbeat_not_found_raises(self):
        reg = AgentRegistry()
        with pytest.raises(KeyError):
            reg.update_heartbeat("t1", "a1")


class TestAgentRegistryFindByCapability:
    def test_find_matching(self):
        reg = AgentRegistry()
        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="a1",
            capabilities=[Capability(name="code", confidence=0.9)],
        )
        reg.register(
            tenant_id="t1",
            role="reviewer",
            agent_id="a2",
            capabilities=[Capability(name="review", confidence=0.8)],
        )
        results = reg.find_by_capability("code")
        assert len(results) == 1
        assert results[0].agent_id == "a1"

    def test_find_none_matching(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        assert reg.find_by_capability("code") == []

    def test_find_with_min_confidence(self):
        reg = AgentRegistry()
        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="a1",
            capabilities=[Capability(name="code", confidence=0.5)],
        )
        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="a2",
            capabilities=[Capability(name="code", confidence=0.9)],
        )
        results = reg.find_by_capability("code", min_confidence=0.7)
        assert len(results) == 1
        assert results[0].agent_id == "a2"

    def test_find_with_tenant_filter(self):
        reg = AgentRegistry()
        reg.register(
            tenant_id="t1",
            role="dev",
            agent_id="a1",
            capabilities=[Capability(name="code", confidence=0.9)],
        )
        reg.register(
            tenant_id="t2",
            role="dev",
            agent_id="a2",
            capabilities=[Capability(name="code", confidence=0.9)],
        )
        results = reg.find_by_capability("code", tenant_id="t1")
        assert len(results) == 1
        assert results[0].tenant_id == "t1"

    def test_find_multiple_matching(self):
        reg = AgentRegistry()
        for i in range(5):
            reg.register(
                tenant_id="t1",
                role="dev",
                agent_id=f"a{i}",
                capabilities=[Capability(name="code", confidence=0.9)],
            )
        results = reg.find_by_capability("code")
        assert len(results) == 5


class TestAgentRegistryFindByState:
    def test_find_by_state(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t1", role="reviewer", agent_id="a2")
        reg.update_state("t1", "a1", AgentState.INITIALIZING)
        reg.update_state("t1", "a1", AgentState.READY)
        results = reg.find_by_state(AgentState.READY)
        assert len(results) == 1
        assert results[0].agent_id == "a1"

    def test_find_boot_agents(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t1", role="dev", agent_id="a2")
        results = reg.find_by_state(AgentState.BOOT)
        assert len(results) == 2

    def test_find_by_state_with_tenant(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        reg.register(tenant_id="t2", role="dev", agent_id="a2")
        results = reg.find_by_state(AgentState.BOOT, tenant_id="t1")
        assert len(results) == 1
        assert results[0].tenant_id == "t1"

    def test_find_no_agents_in_state(self):
        reg = AgentRegistry()
        reg.register(tenant_id="t1", role="dev", agent_id="a1")
        results = reg.find_by_state(AgentState.READY)
        assert len(results) == 0
