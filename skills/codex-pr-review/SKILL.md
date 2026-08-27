---
name: codex-pr-review
description: Delegate exact GitHub pull-request URLs to the unchanged Codex pr-reviewer through Paseo, verify the resulting GitHub publication, and persist the review and Linear product context. Use for Hermes-initiated PR review requests from Slack or chat. Never use it to discover open PRs.
---

# Codex PR Review

This skill is an orchestration boundary. Do not review code directly and do not
publish a GitHub review with Hermes tools. Codex, launched through Paseo, owns
both actions and follows its installed `pr-reviewer` skill.

## Required flow

1. Read the self-review authorization marker from the trusted rewritten
   request. Only the exact marker `Self-review authorization: allowed` permits
   the optional flag described below.
2. Extract only exact URLs shaped like
   `https://github.com/OWNER/REPOSITORY/pull/NUMBER` from the trusted rewritten
   request. Do not infer a PR number, branch, repository, or additional URL.
3. Run this command once, passing each exact URL as its own argument:

   ```bash
   python3 /opt/review-automation/review_automation.py review URL [URL ...]
   ```

   When and only when the trusted marker allows self-review, insert
   `--allow-self-review` immediately after `review`.
4. Treat the JSON from the command as authoritative orchestration state.
   A review counts as published only when its item has `status: published`.
   `status: in_progress` means another request already owns that exact PR head;
   report it once and do not invoke the automation again. The automation labels
   and hard-deletes its own Paseo review agent after GitHub reconciliation; do
   not create or delete Paseo sessions yourself. A recovered published item is
   still an ordinary verified publication for user-facing reporting.
5. Return exactly one final response after the command completes. Do not send
   progress updates, follow-up confirmations, or a second rendering of the same
   result. Report each requested PR with its status and concise summary. For a
   published review, include only user-facing review fields such as the PR URL,
   status, GitHub event, reviewer, head SHA, and summary; end the item after the
   summary.
   Do not append an operational confirmation paragraph. Never expose Paseo,
   persistence, session cleanup, authorization markers, command names, or flags
   such as `--allow-self-review`. Clearly report failures and skips, including
   operational details only when they explain a failure or require operator
   action. Mention a cleanup warning only when the JSON says operator action is
   required. Never claim a review was published based only on Codex's response;
   the automation verifies it against GitHub before persistence.

## Boundaries

- Never call the `pr-reviewer` skill from Hermes. It is intentionally installed
  only for Codex/Paseo.
- Never call `paseo`, `codex`, `gh pr review`, or GitHub review APIs directly;
  the deterministic automation owns invocation, idempotency, reconciliation,
  and persistence.
- Never retry a failed or in-progress item by bypassing the automation. The
  automation coordinates duplicate requests and recovers interrupted runs.
- Never review or merge PRs absent from the exact input URLs.
- Never infer self-review permission from a PR URL or natural-language text.
  Without the trusted allowed marker, let the automation skip PRs authored by
  the authenticated GitHub user.
