---
name: ticket-openspec-planning
description: Turn one or more selected Reserhub Revenue Linear tickets into implementation-ready OpenSpec plans inside correctly scoped isolated worktrees, without editing implementation code. Use when Codex is asked to analyze a ticket, explore affected code, create a ticket worktree, draft an OpenSpec proposal/design/spec/tasks set, assess implementation risk, or prepare a plan for approval without running the full Auto-PR workflow.
---

# Ticket OpenSpec Planning

Convert selected ticket intent into an approved, apply-ready OpenSpec Planning
Bundle. Planning artifacts and the worktree may be created, but implementation
code must remain untouched.

## Inputs

Accept exact Linear issue IDs or Ticket Selection Bundles from
`$linear-ticket-selection`. For each ticket require:

- ticket ID and URL
- title and assigned label
- full description and acceptance criteria
- relevant comments and parent/sub-issue relationships

Fetch missing or potentially stale ticket fields from Linear before planning.

## Workflow

1. Invoke the repository `$bootstrap` skill and load the matching scope and git
   guidance.
2. Read the full ticket. If its product intent or acceptance criteria are too
   incomplete to design safely, stop and request the missing information.
3. Explore the repository with `rg`, `rg --files`, targeted file reads, and
   read-only git commands. Identify:
   - affected repository and base branch
   - likely implementation locations
   - existing architectural patterns
   - current unit, integration, and E2E coverage
   - migrations, compatibility risks, or cross-repository effects
4. Derive an English branch name in `{ISSUE-ID}-hyphenated-slug` form and a
   lowercase OpenSpec change name such as `eng-123-hyphenated-slug`.
5. Create or reuse an isolated worktree from the scope's correct remote base.
   Before reusing one, verify its registration, branch, and status. Stop and ask
   whether to resume if it contains existing changes.
6. Inside that worktree invoke `$openspec-propose` with the ticket context,
   discovered code locations, repository guidance, and test coverage.
7. Use the OpenSpec status output's exact `planningHome`, `changeRoot`,
   `artifactPaths`, `applyRequires`, and `actionContext`. Never assume paths.
8. Verify all apply-required artifacts exist and the change is apply-ready.
9. Present the complete plan and ask explicitly whether it should be approved
   for implementation.

## Plan quality

Ensure the artifacts:

- map every acceptance criterion to requirements and implementation tasks
- identify affected specs and likely code locations
- separate unit, integration, and E2E verification
- record edge cases, failure paths, migrations, compatibility, and risks
- mark breaking changes explicitly
- avoid unrelated refactoring and mixed ticket concerns

## Output contract

Return an OpenSpec Planning Bundle:

```yaml
ticket_id: ENG-123
ticket_url: https://linear.app/example/issue/ENG-123
label: Bug
repository_path: /abs/path/to/repository
base_branch: develop
branch_name: ENG-123-login-redirect-mobile
worktree_path: /abs/path/to/worktree
openspec_change: eng-123-login-redirect-mobile
planning_home: /abs/path/to/planning/home
change_root: /abs/path/to/change
artifact_paths:
  proposal: /abs/path/to/proposal.md
  design: /abs/path/to/design.md
  tasks: /abs/path/to/tasks.md
apply_ready: true
plan_approved: true
```

Include a concise proposal/design summary, affected areas, task groups, test
strategy, breaking changes, edge cases, and risk assessment.

## Authorization boundary

Standalone plan approval authorizes proceeding to implementation only. It does
not by itself authorize commits, pushes, PR creation, or merge. A parent
workflow may define broader authorization explicitly; record that context in
the handoff rather than changing this skill's default.

## Guardrails

- Do not edit implementation code.
- Stop if OpenSpec is unavailable, resolves outside the intended worktree, or
  reports an incompatible action context.
- Do not overwrite or clean a dirty worktree.
- Do not continue an existing OpenSpec change without user confirmation.
- Stop for a material scope ambiguity or a required cross-ticket split.
