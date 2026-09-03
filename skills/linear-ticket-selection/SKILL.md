---
name: linear-ticket-selection
description: Discover, filter, classify, and select actionable Reserhub Revenue Linear tickets without starting implementation. Use when Codex is asked to list assigned or active Linear work, find tickets without completed PRs, choose the next issue, inspect ticket/PR status, or produce a normalized ticket bundle for another workflow.
---

# Linear Ticket Selection

Produce a read-only, normalized selection of actionable Linear tickets. Do not
create branches, worktrees, plans, commits, or PRs.

## Workflow

1. Discover the configured Linear connector operations at runtime.
2. Query issues assigned to the current user unless the request names another
   assignee or exact issue IDs.
3. Exclude issues whose state type is `completed`, `cancelled`, or `duplicate`.
4. Inspect GitHub PR attachments:
   - Include tickets with no PR.
   - Include tickets with an open PR and mark them as resumable.
   - Exclude tickets whose attached PR is merged or closed.
5. Fetch enough issue detail to report the title, priority, state, label, URL,
   and attached PR state accurately.
6. Present eligible tickets in a compact table and ask which tickets to select.
   Treat exact IDs already supplied by the user or caller as an explicit
   selection and do not ask again.

## Label rules

Use exactly one of `Feature`, `Bug`, `Refactor`, or `Task`.

- `Feature`: adds user-visible behavior.
- `Bug`: corrects behavior that is broken or differs from expectations.
- `Refactor`: improves internals without intentionally changing behavior.
- `Task`: configuration, dependencies, documentation, tooling, or other work.

Do not silently assign a missing label. Infer the likely label, explain the
reason briefly, and ask the user to confirm it. Sub-issues inherit the parent's
label; do not relabel a Feature child as Task.

## Output contract

Return a Ticket Selection Bundle for every selected issue:

```yaml
ticket_id: ENG-123
title: Fix login redirect on mobile
url: https://linear.app/example/issue/ENG-123
state: In Progress
priority: Urgent
label: Bug
description_present: true
pr:
  status: none
  url: null
selection_explicit: true
```

Include the full description, acceptance criteria, comments, and relationships
only when requested by the caller. The planning skill fetches those fields
again to avoid relying on stale or partial ticket context.

## Guardrails

- Remain read-only in Linear, GitHub, and the repository.
- Do not treat an open PR as completed work.
- Do not select merged or closed-PR tickets for new implementation.
- Do not guess when connector results are incomplete; report the missing field.
- If no eligible tickets remain, show the applied filters and stop.
