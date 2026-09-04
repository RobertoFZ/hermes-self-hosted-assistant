# pr-decision-review

Explicit-only, human-driven GitHub PR briefing workflow. It helps reviewers understand change size, objectives, structural and database changes, OpenSpec parity, related gitlink PRs, stack decisions, and prior discussion topics without running another defect-oriented code review.

## Install

```bash
npx skills add reservamos/skills --skill pr-decision-review
```

## Invoke

Discover eligible PRs with a minimal deterministic queue:

```text
Use $pr-decision-review.
```

Review named PRs sequentially and skip discovery:

```text
Use $pr-decision-review on PRs 412, 419, and 421.
```

Review every layer of an explicitly selected stack:

```text
Use $pr-decision-review on PR 421 --stack.
```

## Review shape

The default briefing shows:

1. PR identity, exact additions/deletions, and objective
2. what was executed at an outcome level
3. classes and comparable structural units added, modified, or deleted
4. inline database operations and a focused Mermaid diagram when persistence changes
5. an optional focused Mermaid diagram when it materially clarifies another change
6. related OpenSpec parity when proven
7. related implementation PR metadata for changed gitlinks
8. a compact summary of topics already discussed
9. things that deserve a closer look
10. human actions for exploration, commenting, or a review decision

For non-empty PRs with 50 or fewer total additions plus deletions, the briefing shows the complete textual patch after the structural summary. Larger diffs remain private evidence until an explicit `show code <ID>` request.

Stack awareness supplies position, dependency metadata, and relevant discussions from other layers. It never adds another layer's implementation to the current PR briefing. `--stack` reviews layers separately and sequentially.

## Safety

- Selection performs no AI or diff analysis.
- Gitlinks resolve related PR metadata without entering child repositories.
- Resolved, unresolved, and outdated discussions remain available for duplicate validation.
- Publication IDs include the actual repository and PR number; bare `E1` labels cannot trigger writes.
- A deterministic action guard binds comments to the active context, validated route, exact thread, and current head.
- Every provider write requires an explicit human action and a fresh PR-head check.
- Incomplete discussion history is reported as `duplicate protection incomplete`.

## Bundled assets

- `scripts/discover_prs.py`: minimal deterministic external-PR discovery and default selection.
- `scripts/collect_pr_context.py`: selected-PR evidence, complete review-thread history, gitlink identity, and metadata-only stack collection.
- `scripts/resolve_gitlink_prs.py`: maps gitlink commits to minimal associated-PR metadata without traversing child repositories.
- `scripts/prepare_review_actions.py`: rejects stale, ambiguous, cross-PR, or incorrectly routed publication actions before any GitHub write.
- `references/briefing-agent.md`: objective, execution, OpenSpec, and closer-look synthesis.
- `references/discussion-validator.md`: topic memory, duplicate classification, and thread-routing rules.
- `tests/`: focused unit and CLI behavior tests.
- `evals/evals.json`: realistic workflow evaluations.
