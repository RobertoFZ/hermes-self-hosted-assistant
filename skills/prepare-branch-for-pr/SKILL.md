---
name: prepare-branch-for-pr
description: Take a completed Reserhub Revenue implementation branch through required checks, fix-enabled Codex self-review, cohesive atomic commits, final diff verification, and an independent read-only local PR-readiness review. Use when Codex is asked to prepare, finalize, verify, or make a local branch ready for pull-request publication, with or without Linear or OpenSpec, but not to push or create the PR.
---

# Prepare Branch for PR

Produce a verified Ready Branch Bundle. Do not push, create/update a PR, merge,
or remove worktrees.

## Inputs

Resolve or receive:

- repository and worktree path
- correct base branch
- implementation intent or acceptance criteria
- optional OpenSpec artifact paths and task status
- repository-required validation commands
- commit authorization source

An Auto-PR caller may pass `commit_authorization: auto-pr-plan-approved`. A
standalone invocation must follow the repository's normal commit permission
policy.

## Workflow

1. Invoke `$bootstrap` and load the matching implementation, test, and git
   guidance for the resolved repository scope.
2. Inspect the complete effective change against the merge base, including
   committed branch changes, staged and unstaged files, and in-scope untracked
   files. Exclude unrelated user changes.
3. If OpenSpec artifacts are supplied, confirm required tasks are complete and
   accurately checked off. Otherwise use the stated acceptance criteria as the
   review contract.
4. Run every repository-required focused validation. Record exact commands,
   results, and any skipped checks. A required check may not be skipped.
5. Invoke `$codex-self-review` with `fix_findings: true` over the complete
   effective change. Supply the base revision, intent, optional planning
   artifacts, and validation evidence.
6. Validate and apply in-scope review fixes, rerun affected checks, and repeat
   self-review for at most three iterations. Stop for unresolved criticals or a
   material scope deviation.
7. Before committing, establish authorization:
   - accept a valid Auto-PR authorization passed by its parent workflow
   - accept explicit standalone user authorization to commit this scoped change
   - otherwise present the proposed atomic commit partition and ask permission
8. Create cohesive atomic commits under the active repository conventions:
   - keep behavior with the tests needed to validate it
   - keep migrations with their required model/schema changes
   - keep one OpenSpec artifact set coherent with the implementation state
   - separate independently meaningful docs, tooling, or refactors
   - prefer one commit for a small inseparable change
   - never stage unrelated files
9. Verify the committed result:

```bash
git status --short --branch
git diff --check "$MERGE_BASE"..HEAD
git diff --stat "$MERGE_BASE"..HEAD
git diff --name-status "$MERGE_BASE"..HEAD
git log --oneline "$MERGE_BASE"..HEAD
```

10. If hooks or later edits changed the reviewed tree, rerun affected checks and
    `$codex-self-review`, then create an authorized follow-up atomic commit.
11. Invoke `$pr-reviewer` explicitly in read-only `local_pre_pr` mode without
    sharing the self-review's findings or conclusions. Supply the repository
    and worktree paths, base branch, acceptance criteria, planning artifacts,
    and required-check evidence. Require its structured `pre_pr_review`
    handoff and verify that `reviewed_head` equals the stable snapshot's HEAD.
12. Treat `READY_FOR_PR` and `READY_WITH_COMMENTS` as passing. For `NOT_READY`,
    validate and fix in-scope blockers, rerun checks and self-review, create an
    authorized follow-up commit, and repeat final verification and local review
    for at most three iterations.

Discard a local-review verdict if HEAD or working-tree state changes while the
review is running.

## Output contract

Return a Ready Branch Bundle:

```yaml
repository_path: /abs/path/to/repository
worktree_path: /abs/path/to/worktree
base_branch: develop
branch_name: ENG-123-login-redirect-mobile
merge_base: abc1234
reviewed_files: []
checks:
  - command: repository-specific command
    passed: true
self_review:
  iterations: 1
  criticals_remaining: 0
  clean: true
commit_shas:
  - def5678
pre_pr_review:
  verdict: READY_FOR_PR
  iterations: 1
  reviewed_head: def5678
  blocking_findings: 0
  non_blocking_findings: []
working_tree_clean: true
ready_for_publication: true
```

Include the final diff stat and any non-blocking reviewer comments.

## Guardrails

- Stop on failed or skipped required checks.
- Stop if a critical finding persists after three self-review iterations.
- Stop if `NOT_READY` persists after three local-review iterations.
- Do not infer standalone commit authorization from a request that only asks
  for review or diagnosis.
- Never push, force-push, create a PR, merge, or clean a worktree.
