"""Tests for LTM Store — cross-session key-value store."""

from __future__ import annotations

import json
import os

import pytest

from platform_agent.foundation.ltm_store import (
    AgentCoreLTMStore,
    LocalFileLTMStore,
    LTMStore,
)


class TestLocalFileLTMStorePutGetDeleteList:
    """Test basic CRUD operations on LocalFileLTMStore."""

    def test_put_and_get(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("user1/data", "greeting", {"msg": "hello"}, actor_id="user1")
        result = store.get("user1/data", "greeting", actor_id="user1")
        assert result == {"msg": "hello"}

    def test_get_missing_key_returns_none(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        result = store.get("user1/data", "nonexistent", actor_id="user1")
        assert result is None

    def test_put_overwrites_existing(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("user1/data", "key1", "v1", actor_id="user1")
        store.put("user1/data", "key1", "v2", actor_id="user1")
        assert store.get("user1/data", "key1", actor_id="user1") == "v2"

    def test_delete_existing_key(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("user1/data", "to_delete", 42, actor_id="user1")
        assert store.delete("user1/data", "to_delete", actor_id="user1") is True
        assert store.get("user1/data", "to_delete", actor_id="user1") is None

    def test_delete_missing_key_returns_false(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        assert store.delete("user1/data", "ghost", actor_id="user1") is False

    def test_list_keys(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("user1/data", "alpha", 1, actor_id="user1")
        store.put("user1/data", "beta", 2, actor_id="user1")
        store.put("user1/data", "gamma", 3, actor_id="user1")
        keys = store.list_keys("user1/data", actor_id="user1")
        assert sorted(keys) == ["alpha", "beta", "gamma"]

    def test_list_keys_empty_namespace(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        keys = store.list_keys("user1/data", actor_id="user1")
        assert keys == []

    def test_stores_various_types(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        ns = "user1/data"
        store.put(ns, "string_val", "hello", actor_id="user1")
        store.put(ns, "int_val", 42, actor_id="user1")
        store.put(ns, "list_val", [1, 2, 3], actor_id="user1")
        store.put(ns, "null_val", None, actor_id="user1")

        assert store.get(ns, "string_val", actor_id="user1") == "hello"
        assert store.get(ns, "int_val", actor_id="user1") == 42
        assert store.get(ns, "list_val", actor_id="user1") == [1, 2, 3]
        assert store.get(ns, "null_val", actor_id="user1") is None


class TestLocalFileLTMStoreGuardEnforcement:
    """Test that MemoryAccessGuard blocks invalid namespace operations."""

    def test_put_blocked_for_cross_user(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("user999/data", "secret", "value", actor_id="user1")
        # Should be blocked — value not stored
        result = store.get("user999/data", "secret", actor_id="user999")
        assert result is None

    def test_get_blocked_for_cross_user(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        # Store as user1
        store.put("user1/data", "mykey", "myval", actor_id="user1")
        # Attempt get as user2 — blocked
        result = store.get("user1/data", "mykey", actor_id="user2")
        assert result is None

    def test_delete_blocked_for_cross_user(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("user1/data", "mykey", "myval", actor_id="user1")
        # Attempt delete as user2 — blocked
        result = store.delete("user1/data", "mykey", actor_id="user2")
        assert result is False
        # Original should still exist
        assert store.get("user1/data", "mykey", actor_id="user1") == "myval"

    def test_list_keys_blocked_for_cross_user(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("user1/data", "k1", "v1", actor_id="user1")
        # Attempt list as user2 — blocked
        keys = store.list_keys("user1/data", actor_id="user2")
        assert keys == []

    def test_root_namespace_blocked(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("/", "key", "val", actor_id="user1")
        assert store.get("/", "key", actor_id="user1") is None

    def test_empty_namespace_blocked(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("", "key", "val", actor_id="user1")
        assert store.get("", "key", actor_id="user1") is None

    def test_shared_namespace_allowed(self, tmp_path):
        store = LocalFileLTMStore(str(tmp_path))
        store.put("shared/common", "info", {"public": True}, actor_id="user1")
        result = store.get("shared/common", "info", actor_id="user2")
        assert result == {"public": True}


class TestAgentCoreLTMStore:
    """Test that AgentCoreLTMStore raises NotImplementedError for all ops."""

    def test_put_raises(self):
        store = AgentCoreLTMStore()
        with pytest.raises(NotImplementedError):
            store.put("ns", "key", "val", actor_id="user1")

    def test_get_raises(self):
        store = AgentCoreLTMStore()
        with pytest.raises(NotImplementedError):
            store.get("ns", "key", actor_id="user1")

    def test_delete_raises(self):
        store = AgentCoreLTMStore()
        with pytest.raises(NotImplementedError):
            store.delete("ns", "key", actor_id="user1")

    def test_list_keys_raises(self):
        store = AgentCoreLTMStore()
        with pytest.raises(NotImplementedError):
            store.list_keys("ns", actor_id="user1")


class TestLTMStoreABC:
    """Verify LTMStore is abstract and cannot be instantiated directly."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            LTMStore()
