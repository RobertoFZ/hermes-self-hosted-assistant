
# Ticket Quality Fixer

Takes a flagged ticket or Notion page, identifies exactly which rubric
dimensions are failing, asks targeted questions only for the gaps it cannot
infer, generates fixes for the rest silently, requires explicit confirmation
before updating either source, and then re-scores to confirm it passes.

Supports two sources:
- **Linear ticket** — identified by `RES-123`-style identifier.
- **Notion page** — identified by a Notion URL (`https://www.notion.so/...`)
  or a raw Notion page UUID.

Companion to `$ticket-quality-enforcer`. Best run immediately after a flagged
ticket is identified.

Connector calls below are capability-oriented pseudocode. Discover the active
Linear or Notion operation names at runtime.


## Invocation

```
$ticket-quality-fixer RES-123
$ticket-quality-fixer RES-123 --dry-run
$ticket-quality-fixer https://www.notion.so/workspace/Page-Title-abc123def456
$ticket-quality-fixer https://www.notion.so/workspace/Page-Title-abc123def456 --dry-run
```

| Flag | Default | Description |
|---|---|---|
| `--dry-run` | off | Show diff and re-score without updating the source (Linear or Notion) |


## Prerequisites

| Requirement | How to verify |
|---|---|
| Linear MCP configured in Codex (only required for Linear input) | `~/.codex/config.toml` has a `linear` entry |
| Notion MCP configured in Codex (only required for Notion input) | `~/.codex/config.toml` has a `notion` entry |


## Execution steps

Work through each step in order. Do not skip steps.


### Step 1 — Detect source and fetch

Inspect the argument the user passed:

- If it matches `^[A-Z]+-\d+$` (e.g. `RES-123`), treat it as a **Linear** ticket.
- If it is a Notion URL (`notion.so/...` or `*.notion.site/...`) or a raw UUID
  (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`), treat it as a **Notion** page.
- Otherwise, ask the user to provide a Linear identifier or a Notion URL/UUID
  and stop.

Set an internal `source` flag to `linear` or `notion` and use it to branch
behaviour in later steps.

#### Linear

```
linear.get_issue(id: "TICKET_ID")
```

If the ticket does not exist or is trashed/archived, report the error and stop.

Extract:
- `id` — UUID for updating
- `identifier` — e.g. RES-123
- `title`
- `description`
- `state.name`
- `assignee.name`

Use `identifier` as the display label (e.g. "RES-123") in all later steps.

#### Notion

```
notion.fetch(id: "NOTION_URL_OR_UUID")
```

If the page does not exist, is archived, or is not accessible, report the
error and stop. If the page is a database, report that this skill only
operates on Notion pages (not databases) and stop.

Extract:
- `id` — page UUID for updating
- `title` — page title
- `content` — full Markdown body of the page (this plays the role of
  Linear's `description`)
- `url` — canonical Notion URL

Use the page title as the display label in all later steps (e.g.
"AutoPilot: Módulo…"). If the fetched page content exceeds a size that fits
into context, narrow the analysis to the first ~30 000 characters and tell
the user the page was truncated for scoring purposes; do not silently ignore
the rest.


### Step 2 — Score the source

Apply the full rubric from `$ticket-quality-enforcer` to the fetched
content (Linear description or Notion page body, plus the title).
Store the score and notes for each dimension.

If the source already scores 85 or above, report:
"LABEL already scores SCORE/100 — no fixes needed."
and stop. (`LABEL` is the Linear identifier or Notion page title.)

List the failing dimensions (score below their maximum) to the user before
continuing:
"Fixing LABEL (SCORE/100). Failing dimensions: DIMENSION_LIST."


### Step 3 — Classify each failing dimension

For each dimension scoring below maximum, classify it as one of:

**Can infer** — the skill has enough context from the title and existing
description to draft a reasonable fix without asking the user.

**Needs input** — the skill cannot responsibly generate this without
information only the user has.

Use this classification table:

| Dimension | Rule |
|---|---|
| Title clarity | Can infer — rewrite from existing content |
| Business context | Needs input — ask why this matters |
| Acceptance criteria | Needs input if fully absent. Can infer partial improvements if at least one AC exists |
| Scope boundedness | Can infer — identify and flag bundled deliverables from description |
| Edge cases | Needs input — ask about known constraints or dependencies |


### Step 4 — Ask all questions upfront

Ask only about dimensions classified as "Needs input". Ask all questions in
a single message — never one at a time.

Format:

```
I need a few details to fix LABEL before updating it.

[Only if business context is failing]:
1. Why does this ticket matter? What user problem or product need does it solve?
   (1-2 sentences is enough)

[Only if acceptance criteria is fully absent]:
2. What are the conditions that define this ticket as done?
   (e.g. "User can do X", "System handles Y without error", "Existing tests pass")

[Only if edge cases are failing]:
3. Are there any known constraints, edge cases, or dependencies?
   (e.g. "Only applies when RM is active", "Depends on RES-98", "Must not affect existing estrategias")
```

Wait for the user's response before continuing.

If the user's answers are too vague to generate a specific fix, ask one
follow-up clarification per unclear answer — then proceed.


### Step 5 — Generate the fixed content

Using the original ticket content + user's answers, generate improvements
for every failing dimension.

**Language rule:** All generated and updated content must be written in
Spanish, regardless of the language used in the conversation or the user's
answers. If the user answers in English, translate to Spanish before writing
to the ticket.

**Rules for each dimension:**

#### Title clarity
Rewrite to follow: action verb + specific object + context.
Keep it under 10 words. Do not add information not present in the original.
Example: "Revisar RM" → "Implementar validación de descuento en flujo RM"

#### Business context
Write 1-2 sentences using the user's answer from Step 4.
Start with the user or system impact, not with "This ticket...".
Example: "Los usuarios no pueden aplicar descuentos manuales cuando una
estrategia está activa, lo que genera errores en el flujo de RM."

#### Acceptance criteria
Format as a bullet list of testable conditions.
Each condition must be independently verifiable.
Minimum 2 conditions. Start each with "Given", "When", or a clear statement
of expected behaviour.

#### Scope boundedness
If the description bundles multiple deliverables, split them into clearly
labeled sections: "In scope:" and "Out of scope / follow-up tickets:".
Do not remove content — reorganize it.

#### Edge cases
Add a clearly labeled "Constraints / edge cases:" section using the user's
answer from Step 4.


### Step 6 — Assemble the updated content

Merge the original content with all generated fixes into a clean, final
body. Preserve any original content that was not part of a failing
dimension — do not rewrite sections that were already acceptable.

For Notion specifically:
- Preserve existing child pages, embedded databases, callouts, and any
  structural blocks the page already contains. Only restructure the
  textual sections that are failing the rubric.
- Keep the Markdown syntax compatible with Notion-flavored Markdown. If in
  doubt, fetch `notion://docs/enhanced-markdown-spec` via
  `notion.fetch` before generating the new body.

Structure the final body as:

```
## Contexto
[business context — new or preserved]

## Qué construir
[original implementation description, cleaned up if scope was restructured]

## Criterios de aceptación
[bullet list — new or improved]

## Restricciones / casos borde
[bullet list — new or preserved]
```

If a section already existed and passed the rubric, keep it as-is.


### Step 7 — Show the diff and confirm

Before updating anything, show the user a clear before/after comparison:

```
──────────────────────────────────────
LABEL — Proposed changes (SOURCE)
──────────────────────────────────────

TITLE
  Before: Revisar RM
  After:  Implementar validación de descuento en flujo RM

BODY
  Before:
    [original content verbatim]

  After:
    [full updated content]

──────────────────────────────────────
```

`SOURCE` is `Linear` or `Notion`. Then branch on source:

**Linear:** ask explicitly:
`¿Quieres que actualice el ticket de Linear con estos cambios? (sí / no)`
Wait for an explicit affirmative response in the current conversation.

**Notion:** never auto-update. Ask explicitly:
`¿Quieres que actualice la página de Notion con estos cambios? (sí / no)`
(English-speaking user: `Do you want me to update the Notion page with
these changes? (yes / no)`)
Wait for an explicit affirmative response (`sí`, `si`, `yes`, `y`, `ok`,
`adelante`, `proceed`). Any other answer — including silence or anything
ambiguous — is treated as "no": abort the update and offer to refine the
proposal. Never update a Notion page without an explicit confirmation in
the current conversation.

If `--dry-run` is set, skip the confirmation entirely and proceed directly
to Step 9 without updating.


### Step 8 — Update the source

Branch on the detected source:

#### Linear

```
linear.update_issue(
  id: "ISSUE_UUID",
  title: "UPDATED_TITLE",
  description: "UPDATED_DESCRIPTION"
)
```

#### Notion

Update the title and the body in two calls:

1. Title (only if the title actually changed):
   ```
   notion.update_page(
     page_id: "PAGE_UUID",
     command: "update_properties",
     properties: { "title": "UPDATED_TITLE" }
   )
   ```

2. Body — prefer surgical edits via `update_content` so the rest of the
   page (child pages, databases, untouched sections) is preserved:
   ```
   notion.update_page(
     page_id: "PAGE_UUID",
     command: "update_content",
     content_updates: [
       { "old_str": "EXACT_EXISTING_SNIPPET", "new_str": "REPLACEMENT" },
       ...
     ]
   )
   ```

   Only use `replace_content` if the entire body is being rewritten and
   you have verified there are no child pages or embedded databases that
   would be deleted. If `replace_content` reports it would delete child
   content, do not pass `allow_deleting_content: true` — instead, fall
   back to a series of `update_content` edits or stop and report the
   conflict to the user.

If any update fails, report the error and show the generated content so
the user can manually apply it.


### Step 9 — Re-score and confirm

Re-apply the full rubric to the updated content. For Notion in `--dry-run`
mode (or when the user declined the update), re-score against the proposed
content instead of the live page, and clearly label the result as
"proposed score".

Report the result:

```
──────────────────────────────────────
LABEL updated (SOURCE)
──────────────────────────────────────
  Before: ORIGINAL_SCORE/100 (ORIGINAL_VERDICT)
  After:  NEW_SCORE/100 (NEW_VERDICT)

  Dimension changes:
  Title clarity        12 → 20  ✅
  Business context      0 → 20  ✅
  Acceptance criteria   8 → 30  ✅
  Scope                15 → 15  (unchanged)
  Edge cases            0 → 15  ✅
──────────────────────────────────────
```

If the source still scores below 85 after the update, list the remaining
weak dimensions and ask: "Would you like me to take another pass at these?"


## Notes for the AI Supervisor

**This skill does not create new information — it structures what you provide.**
The quality of the output depends entirely on the quality of your answers in
Step 4. Vague answers produce vague AC. The skill will push back once if an
answer is too thin, but it will not invent product requirements.

**Linear and Notion both require explicit confirmation in Codex.** A timed
abort hook cannot be reproduced reliably through Codex's turn-based API, so
silence or ambiguity never authorizes an update.

**Notion never auto-updates.** Notion pages often hold long-form product
specs, design docs, and shared context with non-engineers, so a wrong edit
is more disruptive than on a Linear ticket. Always require an explicit
affirmative answer from the user before calling
`notion.update_page`. Treat anything ambiguous as "no".

**Use `--dry-run` for calibration.** Run it on a few already-good tickets to
confirm the re-score lands at 85+ before using it on real backlog tickets.

**This skill and the enforcer share the same rubric.** If you update thresholds
or criteria in one, update the other to stay consistent.


## Changelog

| Version | Date | Change |
|---|---|---|
| 2.1.0 | 2026-07-20 | Codex migration: both Linear and Notion updates now require explicit confirmation; removed the timed Linear abort hook. |
| 2.0.0 | 2026-05-19 | Added Notion support with explicit confirmation and surgical content updates. |
| 1.1.0 | 2026-04-08 | All generated ticket content must be written in Spanish. User answers in any language are translated before updating Linear. Description section headers updated to Spanish. |
| 1.0.0 | 2026-04-08 | Initial version. |
