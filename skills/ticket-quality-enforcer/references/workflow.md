
# Ticket Quality Enforcer

Fetches all unstarted tickets from the Reserhub Revenue Linear project,
scores each one against a quality rubric, posts structured feedback comments
on flagged tickets via the Linear MCP, and sends a single Slack digest.

No API key needed — uses the Linear MCP already configured in Codex.

Connector calls below are capability-oriented pseudocode. Discover the actual
Linear and optional Slack operation names in the active Codex session.


## Invocation

```
$ticket-quality-enforcer
$ticket-quality-enforcer --project "Reserhub Revenue"
$ticket-quality-enforcer --dry-run
```

| Flag | Default | Description |
|---|---|---|
| `--team` | auto-detected | Linear team name to scope the query |
| `--dry-run` | off | Score and report locally — skip comments and Slack |


## Prerequisites

| Requirement | How to verify |
|---|---|
| Linear MCP configured in Codex | `~/.codex/config.toml` has a `linear` entry |
| Slack connector (optional) | Required only to send the digest; otherwise return digest text |

No Linear API key is needed when the configured MCP handles authentication.


## Execution steps

Work through each step in order. Do not skip steps.


### Step 1 — Resolve team and fetch tickets


#### Step 1a — Resolve the team

**If `--team` was explicitly passed**, use that name and skip to Step 1b.

**Otherwise**, fetch all available teams:

```
linear.list_teams()
```

If only one team exists, use it automatically and inform the user:
"Using team: TEAM_NAME"

If multiple teams exist, present a numbered list and wait for the user
to choose:

```
Available teams:
1. Reserhub
2. Some Other Team

Which team should I audit?
```


#### Step 1b — Fetch tickets from current sprint and backlog

Make two separate calls and tag each result with its source.

Make two separate calls, one per target status, and tag each result with
its status name.

**Not started:**

```
linear.list_issues(
  filter: {
    team: { name: { eq: "TEAM_NAME" } },
    state: { name: { eq: "Not started" } },
    trashed: { eq: false },
    archived: { null: true }
  }
  first: 50
)
```

Tag each result: `source = "Not started"`

**Paused:**

```
linear.list_issues(
  filter: {
    team: { name: { eq: "TEAM_NAME" } },
    state: { name: { eq: "Paused" } },
    trashed: { eq: false },
    archived: { null: true }
  }
  first: 50
)
```

Tag each result: `source = "Paused"`

Merge both lists into a single collection. Deduplicate by `id` if the
same ticket appears in both — keep the first occurrence.

From each ticket, extract:
- `id` — UUID needed for posting comments
- `identifier` — e.g. RES-123
- `title`
- `description`
- `state.name`
- `assignee.name` — use "Unassigned" if absent
- `source` — "Not started" or "Paused"

If both calls return empty, report "No eligible tickets found in TEAM_NAME"
and stop.

Report to the user:
"Found N tickets in TEAM_NAME (X not started · Y paused). Scoring now…"


### Step 2 — Score every ticket against the rubric

For every ticket in the list, evaluate all 5 dimensions and store the result.
Process all tickets before posting any output.

**Critical instruction:** Be literal. Do not infer or assume information not
explicitly present in the ticket text. Empty or missing fields score 0.

Tickets written in Spanish are valid — evaluate content quality, not language.


## THE RUBRIC

This is the AI Supervisor's core design artifact. Adjust thresholds and
criteria as the team's standards evolve.


### Dimension 1 — Title clarity (20 pts)

Good title: action verb + specific object + optional context.

Examples:
- "Implementar validación de cupones en flujo RM"  ← 20 pts
- "Fix null pointer in descuento adicional calculation"  ← 20 pts
- "Revisar RM"  ← 5 pts
- "Bug"  ← 0 pts

| Score | Criterion |
|---|---|
| 20 | Specific verb + object + context. No ambiguity about what to build. |
| 12 | Has verb and object, missing context or slightly vague. |
| 5 | One-word, generic, or reads like a note ("Fix bug", "Revisar esto"). |
| 0 | Empty, missing, or completely unclear. |


### Dimension 2 — Business context / Why (20 pts)

Must answer: "Why does this matter to the user or product?"

| Score | Criterion |
|---|---|
| 20 | Clear rationale present. Connects to user impact or product need. |
| 12 | Some context but thin or implicit — needs to be inferred. |
| 5 | Only describes what to build, not why. |
| 0 | Description is empty or only repeats the title. |


### Dimension 3 — Acceptance criteria (30 pts)  ← HIGHEST WEIGHT

Explicit, testable conditions that define when the ticket is done.
Bullet list, Given/When/Then, or numbered steps are all valid formats.

Strong AC example:
- Given a corrida with estrategia activa, when the user requests a descuento,
  the system applies the configured percentage.
- Existing test suite passes without regressions.
- RM dashboard reflects the updated state within 2 seconds.

| Score | Criterion |
|---|---|
| 30 | 2+ testable, specific conditions explicitly stated. |
| 18 | At least 1 AC condition, even if slightly vague. |
| 8 | Implied AC only ("it should work", screenshot reference). |
| 0 | No acceptance criteria whatsoever. |


### Dimension 4 — Scope boundedness (15 pts)

One clearly bounded deliverable a dev can implement without negotiating scope.

| Score | Criterion |
|---|---|
| 15 | Single, well-scoped deliverable. |
| 10 | Slightly broad but implementable in one PR. |
| 5 | Two or more separate features bundled together. |
| 0 | Scope completely undefined. |


### Dimension 5 — Edge cases / constraints (15 pts)

At least one known edge case, technical constraint, or dependency explicitly
mentioned.

Examples:
- "Applies only when RM is active"
- "Must handle empty corrida list gracefully"
- "Depends on RES-98 being merged first"

| Score | Criterion |
|---|---|
| 15 | 1+ edge cases or constraints explicitly stated. |
| 8 | Constraints implied but not stated. |
| 0 | None mentioned. |


### Verdict thresholds

| Total score | Verdict | Action |
|---|---|---|
| 85–100 | ✅ APPROVED | Terminal summary only. No comment, no Slack. |
| 60–84 | ⚠️ NEEDS REVISION | Post Linear comment + include in Slack digest. |
| 0–59 | ❌ BLOCKED | Post Linear comment + include in Slack digest (urgent). |


### Step 3 — Post comments on flagged tickets

For every NEEDS REVISION or BLOCKED ticket, post a comment using the MCP.
Skip entirely if `--dry-run` is active.

```
linear.create_comment(
  issueId: "ISSUE_UUID",
  body: "COMMENT_BODY"
)
```

Use this comment template:

```
**[⚠️ Needs Revision / ❌ Blocked — Quality Check]**

| Dimension | Score | Max | Notes |
|---|---|---|---|
| Title clarity | X | 20 | [≤10 words: what specifically is missing] |
| Business context | X | 20 | [≤10 words: what specifically is missing] |
| Acceptance criteria | X | 30 | [≤10 words: what specifically is missing] |
| Scope | X | 15 | [≤10 words: what specifically is missing] |
| Edge cases | X | 15 | [≤10 words: what specifically is missing] |
| **Total** | **X** | **100** | |

**Top issues to fix:**
1. [Most critical gap — specific and actionable]
2. [Second gap if present]

*Automated quality check — please revise before picking up this ticket.*
```

Notes must say what is missing, not just that something is missing.
"No acceptance criteria defined" beats "Needs improvement" every time.

If a comment call fails for one ticket, record the failure and continue
with the rest — do not abort the full run.


### Step 4 — Send Slack digest

Only if at least one ticket was flagged and `--dry-run` is off.

Use the Slack MCP to post the digest to `#revenue-alerts`:

```
slack.post_message(
  channel: "#revenue-alerts",
  text: "DIGEST_TEXT"
)
```

Digest format:

```
*Ticket Quality Report — TEAM_NAME*
Checked: N tickets (X not started · Y paused)  ✅ APPROVED: X  ⚠️ NEEDS REVISION: Y  ❌ BLOCKED: Z

❌ Blocked:
• [Paused] <https://linear.app/reserhub/issue/TICKET_ID|TICKET_ID — Title> — SCORE/100 — Top issue: ISSUE

⚠️ Needs Revision:
• [Not started] <https://linear.app/reserhub/issue/TICKET_ID|TICKET_ID — Title> — SCORE/100 — Top issue: ISSUE
```

Send nothing if all tickets are APPROVED.


### Step 5 — Report full results to user

Always finish with a terminal summary, regardless of `--dry-run`:

```
Ticket Quality Report — TEAM_NAME
Ran: TIMESTAMP  |  Tickets checked: N  (X not started · Y paused)

TICKET_ID   SOURCE        SCORE    VERDICT             ASSIGNEE         TITLE
RES-124     Paused        55/100   ❌ BLOCKED          Iván Loeza       Revisar fechas equivalentes
RES-125     Not started   71/100   ⚠️ NEEDS REVISION   Roberto Franco   Descuento en corridas sin estrategia
RES-123     Not started   92/100   ✅ APPROVED         Ignacio Trava    Implementar validación de cupones

Summary
  Approved:          X
  Needs Revision:    Y
  Blocked:           Z
  Linear comments:   Y+Z posted  (or "skipped — dry run")
  Slack digest:      sent  (or "not sent — all approved" / "skipped — dry run")

Weakest dimension across flagged tickets: DIMENSION_NAME (avg X/MAX pts)
```

Sort: BLOCKED first → NEEDS REVISION → APPROVED. Within each group, worst
score first.

The "weakest dimension" line is a team coaching signal — the rubric area that
needs the most attention this cycle.


## Notes for the AI Supervisor

**Always dry-run first.** On first use, run `--dry-run` and compare the
scores against your own read of each ticket. That gap is your calibration
data.

**Comment spam guard.** The skill does not check if it already commented on
a ticket. Re-running on the same backlog will post duplicate comments. Once
the workflow is stable, add a `quality-checked` label in Linear and extend
the Step 1 filter to exclude already-reviewed tickets.

**Weakest dimension = coaching target.** If the same dimension scores low
run after run, that's a habit to address in the team — not a rubric problem.
Bring it to a retro.

**Rubric versioning.** When you change thresholds or criteria, bump the
version at the top of this file and log the change in the changelog below.


## Changelog

| Version | Date | Change |
|---|---|---|
| 3.3.0 | 2026-04-08 | Added trashed and archived exclusion filters. |
| 3.4.0 | 2026-04-08 | Slack channel hardcoded to #revenue-alerts. |
| 3.2.0 | 2026-04-08 | Replaced generic state type filters with exact state names: "Not started" and "Paused". |
| 3.1.0 | 2026-04-08 | Removed project selection. Source column added to terminal and Slack output. |
| 3.0.0 | 2026-04-08 | Replaced all curl/GraphQL with Linear and Slack MCP tool calls. No API keys or env vars required. |
| 2.0.0 | 2026-04-07 | Batch mode: fetch all unstarted tickets automatically. Added `--dry-run` and `--project` flags. Slack changed from per-ticket alerts to single digest. |
| 1.0.0 | 2026-04-07 | Initial version — single ticket mode via curl. |
