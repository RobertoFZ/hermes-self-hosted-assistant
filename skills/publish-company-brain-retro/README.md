# publish-company-brain-retro

Publish the immediately preceding official Matt Pocock `/retro` result to the author's live OAuth-authorized Company Brain path. The workflow filters sensitive content, previews the complete page, accepts a clear affirmative approval, writes at most once, and verifies semantic readback.

## Install

Install the official retro skill, its writing dependency, and both Reservamos skills:

```bash
npx skills add mattpocock/skills --skill writing-for-agents
npx skills add mattpocock/skills --skill retro
npx skills add reservamos/skills --skill setup-company-brain-retros
npx skills add reservamos/skills --skill publish-company-brain-retro
```

Run `$setup-company-brain-retros` once before publishing and whenever access or profile metadata changes.

## Required sequence

1. Explicitly invoke the official `$retro` skill.
2. Wait for its completed retrospective result.
3. With no intervening message, invoke `$publish-company-brain-retro`.

Example third message:

```text
Use $publish-company-brain-retro to review and publish the retro above.
```

The publisher will stop if it must search older turns, files, session stores, or Company Brain for source text.

## Safety contract

- Company Brain is the only target; no personal-brain fallback exists.
- The person slug comes only from live OAuth `direct_write.prefixes`.
- Current `resolver` and `_excluded-people` policies are read by exact MCP slug.
- The full filtered Markdown and exact destination are shown before approval; any unambiguous affirmative reply in the author's language is sufficient.
- Identity, policy, prefix, destination state, and content are revalidated before one write.
- Exact-slug readback must preserve the exact body and semantic frontmatter values before success is reported.

An uncertain write is never retried blindly. The result reports either verified success or `verification incomplete` with a read-only reconciliation path.
