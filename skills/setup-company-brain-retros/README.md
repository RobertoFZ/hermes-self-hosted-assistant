# setup-company-brain-retros

Configure a minimal local author profile and verify that the current OAuth identity can read policies and publish weekly retros only inside its assigned Company Brain namespace. Setup never creates a probe page.

## Install

Install Matt Pocock's official retro skill, its writing dependency, and both Reservamos skills:

```bash
npx skills add mattpocock/skills --skill writing-for-agents
npx skills add mattpocock/skills --skill retro
npx skills add reservamos/skills --skill setup-company-brain-retros
npx skills add reservamos/skills --skill publish-company-brain-retro
```

Confirm installation with `npx skills list`.

## Prerequisites

- A Company Brain connection using OAuth at `https://company-brain.reservamos.com/mcp`.
- Effective `read` and `write` scopes plus page read/write operations.
- Exactly one assigned prefix shaped as `retros/people/<person-slug>/`.
- Read access to the live `resolver` and `_excluded-people` pages.

If the connection is missing, the setup skill detects the current agent and follows [references/company-brain-mcp-setup.md](references/company-brain-mcp-setup.md) to help register and authenticate it through that host's own mechanism. Pi uses its maintained Company Brain integration instead of generic MCP registration.

OAuth consent remains a human action. The skill diagnoses missing access but never grants consent or stores a token.

## Usage

Explicitly invoke the setup skill:

```text
Use $setup-company-brain-retros to configure and verify my weekly-retro publishing access.
```

The result is exactly `READY` or `NOT READY` with evidence or a concrete remediation. A ready setup writes only this local profile:

`${XDG_CONFIG_HOME:-$HOME/.config}/reservamos/company-brain-retros/profile.yaml`

The profile contains display metadata only. Publication authorization is always derived again from live OAuth.

## Next step

Run the official `$retro` skill. Immediately after its completed result, explicitly invoke `$publish-company-brain-retro` with no intervening message.
