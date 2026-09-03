---
name: codex-self-review
description: Review a complete branch, commit, or working-tree diff directly with Codex before commit or pull-request publication, without an external review CLI. Use for pre-PR self-review, Auto-PR review phases, branch-diff audits, test-gap checks, security and error-handling review, or targeted re-review after fixes.
---

# Codex Self Review

Read [references/workflow.md](references/workflow.md) completely before running
the review.

## Procedure

1. Resolve the repository, worktree, base revision, review scope, acceptance
   criteria, active repository guidance, and whether fixes are authorized.
2. Build the complete effective diff, including committed, staged, unstaged,
   and untracked files in scope.
3. Review the diff through the required lenses:
   - correctness and repository rules
   - tests and acceptance criteria
   - error handling and resilience
   - types, APIs, schemas, migrations, and compatibility
   - security, authorization, tenant isolation, and data safety
   - comments, maintainability, and simplification
4. Validate each candidate finding against the surrounding code and report only
   actionable, evidenced issues.
5. Classify findings as critical, warning, or informational and return the
   structured review summary.
6. In report-only mode, do not edit files. When fixes are explicitly authorized,
   fix in-scope criticals and justified warnings, run affected checks, and
   repeat the review for at most three iterations.

## Execution model

- Use one comprehensive Codex pass for small, cohesive diffs.
- For substantial or high-risk diffs, use focused reviewer lanes when the
  active collaboration and repository policies permit them. Otherwise apply
  the same lenses sequentially in the main agent.
- Keep review lanes read-only. Only the coordinating agent applies authorized
  fixes after validating the findings.
- Do not depend on Claude Code or another external review executable.

## Guardrails

- Default standalone review requests to `report-only`.
- Treat fixes as authorized only when the user explicitly requests them or a
  caller supplies `fix_findings: true` under an already approved workflow.
- Never commit, push, create a PR, force-push, or merge unless a separate
  authorized workflow owns that action.
- Never hide unresolved criticals, failed checks, incomplete scope, or material
  deviations from approved requirements.
- Preserve unrelated user changes and exclude them from fixes.
