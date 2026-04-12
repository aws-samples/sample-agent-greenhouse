#!/bin/bash
# post-deploy-session-storage.sh
# Re-applies filesystemConfigurations after agentcore deploy,
# which currently overwrites the runtime config without preserving
# session storage settings (preview feature not yet in CLI).
#
# Usage: ./scripts/post-deploy-session-storage.sh [runtime-id]

set -e

RUNTIME_ID="${1:-RUNTIME_ID_PLACEHOLDER}"
MOUNT_PATH="/mnt/workspace"

echo "🗄️ Re-applying session storage config to runtime: $RUNTIME_ID"

# Get current runtime details
RUNTIME=$(aws bedrock-agentcore-control get-agent-runtime \
  --agent-runtime-id "$RUNTIME_ID" --output json 2>&1)

# Extract required fields
CONTAINER_URI=$(echo "$RUNTIME" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['agentRuntimeArtifact']['containerConfiguration']['containerUri'])")
ROLE_ARN=$(echo "$RUNTIME" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['roleArn'])")
NETWORK_MODE=$(echo "$RUNTIME" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['networkConfiguration']['networkMode'])")

# Check if already configured
HAS_FS=$(echo "$RUNTIME" | python3 -c "
import sys, json
d = json.load(sys.stdin)
fs = d.get('filesystemConfigurations', [])
print('yes' if any(f.get('sessionStorage', {}).get('mountPath') == '$MOUNT_PATH' for f in fs) else 'no')
")

if [ "$HAS_FS" = "yes" ]; then
    echo "✅ Session storage already configured at $MOUNT_PATH — no action needed."
    exit 0
fi

echo "  Container: $CONTAINER_URI"
echo "  Role: $ROLE_ARN"
echo "  Network: $NETWORK_MODE"
echo "  Adding: sessionStorage → $MOUNT_PATH"

aws bedrock-agentcore-control update-agent-runtime \
  --agent-runtime-id "$RUNTIME_ID" \
  --agent-runtime-artifact "{\"containerConfiguration\":{\"containerUri\":\"$CONTAINER_URI\"}}" \
  --role-arn "$ROLE_ARN" \
  --network-configuration "{\"networkMode\":\"$NETWORK_MODE\"}" \
  --filesystem-configurations "[{\"sessionStorage\":{\"mountPath\":\"$MOUNT_PATH\"}}]" \
  --output json > /dev/null

echo "⏳ Waiting for runtime to be ready..."
for i in $(seq 1 30); do
    STATUS=$(aws bedrock-agentcore-control get-agent-runtime \
      --agent-runtime-id "$RUNTIME_ID" --query 'status' --output text 2>/dev/null)
    if [ "$STATUS" = "READY" ]; then
        echo "✅ Session storage enabled at $MOUNT_PATH (runtime $RUNTIME_ID)"
        exit 0
    fi
    sleep 5
done

echo "⚠️ Runtime still updating after 150s — check manually."
exit 1
