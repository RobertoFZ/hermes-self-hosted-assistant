---
name: ticket-quality-fixer
description: Improve a deficient Linear ticket or Notion page using the ticket-quality rubric, asking only for missing product information, generating Spanish structured content, showing a before/after diff, and re-scoring the proposal. Use when given a Linear issue key or Notion page and asked to fix ticket quality, acceptance criteria, scope, business context, or edge cases.
---

# Ticket Quality Fixer

Read [references/workflow.md](references/workflow.md) for source detection, the complete rubric, content structure, update mechanics, and score report.

## Procedure

1. Detect Linear versus Notion input and fetch it through the configured connector.
2. Score it with the same rubric used by `$ticket-quality-enforcer`.
3. Infer only safe structural improvements. Ask all product questions together for missing business context, acceptance criteria, or constraints.
4. Generate the proposed title and body in Spanish while preserving valid existing content and Notion child structures.
5. Show a complete before/after comparison.
6. Require explicit confirmation in the current conversation before updating either Linear or Notion. In dry-run mode, do not update.
7. Re-score the live or proposed content and report remaining gaps.

## Guardrails

- Never invent requirements or treat silence as consent.
- Prefer surgical Notion content updates; never authorize deletion of child content.
- If the required connector is unavailable, provide the complete manual patch instead.
- Keep the enforcer and fixer rubrics synchronized.

