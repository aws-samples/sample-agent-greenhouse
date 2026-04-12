#!/usr/bin/env bash
# smoke-test.sh — Post-deploy end-to-end verification for Plato Agent.
#
# Run this EVERY TIME after deploying. If any check fails, the deploy
# is NOT considered successful. No exceptions.
#
# Usage:
#   bash scripts/smoke-test.sh [--runtime-arn ARN] [--memory-id ID] [--region REGION]
#
# Requirements:
#   - AWS CLI configured with permissions to invoke AgentCore
#   - jq installed

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

# Parse args
RUNTIME_ARN="${AGENTCORE_RUNTIME_ARN:-}"
MEMORY_ID="${AGENTCORE_MEMORY_ID:-}"
REGION="${AWS_REGION:-us-west-2}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --runtime-arn) RUNTIME_ARN="$2"; shift 2;;
        --memory-id) MEMORY_ID="$2"; shift 2;;
        --region) REGION="$2"; shift 2;;
        *) echo "Unknown arg: $1"; exit 1;;
    esac
done

check_pass() { echo -e "  ${GREEN}✅ PASS${NC}: $1"; ((PASS++)); }
check_fail() { echo -e "  ${RED}❌ FAIL${NC}: $1"; ((FAIL++)); }
check_warn() { echo -e "  ${YELLOW}⚠️  WARN${NC}: $1"; ((WARN++)); }

echo "================================================"
echo "  Plato Agent — Post-Deploy Smoke Test"
echo "================================================"
echo ""
echo "Runtime ARN: ${RUNTIME_ARN:-NOT SET}"
echo "Memory ID:   ${MEMORY_ID:-NOT SET}"
echo "Region:      ${REGION}"
echo ""

# ── Check 1: Agent reachable ──────────────────────────────────────────
echo "── Check 1: Agent Reachable ──"
if [ -z "$RUNTIME_ARN" ]; then
    check_fail "AGENTCORE_RUNTIME_ARN not set"
else
    RESPONSE=$(aws bedrock-agentcore invoke-agent-runtime \
        --agent-runtime-arn "$RUNTIME_ARN" \
        --payload '{"message": "ping"}' \
        --runtime-session-id "smoke-test-$(uuidgen | tr '[:upper:]' '[:lower:]')" \
        --region "$REGION" \
        --output text 2>&1) || true

    if echo "$RESPONSE" | grep -qi "error\|exception\|denied"; then
        check_fail "Agent invoke failed: $(echo "$RESPONSE" | head -1)"
    else
        check_pass "Agent responded to basic invoke"
    fi
fi
echo ""

# ── Check 2: Agent knows its identity ────────────────────────────────
echo "── Check 2: Agent Identity ──"
SESSION_ID="smoke-test-identity-$(uuidgen | tr '[:upper:]' '[:lower:]')"
RESPONSE=$(aws bedrock-agentcore invoke-agent-runtime \
    --agent-runtime-arn "$RUNTIME_ARN" \
    --payload '{"message": "What is your name? Reply in one word."}' \
    --runtime-session-id "$SESSION_ID" \
    --region "$REGION" \
    --output text 2>&1) || true

if echo "$RESPONSE" | grep -qi "plato"; then
    check_pass "Agent identifies as Plato"
else
    check_warn "Agent response doesn't mention 'Plato': $(echo "$RESPONSE" | head -1)"
fi
echo ""

# ── Check 3: Skills loaded ───────────────────────────────────────────
echo "── Check 3: Skills Loaded ──"
RESPONSE=$(aws bedrock-agentcore invoke-agent-runtime \
    --agent-runtime-arn "$RUNTIME_ARN" \
    --payload '{"message": "List your available skills. Just skill names, one per line."}' \
    --runtime-session-id "$SESSION_ID" \
    --region "$REGION" \
    --output text 2>&1) || true

SKILL_COUNT=$(echo "$RESPONSE" | grep -ci "review\|debug\|security\|migration\|deploy\|architecture\|cost\|test" || true)
if [ "$SKILL_COUNT" -ge 3 ]; then
    check_pass "Skills loaded (found $SKILL_COUNT skill keywords)"
else
    check_warn "Skills may not be loaded properly (found $SKILL_COUNT keywords)"
fi
echo ""

# ── Check 4: Memory tools available ──────────────────────────────────
echo "── Check 4: Memory Tools ──"
RESPONSE=$(aws bedrock-agentcore invoke-agent-runtime \
    --agent-runtime-arn "$RUNTIME_ARN" \
    --payload '{"message": "Do you have save_memory and recall_memory tools? Answer yes or no.", "actor_id": "smoke-test-user"}' \
    --runtime-session-id "$SESSION_ID" \
    --region "$REGION" \
    --output text 2>&1) || true

if echo "$RESPONSE" | grep -qi "yes"; then
    check_pass "Memory tools reported available"
else
    check_warn "Memory tools may not be wired: $(echo "$RESPONSE" | head -1)"
fi
echo ""

# ── Check 5: Claude Code CLI ─────────────────────────────────────────
echo "── Check 5: Claude Code CLI ──"
RESPONSE=$(aws bedrock-agentcore invoke-agent-runtime \
    --agent-runtime-arn "$RUNTIME_ARN" \
    --payload '{"message": "Try running claude code CLI with: echo hello. Report if it works or if you get an error."}' \
    --runtime-session-id "smoke-test-cc-$(uuidgen | tr '[:upper:]' '[:lower:]')" \
    --region "$REGION" \
    --output text 2>&1) || true

if echo "$RESPONSE" | grep -qi "not found\|not install\|not available\|error\|fail"; then
    check_fail "Claude Code CLI not available in runtime"
else
    check_pass "Claude Code CLI appears functional"
fi
echo ""

# ── Check 6: Memory resource (if memory_id provided) ─────────────────
echo "── Check 6: Memory Resource ──"
if [ -z "$MEMORY_ID" ]; then
    check_warn "AGENTCORE_MEMORY_ID not set, skipping memory resource check"
else
    MEM_STATUS=$(aws bedrock-agentcore-control get-memory \
        --memory-id "$MEMORY_ID" \
        --region "$REGION" \
        --query 'status' --output text 2>&1) || true

    if echo "$MEM_STATUS" | grep -qi "ACTIVE"; then
        check_pass "Memory resource $MEMORY_ID is ACTIVE"
    else
        check_fail "Memory resource status: $MEM_STATUS"
    fi
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────────
echo "================================================"
echo "  Results: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}, ${YELLOW}${WARN} warnings${NC}"
echo "================================================"

if [ "$FAIL" -gt 0 ]; then
    echo -e "\n${RED}DEPLOY NOT VERIFIED — $FAIL check(s) failed.${NC}"
    echo "Fix the failures before declaring deploy successful."
    exit 1
else
    echo -e "\n${GREEN}DEPLOY VERIFIED ✅${NC}"
    exit 0
fi
