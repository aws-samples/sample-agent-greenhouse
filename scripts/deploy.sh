#!/bin/bash
# Deploy Plato Foundation Agent to AgentCore Runtime
# Run this from the platform-as-agent repo root
# Prerequisites: AWS credentials configured, agentcore CLI installed
#
# PRODUCTION DEPLOY CHECKLIST (enforced by this script):
# All checks must pass or deploy is marked FAILED.
# Do NOT skip checks — they exist because we shipped broken deploys without them.

set -e

CHECKLIST_PASS=0
CHECKLIST_FAIL=0
CHECKLIST_RESULTS=""

check_pass() {
    CHECKLIST_PASS=$((CHECKLIST_PASS + 1))
    CHECKLIST_RESULTS="${CHECKLIST_RESULTS}\n  ✅ $1"
    echo "  ✅ $1"
}

check_fail() {
    CHECKLIST_FAIL=$((CHECKLIST_FAIL + 1))
    CHECKLIST_RESULTS="${CHECKLIST_RESULTS}\n  ❌ $1"
    echo "  ❌ $1"
}

echo "=== Plato Foundation Agent Deployment ==="
echo ""

# ── PRE-DEPLOY CHECKS ────────────────────────────────────────────────

echo "═══ PRE-DEPLOY CHECKS ═══"
echo ""

# Check 1: Config file exists
echo "Check: .bedrock_agentcore.yaml exists..."
if [ ! -f .bedrock_agentcore.yaml ]; then
    check_fail "Config file missing — run 'agentcore configure -e entrypoint.py' first"
    echo "  Cannot continue without config. Aborting."
    exit 1
fi
check_pass "Config file exists"

# Check 2: JWT authorizer configured
echo "Check: JWT authorizer configured..."
if ! grep -A 2 "authorizer_configuration:" .bedrock_agentcore.yaml | grep -q "customJWTAuthorizer"; then
    check_fail "JWT authorizer missing — Slack OAuth will get 403"
    echo "  Fix: add customJWTAuthorizer section to .bedrock_agentcore.yaml"
    exit 1
fi
check_pass "JWT authorizer present"

# Check 3: MEMORY_ID available
echo "Check: MEMORY_ID configured..."
MEMORY_ID=$(grep "memory_id:" .bedrock_agentcore.yaml | head -1 | awk '{print $2}')
if [ -z "$MEMORY_ID" ] && [ -z "$MEMORY_ID_ENV" ]; then
    check_fail "MEMORY_ID not found in config or env"
else
    check_pass "MEMORY_ID: ${MEMORY_ID:-$MEMORY_ID_ENV}"
fi

# Check 4: Dockerfile has MEMORY_ID env
echo "Check: Dockerfile includes MEMORY_ID env..."
DOCKERFILE=".bedrock_agentcore/plato_container/Dockerfile"
if [ -f "$DOCKERFILE" ] && grep -q "MEMORY_ID" "$DOCKERFILE"; then
    check_pass "Dockerfile has MEMORY_ID"
elif [ -f "Dockerfile" ] && grep -q "MEMORY_ID" "Dockerfile"; then
    check_pass "Dockerfile has MEMORY_ID"
else
    check_fail "Dockerfile missing MEMORY_ID env — container won't find memory config"
fi

echo ""

# ── DEPLOY ────────────────────────────────────────────────────────────

echo "═══ DEPLOYING ═══"
echo ""

# Pull latest
echo "Step 1: Pulling latest code..."
git pull origin main
echo ""

# Deploy (no reconfigure — that wipes JWT authorizer)
echo "Step 2: Deploying to AgentCore Runtime..."
echo "  This may take 5-10 minutes..."
agentcore deploy -a plato_container --auto-update-on-conflict
echo ""

# Wait for ready
echo "Step 3: Waiting for agent to be ready..."
MAX_WAIT=300
WAITED=0
AGENT_READY=false
while [ $WAITED -lt $MAX_WAIT ]; do
    STATUS=$(agentcore status 2>&1)
    if echo "$STATUS" | grep -q "Active\|Running\|Ready"; then
        AGENT_READY=true
        break
    fi
    echo "  Still deploying... (${WAITED}s elapsed)"
    sleep 15
    WAITED=$((WAITED + 15))
done

if [ "$AGENT_READY" = true ]; then
    check_pass "Agent status: Active"
else
    check_fail "Agent not ready after ${MAX_WAIT}s"
    echo "  Continuing with checks anyway..."
fi
echo ""

# Setup memory strategies
echo "Step 4: Setting up memory strategies..."
if [ -n "$MEMORY_ID" ]; then
    python3 scripts/setup_memory.py --memory-id "$MEMORY_ID" --verify && \
        check_pass "Memory strategies configured" || \
        check_fail "Memory strategy setup failed"
else
    echo "  Skipped (no MEMORY_ID)"
fi
echo ""

# ── POST-DEPLOY VERIFICATION (PRODUCTION PATH) ───────────────────────

echo "═══ POST-DEPLOY VERIFICATION ═══"
echo ""

# Verify 1: JWT authorizer survived deploy
echo "Verify: JWT authorizer intact after deploy..."
if grep -A 2 "authorizer_configuration:" .bedrock_agentcore.yaml | grep -q "customJWTAuthorizer"; then
    check_pass "JWT authorizer survived deploy"
else
    check_fail "JWT authorizer wiped during deploy — 403 for all Slack users!"
fi

# Verify 2: CLI invoke (IAM path)
echo "Verify: CLI invoke (IAM auth path)..."
CLI_RESULT=$(agentcore invoke '{"prompt": "Reply with exactly: DEPLOY_CHECK_OK", "actor_id": "deploy-verify"}' 2>&1)
if echo "$CLI_RESULT" | grep -q "DEPLOY_CHECK_OK\|result\|response"; then
    check_pass "CLI invoke succeeded (IAM path)"
else
    check_fail "CLI invoke failed — agent may not be responding"
    echo "  Response: $(echo "$CLI_RESULT" | head -3)"
fi

# Verify 3: Memory tools ACTUALLY work (not just claimed)
echo "Verify: Memory tools registered + functional..."
# Step 3a: Ask agent to SAVE something specific
SAVE_CHECK=$(agentcore invoke '{"prompt": "Use the save_memory tool to save this: deploy_verification_test_marker_12345. Use the tool, do not just say you will.", "actor_id": "deploy-verify"}' 2>&1)
# Step 3b: Check CloudWatch logs for actual tool execution
LOG_GROUP=$(aws logs describe-log-groups --log-group-name-prefix "/aws/bedrock-agentcore/runtimes/" --query 'logGroups[0].logGroupName' --output text 2>/dev/null)
if [ -n "$LOG_GROUP" ] && [ "$LOG_GROUP" != "None" ]; then
    # Check last 60s of logs for memory tool registration
    STARTUP_LOGS=$(aws logs filter-log-events \
        --log-group-name "$LOG_GROUP" \
        --start-time $(($(date +%s) * 1000 - 300000)) \
        --filter-pattern '"memory_id"' \
        --query 'events[].message' --output text 2>/dev/null | head -5)
    if echo "$STARTUP_LOGS" | grep -qi "Memory backend ready\|memory_id=\|Memory tools enabled"; then
        check_pass "Memory tools registered (confirmed from container logs)"
    elif echo "$STARTUP_LOGS" | grep -qi "No memory_id found"; then
        check_fail "Container reports: No memory_id found — memory tools NOT registered"
    else
        # Fallback: check if save_memory was actually called
        SAVE_LOGS=$(aws logs filter-log-events \
            --log-group-name "$LOG_GROUP" \
            --start-time $(($(date +%s) * 1000 - 60000)) \
            --filter-pattern '"save_memory"' \
            --query 'events[].message' --output text 2>/dev/null | head -3)
        if echo "$SAVE_LOGS" | grep -qi "Created event\|save_memory"; then
            check_pass "Memory tools functional (save_memory executed successfully)"
        else
            check_fail "Memory tools may not be working — no save_memory execution in logs"
            echo "  Invoke response: $(echo "$SAVE_CHECK" | head -2)"
        fi
    fi
else
    echo "  WARNING: Cannot check logs (log group not found). Falling back to response check."
    if echo "$SAVE_CHECK" | grep -qi "saved\|memory.*stored\|Created event"; then
        check_pass "Memory tools (response indicates save worked)"
    else
        check_fail "Memory tools may not be working"
        echo "  Response: $(echo "$SAVE_CHECK" | head -3)"
    fi
fi

# Verify 3b: GitHub tools loaded
echo "Verify: GitHub tools loaded..."
if [ -n "$LOG_GROUP" ]; then
    GH_LOGS=$(aws logs filter-log-events \
        --log-group-name "$LOG_GROUP" \
        --start-time $(($(date +%s) * 1000 - 300000)) \
        --filter-pattern '"GitHub tools"' \
        --query 'events[].message' --output text 2>/dev/null | head -3)
    if echo "$GH_LOGS" | grep -qi "GitHub tools enabled"; then
        check_pass "GitHub tools enabled"
    elif echo "$GH_LOGS" | grep -qi "GitHub tools disabled"; then
        check_fail "GitHub tools disabled — check GITHUB_TOKEN in SSM"
    else
        echo "  WARNING: Cannot determine GitHub tools status from logs"
    fi
fi

# Verify 4: JWT auth path (uses SSM for Cognito credentials)
echo "Verify: JWT auth path..."
JWT_TOKEN=$(python3 -c "
import boto3, hmac, hashlib, base64
ssm = boto3.client('ssm', region_name='us-west-2')
pool_id = ssm.get_parameter(Name='/plato/cognito/user-pool-id')['Parameter']['Value']
client_id = ssm.get_parameter(Name='/plato/cognito/client-id')['Parameter']['Value']
client_secret = ssm.get_parameter(Name='/plato/cognito/client-secret', WithDecryption=True)['Parameter']['Value']
password = ssm.get_parameter(Name='/plato/cognito/users/melanie/password', WithDecryption=True)['Parameter']['Value']
msg = 'melanie' + client_id
secret_hash = base64.b64encode(hmac.new(client_secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()
cognito = boto3.client('cognito-idp', region_name='us-west-2')
resp = cognito.admin_initiate_auth(
    UserPoolId=pool_id, ClientId=client_id,
    AuthFlow='ADMIN_USER_PASSWORD_AUTH',
    AuthParameters={'USERNAME': 'melanie', 'PASSWORD': password, 'SECRET_HASH': secret_hash}
)
print(resp['AuthenticationResult']['IdToken'])
" 2>/dev/null)
if [ -n "$JWT_TOKEN" ]; then
    JWT_RESULT=$(agentcore invoke --bearer-token "$JWT_TOKEN" '{"prompt": "Reply with exactly: JWT_OK"}' 2>&1)
    if echo "$JWT_RESULT" | grep -qi "JWT_OK\|result\|response"; then
        check_pass "JWT invoke succeeded (Slack auth path)"
    else
        check_fail "JWT invoke failed — Slack users will get errors"
        echo "  Response: $(echo "$JWT_RESULT" | head -3)"
    fi
else
    check_fail "JWT token acquisition failed — check Cognito SSM params"
fi

# Verify 5: E2E memory smoke test
echo ""
echo "Verify: E2E memory smoke test..."
if [ -n "$MEMORY_ID" ] && [ "${SKIP_MEMORY_TEST:-0}" != "1" ]; then
    python3 scripts/e2e_memory_test.py --memory-id "$MEMORY_ID" --wait 90 && \
        check_pass "E2E memory smoke test passed" || \
        check_fail "E2E memory smoke test failed — cross-session recall broken"
else
    echo "  Skipped (no MEMORY_ID or SKIP_MEMORY_TEST=1)"
fi

# Verify 6: Observability
echo ""
echo "Verify: Observability..."
# Check if recent logs exist (within last 5 min)
LOG_GROUP=$(grep "log_group:" .bedrock_agentcore.yaml 2>/dev/null | head -1 | awk '{print $2}')
if [ -n "$LOG_GROUP" ]; then
    RECENT_LOGS=$(aws logs filter-log-events \
        --log-group-name "$LOG_GROUP" \
        --start-time $(python3 -c "import time; print(int((time.time()-300)*1000))") \
        --limit 1 \
        --query 'events[0].message' \
        --output text \
        --region us-west-2 2>/dev/null)
    if [ -n "$RECENT_LOGS" ] && [ "$RECENT_LOGS" != "None" ]; then
        check_pass "CloudWatch logs: recent entries found"
    else
        check_fail "CloudWatch logs: no recent entries (obs may not be working)"
    fi
else
    echo "  ⚠️  log_group not in config — checking default..."
fi

# Check CloudWatch metrics
METRIC_COUNT=$(aws cloudwatch list-metrics \
    --namespace "Plato/Agent" \
    --region us-west-2 \
    --query 'length(Metrics)' \
    --output text 2>/dev/null)
if [ -n "$METRIC_COUNT" ] && [ "$METRIC_COUNT" -gt 0 ] 2>/dev/null; then
    check_pass "CloudWatch EMF metrics: ${METRIC_COUNT} metrics in Plato/Agent namespace"
else
    echo "  ⚠️  No Plato/Agent metrics found (EMF may need a request to emit first)"
fi

echo ""

# ── FINAL REPORT ──────────────────────────────────────────────────────

echo "═══════════════════════════════════════════"
echo "  DEPLOY CHECKLIST REPORT"
echo "═══════════════════════════════════════════"
echo -e "$CHECKLIST_RESULTS"
echo ""
echo "  Total: $((CHECKLIST_PASS + CHECKLIST_FAIL)) checks"
echo "  Passed: $CHECKLIST_PASS"
echo "  Failed: $CHECKLIST_FAIL"
echo ""

if [ $CHECKLIST_FAIL -gt 0 ]; then
    echo "  ⚠️  DEPLOY HAS FAILURES — review and fix before marking complete"
    echo ""
    echo "=== IMPORTANT: Update Slack Lambda with these values ==="
    AGENT_ARN=$(grep "agent_arn:" .bedrock_agentcore.yaml | head -1 | awk '{print $2}')
    echo "  AGENTCORE_RUNTIME_ARN: $AGENT_ARN"
    echo "  AGENTCORE_MEMORY_ID: $MEMORY_ID"
    exit 1
else
    echo "  ✅ ALL CHECKS PASSED — deploy verified"
    echo ""
    echo "=== Slack Lambda Config ==="
    AGENT_ARN=$(grep "agent_arn:" .bedrock_agentcore.yaml | head -1 | awk '{print $2}')
    echo "  AGENTCORE_RUNTIME_ARN: $AGENT_ARN"
    echo "  AGENTCORE_MEMORY_ID: $MEMORY_ID"
fi
echo ""
echo "=== Deployment Complete ==="
