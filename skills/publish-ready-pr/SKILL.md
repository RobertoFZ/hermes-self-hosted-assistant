---
name: publish-ready-pr
description: Validate a reviewed Reserhub Revenue Ready Branch Bundle, push its branch normally, create or update the matching GitHub pull request with repository metadata and template conventions, optionally move the linked Linear ticket to review, and return a publication/cleanup bundle. Use when Codex is explicitly asked to publish, create, open, or update a PR for a branch that has already passed local readiness checks.
---

# Publish Ready PR

Publish a verified branch without changing its implementation. Do not merge the
PR or remove its worktree.

## Authorization

Proceed only when:

- the user explicitly asks to publish/create/update the PR, or
- a parent workflow supplies a valid publication authorization such as
  `auto-pr-plan-approved`.

Neither branch readiness nor a prior commit authorizes publication by itself.

## Required input

Consume a Ready Branch Bundle from `$prepare-branch-for-pr` plus:

- ticket ID, title, URL, and one label when linked to Linear
- repository owner/name and PR base branch
- PR title and body/template context
- optional OpenSpec change and artifact paths

## Freshness gate

Before any write:

1. Invoke `$bootstrap` and the matching `$repo-git-workflow-guidance`.
2. Confirm the current branch and worktree match the bundle.
3. Require current HEAD to equal `pre_pr_review.reviewed_head`.
4. Require a clean working tree with no unintended files.
5. Require all mandatory checks to have passed.
6. Require a clean self-review and a current `READY_FOR_PR` or
   `READY_WITH_COMMENTS` local-review verdict.
7. Confirm the branch is not a protected base branch.

If any evidence is missing or stale, stop and send the branch back through
`$prepare-branch-for-pr`.

## Publication workflow

1. Derive repository-conformant metadata:
   - branch: `{ISSUE-ID}-english-hyphenated-slug`
   - PR title: `[{ISSUE-ID}] English description`
   - PR label: the ticket's single `Feature`, `Bug`, `Refactor`, or `Task` label
   - PR body: matching repository template with the Linear URL
2. Discover whether the branch already has a PR.
3. Confirm the required GitHub label exists; stop if it does not.
4. Push the branch normally. Never force-push.
5. Create or update the PR with `gh`, apply the title, base, body, label, and
   `--assignee @me`.
6. Verify the resulting PR URL, head SHA, base, assignee, label, and open state
   using `gh pr view`.
7. When a Linear connector supports updates and a ticket is linked, move it to
   the team's review state only after the GitHub write succeeds.

## Output contract

Return a Published PR Bundle:

```yaml
ticket_id: ENG-123
ticket_url: https://linear.app/example/issue/ENG-123
repository_path: /abs/path/to/repository
worktree_path: /abs/path/to/worktree
base_branch: develop
branch_name: ENG-123-login-redirect-mobile
published_head: def5678
commit_shas:
  - def5678
pr:
  number: 123
  url: https://github.com/example/repository/pull/123
  state: OPEN
  title: "[ENG-123] Fix login redirect on mobile"
  label: Bug
  assignee_verified: true
linear_review_state_updated: true
cleanup_targets:
  - owning_repo_root: /abs/path/to/repository
    worktree_path: /abs/path/to/worktree
    branch_name: ENG-123-login-redirect-mobile
    associated_pr_url: https://github.com/example/repository/pull/123
    published_head: def5678
```

Preserve the Ready Branch Bundle's checks and both review summaries in the
handoff.

## Guardrails

- Stop when a required check was skipped or could not run.
- Stop on stale review evidence, a dirty tree, or unexpected HEAD.
- Never force-push after divergence; report the rejection.
- Never silently create a missing repository label.
- Stop and preserve the branch if PR creation or update fails.
- Never merge or clean worktrees.
