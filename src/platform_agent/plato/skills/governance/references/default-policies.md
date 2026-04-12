# Default Cedar Policy Templates

## Table of Contents
- [Role-Based Policies](#role-based-policies)
- [Developer Role](#developer-role)
- [Reviewer Role](#reviewer-role)
- [Admin Role](#admin-role)
- [Monitor Role](#monitor-role)
- [Common Deny Policies](#common-deny-policies)

## Role-Based Policies

Each agent role gets a baseline set of Cedar policies. Use `create_agent_policies(role)`
to generate these automatically.

### Developer Role

```cedar
// Developers can read all files
permit(
  principal == Agent::"*",
  action == Action::"read",
  resource == File::"*"
) when { principal.role == "developer" };

// Developers can write to project files
permit(
  principal == Agent::"*",
  action == Action::"write",
  resource == File::"project/*"
) when { principal.role == "developer" };

// Developers can send messages
permit(
  principal == Agent::"*",
  action == Action::"send_message",
  resource == Message::"*"
) when { principal.role == "developer" };
```

### Reviewer Role

```cedar
// Reviewers can read all files
permit(
  principal == Agent::"*",
  action == Action::"read",
  resource == File::"*"
) when { principal.role == "reviewer" };

// Reviewers can review code
permit(
  principal == Agent::"*",
  action == Action::"review",
  resource == Code::"*"
) when { principal.role == "reviewer" };
```

### Admin Role

```cedar
// Admins inherit all developer permissions plus:

// Admins can manage agents
permit(
  principal == Agent::"*",
  action == Action::"manage",
  resource == Agent::"*"
) when { principal.role == "admin" };

// Admins can manage policies
permit(
  principal == Agent::"*",
  action == Action::"manage",
  resource == Policy::"*"
) when { principal.role == "admin" };
```

### Monitor Role

```cedar
// Monitors can read metrics
permit(
  principal == Agent::"*",
  action == Action::"read",
  resource == Metrics::"*"
) when { principal.role == "monitor" };

// Monitors can read audit logs
permit(
  principal == Agent::"*",
  action == Action::"read",
  resource == AuditLog::"*"
) when { principal.role == "monitor" };
```

## Common Deny Policies

```cedar
// No agent can access secrets
forbid(
  principal == Agent::"*",
  action == Action::"read",
  resource == File::"secrets/*"
);

// Cold start denial: agents must be READY
forbid(
  principal == Agent::"*",
  action == Action::"*",
  resource == Resource::"*"
) when { principal.state != "ready" };

// Cross-boundary denial: tenant isolation
forbid(
  principal == Agent::"*",
  action == Action::"*",
  resource == Resource::"*"
) when { principal.tenant_id != resource.tenant_id };
```
