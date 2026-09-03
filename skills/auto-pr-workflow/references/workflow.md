# Auto-PR Workflow Orchestrator

Auto-PR composes reusable phase skills:

`linear-ticket-selection` → `ticket-openspec-planning` →
`openspec-apply-change` → `prepare-branch-for-pr` → `publish-ready-pr` →
`[separate explicit request] merge-pr-and-clean-worktree`

Read every invoked skill completely before executing its phase. Treat the
phase's output bundle as the next phase's input contract.

## Phase-aware dependency preflight

Before ticket discovery, verify the ticket-to-PR path can resolve:

- `$linear-ticket-selection`, `$ticket-openspec-planning`,
  `$openspec-propose`, `$openspec-apply-change`, `$prepare-branch-for-pr`,
  `$codex-self-review`, `$pr-reviewer`, and `$publish-ready-pr`
- the target repository's `$bootstrap` and `$repo-git-workflow-guidance`
- authenticated read access to Linear and GitHub
- the `git`, `gh`, and `openspec` commands

Use read-only capability and authentication checks. Stop and list every missing
dependency before reading or changing ticket state, creating a worktree, or
writing an OpenSpec artifact. Do not substitute an ad hoc phase.

The merge path is optional during ticket-to-PR execution. Only after a separate
explicit merge request, verify `$merge-pr-and-clean-worktree`,
`$cleaning-worktrees`, repository merge-readiness guidance, and GitHub write
access before entering Phase 6.

## Authorization model

Auto-PR has three authorization gates:

1. **Ticket selection:** required before ticket planning.
2. **OpenSpec plan approval:** required before implementation. Within Auto-PR,
   explicit ticket selection plus explicit plan approval authorizes scoped
   atomic commits, normal push, and matching PR creation/update.
3. **Merge request:** always separate and explicit for one exact or unambiguous
   PR. The first two gates never authorize merge or cleanup.

When a phase skill is invoked outside Auto-PR, its standalone authorization
rules apply. Do not export Auto-PR's broader authorization to an unrelated
workflow.

## Phase 1 — Select actionable tickets

Invoke `$linear-ticket-selection`.

Require one or more Ticket Selection Bundles with:

- exact ticket ID, title, URL, priority, state, and label
- no merged or closed attached PR
- explicit selection

Stop when no eligible ticket exists, required Linear data is unavailable, or a
missing label cannot be confirmed.

**Checkpoint 1:** Ask which eligible tickets to proceed with unless the user
already supplied exact IDs.

## Phase 2 — Create and approve OpenSpec plans

Invoke `$ticket-openspec-planning` for every selected ticket.

The phase owns:

- full ticket and acceptance-criteria retrieval
- repository exploration
- scope and base-branch resolution
- isolated ticket worktree creation/reuse
- `$openspec-propose`
- apply-readiness validation
- plan presentation

Require an OpenSpec Planning Bundle for each ticket. Verify its worktree,
planning paths, and action context all resolve inside the intended ticket
scope.

**Checkpoint 2:** Present all ticket plans together and ask whether to implement
them. Do not edit implementation code before explicit approval.

Record the approval as:

```yaml
authorization:
  source: auto-pr-workflow
  tickets_selected: true
  openspec_plans_approved: true
  scoped_commits_authorized: true
  normal_push_authorized: true
  pr_create_or_update_authorized: true
  merge_authorized: false
```

## Phase 3 — Apply approved changes

Determine ticket dependency order from the approved OpenSpec tasks.

Tickets are independent only when:

- their approved file paths do not overlap
- they belong to different domain areas
- neither depends on the other's changes

Use parallel workers only when the active collaboration policy permits. If
dependency or overlap is uncertain, process sequentially and report the
uncertainty. For dependent tickets, complete the prerequisite first and update
the dependent worktree using the repository's approved git flow.

For each ticket:

1. Enter its exact worktree.
2. Announce the OpenSpec change name.
3. Invoke `$openspec-apply-change`.
4. Implement only approved tasks and mark task state immediately.
5. Keep implementation and artifacts current.
6. Do not commit during apply.

Stop that ticket's pipeline when:

- a task or product requirement is ambiguous
- implementation requires a material plan change
- OpenSpec blocks apply or reports incompatible scope
- required tasks remain incomplete without approved partial delivery

Other independent ticket pipelines may continue.

## Phase 4 — Prepare each branch for PR

Invoke `$prepare-branch-for-pr` with:

```yaml
repository_path: <ticket worktree repository>
worktree_path: <ticket worktree>
base_branch: <resolved base>
acceptance_criteria: <Linear criteria>
planning_artifacts: <OpenSpec artifact paths>
required_checks: <commands required by repository guidance>
commit_authorization: auto-pr-plan-approved
```

That skill owns:

- repository-required checks
- `$codex-self-review` with in-scope fixes
- autonomous cohesive atomic commits
- final committed-diff verification
- `$pr-reviewer` in independent read-only local mode
- up to three validated remediation iterations

Do not leak self-review findings or conclusions into the independent PR
reviewer. Require a Ready Branch Bundle whose current reviewed head matches
HEAD, mandatory checks passed, the worktree is clean, and the verdict is
`READY_FOR_PR` or `READY_WITH_COMMENTS`.

Stop publication for a ticket on failed/skipped required checks, unresolved
critical findings, persistent `NOT_READY`, stale review evidence, or material
scope deviation.

## Phase 5 — Publish ready PRs

Invoke `$publish-ready-pr` for every Ready Branch Bundle with:

```yaml
publication_authorization: auto-pr-plan-approved
ticket_id: <Linear ID>
ticket_title: <Linear title>
ticket_url: <Linear URL>
linear_label: <Feature|Bug|Refactor|Task>
openspec_change: <change name>
openspec_artifacts: <resolved paths>
ready_branch_bundle: <phase 4 output>
```

The publication skill owns:

- freshness validation
- normal push without force
- direct `gh` PR creation or update
- repository template, title, ticket link, label, and assignee
- verification of the resulting GitHub metadata
- optional Linear transition to the team's review state
- exact cleanup-target recording

Require a Published PR Bundle. Preserve it for later merge/cleanup because its
`cleanup_targets` bind the PR, branch, published head, owning repository, and
registered worktree.

## Unified result

After every selected ticket completes or stops, report:

| Ticket | Plan | Implementation | Readiness | Publication | Detail |
| --- | --- | --- | --- | --- | --- |
| ENG-123 | approved | complete | READY_FOR_PR | PR #123 | checks passed |
| ENG-200 | approved | stopped | not reviewed | not published | failing test |

Include:

- OpenSpec change and task state
- exact test commands and results
- self-review iteration count
- local PR-review verdict and non-blocking comments
- atomic commit SHAs
- PR URLs and metadata verification
- recorded cleanup targets

Do not publish failed ticket pipelines. Report the blocker and wait for
direction while preserving their worktrees and branches.

## Phase 6 — Explicit merge and cleanup

Enter only after a separate explicit user request for an exact or unambiguous
PR.

Invoke `$merge-pr-and-clean-worktree` with the matching Published PR Bundle.
That skill owns repository merge readiness, verified-head merge, GitHub merged
state confirmation, and safe worktree cleanup through `$cleaning-worktrees`.

For multiple coordinated PRs, resolve and verify their dependency order before
merging. A failed or unconfirmed merge never authorizes cleanup.

## Resume behavior

When resuming:

1. Rediscover the ticket and linked PR state.
2. Inspect the registered worktree and its effective git state.
3. Read current OpenSpec status dynamically.
4. Reconstruct the latest valid bundle from source evidence.
5. Resume from the earliest phase whose output is missing or stale.

Never trust a saved readiness or publication bundle when HEAD, worktree state,
ticket scope, OpenSpec artifacts, required checks, or GitHub PR state changed.

## Error handling

| Situation | Action |
| --- | --- |
| Linear returns no eligible issues | Report filters and stop |
| Ticket lacks product context | Ask for context before planning |
| Ticket lacks a label | Infer and request confirmation |
| Dirty existing worktree | Ask whether to resume; never overwrite |
| OpenSpec unavailable or out of scope | Stop; do not substitute an ad hoc plan |
| Apply requires a material plan change | Stop and request plan re-approval |
| Required check fails or is skipped | Stop that ticket before publication |
| Self-review critical persists | Stop before commit/publication |
| Local reviewer remains `NOT_READY` | Stop after its bounded remediation loop |
| Review bundle is stale | Repeat preparation against current state |
| Push is rejected or diverged | Stop; never force-push |
| PR write fails | Preserve branch and report the exact failure |
| Merge request is ambiguous | Ask for the exact PR |
| Merge conflicts or readiness fails | Stop; do not auto-resolve or clean |
| Cleanup target is dirty or ambiguous | Skip it and report why |
