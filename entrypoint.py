"""AgentCore Runtime Entry Point — Foundation Agent.

Uses BedrockAgentCoreApp for proper AgentCore Runtime integration.
Supports both local testing and cloud deployment via `agentcore deploy`.

Three-layer memory architecture:
- Layer 1: FileSessionManager (conversation persistence to /mnt/workspace/.sessions/)
- Layer 2: AgentCore Memory LTM (cross-session semantic insights)
- Layer 3: Workspace files (agent work products in /mnt/workspace/projects/)

Session isolation: each session_id gets its own Agent instance with
separate conversation history persisted by FileSessionManager.

Usage:
    Local:  python entrypoint.py
    Deploy: agentcore configure -e entrypoint.py && agentcore deploy
    Test:   agentcore invoke '{"prompt": "Hello!"}'
"""

import json
import os
import logging
import threading
import sys
from collections import OrderedDict
from dataclasses import dataclass

# ── Logging setup (must be before any getLogger calls) ────────────────
# AgentCore Runtime captures stdout/stderr → CloudWatch Logs.
# format='%(message)s' outputs raw JSON so CW Logs Insights can parse
# structured log lines from hooks (AuditHook, TelemetryHook, etc.).
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)

# Ensure src/ is on the path for direct_code_deploy mode
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from bedrock_agentcore import BedrockAgentCoreApp
from strands.session import FileSessionManager, S3SessionManager

from platform_agent.foundation.agent import FoundationStrandsAgent
from platform_agent.foundation.tools.memory_tools import create_memory_tools
from platform_agent.plato import create_plato_agent
from platform_agent.foundation.tools.github_tool import (
    github_get_repo,
    github_list_prs,
    github_get_pr_diff,
    github_list_pr_files,
    github_list_issues,
    github_get_file,
    github_create_issue,
    github_create_pr_review,
    github_merge_pr,
    github_create_repo,
    github_create_or_update_file,
    github_set_branch_protection,
    github_add_labels,
)
from platform_agent.plato.skills.aidlc_inception.tools import (
    aidlc_start_inception,
    aidlc_get_questions,
    aidlc_submit_answers,
    aidlc_approve_stage,
    aidlc_reject_stage,
    aidlc_get_status,
    aidlc_generate_artifacts,
)

logger = logging.getLogger(__name__)

# ── Configuration (via environment variables) ──────────────────────────
WORKSPACE_DIR = os.environ.get(
    "WORKSPACE_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace"),
)
MODEL_ID = os.environ.get(
    "MODEL_ID", "global.anthropic.claude-opus-4-6-v1"
)
ENABLE_CLAUDE_CODE = (
    os.environ.get("ENABLE_CLAUDE_CODE", "true").lower() == "true"
)
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "100"))
SESSION_STORAGE_DIR = os.environ.get(
    "SESSION_STORAGE_DIR", "/mnt/workspace/.sessions"
)


# ── Lazy-init globals (set on first invoke to avoid 30s cold start) ───
_extra_tools = None
agent_pool = None
memory_client = None
memory_backend = None
_initialized = False
_init_lock = threading.Lock()


def _ensure_initialized():
    """Lazy initialization — only runs once on first invoke.

    AgentCore Runtime requires initialization to complete within 30s.
    We defer all heavy work (Bedrock client, soul loading, etc.) to
    the first invoke so the HTTP server starts instantly.
    """
    global _extra_tools, agent_pool, memory_client, memory_backend, _initialized

    if _initialized:
        return

    with _init_lock:
        if _initialized:
            return

        # --- Extra tools (GitHub + memory) ---
        _extra_tools = []

        # GitHub tools — try env var first, fall back to SSM
        if not os.environ.get("GITHUB_TOKEN"):
            try:
                import boto3
                ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-west-2"))
                token = ssm.get_parameter(Name=os.environ.get("GITHUB_TOKEN_SSM_PATH", "/plato/github/token"), WithDecryption=True)["Parameter"]["Value"]
                os.environ["GITHUB_TOKEN"] = token
                logger.info("GITHUB_TOKEN loaded from SSM")
            except Exception as e:
                logger.warning("Could not load GITHUB_TOKEN from SSM: %s", e)

        if os.environ.get("GITHUB_TOKEN"):
            _extra_tools.extend([
                github_get_repo,
                github_list_prs,
                github_get_pr_diff,
                github_list_pr_files,
                github_list_issues,
                github_get_file,
                github_create_issue,
                github_create_pr_review,
                github_merge_pr,
                github_create_repo,
                github_create_or_update_file,
                github_set_branch_protection,
                github_add_labels,
            ])
            logger.info("GitHub tools enabled (%d tools)", 13)
        else:
            logger.warning("GITHUB_TOKEN not set — GitHub tools disabled")

        # AIDLC Inception tools (always available)
        _extra_tools.extend([
            aidlc_start_inception,
            aidlc_get_questions,
            aidlc_submit_answers,
            aidlc_approve_stage,
            aidlc_reject_stage,
            aidlc_get_status,
            aidlc_generate_artifacts,
        ])
        logger.info("AIDLC Inception tools enabled (7 tools)")

        # --- Agent Pool ---
        agent_pool = AgentPool(max_size=MAX_SESSIONS)

        # --- AgentCore Memory ---
        try:
            from bedrock_agentcore.memory import MemoryClient

            memory_client = MemoryClient(
                region_name=os.environ.get("AWS_REGION", "us-west-2"),
            )
            logger.info("AgentCore Memory client ready")

            # Create memory backend for tools (save_memory / recall_memory)
            mem_id = _get_memory_id()
            if mem_id:
                from platform_agent.memory import AgentCoreMemory
                memory_backend = AgentCoreMemory(
                    memory_id=mem_id,
                    region=os.environ.get("AWS_REGION", "us-west-2"),
                )
                logger.info("AgentCore Memory backend ready (memory_id=%s)", mem_id)
            else:
                logger.warning("No memory_id found — recall_memory/save_memory tools will NOT be available")
        except Exception:
            logger.info("AgentCore Memory not available (no SDK or config)")

        _initialized = True
        logger.info("Foundation Agent initialized (lazy)")


# ── Agent Pool (session isolation) ────────────────────────────────────


class SessionBusy(Exception):
    """Raised when a session is already processing a request."""
    pass


class AgentPool:
    """Thread-safe pool of per-session FoundationStrandsAgent instances.

    Each session_id gets its own agent with FileSessionManager for durable
    conversation persistence and 11+ hooks from FoundationStrandsAgent.
    LRU eviction when pool exceeds max_size.

    Per-session locks prevent concurrent invocations on the same agent
    (Strands Agent does not support concurrent invoke on one instance).
    """

    def __init__(self, max_size: int = 100):
        self._agents: OrderedDict[str, FoundationStrandsAgent] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size
        # Per-session locks: prevent concurrent invoke on same agent instance
        self._session_locks: dict[str, threading.Lock] = {}

    def get_or_create(
        self, session_id: str, actor_id: str = "default"
    ) -> FoundationStrandsAgent:
        with self._lock:
            if session_id in self._agents:
                self._agents.move_to_end(session_id)
                return self._agents[session_id]

            agent = self._create_agent(session_id, actor_id)
            self._agents[session_id] = agent
            self._session_locks[session_id] = threading.Lock()

            while len(self._agents) > self._max_size:
                evicted_id, _ = self._agents.popitem(last=False)
                self._session_locks.pop(evicted_id, None)
                logger.debug("Evicted session %s from agent pool", evicted_id)

            return agent

    def acquire_session(self, session_id: str, blocking: bool = True) -> bool:
        """Acquire the per-session lock. Returns False if non-blocking and busy."""
        with self._lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                # Session not yet created — nothing to lock
                return True
        return lock.acquire(blocking=blocking)

    def release_session(self, session_id: str) -> None:
        """Release the per-session lock."""
        with self._lock:
            lock = self._session_locks.get(session_id)
        if lock is not None:
            try:
                lock.release()
            except RuntimeError:
                pass  # Already released

    def _create_agent(
        self, session_id: str, actor_id: str = "default"
    ) -> FoundationStrandsAgent:
        # Build per-session extra tools: base extras + memory tools
        session_extra_tools = list(_extra_tools) if _extra_tools else []
        if memory_backend:
            mem_tools = create_memory_tools(
                memory_backend=memory_backend,
                actor_id=actor_id,
                session_id=session_id,
            )
            session_extra_tools.extend(mem_tools)

        # Layer 1: Session persistence for durable conversation history.
        #
        # Strategy (ordered by preference):
        #
        # 1. FileSessionManager on /mnt/workspace/.sessions/
        #    → AgentCore Runtime managed session storage (preview) keeps
        #      this mount persistent across stop/resume cycles.  Each
        #      session gets its own isolated storage; the platform handles
        #      replication and durability (up to 1 GB, 14-day idle TTL).
        #    → NOTE: /mnt/workspace is only mounted at invocation time,
        #      not during container init.  _create_agent is called per-
        #      request so the mount is available here.
        #
        # 2. S3SessionManager (fallback for envs without mounted storage)
        #    → Used when /mnt/workspace is not available (e.g. local dev
        #      or pre-session-storage runtimes).
        #
        # 3. FileSessionManager on /tmp (last resort)
        #    → Ephemeral; only for local dev without S3.
        storage_dir = SESSION_STORAGE_DIR  # default: /mnt/workspace/.sessions
        if os.path.isdir(os.path.dirname(storage_dir)):
            # /mnt/workspace exists → use AgentCore managed session storage
            os.makedirs(storage_dir, exist_ok=True)
            session_mgr = FileSessionManager(
                session_id=session_id,
                storage_dir=storage_dir,
            )
            logger.info(
                "Using FileSessionManager on managed session storage "
                "(dir=%s, session=%s)", storage_dir, session_id
            )
        else:
            # /mnt/workspace not available → try S3, then /tmp
            s3_bucket = os.environ.get(
                "SESSION_S3_BUCKET", ""
            )
            try:
                session_mgr = S3SessionManager(
                    session_id=session_id,
                    bucket=s3_bucket,
                    prefix="sessions/",
                    region_name=os.environ.get("AWS_REGION", "us-west-2"),
                )
                logger.info(
                    "Using S3SessionManager (bucket=%s, session=%s)",
                    s3_bucket, session_id,
                )
            except Exception as e:
                logger.warning(
                    "S3SessionManager failed (%s), falling back to /tmp",
                    e,
                )
                import tempfile
                fallback_dir = os.path.join(
                    tempfile.gettempdir(), "plato-sessions"
                )
                os.makedirs(fallback_dir, exist_ok=True)
                session_mgr = FileSessionManager(
                    session_id=session_id,
                    storage_dir=fallback_dir,
                )

        # create_plato_agent builds FoundationAgent with the Plato DomainHarness,
        # wiring all 11+ hooks, skills, and domain policies defined in
        # plato_harness.yaml through the harness.  All kwargs are forwarded
        # directly so behavior is identical to the previous direct construction.
        foundation_agent = create_plato_agent(
            workspace_dir=WORKSPACE_DIR,
            model_id=MODEL_ID,
            extra_tools=session_extra_tools,
            enable_claude_code=ENABLE_CLAUDE_CODE,
            session_id=session_id,
            session_manager=session_mgr,
            actor_id=actor_id,
            # MemoryExtractionHook disabled — AgentCore Memory strategies
            # handle LTM extraction automatically via the STM → LTM pipeline
            # (see _ingest_to_stm).  The hook's heuristic extraction to local
            # files was redundant and lost on container recycle.
            enable_memory_extraction=False,
        )

        logger.info(
            "Created PlatoAgent for session %s "
            "(%d hooks, %d extra tools, FileSessionManager=%s)",
            session_id,
            len(foundation_agent.hook_registry),
            len(session_extra_tools),
            SESSION_STORAGE_DIR,
        )
        return foundation_agent


# ── AgentCore Memory helpers ─────────────────────────────────────────


def _get_memory_id() -> str | None:
    """Get the memory_id from env, config, YAML, or AgentCore API.

    Search order:
    1. MEMORY_ID env var (set in Dockerfile or deploy config)
    2. BEDROCK_AGENTCORE_MEMORY_ID env var (toolkit convention)
    3. .bedrock_agentcore.yaml config file
    4. AgentCore list-memories API (auto-discover by agent name pattern)
    """
    # 1. Direct env var
    mid = os.environ.get("MEMORY_ID")
    if mid:
        return mid
    # 2. Toolkit standard env var
    mid = os.environ.get("BEDROCK_AGENTCORE_MEMORY_ID")
    if mid:
        logger.info("Found memory_id from BEDROCK_AGENTCORE_MEMORY_ID: %s", mid)
        return mid
    # Also check the agentcore config (local path, repo root, or /app)
    try:
        import yaml
        for base_dir in [os.path.dirname(__file__), "/app", "."]:
            cfg_path = os.path.join(base_dir, ".bedrock_agentcore.yaml")
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    cfg = yaml.safe_load(f)
                agents = cfg.get("agents", {})
                for agent_cfg in agents.values():
                    mem = agent_cfg.get("memory", {})
                    if mem.get("memory_id"):
                        logger.info("Found memory_id from config: %s", mem["memory_id"])
                        return mem["memory_id"]
    except Exception:
        pass

    # 4. Auto-discover from AgentCore API
    try:
        import boto3
        client = boto3.client(
            "bedrock-agentcore",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
        )
        response = client.list_memories(maxResults=10)
        memories = response.get("memories", [])
        for mem in memories:
            mem_id = mem.get("memoryId", "")
            # Match by agent name pattern in the memory name
            if "plato" in mem_id.lower() or "plato" in mem.get("name", "").lower():
                logger.info("Auto-discovered memory_id from API: %s", mem_id)
                return mem_id
        # If only one memory exists, use it
        if len(memories) == 1:
            mem_id = memories[0].get("memoryId", "")
            logger.info("Auto-discovered sole memory_id from API: %s", mem_id)
            return mem_id
    except Exception as e:
        logger.debug("Could not auto-discover memory_id: %s", e)

    return None


# ── LTM context loading with token cap ────────────────────────────────

# Maximum characters to inject as LTM context.  ~1500 tokens ≈ 6000
# chars for English; Chinese/mixed text averages ~2 chars/token so 6000
# chars ≈ ~3000 tokens.  We use a conservative char limit and also
# count items to keep the context focused and avoid quality degradation
# as LTM grows over time.
#
# The cap forces relevance-based pruning: each record carries a score
# from AgentCore's semantic search, and lower-scored records are dropped
# first when the budget is exceeded.
MAX_LTM_CHARS = 6000  # ~1500 tokens English, ~3000 tokens Chinese


@dataclass
class _ScoredRecord:
    """A single LTM record with its relevance score and metadata."""
    text: str
    score: float
    strategy_id: str
    section: str  # "preferences" | "summaries" | "knowledge" | "episodes"


def _load_ltm_context(actor_id: str = "default", current_message: str = "") -> str:
    """Load cross-session context from AgentCore Memory LTM.

    Queries multiple memory strategies to build a rich context:
    - User preferences (stable across all sessions)
    - Conversation summaries (recent session summaries)
    - Semantic knowledge (relevant facts matched to current message)
    - Episodic memory (what happened in past interactions)

    Token cap: The total injected context is capped at MAX_LTM_CHARS
    (~1500 tokens).  When the combined results exceed this budget,
    lower-scored records are pruned first.  Preferences get a slight
    score boost (+0.1) since they tend to be the most broadly useful
    across conversations.

    Args:
        actor_id: The user/actor identifier for namespace scoping.
        current_message: The current user message for semantic matching.
            Falls back to a generic query if empty.

    Returns:
        Formatted LTM context string, or empty string if no memory available.
    """
    if not memory_client:
        return ""
    memory_id = _get_memory_id()
    if not memory_id:
        return ""

    all_records: list[_ScoredRecord] = []

    def _search(
        namespace: str,
        query: str,
        section: str,
        top_k: int = 5,
        strategy_id: str = "",
        score_boost: float = 0.0,
    ) -> None:
        """Search a single namespace and append scored results.

        Args:
            namespace: Namespace prefix for scoping.  AgentCore
                ``retrieve_memory_records`` performs *prefix matching*,
                so ``/strategies/X/actors/A/`` returns records from
                all sub-namespaces (e.g. ``…/sessions/S1/``).
            query: Semantic search query string.
            section: Section label for formatting.
            top_k: Maximum results to return.
            strategy_id: Optional memoryStrategyId filter for extra
                precision (e.g. "conversationSummary").
            score_boost: Added to the raw score for priority weighting
                (e.g. preferences get a slight boost).
        """
        try:
            search_criteria: dict = {
                "search_query": query,
                "top_k": top_k,
            }
            if strategy_id:
                search_criteria["memoryStrategyId"] = strategy_id
            response = memory_client.retrieve_memory_records(
                memory_id=memory_id,
                namespace=namespace,
                search_criteria=search_criteria,
            )
            for rec in response.get("memoryRecordSummaries", []):
                text = rec.get("content", {}).get("text", "")
                raw_score = rec.get("score", 0.0)
                if text:
                    all_records.append(_ScoredRecord(
                        text=text,
                        score=raw_score + score_boost,
                        strategy_id=strategy_id or rec.get("memoryStrategyId", ""),
                        section=section,
                    ))
        except Exception:
            logger.debug(
                "LTM search failed (ns=%s, actor=%s)", namespace, actor_id,
                exc_info=True,
            )

    # 1. User preferences — stable across sessions (slight score boost)
    prefs_ns = f"/strategies/userPreferences/actors/{actor_id}/"
    _search(
        prefs_ns, "user preferences and working style",
        section="preferences", top_k=5,
        strategy_id="userPreferences", score_boost=0.1,
    )

    # 2. Conversation summaries — recent session context
    summary_ns = f"/strategies/conversationSummary/actors/{actor_id}/"
    _search(
        summary_ns,
        current_message or "recent conversation topics and context",
        section="summaries", top_k=3,
        strategy_id="conversationSummary",
    )

    # 3. Semantic knowledge — matched to current message
    semantic_ns = f"/strategies/semanticKnowledge/actors/{actor_id}/"
    _search(
        semantic_ns,
        current_message or "technical knowledge and decisions",
        section="knowledge", top_k=5,
        strategy_id="semanticKnowledge",
    )

    # 4. Episodic memory — what happened in past interactions
    episodic_ns = f"/strategies/episodicMemory/actors/{actor_id}/"
    _search(
        episodic_ns,
        current_message or "past interactions and events",
        section="episodes", top_k=3,
        strategy_id="episodicMemory",
    )

    if not all_records:
        return ""

    # Sort by score descending — highest relevance first
    all_records.sort(key=lambda r: r.score, reverse=True)

    # Deduplicate: same text from different strategies → keep highest score
    seen_texts: set[str] = set()
    unique_records: list[_ScoredRecord] = []
    for rec in all_records:
        # Normalize whitespace for dedup comparison
        norm = " ".join(rec.text.split())
        if norm not in seen_texts:
            seen_texts.add(norm)
            unique_records.append(rec)

    # Budget-aware assembly: add records until char cap is reached
    budget = MAX_LTM_CHARS
    selected: list[_ScoredRecord] = []
    for rec in unique_records:
        # Account for section header + bullet formatting overhead (~20 chars)
        cost = len(rec.text) + 20
        if budget - cost < 0 and selected:
            # Budget exhausted — stop adding
            break
        selected.append(rec)
        budget -= cost

    # Group selected records by section for formatted output
    section_order = ["preferences", "summaries", "knowledge", "episodes"]
    section_labels = {
        "preferences": "[User Preferences]",
        "summaries": "[Previous Conversations]",
        "knowledge": "[Relevant Knowledge]",
        "episodes": "[Past Interactions]",
    }
    grouped: dict[str, list[str]] = {s: [] for s in section_order}
    for rec in selected:
        grouped[rec.section].append(rec.text)

    lines: list[str] = []
    for section in section_order:
        items = grouped[section]
        if items:
            lines.append(section_labels[section])
            lines.extend(f"- {t}" for t in items)

    result = "\n".join(lines)
    logger.info(
        "LTM context loaded: %d records, %d chars (cap=%d, actor=%s)",
        len(selected), len(result), MAX_LTM_CHARS, actor_id,
    )
    return result



def _ingest_to_stm(
    actor_id: str,
    session_id: str,
    user_message: str,
    agent_response: str,
) -> None:
    """Write conversation turn to AgentCore Memory STM.

    This feeds the STM → LTM pipeline: AgentCore asynchronously processes
    STM events through configured strategies (semantic, summary,
    preferences, episodic) to build long-term memory.

    Runs fire-and-forget: failures are logged but never block the response.

    Note: This is *complementary* to FileSessionManager.
    - FileSessionManager: persists conversation for Strands Agent replay
    - STM create_event: feeds AgentCore Memory strategies for LTM extraction
    Both are needed for full cross-session continuity.
    """
    if not memory_backend:
        return
    try:
        memory_backend.add_user_message(
            actor_id=actor_id,
            session_id=session_id,
            text=user_message,
        )
    except Exception:
        logger.debug("STM ingest failed (user msg, actor=%s)", actor_id, exc_info=True)
    try:
        memory_backend.add_assistant_message(
            actor_id=actor_id,
            session_id=session_id,
            text=agent_response,
        )
    except Exception:
        logger.debug("STM ingest failed (assistant msg, actor=%s)", actor_id, exc_info=True)


# ── AgentCore App ─────────────────────────────────────────────────────
app = BedrockAgentCoreApp()


def _extract_identity(payload: dict, context=None) -> tuple[str, str, str]:
    """Extract user identity from the Authorization header JWT or payload.

    When JWT Authorizer is configured, the Runtime validates the Bearer token
    and forwards it via RequestContext.request_headers.  We decode the JWT
    (ID token) to extract verified claims:

        sub            → actor_id (unique Cognito user identifier)
        cognito:username → user_name
        custom:role    → role (admin / standard)
        custom:slack_id → available for audit / logging

    The JWT is already validated by the Runtime's JWT Authorizer, so we
    only need to decode the payload — no signature verification here.

    Fallback: payload fields (backward compat when identity is disabled).

    Returns:
        (actor_id, user_name, role) tuple.
    """
    actor_id = "default"
    user_name = ""
    role = "standard"

    # Try JWT from Authorization header (verified by Runtime JWT Authorizer)
    if context and hasattr(context, "request_headers") and context.request_headers:
        auth_header = context.request_headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            jwt_token = auth_header[7:]
            claims = _decode_jwt_claims(jwt_token)
            if claims:
                actor_id = claims.get("sub", "default")
                user_name = claims.get("cognito:username", "")
                role = claims.get("custom:role", "standard")
                slack_id = claims.get("custom:slack_id", "")

                logger.info(
                    "Verified identity from JWT: actor=%s, name=%s, "
                    "role=%s, slack_id=%s",
                    actor_id, user_name, role, slack_id,
                )
                return actor_id, user_name, role

    # Fallback: custom headers (alternative injection path)
    if context and hasattr(context, "request_headers") and context.request_headers:
        headers = context.request_headers
        for key, value in headers.items():
            key_lower = key.lower()
            if key_lower.endswith("custom-actorid"):
                actor_id = value
            elif key_lower.endswith("custom-username"):
                user_name = value
            elif key_lower.endswith("custom-role"):
                role = value

        if actor_id != "default":
            logger.info(
                "Using identity from custom headers: actor=%s, name=%s, role=%s",
                actor_id, user_name, role,
            )
            return actor_id, user_name, role

    # Final fallback: payload (non-JWT mode / backward compatibility)
    actor_id = (
        payload.get("user_id")
        or payload.get("actor_id")
        or "default"
    )
    user_name = payload.get("user_name", "")
    role = payload.get("user_role", "") or role

    logger.info(
        "Identity from payload fallback: actor=%s, name=%s, role=%s",
        actor_id, user_name, role,
    )
    return actor_id, user_name, role


def _decode_jwt_claims(token: str) -> dict | None:
    """Decode JWT payload without signature verification.

    The JWT has already been verified by AgentCore Runtime's JWT Authorizer.
    We only need to extract claims from the base64-encoded payload section.

    Returns the claims dict, or None on decode failure.
    """
    import base64

    try:
        parts = token.split(".")
        if len(parts) != 3:
            logger.warning("JWT does not have 3 parts")
            return None

        # Decode the payload (second part), adding padding
        payload_b64 = parts[1]
        # Add padding if needed
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding

        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        claims = json.loads(payload_bytes)

        # Basic sanity: must have 'sub' and 'iss' claims
        if "sub" not in claims or "iss" not in claims:
            logger.warning("JWT missing required claims (sub/iss)")
            return None

        return claims

    except Exception as e:
        logger.warning("Failed to decode JWT: %s", e)
        return None


# ── Role-based tool policies ─────────────────────────────────────────

# GitHub write tools — readonly users cannot use these
_GITHUB_WRITE_TOOLS = {
    "github_create_issue",
    "github_create_pr_review",
    "github_merge_pr",
    "github_create_repo",
    "github_create_or_update_file",
    "github_set_branch_protection",
    "github_add_labels",
}

# Readonly denylist: all GitHub write tools + claude_code
_READONLY_DENIED = _GITHUB_WRITE_TOOLS | {"claude_code"}

# Role → denylist mapping
#   admin:    full access (no restrictions)
#   standard: full access (same as admin)
#   readonly: GitHub read-only + no claude_code
_ROLE_DENYLISTS: dict[str, set[str]] = {
    "admin": set(),
    "standard": set(),
    "readonly": _READONLY_DENIED,
}


def _apply_role_tool_policy(agent, role: str) -> None:
    """Apply role-based tool access policy to the agent.

    Updates the ToolPolicyHook's denylist based on the user's role.
    Called on every invocation to ensure the correct policy is active
    (sessions may be reused across users after pool eviction).

    Role permissions:
        admin:    full access (no restrictions)
        standard: full access (same as admin)
        readonly: GitHub read-only (list/get/diff only) + no claude_code
    """
    denylist = _ROLE_DENYLISTS.get(role, _ROLE_DENYLISTS["standard"])

    if hasattr(agent, "tool_policy_hook") and agent.tool_policy_hook:
        # Set (not merge) — ensures role change takes effect cleanly
        agent.tool_policy_hook.denylist = denylist or None
        if denylist:
            logger.info(
                "Applied role=%s tool policy: denied %s",
                role, sorted(denylist),
            )
        else:
            logger.info("Applied role=%s tool policy: full access", role)


@app.entrypoint
def invoke(payload, context=None):
    """Main entry point for AgentCore Runtime.

    Three-layer memory architecture:
    - Layer 1: FileSessionManager persists conversation automatically
    - Layer 2: LTM context injected as user message (not system prompt)
    - Layer 3: Workspace files for agent work products

    Args:
        payload: Dict with 'message' (preferred) or 'prompt' key.
        context: RequestContext from AgentCore with session_id.

    Returns:
        Dict with 'result' key containing the agent response.
    """
    user_message = (
        payload.get("message")
        or payload.get("prompt")
        or "Hello! How can I help you today?"
    )
    actor_id, user_name, role = _extract_identity(payload, context)

    # Lazy initialization (avoids 30s startup timeout)
    _ensure_initialized()

    # Session isolation via context.session_id
    session_id = "default"
    if context and hasattr(context, "session_id") and context.session_id:
        session_id = context.session_id

    # Get or create session-isolated FoundationStrandsAgent
    # (FileSessionManager handles conversation persistence automatically)
    foundation_agent = agent_pool.get_or_create(session_id, actor_id)

    # Apply role-based tool policy (only when role is known from JWT)
    _apply_role_tool_policy(foundation_agent, role)

    # Per-session concurrency protection — Strands Agent does not support
    # concurrent invoke on the same instance.  Block and wait (SQS will
    # retry with backoff if the Lambda times out).
    if not agent_pool.acquire_session(session_id, blocking=True):
        raise RuntimeError(f"Session {session_id} is busy")

    try:
        # Layer 2: Inject LTM context once at session start.
        # Only query AgentCore Memory on first turn to avoid wasting
        # 4 API calls per subsequent message in the same session.
        needs_ltm = (
            foundation_agent._agent is None
            or not foundation_agent._agent.messages
        )
        ltm_context = (
            _load_ltm_context(actor_id, current_message=user_message)
            if needs_ltm else ""
        )

        # Ensure the Strands Agent is built once and cached.
        # Do NOT call _build_strands_agent() directly — use invoke() first
        # or check _agent to avoid duplicate SessionManager registration.
        if foundation_agent._agent is None:
            # First invocation for this session — invoke() will build it
            context_parts = []
            if ltm_context:
                context_parts.append(f"<long-term-memory>\n{ltm_context}\n</long-term-memory>")
            if user_name:
                context_parts.append(
                    f"<user-identity>\n"
                    f"Name: {user_name}\n"
                    f"Role: {role}\n"
                    f"</user-identity>"
                )
            if context_parts:
                first_message = "\n\n".join(context_parts) + f"\n\n{user_message}"
            else:
                first_message = user_message
            response_text = foundation_agent.invoke(first_message)
        else:
            # Agent already exists — check if LTM was already injected
            agent_obj = foundation_agent._agent
            is_first_turn = not agent_obj.messages or len(agent_obj.messages) == 0

            if ltm_context and is_first_turn:
                agent_obj.messages.insert(0, {
                    "role": "user",
                    "content": [{"text": f"<long-term-memory>\n{ltm_context}\n</long-term-memory>"}],
                })
                agent_obj.messages.insert(1, {
                    "role": "assistant",
                    "content": [{"text": "Context noted."}],
                })

            response_text = foundation_agent.invoke(user_message)
    finally:
        agent_pool.release_session(session_id)

    # Feed STM → LTM pipeline (fire-and-forget, after releasing session lock)
    _ingest_to_stm(actor_id, session_id, user_message, response_text)

    return {"result": response_text}


# ── WebSocket streaming handler ──────────────────────────────────────


@app.websocket
async def ws_handler(websocket, context=None):
    """WebSocket handler for real-time streaming to Slack.

    Protocol (matches what slack/handler.py expects):
        Client sends: {"prompt": "...", "user_id": "...", "session_id": "..."}
        Server sends: {"type": "delta", "content": "token"}
                      {"type": "tool_start", "name": "tool_name"}
                      {"type": "complete", "content": "full response"}
                      {"type": "error", "message": "..."}
    """
    import asyncio
    import json as _json
    import queue

    await websocket.accept()

    try:
        data = await websocket.receive_json()
    except Exception:
        await websocket.close(code=1003, reason="Invalid JSON")
        return

    user_message = data.get("prompt") or data.get("message") or "Hello!"

    # Extract identity from JWT headers (if available) or payload
    actor_id, user_name, role = _extract_identity(data, context)

    session_id = data.get("session_id") or "default"
    if context and hasattr(context, "session_id") and context.session_id:
        session_id = context.session_id

    _ensure_initialized()

    # Thread-safe queue for streaming events from callback_handler → WS
    event_queue: queue.Queue = queue.Queue()
    _DONE = object()

    class _WSCallbackHandler:
        """Callback handler that pushes Strands streaming events to a queue."""

        def __call__(self, **kwargs):
            data_text = kwargs.get("data", "")
            complete = kwargs.get("complete", False)
            event = kwargs.get("event", {})

            # Check for tool_use start
            tool_use = (
                event.get("contentBlockStart", {})
                .get("start", {})
                .get("toolUse")
            )
            if tool_use:
                event_queue.put({
                    "type": "tool_start",
                    "name": tool_use.get("name", "unknown"),
                })

            # Stream text tokens
            if data_text and not complete:
                event_queue.put({
                    "type": "delta",
                    "content": data_text,
                })

            # Completion marker (handled separately below)

    # Use AgentPool.get_or_create() — same as HTTP path.
    # No more temporary Agent instances.  FileSessionManager ensures
    # history is persisted regardless of Agent instance lifecycle.
    ws_agent = agent_pool.get_or_create(session_id, actor_id)

    # Apply role-based tool policy
    _apply_role_tool_policy(ws_agent, role)

    # Per-session concurrency protection — non-blocking for WS.
    # If session is busy, return error immediately instead of waiting.
    if not agent_pool.acquire_session(session_id, blocking=False):
        await websocket.send_text(_json.dumps({
            "type": "error",
            "message": "Session is busy processing another request. Please wait.",
        }))
        await websocket.close()
        return

    try:
        # Layer 2: Inject LTM context on first turn only.
        needs_ltm = (
            ws_agent._agent is None
            or not ws_agent._agent.messages
        )
        ltm_context = (
            _load_ltm_context(actor_id, current_message=user_message)
            if needs_ltm else ""
        )

        # Reuse the cached Strands Agent (with full conversation history)
        # and pass the WS callback handler per-call for streaming.
        # This preserves multi-turn memory — the old approach built a fresh
        # Agent each WS invocation, causing complete amnesia between turns.
        ws_callback = _WSCallbackHandler()

        # Inject LTM into first message if needed
        context_parts = []
        if ltm_context:
            context_parts.append(f"<long-term-memory>\n{ltm_context}\n</long-term-memory>")
        if user_name:
            context_parts.append(
                f"<user-identity>\n"
                f"Name: {user_name}\n"
                f"Role: {role}\n"
                f"</user-identity>"
            )
        if context_parts:
            actual_message = "\n\n".join(context_parts) + f"\n\n{user_message}"
        else:
            actual_message = user_message

        # Run agent in a thread (it's synchronous)
        agent_response_text = ""

        def _run_agent():
            nonlocal agent_response_text
            try:
                text = ws_agent.invoke_streaming(actual_message, ws_callback)
                agent_response_text = text or ""
                event_queue.put({"type": "complete", "content": text})
            except Exception as e:
                logger.error("WS agent error: %s", e, exc_info=True)
                event_queue.put({"type": "error", "message": str(e)})
            finally:
                event_queue.put(_DONE)

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _run_agent)

        # Stream events from queue to WebSocket
        try:
            while True:
                # Poll queue with timeout to avoid blocking forever
                try:
                    evt = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: event_queue.get(timeout=1.0)
                    )
                except queue.Empty:
                    continue

                if evt is _DONE:
                    break

                await websocket.send_text(_json.dumps(evt))
        except Exception:
            logger.debug("WebSocket disconnected during streaming")
    finally:
        agent_pool.release_session(session_id)

    # Feed STM → LTM pipeline (fire-and-forget, non-blocking)
    if agent_response_text:
        _ingest_to_stm(actor_id, session_id, user_message, agent_response_text)

    # FileSessionManager persists conversation automatically — no manual save.

    try:
        await websocket.close()
    except Exception:
        pass


if __name__ == "__main__":
    app.run()
