---
name: merge-pr-and-clean-worktree
description: Resolve one explicitly identified Reserhub Revenue GitHub PR, run repository-specific merge readiness, merge only after all gates pass, confirm the merged state, and safely remove only its exact clean registered feature worktree through the repository cleanup skill. Use when Codex is explicitly asked to merge a PR and optionally clean its local worktree, whether or not the PR was created by Auto-PR.
---

# Merge PR and Clean Worktree

Merge one exact PR and clean only its verified feature worktree. This skill is
never implied by ticket selection, plan approval, commits, push, or PR creation.

## Authorization and inputs

Require a separate explicit merge request identifying a PR number/URL or an
unambiguous feature PR. If multiple PRs could match, ask which one.

Accept a Published PR Bundle when available. Otherwise resolve:

- owning repository and PR
- head and base branches
- current PR head SHA
- matching registered feature worktree, if any

Do not infer a worktree from its directory name. Match the PR head branch
against `git worktree list --porcelain`.

## Merge readiness

1. Invoke `$bootstrap`, `$repo-git-workflow-guidance`, and the matching
   repository merge-readiness guidance.
2. Resolve the exact PR with `gh pr view`.
3. Fetch and triage unresolved review threads.
4. Keep the feature branch checked out in its worktree and update it against
   the correct base using the documented repository flow.
5. Run every required validation and wait for GitHub checks.
6. Stop for unresolved review direction, failed or skipped validation,
   conflicts, branch protection failures, or any other merge blocker.
7. Re-query the PR head SHA after all gates. If it changed, restart readiness
   against the new head.
8. Run the repository-approved `gh pr merge` flow, binding it to the verified
   head with `--match-head-commit` when supported.
9. Re-query GitHub and require a merged state and non-null `mergedAt`.

For coordinated PRs, require the user to identify the set and merge them only in
their verified dependency order. Confirm each merge independently.

## Safe cleanup

Begin cleanup only after GitHub confirms the associated PR merged.

1. Invoke `$cleaning-worktrees` from the stable monorepo primary checkout.
2. For each exact cleanup target:
   - require an absolute, narrow path
   - reject `/`, home directories, workspace roots, and primary checkouts
   - confirm registration in the owning repository
   - inspect `git status --short --branch`
   - require the worktree to be clean and represented by the verified published
     head
   - confirm the target belongs to the merged PR
3. Run `worktree-remove-safe <path>`. Use the repository's documented safe
   wrapper fallback only when the alias is unavailable.
4. Verify the path is no longer registered and no longer exists.

If no matching worktree exists, report that no local cleanup was needed. Do not
delete the local branch.

## Output contract

Return:

```yaml
pr_url: https://github.com/example/repository/pull/123
verified_head: def5678
merged: true
merged_at: 2026-07-30T12:00:00Z
cleanup:
  - worktree_path: /abs/path/to/worktree
    status: removed
    recoverable_from_git: true
```

Report every removed, skipped, or failed cleanup target. If cleanup fails after
merge, state clearly that the PR merged and local cleanup remains incomplete.

## Guardrails

- Never merge without a distinct explicit merge request.
- Never auto-resolve rebase conflicts.
- Never clean before GitHub confirms the merge.
- Never use `rm -rf` or raw `git worktree remove`.
- Never remove a dirty, ambiguous, unpublished, or unregistered worktree.
- Never fall back to broad pruning unless separately requested.
