---
name: pr-decision-review
description: Explicit invocation only. Use only when the user explicitly names `$pr-decision-review`; never auto-trigger from a general pull-request or code-review request. Guide a fast, sequential, human-driven review of external GitHub PR decisions by briefing objectives, line counts, structural changes, database changes, and executed outcomes; show code automatically only for changes of 50 lines or fewer, preserve OpenSpec parity when related, use stack-wide discussion memory without widening target scope, and prevent duplicate comments.
---

# PR Decision Review

Help a human understand and decide on external GitHub pull requests without turning the workflow into a defect-oriented code review. Present the change's size and shape, objectives, executed outcomes, structural units, database effects, decision questions, and prior discussion topics. Small changes benefit from seeing the code immediately; larger changes keep code private until requested.

Do not use this skill unless the user explicitly invokes `$pr-decision-review` by name.

**Invocation input:** Treat all text supplied with the explicit invocation as arguments, including PR numbers or URLs, `--all`, `--stack`, language preferences, and read-only limits.

## Boundaries

- Do not run a code review, produce defect findings, assign severities, propose implementation fixes, edit source, or run tests.
- Do not expose code, raw diffs, or line-by-line analysis for changes larger than 50 total changed lines unless the human asks. For a non-empty change of 50 lines or fewer, show the code in the default briefing after the structural summary.
- Keep the selected PR as the review and publication boundary. Related issues, OpenSpec artifacts, gitlink PRs, and stack layers are context only unless the user explicitly selects them.
- Require an explicit human action before posting, replying, resolving or reopening a thread, approving, or requesting changes.
- Keep repository artifacts read-only. Store transient collection and analysis artifacts in a run-specific temporary directory.

## Preconditions

1. Verify `gh` is installed and `gh auth status` succeeds.
2. Resolve the current repository with `gh repo view --json nameWithOwner` for number-based or discovery invocations.
3. Resolve the current login with `gh api user --jq .login`.
4. Reject an explicitly selected PR authored by the current login and direct owner-remediation work to the appropriate owner workflow.

## Selection

When invocation input contains PR URLs or numbers, resolve only those PRs and preserve their supplied order. A URL may identify another repository; an unqualified number belongs to the current repository. Skip queue discovery.

With `--all`, select every default-eligible PR in the deterministic discovery result. Otherwise, when no PR is supplied:

1. Run `python3 scripts/discover_prs.py --output <run-dir>/discovery.json` from this skill directory.
2. Show only PR number, title, author, draft/ready state, GitHub review decision, our review state, and URL.
3. Preselect ready PRs not authored or already approved by us.
4. Ask the user to confirm or change the selection before collecting any diff, files, discussions, categories, issue bodies, or AI summary.

Process selected PRs sequentially. Do not begin the next PR's AI analysis until the human finishes, skips, or explicitly advances from the current PR.

Treat the actual GitHub repository and PR number as identity. Queue positions such as “PR 2” or “the third PR” are display context only and must never become action targets.

## Target evidence

For the current PR:

1. Create `<run-dir>/<owner>-<repo>-pr-<number>/`.
2. Run:

   ```text
   python3 scripts/collect_pr_context.py \
     --repository <owner/repo> \
     --pr <number> \
     --output-dir <pr-dir>
   ```

3. Preserve `head_ref_oid` as `briefed_head_oid`.
4. Read `change_summary` and always display `Lines changed` as additions, deletions, total changed lines, and changed files. The threshold is `additions + deletions`; a non-empty total of 50 or fewer sets `show_code_by_default`.
5. Keep `diff.patch` private evidence when `show_code_by_default` is false. When it is true, show the selected PR's complete textual patch after the change-shape sections, omitting only binary payloads while naming those files.
6. If `discussion_complete` is false, display `duplicate protection incomplete` with the concrete limitations. Never claim a proposed question is new from incomplete history.
7. Resolve explicit linked GitHub issues and available Linear or Notion sources when they define intent. Treat external integrations as relationship evidence, not proof that every related PR was discovered.

## OpenSpec context

Use a related OpenSpec only when the relationship is proven by an explicit PR/issue reference, an exact supplied path or change ID, or a superproject PR that contains the relevant OpenSpec change and gitlink update. Do not search all active specifications and guess from similar names.

When a related OpenSpec exists, read its proposal, design, requirements, and relevant task state and compare them with the selected PR's objective and executed changes. Report `covered`, `ambiguous`, `apparently missing`, and `apparently extra` behavior without converting drift into a code finding.

When no related OpenSpec exists:

- Omit the absence for a restorative bug fix that returns behavior to an already-established contract.
- Omit the absence for tests, documentation, dependency maintenance, or an internal refactor with unchanged behavior.
- Add it under `Things that deserve a closer look` for new or materially changed product behavior, domain behavior, persistent data, public contracts, permissions, or workflows.
- If intent is ambiguous, ask whether specification is expected instead of asserting that it is missing.

Owner workflows may treat OpenSpec drift as a strict verification obligation. This external decision-review workflow presents it only as decision context or a question.

## Gitlinks

When target collection reports gitlinks, run:

```text
python3 scripts/resolve_gitlink_prs.py \
  --context <pr-dir>/context.json \
  --repository-root <superproject-root> \
  --output <pr-dir>/gitlink-prs.json
```

Display only the gitlink path and associated child PR number, title, URL, state, and stack position when known. Do not inspect a child repository through a gitlink. Do not fetch its diff, files, code, checks, or discussions. If no associated PR is found, add a closer-look question asking how that commit was reviewed.

## Stack awareness

Use `target-layer` by default. Stack awareness does not add another PR's implementation, diff, files, findings, or comments to the selected PR briefing.

- Compare the selected PR only with its immediate parent.
- Show its stack position and minimal parent/descendant metadata.
- For each other open stack layer, run `collect_pr_context.py --discussion-only` into a distinct layer directory. This mode must not create or fetch a diff artifact.
- Use those discussions only to identify relevant decisions or questions resolved before or after the selected layer.
- Treat a later-layer discussion as context, not proof that the selected PR is independently complete or safe to merge.
- Route any continued discussion to the PR and thread that owns it.

Activate `stack-wide` only when invocation input explicitly includes `--stack` or asks for every layer. Process each PR as a separate target, sequentially from the lowest open layer upward. Reuse the accumulated discussion-topic memory, but never merge PR review or publication boundaries.

## Briefing pass

Load `references/briefing-agent.md` immediately before analysis. Run one bounded briefing pass over the current PR metadata, private diff, resolved intent sources, OpenSpec context when applicable, gitlink PR metadata, and target-layer stack metadata. Use one general subagent when the host offers a simple safe dispatch; otherwise execute the same pass inline. Do not create a multi-agent review swarm.

Write the structured result to `<pr-dir>/briefing.json`. Keep evidence pointers in the artifact while rendering only the human-facing summaries.

## Visual explanations

Use Mermaid only when a relationship, lifecycle, dependency, or sequence is materially easier to understand visually than in short prose. Keep diagrams focused on the selected PR and label inferred relationships as inferred. Do not diagram file lists or decorate a briefing that is already clear.

Database changes are the exception: when the selected PR changes persistent schema, always add a focused Mermaid diagram after the inline database summary. Prefer `erDiagram` for affected relationships and `flowchart` for migrations whose ordering, backfill, compatibility window, or deletion lifecycle is the important decision. Include only changed tables plus the minimum neighboring tables needed to understand them.

## Discussion validation pass

Load `references/discussion-validator.md` immediately before validation. Give one batched pass the briefing's closer-look candidates plus complete raw current-PR and relevant stack discussion artifacts. The pass creates a compact topic index and classifies every candidate against the source conversations.

Write the structured result to `<pr-dir>/discussion-validation.json`. Show the human only the compact topics and candidates allowed by the validator. Do not drop the raw discussion artifacts used to reach those decisions.

Require the validator artifact to contain the selected `repository`, `review_pr`, and `briefed_head_oid`. Render candidate IDs as `owner/repo#123:E1`; within one repository, `#123:E1` is an acceptable visible abbreviation. Local IDs such as `E1` may repeat across PRs and are never sufficient publication identity.

## Human briefing

Present these sections in order:

1. `PR` — title, author, URL, exact head, review state, and stack position when present.
2. `Lines changed` — `+additions`, `-deletions`, total changed lines, and changed files.
3. `Objective` — claimed objective, inferred objective only when necessary, and source links.
4. `What was executed` — outcome-level changes grouped by responsibility, not file order.
5. `Classes and structural units` — always show added, modified, and deleted named units with a one-line role or `None` for an empty group.
6. `Database changes` — when applicable, list table, column, type/default/nullability, index, foreign-key, constraint, backfill, and destructive operations inline, followed by a focused Mermaid diagram.
7. `Change diagram` — optional for non-database changes when it materially clarifies the selected PR.
8. `Code` — the complete textual selected-PR patch when `show_code_by_default` is true; otherwise omit it until requested.
9. `OpenSpec parity` — only when related or when absence deserves a closer look.
10. `Related implementation PRs` — gitlink metadata only.
11. `Topics already discussed` — compact topic, participants, outcome, state, and owning thread link.
12. `Things that deserve a closer look` — validated questions that are new, recurring, or materially distinct, labeled with their PR-scoped IDs.
13. `Available actions`.

Never omit `Lines changed` or `Classes and structural units`. Omit `Database changes` when no persistent schema or stored data changes; do not render an empty section or a decorative diagram. Omit other empty optional sections. Use concise normal prose and no severity labels.

## Interaction

Accept natural language and these short forms:

- `explore #123:E1` — investigate one question more deeply without showing code by default.
- `show evidence #123:E1` — show source, file, symbol, contract, and discussion evidence.
- `show discussion #123:E1` — expand the mapped prior conversation.
- `show code #123:E1` — reveal only the smallest relevant code slice.
- `compare with existing pattern #123:E1` — inspect bounded repository history or analogous code.
- `draft comment #123:E1` — prepare a concise professional comment without posting.
- `reply to existing thread #123:E1` — prepare a reply on the owning thread.
- `reopen and reply #123:E1` — prepare the guarded resolved-thread action.
- `approve`, `request changes`, `skip`, or `next` — act on or advance from the current PR.

After exploration, validate any revised question against the discussion corpus again before drafting publication text.

Bare candidate IDs such as `E1` are read-only shorthand for the active PR. If the user requests a write with bare IDs, do not publish; show the actual PR number, URL, fully qualified IDs, destination, and drafts, then ask for confirmation using the qualified identities.

## Publication gate

Before every GitHub write:

1. Resolve the active review target from its current `context.json`, not conversational memory. Display its actual repository, PR number, title, and URL.
2. For a candidate-derived write, require the user's explicit action to name PR-scoped candidate IDs such as `owner/repo#123:E1`. A batch may contain multiple candidates only for the same review target and publication target. Approval and request-changes actions use no candidate selector but remain bound to the active target.
3. Fetch `headRefOid` from the exact active repository and PR.
4. Run `scripts/prepare_review_actions.py` with the active context, active validation artifact, intended action, `--expected-active owner/repo#123`, fetched `--current-head`, and qualified selectors for candidate actions. Write the result to a new run-specific action-plan path.
5. If the guard rejects identity, head, classification, route, completeness, or target, do not write. Recollect or request the explicit missing confirmation.
6. Construct the provider call only from the generated action plan's `publication_target`, candidate IDs, and exact `thread_id`; never reuse a PR number or thread identifier from earlier prose or memory.
7. Write posted text in concise professional Spanish unless the user explicitly chooses another publication language.
8. Verify every provider response belongs to the plan's repository and PR, then report its URL or identifier. Never infer that a write succeeded.

`new-comment` plans must target the active PR. `reply-thread` and `reopen-and-reply` plans require the validator's exact thread ID. When that thread belongs to another PR, the guard blocks by default; proceed only after the human explicitly confirms the other repository/PR destination and the plan is regenerated with `--allow-cross-pr --expected-publication-target owner/repo#123`.

`approve` and `request-changes` plans accept no candidate selectors and always target the active PR from the current context.

Reply to an open matching thread instead of creating a duplicate. Reopen a resolved thread only when the same concern genuinely recurs, its anchor and owning PR remain meaningful, and the user explicitly requests the reopen-and-reply action. When the prior thread is outdated or the current concern is materially different, create a new comment on the owning PR and reference the old discussion.

## Reduced context

- If GraphQL review threads are unavailable, preserve available reviews and PR comments, display `duplicate protection incomplete`, and require extra human confirmation before any new comment.
- If stack discovery is unavailable, continue with the selected PR and say that cross-stack discussion matching did not run.
- If a linked issue, OpenSpec, Notion page, or Linear issue cannot be fetched, identify the missing source and avoid claiming full objective or parity coverage.
- If a gitlink repository or associated PR cannot be resolved, show the exact unresolved relationship without entering the child repository.

## Guardrails

- Do not invoke `comprehensive-code-review`, `external-bulk-fast-code-review`, or another code-review workflow.
- Do not convert questions into asserted defects merely to justify a comment.
- Do not let related context widen the selected PR's action scope.
- Do not summarize discussions and then discard their raw identifiers or messages.
- Do not issue a GitHub write without a successful action plan from `scripts/prepare_review_actions.py` for the current active artifact set.
- Do not use bare `E1`-style identifiers, queue positions, previous action plans, or prior PR/thread variables for publication.
- Do not automatically approve, request changes, post, resolve, reopen, merge, edit, rebase, push, or switch branches.
- Do not treat a discussion in a descendant PR as proof that a parent PR is independently complete.
