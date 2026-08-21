---
name: pr-reviewer
description: Review GitHub PRs or local pre-PR branches in the Reserhub Revenue repositories. By default, discover every open non-draft PR across the configured repositories, identify PRs that need review, review them, and publish APPROVE or COMMENT automatically; use a named PR when provided and suppress publication only for an explicit dry-run or no-publish request. Use when asked to review a PR, revisar un PR, code-review a pull request, review open ready PRs, invoke pr-reviewer without a target, review the current branch before creating a PR, run a pre-PR review, or revisar una rama local. Review logic, security, architecture, tests, migrations, failure paths, and cross-repo effects while deferring CI-covered issues; keep local reviews read-only, write GitHub feedback in informal tú Spanish, approve at most, and never merge.
---

# PR Reviewer

Read [references/workflow.md](references/workflow.md) for the complete PR procedures. For a local branch or pre-PR review, read [references/local-branch-workflow.md](references/local-branch-workflow.md). Load each specialized reference linked below when its subject is relevant.

## Absolute rules

1. Never merge or close a PR.
2. Never submit `REQUEST_CHANGES`; use only `APPROVE` or `COMMENT`.
3. In local mode, never commit, push, checkout, reset, rebase, stash, create a PR, or modify the working tree/index. Emit a readiness report only.
4. Drop findings covered by CI according to [references/ci-already-covered.md](references/ci-already-covered.md).
5. Write all GitHub-facing text in informal `tú` Spanish using [references/comment-style.md](references/comment-style.md). Match the user's language for local reports.
6. Apply the approval/readiness gate and severity rules exactly as written in [references/severity-rubric.md](references/severity-rubric.md).
7. Publish GitHub reviews immediately after analysis without asking for confirmation. Suppress publication only when the user explicitly requests dry-run, `no publiques`, or equivalent.
8. Never use `/tmp` for review payloads, archives, or repository snapshots. Prefer `gh api` field flags or standard input; when a scratch artifact is unavoidable, keep it under `/opt/data/pr-reviewer-tmp` and remove it after use.

When invoked without a PR target or local-branch request, use the default batch mode: discover open non-draft PRs across all configured repositories, exclude the authenticated user's own PRs, skip any PR already reviewed at its current head, review the remaining PRs, and publish each result automatically.

## Review lenses

- Load [references/review-categories.md](references/review-categories.md) for the seven categories and repository-specific checks.
- Always load [references/boundary-risk-checklist.md](references/boundary-risk-checklist.md) for behavior changes, large branches, and integration work.
- Load [references/cross-repo-impact.md](references/cross-repo-impact.md) for contract changes.
- Load [references/migration-safety.md](references/migration-safety.md) for database migrations.
- Load [references/gh-runbook.md](references/gh-runbook.md) before submitting any review.

Use `gh` for GitHub PR reads and writes, read-only `git` commands for local reviews, and the configured Linear connector for ticket context. In batch mode, use parallel review workers only when the active collaboration policy permits; otherwise process sequentially without changing the decision rules.

For every GitHub PR mode, read [references/workspace.md](references/workspace.md)
and resolve the monorepo before analysis. Use its fetched remote-tracking refs
for repository guidance and cross-repo consumer searches; never assume the
agent's current directory is the monorepo. Local pre-PR mode remains strictly
read-only and does not run the fetch preparation.

For local regression evaluation, run `scripts/eval.py`; see [references/evals/README.md](references/evals/README.md).
