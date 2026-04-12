"""DynamoDB-backed stores for the Control Plane.

Provides DynamoDB implementations of AgentRegistry, TaskManager, and
AuditStore using a single-table design with GSIs for efficient queries.

Table schema:
    PK: TENANT#{tenant_id}
    SK: AGENT#{agent_id} | TASK#{task_id} | AUDIT#{ts}#{uuid} | POLICY#{id}

GSI-1 (state-index):
    GSI1PK: STATE#{state}
    GSI1SK: TENANT#{tenant_id}#AGENT#{agent_id}

GSI-2 (capability-index):
    GSI2PK: CAP#{capability_name}
    GSI2SK: {confidence}#{agent_id}

Usage:
    table = create_table(dynamodb_resource)
    registry = DynamoDBAgentRegistry(table)
    task_mgr = DynamoDBTaskManager(table)
    audit = DynamoDBAuditStore(table)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from platform_agent.plato.control_plane.registry import (
    AgentRecord,
    AgentState,
    Capability,
    VALID_TRANSITIONS,
)
from platform_agent.plato.control_plane.task_manager import Task, TaskStatus, TaskType
from platform_agent.plato.control_plane.audit import AuditEntry

logger = logging.getLogger(__name__)

TABLE_NAME = "plato-control-plane"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decimal_default(obj: Any) -> Any:
    """JSON serializer for Decimal (from DDB)."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def _to_decimal(val: float | int) -> Decimal:
    """Convert float to Decimal for DDB."""
    return Decimal(str(val))


def _agent_pk(tenant_id: str) -> str:
    return f"TENANT#{tenant_id}"


def _agent_sk(agent_id: str) -> str:
    return f"AGENT#{agent_id}"


def _task_sk(task_id: str) -> str:
    return f"TASK#{task_id}"


def _audit_sk() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"AUDIT#{ts}#{uuid.uuid4().hex[:8]}"


def _policy_sk(policy_id: str) -> str:
    return f"POLICY#{policy_id}"


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def create_table(dynamodb_resource: Any, table_name: str = TABLE_NAME) -> Any:
    """Create the single-table with GSIs.

    Args:
        dynamodb_resource: boto3 dynamodb resource.
        table_name: Table name.

    Returns:
        The DynamoDB Table object.
    """
    table = dynamodb_resource.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "GSI1PK", "AttributeType": "S"},
            {"AttributeName": "GSI1SK", "AttributeType": "S"},
            {"AttributeName": "GSI2PK", "AttributeType": "S"},
            {"AttributeName": "GSI2SK", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "state-index",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "capability-index",
                "KeySchema": [
                    {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.meta.client.get_waiter("table_exists").wait(TableName=table_name)
    return table


# ---------------------------------------------------------------------------
# DynamoDBAgentRegistry
# ---------------------------------------------------------------------------

class DynamoDBAgentRegistry:
    """DynamoDB-backed agent registry.

    Same interface as AgentRegistry but persists to DynamoDB.
    """

    def __init__(self, table: Any) -> None:
        self._table = table

    def _record_from_item(self, item: dict) -> AgentRecord:
        """Deserialize a DDB item into AgentRecord."""
        caps = [
            Capability(name=c["name"], confidence=float(c["confidence"]))
            for c in json.loads(item.get("capabilities", "[]"))
        ]
        return AgentRecord(
            agent_id=item["agent_id"],
            tenant_id=item["tenant_id"],
            role=item.get("role", ""),
            capabilities=caps,
            state=AgentState(item.get("state", "boot")),
            tools=json.loads(item.get("tools", "[]")),
            config=json.loads(item.get("config", "{}")),
            last_heartbeat=(
                datetime.fromisoformat(item["last_heartbeat"])
                if item.get("last_heartbeat")
                else None
            ),
            registered_at=datetime.fromisoformat(item["registered_at"]),
        )

    def _item_from_record(self, record: AgentRecord) -> dict:
        """Serialize AgentRecord to DDB item."""
        item: dict[str, Any] = {
            "PK": _agent_pk(record.tenant_id),
            "SK": _agent_sk(record.agent_id),
            "entity_type": "AGENT",
            "agent_id": record.agent_id,
            "tenant_id": record.tenant_id,
            "role": record.role,
            "capabilities": json.dumps([c.to_dict() for c in record.capabilities]),
            "state": record.state.value,
            "tools": json.dumps(record.tools),
            "config": json.dumps(record.config),
            "registered_at": record.registered_at.isoformat(),
            # GSI1: state lookup
            "GSI1PK": f"STATE#{record.state.value}",
            "GSI1SK": f"TENANT#{record.tenant_id}#AGENT#{record.agent_id}",
        }
        if record.last_heartbeat:
            item["last_heartbeat"] = record.last_heartbeat.isoformat()
        return item

    def register(
        self,
        tenant_id: str,
        role: str,
        capabilities: list[Capability] | None = None,
        tools: list[str] | None = None,
        config: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> AgentRecord:
        """Register a new agent."""
        if agent_id is None:
            agent_id = str(uuid.uuid4())

        # Check uniqueness via conditional put
        record = AgentRecord(
            agent_id=agent_id,
            tenant_id=tenant_id,
            role=role,
            capabilities=capabilities or [],
            tools=tools or [],
            config=config or {},
        )
        item = self._item_from_record(record)

        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ValueError(
                f"Agent '{agent_id}' already registered for tenant '{tenant_id}'"
            )

        # Write capability index entries
        for cap in record.capabilities:
            self._table.put_item(Item={
                "PK": _agent_pk(tenant_id),
                "SK": f"CAP#{agent_id}#{cap.name}",
                "entity_type": "CAPABILITY_MAP",
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "GSI2PK": f"CAP#{cap.name}",
                "GSI2SK": f"{_to_decimal(cap.confidence)}#{agent_id}",
            })

        logger.info("Registered agent %s for tenant %s", agent_id, tenant_id)
        return record

    def get(self, tenant_id: str, agent_id: str) -> AgentRecord | None:
        """Get an agent record."""
        resp = self._table.get_item(
            Key={"PK": _agent_pk(tenant_id), "SK": _agent_sk(agent_id)}
        )
        item = resp.get("Item")
        if not item:
            return None
        return self._record_from_item(item)

    def list_agents(self, tenant_id: str | None = None) -> list[AgentRecord]:
        """List agents, optionally filtered by tenant."""
        if tenant_id:
            resp = self._table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={
                    ":pk": _agent_pk(tenant_id),
                    ":prefix": "AGENT#",
                },
            )
            return [self._record_from_item(i) for i in resp.get("Items", [])]

        # Scan for all agents (use GSI1 for efficiency)
        resp = self._table.scan(
            FilterExpression="entity_type = :et",
            ExpressionAttributeValues={":et": "AGENT"},
        )
        return [self._record_from_item(i) for i in resp.get("Items", [])]

    def deregister(self, tenant_id: str, agent_id: str) -> bool:
        """Remove an agent."""
        try:
            self._table.delete_item(
                Key={"PK": _agent_pk(tenant_id), "SK": _agent_sk(agent_id)},
                ConditionExpression="attribute_exists(PK)",
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def update_state(
        self,
        tenant_id: str,
        agent_id: str,
        new_state: AgentState,
    ) -> AgentRecord | None:
        """Update agent state with transition validation."""
        record = self.get(tenant_id, agent_id)
        if record is None:
            return None

        if new_state not in VALID_TRANSITIONS.get(record.state, set()):
            logger.warning(
                "Invalid transition %s → %s for %s",
                record.state.value,
                new_state.value,
                agent_id,
            )
            return None

        if new_state == AgentState.TERMINATED:
            self.deregister(tenant_id, agent_id)
            record.state = new_state
            return record

        self._table.update_item(
            Key={"PK": _agent_pk(tenant_id), "SK": _agent_sk(agent_id)},
            UpdateExpression="SET #st = :s, GSI1PK = :g1pk, GSI1SK = :g1sk",
            ExpressionAttributeNames={"#st": "state"},
            ExpressionAttributeValues={
                ":s": new_state.value,
                ":g1pk": f"STATE#{new_state.value}",
                ":g1sk": f"TENANT#{tenant_id}#AGENT#{agent_id}",
            },
        )
        record.state = new_state
        return record

    def update_heartbeat(
        self,
        tenant_id: str,
        agent_id: str,
        timestamp: datetime | None = None,
    ) -> bool:
        """Update agent heartbeat timestamp."""
        ts = (timestamp or datetime.now(timezone.utc)).isoformat()
        try:
            self._table.update_item(
                Key={"PK": _agent_pk(tenant_id), "SK": _agent_sk(agent_id)},
                UpdateExpression="SET last_heartbeat = :ts",
                ExpressionAttributeValues={":ts": ts},
                ConditionExpression="attribute_exists(PK)",
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def find_by_capability(
        self,
        capability: str,
        min_confidence: float = 0.0,
        tenant_id: str | None = None,
    ) -> list[AgentRecord]:
        """Find agents with a given capability using GSI2."""
        resp = self._table.query(
            IndexName="capability-index",
            KeyConditionExpression="GSI2PK = :pk",
            ExpressionAttributeValues={":pk": f"CAP#{capability}"},
        )
        agent_ids = []
        for item in resp.get("Items", []):
            conf = float(item["GSI2SK"].split("#")[0])
            if conf >= min_confidence:
                aid = item["agent_id"]
                tid = item["tenant_id"]
                if tenant_id is None or tid == tenant_id:
                    agent_ids.append((tid, aid))

        records = []
        for tid, aid in agent_ids:
            rec = self.get(tid, aid)
            if rec:
                records.append(rec)
        return records

    def find_by_state(
        self,
        state: AgentState,
        tenant_id: str | None = None,
    ) -> list[AgentRecord]:
        """Find agents by state using GSI1."""
        kwargs: dict[str, Any] = {
            "IndexName": "state-index",
            "KeyConditionExpression": "GSI1PK = :pk",
            "ExpressionAttributeValues": {":pk": f"STATE#{state.value}"},
        }
        if tenant_id:
            kwargs["KeyConditionExpression"] += " AND begins_with(GSI1SK, :prefix)"
            kwargs["ExpressionAttributeValues"][":prefix"] = f"TENANT#{tenant_id}"

        resp = self._table.query(**kwargs)
        records = []
        for item in resp.get("Items", []):
            rec = self.get(item["tenant_id"], item["agent_id"])
            if rec:
                records.append(rec)
        return records

    @property
    def agent_count(self) -> int:
        """Count all agents."""
        return len(self.list_agents())


# ---------------------------------------------------------------------------
# DynamoDBTaskManager
# ---------------------------------------------------------------------------

class DynamoDBTaskManager:
    """DynamoDB-backed task manager.

    Same interface as TaskManager but persists to DynamoDB.
    Claim uses conditional write for atomic contention handling.
    """

    def __init__(self, table: Any) -> None:
        self._table = table

    def _task_from_item(self, item: dict) -> Task:
        """Deserialize DDB item to Task."""
        return Task(
            task_id=item["task_id"],
            tenant_id=item["tenant_id"],
            type=TaskType(item.get("task_type", "direct")),
            source_agent=item.get("source_agent", ""),
            intent=item.get("intent", ""),
            payload=json.loads(item.get("payload", "{}")),
            required_capabilities=json.loads(item.get("required_capabilities", "[]")),
            priority=int(item.get("priority", 0)),
            assigned_to=item.get("assigned_to", ""),
            status=TaskStatus(item.get("status", "pending")),
            retry_count=int(item.get("retry_count", 0)),
            max_retries=int(item.get("max_retries", 3)),
            parent_task_id=item.get("parent_task_id", ""),
            created_at=datetime.fromisoformat(item["created_at"]),
            deadline=(
                datetime.fromisoformat(item["deadline"])
                if item.get("deadline")
                else None
            ),
            claimed_at=(
                datetime.fromisoformat(item["claimed_at"])
                if item.get("claimed_at")
                else None
            ),
            completed_at=(
                datetime.fromisoformat(item["completed_at"])
                if item.get("completed_at")
                else None
            ),
            result=json.loads(item.get("result", "{}")),
        )

    def _item_from_task(self, task: Task) -> dict:
        """Serialize Task to DDB item."""
        item: dict[str, Any] = {
            "PK": _agent_pk(task.tenant_id),
            "SK": _task_sk(task.task_id),
            "entity_type": "TASK",
            "task_id": task.task_id,
            "tenant_id": task.tenant_id,
            "task_type": task.type.value,
            "source_agent": task.source_agent,
            "intent": task.intent,
            "payload": json.dumps(task.payload),
            "required_capabilities": json.dumps(task.required_capabilities),
            "priority": task.priority,
            "assigned_to": task.assigned_to,
            "status": task.status.value,
            "retry_count": task.retry_count,
            "max_retries": task.max_retries,
            "parent_task_id": task.parent_task_id,
            "created_at": task.created_at.isoformat(),
            "result": json.dumps(task.result),
            # GSI1: status lookup
            "GSI1PK": f"STATUS#{task.status.value}",
            "GSI1SK": f"TENANT#{task.tenant_id}#TASK#{task.task_id}",
        }
        if task.deadline:
            item["deadline"] = task.deadline.isoformat()
        if task.claimed_at:
            item["claimed_at"] = task.claimed_at.isoformat()
        if task.completed_at:
            item["completed_at"] = task.completed_at.isoformat()
        return item

    def create_task(
        self,
        tenant_id: str,
        intent: str,
        task_type: TaskType = TaskType.DIRECT,
        source_agent: str = "",
        payload: dict[str, Any] | None = None,
        required_capabilities: list[str] | None = None,
        priority: int = 0,
        max_retries: int = 3,
        parent_task_id: str = "",
        deadline: datetime | None = None,
        task_id: str | None = None,
    ) -> Task:
        """Create a new task."""
        if task_id is None:
            task_id = str(uuid.uuid4())

        task = Task(
            task_id=task_id,
            tenant_id=tenant_id,
            type=task_type,
            source_agent=source_agent,
            intent=intent,
            payload=payload or {},
            required_capabilities=required_capabilities or [],
            priority=priority,
            max_retries=max_retries,
            parent_task_id=parent_task_id,
            deadline=deadline,
        )
        self._table.put_item(Item=self._item_from_task(task))
        logger.info("Created task %s for tenant %s", task_id, tenant_id)
        return task

    def get_task(self, task_id: str, tenant_id: str = "") -> Task | None:
        """Get a task by ID.

        If tenant_id is provided, do a direct get. Otherwise scan.
        """
        if tenant_id:
            resp = self._table.get_item(
                Key={"PK": _agent_pk(tenant_id), "SK": _task_sk(task_id)}
            )
            item = resp.get("Item")
            return self._task_from_item(item) if item else None

        # Scan to find task by ID (less efficient)
        resp = self._table.scan(
            FilterExpression="entity_type = :et AND task_id = :tid",
            ExpressionAttributeValues={":et": "TASK", ":tid": task_id},
        )
        items = resp.get("Items", [])
        return self._task_from_item(items[0]) if items else None

    def list_tasks(
        self,
        tenant_id: str | None = None,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        """List tasks with optional filters."""
        if tenant_id:
            resp = self._table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={
                    ":pk": _agent_pk(tenant_id),
                    ":prefix": "TASK#",
                },
            )
            tasks = [self._task_from_item(i) for i in resp.get("Items", [])]
        else:
            resp = self._table.scan(
                FilterExpression="entity_type = :et",
                ExpressionAttributeValues={":et": "TASK"},
            )
            tasks = [self._task_from_item(i) for i in resp.get("Items", [])]

        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def claim_task(self, task_id: str, agent_id: str) -> Task:
        """Claim a task atomically using conditional write.

        Raises ValueError if already claimed.
        """
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        now = datetime.now(timezone.utc)
        try:
            self._table.update_item(
                Key={"PK": _agent_pk(task.tenant_id), "SK": _task_sk(task_id)},
                UpdateExpression=(
                    "SET assigned_to = :agent, #st = :status, claimed_at = :ts, "
                    "GSI1PK = :g1pk, GSI1SK = :g1sk"
                ),
                ConditionExpression="#st = :pending",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":agent": agent_id,
                    ":status": TaskStatus.CLAIMED.value,
                    ":pending": TaskStatus.PENDING.value,
                    ":ts": now.isoformat(),
                    ":g1pk": f"STATUS#{TaskStatus.CLAIMED.value}",
                    ":g1sk": f"TENANT#{task.tenant_id}#TASK#{task_id}",
                },
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            raise ValueError(
                f"Task '{task_id}' is not in pending state (already claimed or assigned)"
            )

        task.assigned_to = agent_id
        task.status = TaskStatus.CLAIMED
        task.claimed_at = now
        return task

    def assign_task(self, task_id: str, agent_id: str) -> Task:
        """Assign a task to an agent (by dispatcher)."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        self._table.update_item(
            Key={"PK": _agent_pk(task.tenant_id), "SK": _task_sk(task_id)},
            UpdateExpression=(
                "SET assigned_to = :agent, #st = :status, "
                "GSI1PK = :g1pk, GSI1SK = :g1sk"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":agent": agent_id,
                ":status": TaskStatus.ASSIGNED.value,
                ":g1pk": f"STATUS#{TaskStatus.ASSIGNED.value}",
                ":g1sk": f"TENANT#{task.tenant_id}#TASK#{task_id}",
            },
        )
        task.assigned_to = agent_id
        task.status = TaskStatus.ASSIGNED
        return task

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: dict[str, Any] | None = None,
    ) -> Task:
        """Update task status."""
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        update_expr = "SET #st = :status, GSI1PK = :g1pk, GSI1SK = :g1sk"
        values: dict[str, Any] = {
            ":status": status.value,
            ":g1pk": f"STATUS#{status.value}",
            ":g1sk": f"TENANT#{task.tenant_id}#TASK#{task_id}",
        }
        if result is not None:
            update_expr += ", #res = :result"
            values[":result"] = json.dumps(result)
        if status == TaskStatus.COMPLETED:
            update_expr += ", completed_at = :ts"
            values[":ts"] = _now_iso()

        self._table.update_item(
            Key={"PK": _agent_pk(task.tenant_id), "SK": _task_sk(task_id)},
            UpdateExpression=update_expr,
            ExpressionAttributeNames={"#st": "status", "#res": "result"}
            if result is not None
            else {"#st": "status"},
            ExpressionAttributeValues=values,
        )
        task.status = status
        if result:
            task.result = result
        return task


# ---------------------------------------------------------------------------
# DynamoDBAuditStore
# ---------------------------------------------------------------------------

class DynamoDBAuditStore:
    """DynamoDB-backed audit store.

    Same interface as AuditStore but persists to DynamoDB.
    """

    def __init__(self, table: Any) -> None:
        self._table = table

    def log(
        self,
        agent_id: str = "",
        tenant_id: str = "",
        action: str = "",
        details: str | dict[str, Any] = "",
        result: str = "success",
    ) -> AuditEntry:
        """Log an audit entry."""
        now = datetime.now(timezone.utc)
        entry_id = uuid.uuid4().hex[:8]
        # AuditEntry.details expects dict
        if isinstance(details, str):
            details_dict: dict[str, Any] = {"message": details} if details else {}
        else:
            details_dict = details
        entry = AuditEntry(
            agent_id=agent_id,
            tenant_id=tenant_id,
            action=action,
            details=details_dict,
            result=result,
            timestamp=now,
        )
        self._table.put_item(Item={
            "PK": _agent_pk(tenant_id),
            "SK": f"AUDIT#{now.strftime('%Y%m%dT%H%M%S')}#{entry_id}",
            "entity_type": "AUDIT",
            "agent_id": agent_id,
            "tenant_id": tenant_id,
            "action": action,
            "details": json.dumps(details_dict),
            "result": result,
            "timestamp": now.isoformat(),
        })
        return entry

    def _get_all_audit_items(self, tenant_id: str | None = None) -> list[dict]:
        """Get all audit items, optionally filtered by tenant."""
        if tenant_id:
            resp = self._table.query(
                KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
                ExpressionAttributeValues={
                    ":pk": _agent_pk(tenant_id),
                    ":prefix": "AUDIT#",
                },
            )
            return resp.get("Items", [])

        resp = self._table.scan(
            FilterExpression="entity_type = :et",
            ExpressionAttributeValues={":et": "AUDIT"},
        )
        return resp.get("Items", [])

    def generate_report(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Generate an audit report."""
        items = self._get_all_audit_items(tenant_id)
        action_counts: dict[str, int] = {}
        result_counts: dict[str, int] = {}
        agent_counts: dict[str, int] = {}

        for item in items:
            action = item.get("action", "unknown")
            result = item.get("result", "unknown")
            agent = item.get("agent_id", "unknown")

            action_counts[action] = action_counts.get(action, 0) + 1
            result_counts[result] = result_counts.get(result, 0) + 1
            agent_counts[agent] = agent_counts.get(agent, 0) + 1

        violations = [i for i in items if i.get("result") not in ("success", "info")]
        return {
            "total_entries": len(items),
            "action_counts": action_counts,
            "result_counts": result_counts,
            "top_agents": agent_counts,
            "violation_count": len(violations),
        }

    def get_violations(self, tenant_id: str | None = None) -> list[dict]:
        """Get policy violation entries."""
        items = self._get_all_audit_items(tenant_id)
        return [i for i in items if i.get("result") not in ("success", "info")]
