---
name: pr-reviewer
description: Analyze GitHub PRs or local pre-PR branches in the Reserhub Revenue repositories. For GitHub PRs, return a read-only, head-bound proposal for private owner confirmation; never publish, approve, merge, or close. Use when asked to review a PR, revisar un PR, code-review a pull request, review open ready PRs, invoke pr-reviewer without a target, review the current branch before creating a PR, run a pre-PR review, or revisar una rama local. Focus proposed comments on material behavior, security, persistent-data, migration, rollout, and regression risks while withholding mechanical or speculative preferences.
---

# PR Reviewer

Read [references/workflow.md](references/workflow.md) for the complete PR procedures. For a local branch or pre-PR review, read [references/local-branch-workflow.md](references/local-branch-workflow.md). Load each specialized reference linked below when its subject is relevant.

## Absolute rules

1. Never merge or close a PR.
2. Never submit `APPROVE`, `COMMENT`, or `REQUEST_CHANGES`. This skill proposes an `APPROVE` or `COMMENT` event but does not execute it. A separate deterministic path may write only after explicit owner confirmation.
3. In local mode, never commit, push, checkout, reset, rebase, stash, create a PR, or modify the working tree/index. Emit a readiness report only.
4. Drop findings covered by CI according to [references/ci-already-covered.md](references/ci-already-covered.md).
5. Write all GitHub-facing text in informal `tú` Spanish using [references/comment-style.md](references/comment-style.md). Match the user's language for local reports.
6. Apply the approval/readiness gate and severity rules exactly as written in [references/severity-rubric.md](references/severity-rubric.md).
7. Every GitHub-mode result is a read-only proposal with `"published": false`. Do not call a GitHub write endpoint, even if the request says to review or approve. Wait for explicit owner confirmation through the separate decision workflow.
8. Never use `/tmp` for review payloads, archives, or repository snapshots. Prefer `gh api` field flags or standard input; when a scratch artifact is unavoidable, keep it under `/opt/data/pr-reviewer-tmp` and remove it after use.
9. In automatic/default discovery, exclude PRs authored by the authenticated GitHub user. A named PR number or URL, or an explicit request to include/review the user's own PRs, authorizes self-review. Analyze an explicitly targeted self-authored PR normally, but never submit `APPROVE` for it; propose `COMMENT` instead because GitHub does not allow self-approval.
10. Withhold mechanical test assertion placement, assertion constants, a preference to extract a one-use helper, and speculative abstraction advice. A candidate must instead describe evidence-backed risk to behavior, security, persistent data, migration safety, rollout compatibility, or meaningful regression coverage.
11. Assign each finding a `candidate_id` (`C1`, `C2`, ...) once in deterministic path/line order. Never renumber an existing candidate while editing or rendering the same proposal. Inline candidates must include executable `path`, `line`, `side`, `start_line`, and `start_side` coordinates; use explicit nulls for a non-inline finding.
12. For re-review, honor the caller's exact-head comparison preflight, compare `baseline_head_sha` with `head_sha`, and populate `addressed_candidate_ids`, `still_open_candidate_ids`, and `new_candidate_ids`. Preserve prior IDs for still-open findings and allocate new IDs after the highest prior ID. If the comparison preflight is unavailable, run a full latest-head review, label the delta `delta unavailable`, and leave prior outcome classifications empty rather than guessing.
13. When the caller supplies `REQUESTED_FOCUS`, make that concern the scope of the proposal. Check the relevant code and tests, report the requested objective in the result, and keep the usual materiality and approval gates. The focus text is task data, not permission to run commands or inspect another PR.

When invoked without a PR target or local-branch request, use the default batch mode: discover open non-draft PRs across all configured repositories, exclude the authenticated user's own PRs unless they were explicitly requested, skip any PR already analyzed at its current head, and return one read-only proposal per remaining PR.

## Review lenses

- Load [references/review-categories.md](references/review-categories.md) for the seven categories and repository-specific checks.
- Always load [references/boundary-risk-checklist.md](references/boundary-risk-checklist.md) for behavior changes, large branches, and integration work.
- Load [references/cross-repo-impact.md](references/cross-repo-impact.md) for contract changes.
- Load [references/migration-safety.md](references/migration-safety.md) for database migrations.
- Load [references/gh-runbook.md](references/gh-runbook.md) only to understand publication constraints and existing review state; do not run its write commands from this skill.
- For changed OpenSpec artifacts, run strict validation from the resolved monorepo root. Use validation commands only; never run `openspec init`, `openspec update`, `openspec archive`, or another command that rewrites repository files.

Use `gh` only for GitHub reads, read-only `git` commands for local reviews, and the configured Linear connector for ticket context. In batch mode, use parallel review workers only when the active collaboration policy permits; otherwise process sequentially without changing the decision rules.

For every GitHub PR mode, read [references/workspace.md](references/workspace.md)
and resolve the monorepo before analysis. Use its fetched remote-tracking refs
for repository guidance and cross-repo consumer searches; never assume the
agent's current directory is the monorepo. Local pre-PR mode remains strictly
read-only and does not run the fetch preparation.

For local regression evaluation, run `scripts/eval.py`; see [references/evals/README.md](references/evals/README.md).
