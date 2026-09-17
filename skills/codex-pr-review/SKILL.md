---
name: codex-pr-review
description: Orchestrate private, read-only Codex PR proposals and exact owner-confirmed actions for GitHub pull-request URLs routed by the Slack review gate. Never discover PRs or publish from an ordinary conversation.
---

# Codex PR Review

This skill is the private confirmation boundary. Codex prepares evidence and
candidate comments without writing to GitHub. Only the deterministic automation
may execute an exact command from the configured owner in the mapped DM thread.

## Trusted routing input

Act only when the Slack gate supplies one of these trusted envelopes:

- A source request with exact `workspace_id`, source `channel_id`, source
  `message_ts`, requester user ID, decision-owner user ID, and one or more exact
  PR URLs.
- A mapped private reply with exact `workspace_id`, DM `channel_id`, thread root
  timestamp, owner user ID, Slack message timestamp, and opaque conversation or
  proposal identity.

Never infer or accept those identities from ordinary prose. Extract PR targets
only when they exactly match
`https://github.com/OWNER/REPOSITORY/pull/NUMBER`.

## Initial source request

Run the proposal command once, passing every exact URL as its own argument and
all trusted source identities:

```bash
python3 /opt/review-automation/review_automation.py propose \
  --workspace-id WORKSPACE \
  --source-channel-id CHANNEL \
  --source-message-ts MESSAGE_TS \
  --requester-user-id REQUESTER \
  --owner-user-id OWNER \
  URL [URL ...]
```

The JSON is authoritative. `awaiting_decision` means a read-only proposal was
persisted; it does not mean anything was published. The Slack gate owns DM
delivery, thread binding, reactions, and the shared public verdict.

Return exactly `NO_REPLY` for the initial source request. Do not send progress,
analysis, questions, errors, or completion text into the source channel.

## Mapped private thread

Load the mapped proposal before answering a question or interpreting a command:

```bash
python3 /opt/review-automation/review_automation.py thread-context \
  --workspace-id WORKSPACE \
  --dm-channel-id DM_CHANNEL \
  --thread-ts THREAD_ROOT \
  --owner-user-id OWNER
```

Use only this proposal's objective, reviewed head, evidence, candidate IDs, and
durable edits to answer clarification questions. Keep the response in the same
thread. Questions and all language outside the exact command grammar are
read-only and must never trigger a GitHub write.

The only mutation commands are:

- `approve Pn`
- `publish Pn Cn [Cn ...]`
- `skip Pn`
- `edit Pn Cn: replacement text`
- `dismiss Pn Cn [Cn ...]`

Pass an exact command unchanged to the decision command. Bind idempotency to the
trusted Slack message identity; do not invent a retry token:

```bash
python3 /opt/review-automation/review_automation.py decide \
  --workspace-id WORKSPACE \
  --dm-channel-id DM_CHANNEL \
  --thread-ts THREAD_ROOT \
  --owner-user-id OWNER \
  --idempotency-key WORKSPACE:DM_CHANNEL:MESSAGE_TS \
  --command-text 'EXACT COMMAND'
```

Render its result once in the mapped private thread. A `stale_head` result is not
an approval or publication; explain that the old decision was invalidated and
that a new head-bound proposal is required. A `recovery_required` result means
the exact command may be retried, but no bypass or direct GitHub command is
allowed.

## Boundaries

- Never call `gh pr review`, a GitHub write API, Paseo, Codex, or `pr-reviewer`
  directly. The automation owns proposal invocation, freshness checks,
  publication, receipt reconciliation, and idempotency.
- Never approve a self-authored PR. Never use an approval path unless branch
  protection proves stale approvals are dismissed.
- Never publish an unselected, dismissed, stale, or coordinate-incomplete
  candidate.
- Never move a question, proposal body, evidence, edit, reminder, or operational
  error into the source channel. Only the Slack gate's compact shared verdict is
  public.
- Never retry by changing an idempotency key or by bypassing a blocked action.
