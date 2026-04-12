# DynamoDB Audit Trail Schema

> **Table**: `plato-audit-trail`
> **Purpose**: Durable, queryable audit trail for compliance and observability.
> **Retention**: 90 days (TTL-based expiration).

---

## Table Schema

| Attribute | Type | Description |
|-----------|------|-------------|
| **PK** (Partition Key) | String | `TENANT#{tenant_id}#SESSION#{session_id}` |
| **SK** (Sort Key) | String | `TS#{iso_timestamp}#EVENT#{event_type}` |
| session_id | String | Session identifier |
| tenant_id | String | Tenant/organization identifier |
| event_type | String | Event type (e.g., `tool_call`, `invocation`, `stage_transition`) |
| tool_name | String | Tool that was invoked (if applicable) |
| skill_name | String | Active skill during the event |
| timestamp | String | ISO 8601 timestamp |
| payload | Map (JSON) | Event-specific data (tool input, output preview, etc.) |
| quality_labels | Map | Human-applied quality labels (for review accuracy tracking) |
| expire_at | Number | TTL epoch seconds (90 days from creation) |

---

## Global Secondary Indexes

### GSI1: EventType-Timestamp-index

Query all events of a specific type across tenants/sessions.

| Attribute | Role |
|-----------|------|
| event_type | Partition Key |
| timestamp | Sort Key |

**Use case**: "Show me all `tool_call` events in the last 24 hours."

### GSI2: TenantId-index

Query all events for a specific tenant.

| Attribute | Role |
|-----------|------|
| tenant_id | Partition Key |
| timestamp | Sort Key |

**Use case**: "Show me all events for tenant `acme-corp` this week."

---

## CreateTable CLI Command

```bash
aws dynamodb create-table \
  --table-name plato-audit-trail \
  --attribute-definitions \
    AttributeName=PK,AttributeType=S \
    AttributeName=SK,AttributeType=S \
    AttributeName=event_type,AttributeType=S \
    AttributeName=timestamp,AttributeType=S \
    AttributeName=tenant_id,AttributeType=S \
  --key-schema \
    AttributeName=PK,KeyType=HASH \
    AttributeName=SK,KeyType=RANGE \
  --global-secondary-indexes \
    '[
      {
        "IndexName": "EventType-Timestamp-index",
        "KeySchema": [
          {"AttributeName": "event_type", "KeyType": "HASH"},
          {"AttributeName": "timestamp", "KeyType": "RANGE"}
        ],
        "Projection": {"ProjectionType": "ALL"},
        "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
      },
      {
        "IndexName": "TenantId-index",
        "KeySchema": [
          {"AttributeName": "tenant_id", "KeyType": "HASH"},
          {"AttributeName": "timestamp", "KeyType": "RANGE"}
        ],
        "Projection": {"ProjectionType": "ALL"},
        "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5}
      }
    ]' \
  --provisioned-throughput ReadCapacityUnits=5,WriteCapacityUnits=5 \
  --tags Key=Project,Value=plato Key=Environment,Value=production
```

**Enable TTL** (run after table creation):

```bash
aws dynamodb update-time-to-live \
  --table-name plato-audit-trail \
  --time-to-live-specification Enabled=true,AttributeName=expire_at
```

---

## IAM Policy

Minimal IAM policy for the Plato agent Lambda/ECS task to write audit entries:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PlatoAuditWrite",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/plato-audit-trail"
      ]
    },
    {
      "Sid": "PlatoAuditRead",
      "Effect": "Allow",
      "Action": [
        "dynamodb:Query",
        "dynamodb:GetItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/plato-audit-trail",
        "arn:aws:dynamodb:*:*:table/plato-audit-trail/index/*"
      ]
    }
  ]
}
```

---

## Example PutItem

```python
import time
from datetime import datetime, timezone, timedelta

now = datetime.now(timezone.utc)
expire_at = int((now + timedelta(days=90)).timestamp())

item = {
    "PK": {"S": "TENANT#acme-corp#SESSION#sess_abc123"},
    "SK": {"S": f"TS#{now.isoformat()}#EVENT#tool_call"},
    "session_id": {"S": "sess_abc123"},
    "tenant_id": {"S": "acme-corp"},
    "event_type": {"S": "tool_call"},
    "tool_name": {"S": "github_get_tree"},
    "skill_name": {"S": "aidlc_inception"},
    "timestamp": {"S": now.isoformat()},
    "payload": {"M": {
        "tool_input": {"S": "{\"repo\": \"org/repo\", \"branch\": \"main\"}"},
        "tool_output_preview": {"S": "src/\n  main.py\n  utils.py\ntests/\n  test_main.py"},
        "status": {"S": "completed"},
    }},
    "quality_labels": {"M": {}},
    "expire_at": {"N": str(expire_at)},
}

# boto3 usage:
# dynamodb.put_item(TableName="plato-audit-trail", Item=item)
```

---

## Example Queries

### Query all events in a session

```python
response = dynamodb.query(
    TableName="plato-audit-trail",
    KeyConditionExpression="PK = :pk",
    ExpressionAttributeValues={
        ":pk": {"S": "TENANT#acme-corp#SESSION#sess_abc123"},
    },
    ScanIndexForward=True,  # chronological order
)
```

### Query all tool_call events in the last 24 hours (GSI1)

```python
from datetime import datetime, timezone, timedelta

since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

response = dynamodb.query(
    TableName="plato-audit-trail",
    IndexName="EventType-Timestamp-index",
    KeyConditionExpression="event_type = :et AND #ts >= :since",
    ExpressionAttributeNames={"#ts": "timestamp"},
    ExpressionAttributeValues={
        ":et": {"S": "tool_call"},
        ":since": {"S": since},
    },
)
```

### Query all events for a tenant this week (GSI2)

```python
from datetime import datetime, timezone, timedelta

week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

response = dynamodb.query(
    TableName="plato-audit-trail",
    IndexName="TenantId-index",
    KeyConditionExpression="tenant_id = :tid AND #ts >= :since",
    ExpressionAttributeNames={"#ts": "timestamp"},
    ExpressionAttributeValues={
        ":tid": {"S": "acme-corp"},
        ":since": {"S": week_ago},
    },
)
```

### Find sessions with quality labels

```python
response = dynamodb.query(
    TableName="plato-audit-trail",
    KeyConditionExpression="PK = :pk",
    FilterExpression="attribute_exists(quality_labels.accuracy)",
    ExpressionAttributeValues={
        ":pk": {"S": "TENANT#acme-corp#SESSION#sess_abc123"},
    },
)
```
