---
name: auto-pr-workflow
description: Autonomously orchestrate selected Linear tickets from discovery through approved OpenSpec planning, implementation, verified atomic commits, and ready-to-review GitHub PR publication; when separately requested, merge a specific workflow PR and safely clean its feature worktree. Use when Codex is asked for the complete ticket-to-PR workflow, to resume that end-to-end workflow, or to merge and clean a PR produced by it. Use the individual phase skills for partial workflows.
---

# Auto PR Workflow

Read [references/workflow.md](references/workflow.md) completely before executing this workflow.

## Workflow

1. Run the phase-aware dependency preflight from
   [references/workflow.md](references/workflow.md). Stop before reading or
   changing ticket state when a required command, connector, or skill is
   unavailable.
2. Invoke `$linear-ticket-selection` and wait for explicit ticket selection.
3. Invoke `$ticket-openspec-planning` for every selected ticket and wait for
   explicit approval of all implementation plans.
4. Determine ticket dependency order. Use parallel workers only when the active
   collaboration policy permits and the approved plans are independent.
5. In each ticket worktree invoke `$openspec-apply-change`. Implement only the
   approved tasks, keep artifacts current, and do not commit.
6. Invoke `$prepare-branch-for-pr` with
   `commit_authorization: auto-pr-plan-approved`. It owns required checks,
   fix-enabled self-review, atomic commits, final verification, and the
   independent local PR-readiness gate.
7. Invoke `$publish-ready-pr` with
   `publication_authorization: auto-pr-plan-approved` for each Ready Branch
   Bundle. It owns normal push, PR creation/update, metadata verification, and
   the optional Linear review-state update.
8. Report all Published PR Bundles and any failed ticket pipelines.
9. Only after a separate explicit merge request, invoke
   `$merge-pr-and-clean-worktree` for the exact PR and cleanup targets.

## Codex compatibility

- Discover available connector/MCP operations at runtime.
- Require OpenSpec and the named phase skills; do not substitute ad hoc versions
  of missing phases.
- Treat explicit ticket selection plus OpenSpec plan approval as authorization for all scoped commit, normal-push, and PR create/update operations in this workflow. Do not ask again for those operations.
- Do not treat ticket selection, plan approval, or PR creation as merge
  authorization. Merge only after a separate explicit user request identifying
  the PR or an unambiguous feature.
- Use concise commentary checkpoints for non-blocking updates and ask direct questions only when explicit approval or missing information is required.
- Preserve existing worktrees and unrelated user changes.
- Stop on failed tests, unresolved conflicts, or a material deviation from the approved plan.
