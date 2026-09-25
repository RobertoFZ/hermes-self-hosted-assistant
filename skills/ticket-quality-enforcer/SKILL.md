---
name: ticket-quality-enforcer
description: Audit unstarted or paused Linear tickets against a five-dimension quality rubric, rank specification gaps, and optionally publish structured feedback and a Slack digest. Use when asked to check backlog quality, score Linear tickets, enforce ticket readiness, identify weak acceptance criteria, or run the ticket-quality audit in dry-run mode.
---

# Ticket Quality Enforcer

Read [references/workflow.md](references/workflow.md) for the exact rubric, thresholds, comment template, digest, and report format.

## Procedure

1. Resolve the Linear team, then fetch eligible non-archived, non-trashed tickets through the configured Linear connector.
2. Score title clarity, business context, acceptance criteria, scope boundedness, and edge cases literally. Do not infer unstated content.
3. Present the sorted report and weakest aggregate dimension.
4. In dry-run mode, make no external changes. Otherwise, publish Linear comments only when explicitly requested or approved after presenting the action plan.
5. Send Slack only when a Slack connector is available and authorized. If unavailable, return the ready-to-send digest in chat.

## Guardrails

- Check for an existing quality-check comment or marker before posting.
- Continue the batch when one ticket fails.
- Evaluate Spanish and English tickets by content quality, not language.
- Default the first calibration run to dry-run unless the user explicitly requests live posting.

