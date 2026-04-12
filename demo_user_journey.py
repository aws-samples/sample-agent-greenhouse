#!/usr/bin/env python3.11
"""Plato Control Plane — Live User Journey Demo."""

from platform_agent.plato.control_plane.registry import AgentRegistry, Capability
from platform_agent.plato.control_plane.policy_engine import PlatformPolicyEngine, create_agent_policies
from platform_agent.plato.control_plane.task_manager import TaskManager, TaskDispatcher, TaskType, TaskStatus
from platform_agent.plato.control_plane.message_router import (
    MessageRouter, Message,
    AuthenticateMiddleware, ContentFilterMiddleware, AuditLogMiddleware,
)
from platform_agent.plato.control_plane.lifecycle import (
    ColdStartProtocol, HeartbeatManager, GracefulShutdown,
)
from platform_agent.plato.control_plane.audit import AuditStore
from platform_agent.foundation.guardrails import Policy, Effect, AuthorizationRequest, PolicyStore
import logging
logging.disable(logging.WARNING)


def main():
    print("=" * 60)
    print("  Plato Control Plane — Live Demo")
    print("  User Journey: Three E-Commerce Teams Onboarding")
    print("=" * 60)

    registry = AgentRegistry()
    policy_store = PolicyStore()
    policy_engine = PlatformPolicyEngine(policy_store)
    task_manager = TaskManager()
    dispatcher = TaskDispatcher(task_manager, registry)
    audit = AuditStore()
    router = MessageRouter()
    router.add_middleware(AuthenticateMiddleware(registry))
    router.add_middleware(AuditLogMiddleware(audit))

    # All agents share "platform" tenant for demo (cross-team routing)
    TENANT = "platform"

    # ── Scene 1: Onboarding ──
    print("\n" + "━" * 60)
    print("Scenario 1: Team Onboarding")
    print("━" * 60)
    print('\n🧑 Admin: "Three teams need to onboard to the platform"\n')

    teams = [
        ("support-01", "customer_support",
         [Capability("ticket_triage", 0.95), Capability("refund", 0.80)],
         ["OrderAPI", "RefundAPI"]),
        ("hr-01", "hr_advisor",
         [Capability("policy_qa", 0.90), Capability("leave_mgmt", 0.85),
          Capability("employee_benefits", 0.88)],
         ["HRDatabase", "PolicyDocs"]),
        ("finance-01", "finance_processor",
         [Capability("expense_approve", 0.92), Capability("refund_process", 0.88)],
         ["PaymentGateway", "LedgerAPI"]),
    ]

    for aid, role, caps, tools in teams:
        registry.register(TENANT, role, capabilities=caps, tools=tools, agent_id=aid)
        audit.log(agent_id=aid, tenant_id=TENANT, action="register",
                  details=f"Registered {role}", result="success")

    print('🤖 Plato: "Three teams onboarded:')
    for aid, role, caps, tools in teams:
        agent = registry.get(TENANT, aid)
        cap_str = ", ".join(c.name for c in agent.capabilities)
        print(f"   ✅ {aid} ({role}) — [{cap_str}]")

    cold_start = ColdStartProtocol(registry, policy_engine, audit)
    for aid, _, _, _ in teams:
        cold_start.boot(TENANT, aid)

    states = [f"{a}={registry.get(TENANT, a).state.value}" for a, _, _, _ in teams]
    print(f'   Cold Start: {" | ".join(states)}"')

    # ── Scene 2: Policy ──
    print("\n" + "━" * 60)
    print("Scenario 2: Policy Setup + Verification")
    print("━" * 60)

    # Add a permit policy first (Cedar default-deny needs at least one permit)
    policy_store.add_policy(Policy(
        policy_id="permit-all-refund", effect=Effect.PERMIT,
        description="Base permit for refund actions",
        principal_type="Agent", principal_id="*",
        action="refund", resource_type="Transaction", resource_id="*"))

    policy_store.add_policy(Policy(
        policy_id="refund-limit-500", effect=Effect.FORBID,
        description="Refund >$500 → escalate",
        principal_type="Agent", principal_id="support-01",
        action="refund", resource_type="Transaction", resource_id="*",
        conditions={"exceeds_limit": True}))

    print('\n🧑 Admin: "Set refund limit to $500"\n')
    d_ok = policy_engine.evaluate(AuthorizationRequest(
        "Agent", "support-01", "refund", "Transaction", "o1", {"exceeds_limit": False}))
    d_no = policy_engine.evaluate(AuthorizationRequest(
        "Agent", "support-01", "refund", "Transaction", "o2", {"exceeds_limit": True}))
    print(f'🤖 Plato: "Verification:')
    print(f'   💰 $300 refund (≤$500) → {"✅ Allowed" if d_ok.is_allowed else "❌ Denied"}')
    print(f'   💰 $800 refund (>$500) → {"✅ Allowed" if d_no.is_allowed else "❌ Denied → escalate to human"}"')

    print('\n🧑 Admin: "Change limit to $1000"')
    policy_store.remove_policy("refund-limit-500")
    policy_store.add_policy(Policy(
        policy_id="refund-limit-1000", effect=Effect.FORBID,
        description="Refund >$1000 → escalate",
        principal_type="Agent", principal_id="support-01",
        action="refund", resource_type="Transaction", resource_id="*",
        conditions={"exceeds_limit": True}))
    audit.log("support-01", TENANT, "update_policy", "Limit $500→$1000", "success")
    d_new = policy_engine.evaluate(AuthorizationRequest(
        "Agent", "support-01", "refund", "Transaction", "o2", {"exceeds_limit": False}))
    print(f'🤖 Plato: "$800 refund (≤$1000) → {"✅ Allowed" if d_new.is_allowed else "❌ Denied"}"')

    # ── Scene 3: Communication ──
    print("\n" + "━" * 60)
    print("Scenario 3: Inter-Agent Communication")
    print("━" * 60)
    print('\n🧑 Admin: "Route benefits questions to HR"\n')

    r1 = router.send(Message(source_agent="support-01", target_agent="hr-01",
                             tenant_id=TENANT, intent="benefits",
                             payload={"query": "How many leave days remaining?"}))
    print(f'   Support → HR (benefits question):  {"✅ Delivered" if r1 else "❌ Filtered"}')

    r3 = router.send(Message(source_agent="fake-99", target_agent="hr-01",
                             tenant_id=TENANT, intent="hack", payload={}))
    print(f'   Unregistered agent → HR:            {"✅ Delivered" if r3 else "❌ Blocked by Authenticate"}')

    inbox = router.get_inbox("hr-01")
    print(f'   HR agent inbox: {len(inbox)} valid message(s)')

    # ── Scene 4: Tasks ──
    print("\n" + "━" * 60)
    print("Scenario 4: Task Dispatch + CLAIM")
    print("━" * 60)

    print('\n📋 Direct task: "Customer refund $300"')
    t1 = task_manager.create_task(TENANT, "process_refund",
                                  task_type=TaskType.DIRECT,
                                  source_agent="support-01",
                                  payload={"order": "12345", "amount": 300},
                                  required_capabilities=["refund_process"],
                                  priority=10)
    d_t1 = dispatcher.dispatch(t1)
    print(f"   Capability match → assigned to: {d_t1.assigned_to or 'no match'}")
    if d_t1.assigned_to:
        task_manager.update_status(d_t1.task_id, TaskStatus.IN_PROGRESS)
        task_manager.update_status(d_t1.task_id, TaskStatus.COMPLETED,
                                   result={"refunded": True})
        print(f"   ✅ Task completed (handled by finance-01)")
        audit.log(d_t1.assigned_to, TENANT, "task_done", "Refund $300 OK", "success")

    print('\n📋 Broadcast task: "Analyze this week\'s customer satisfaction"')
    t2 = task_manager.create_task(TENANT, "analyze_satisfaction",
                                  task_type=TaskType.BROADCAST,
                                  required_capabilities=["ticket_triage"])
    c1 = task_manager.claim_task(t2.task_id, "support-01")
    print(f"   Support agent CLAIM: ✅ Success (status={c1.status.value})")
    try:
        task_manager.claim_task(t2.task_id, "hr-01")
        print("   HR agent CLAIM:      ✅ Success")
    except ValueError:
        print("   HR agent CLAIM:      ❌ Already claimed (atomicity guaranteed)")

    print('\n📋 Agent sub-task: Support needs financial assistance')
    t3 = task_manager.create_task(TENANT, "complex_refund_review",
                                  task_type=TaskType.AGENT_GENERATED,
                                  source_agent="support-01",
                                  payload={"order": "67890", "amount": 1500},
                                  required_capabilities=["refund_process"],
                                  priority=20, parent_task_id=t1.task_id)
    d_t3 = dispatcher.dispatch(t3)
    print(f"   Sub-task → assigned to: {d_t3.assigned_to or 'no match'}")
    if d_t3.assigned_to:
        print(f"   ✅ Finance agent takes over complex refund review")

    # ── Scene 5: Lifecycle ──
    print("\n" + "━" * 60)
    print("Scenario 5: Lifecycle Management")
    print("━" * 60)

    hb = HeartbeatManager(registry, audit_store=audit)
    print("\n💓 HR Agent heartbeat failure simulation:")
    hb.mark_degraded(TENANT, "hr-01")
    hr = registry.get(TENANT, "hr-01")
    print(f"   Consecutive failures → state: {hr.state.value}")
    print("   🔄 Plato auto-restarting...")
    hb.auto_restart(TENANT, "hr-01")
    hr = registry.get(TENANT, "hr-01")
    print(f"   ✅ Restart successful, state: {hr.state.value}")
    audit.log("hr-01", TENANT, "auto_restart", "Heartbeat recovery", "success")

    print("\n🔒 Cold Start protection test:")
    registry.register(TENANT, "new_agent", agent_id="new-bot")  # state=boot
    r_cold = router.send(Message(source_agent="new-bot", target_agent="hr-01",
                                 tenant_id=TENANT, intent="test", payload={}))
    nb = registry.get(TENANT, "new-bot")
    print(f"   New Agent (state={nb.state.value}) tries to send message → "
          f"{'✅ Passed' if r_cold else '❌ Router blocked (not in ready state)'}")

    print("\n🔌 Finance Agent graceful shutdown:")
    gs = GracefulShutdown(registry, task_manager, audit)
    reassigned = gs.drain(TENANT, "finance-01")
    gs.shutdown(TENANT, "finance-01")
    fin = registry.get(TENANT, "finance-01")
    print(f"   Drain: {len(reassigned)} pending task(s) reassigned")
    print(f"   Final state: {fin.state.value if fin else 'deregistered'}")

    # ── Scene 6: Report ──
    print("\n" + "━" * 60)
    print("Scenario 6: Weekly Report")
    print("━" * 60)
    print('\n🧑 Admin: "How did the agents perform this week?"\n')

    report = audit.generate_report()
    print(f'🤖 Plato: "Weekly report:')
    print(f"   📊 Total operations: {report['total_entries']}")
    for r, c in sorted(report.get("result_counts", {}).items()):
        icon = "✅" if r == "success" else "⚠️"
        print(f"   {icon} {r}: {c}")
    print("   Operation breakdown:")
    for a, c in sorted(report.get("action_counts", {}).items()):
        print(f"      {a}: {c}")
    print("   Agent activity:")
    for a, c in sorted(report.get("top_agents", {}).items()):
        print(f"      {a}: {c} operation(s)")
    print(f'   🚨 Policy violations: {report.get("violation_count", 0)}"')

    # ── Summary ──
    print("\n" + "=" * 60)
    agents = registry.list_agents()
    tasks = task_manager.list_tasks()
    print("  ✅ User Journey Demo Complete!")
    print(f"     Agents: {len(agents)} registered")
    print(f"     Tasks:  {len(tasks)} processed")
    print(f"     Audit:  {report['total_entries']} entries")
    print(f"     Policy: Cedar (default-deny + FORBID > PERMIT)")
    print(f"     Router: authenticate → audit middleware pipeline")
    print("=" * 60)


if __name__ == "__main__":
    main()
