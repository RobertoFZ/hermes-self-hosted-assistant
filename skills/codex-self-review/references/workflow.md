# Codex Self Review Workflow

Use this workflow for standalone reviews and as the review phase of another
skill such as `auto-pr-workflow`.

## 1. Resolve the review contract

Determine or safely infer:

```text
repository_path
base_revision
review_target
acceptance_criteria
planning_artifacts
required_checks
fix_findings
```

Use `origin/<base-branch>` and its merge base for a branch review. Use the
specified commit parent for a commit review. For uncommitted-only review, keep
the staged, unstaged, and untracked scopes distinct.

Load the repository's canonical agent guidance before reviewing. In Reserhub
Revenue, invoke `$bootstrap` and every focused guidance skill selected by it.

Default `fix_findings` to `false`. A parent workflow may set it to `true` only
when its approval model already authorizes scoped implementation fixes.

## 2. Capture the complete change

For a branch review:

```bash
git fetch origin
MERGE_BASE="$(git merge-base HEAD "origin/${BASE_BRANCH}")"
git status --short --branch
git diff --stat "$MERGE_BASE"
git diff --name-status "$MERGE_BASE"
git diff --check "$MERGE_BASE"
git diff "$MERGE_BASE"
git ls-files --others --exclude-standard
```

`git diff "$MERGE_BASE"` includes committed, staged, and unstaged tracked
changes in the effective tree. It excludes untracked content, so open every
in-scope untracked file separately.

Do not review only the last commit when the requested scope is the complete
branch. Identify unrelated pre-existing changes and exclude them from both the
review result and any fixes.

Record:

- base and merge-base revisions
- reviewed file list and diff stat
- untracked files included
- acceptance criteria and planning artifacts used
- checks already run and their results

## 3. Select review depth

Use a single comprehensive pass when the diff is small, cohesive, and
low-risk. Use focused lanes for a substantial, cross-domain, security-sensitive,
migration-heavy, or contract-changing diff when current policy permits reviewer
subagents.

Focused lanes:

1. **Correctness and repository compliance**
   Trace changed behavior, edge cases, state transitions, regressions, and
   violations of applicable `AGENTS.md` or local guidance.
2. **Tests and acceptance criteria**
   Map requirements and changed branches to behavioral coverage. Flag missing
   tests only when a realistic regression would otherwise go undetected.
3. **Error handling and resilience**
   Inspect exception paths, fallbacks, retries, logging, user-visible errors,
   partial failures, and cleanup.
4. **Contracts and compatibility**
   Inspect types, serializers, APIs, schemas, migrations, stored data,
   backward compatibility, and cross-repository consumers.
5. **Security and data safety**
   Inspect authentication, authorization, capability gating, tenant isolation,
   validation, secrets, injection, unsafe side effects, and data-loss risks.
6. **Maintainability**
   Inspect inaccurate comments, duplication, unnecessary complexity, naming,
   dead code, and simplifications that preserve behavior.

When reviewer lanes are allowed:

- Give each reviewer only the repository path, review contract, complete diff
  scope, applicable guidance, and its assigned lens.
- Require read-only analysis with exact file and line evidence.
- Run independent lanes concurrently only when the active collaboration policy
  permits it; otherwise run them sequentially.
- Have the coordinating agent verify and deduplicate all findings.

When reviewer lanes are not allowed, apply all applicable lenses sequentially
in one Codex review.

## 4. Validate findings

For every candidate finding:

1. Open the surrounding implementation and relevant callers, tests, or schema.
2. Confirm the changed code introduced or exposes the issue.
3. Identify a concrete failure mode or maintenance cost.
4. Confirm repository guidance, tests, or existing behavior does not already
   resolve it.
5. Record the narrowest safe remediation.

Do not report:

- preferences without a repository rule or material consequence
- deterministic formatting or lint issues already covered by required checks
- speculative risks without a reachable failure path
- pre-existing issues outside the reviewed change
- requests to broaden the approved ticket scope

## 5. Classify and report

Use these severities:

| Severity | Meaning | Required action |
|---|---|---|
| Critical | Bug, security issue, data loss, incorrect behavior, unmet acceptance criterion, or unsafe migration | Fix before commit or PR publication |
| Warning | Material coverage, resilience, compatibility, or maintainability concern | Fix when authorized and in scope; otherwise document |
| Informational | Optional improvement with no blocking impact | Document briefly |

Every critical or warning must include:

- severity and confidence
- `path:line`
- concise title
- evidence and failure scenario
- impact
- recommended remediation

Order findings by severity and impact. If no actionable findings remain, state
that explicitly; do not invent observations to fill categories.

## 6. Fix and re-review when authorized

When `fix_findings: true`:

1. Verify each finding before editing.
2. Fix in-scope criticals first, then justified warnings.
3. Keep changes minimal and consistent with approved requirements.
4. Run the affected repository checks.
5. Rebuild the complete effective diff and repeat the applicable review lenses.
6. Stop after three review iterations.

Stop and return control to the caller when:

- a critical remains after three iterations
- a required check fails
- a fix requires a material requirements or planning change
- a finding belongs to unrelated user work
- the base is missing, the diff is incomplete, or a conflict prevents a
  reliable review

Do not commit during this skill. Return the clean reviewed tree to the owning
workflow.

## 7. Return structured metadata

Return:

```text
review_method: codex_self_review
review_mode: report_only | fix_authorized
review_base: <revision>
merge_base: <revision|null>
reviewed_files: [<path>, ...]
review_lenses: [<lens>, ...]
review_iterations: <number>
criticals_found: <number>
criticals_fixed: <number>
warnings_found: <number>
warnings_fixed: <number>
warnings_noted: [<finding>, ...]
informational_noted: [<finding>, ...]
checks_run: [<command and result>, ...]
review_clean: <true|false>
blocking_reason: <null|string>
```

`review_clean` is true only when no critical remains and every required review
scope was inspected. It does not imply that tests passed; report test evidence
separately so the owning workflow can require both conditions.
