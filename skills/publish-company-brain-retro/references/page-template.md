# Company Brain weekly-retro page contract

Render one complete Markdown page. Quote YAML strings when punctuation or non-ASCII text could make parsing ambiguous.

```markdown
---
title: "<display-name> weekly retro — <period-end>"
type: note
kind: weekly-retro
author: <oauth-person-slug>
display_name: "<display-name>"
squad: <default-squad>
collaborating_squads: [<optional-squad-slugs>]
period_start: <YYYY-MM-DD>
period_end: <YYYY-MM-DD>
created: <YYYY-MM-DD>
published_at: <YYYY-MM-DD>
visibility: company
source_skill: mattpocock-retro
---

<filtered, author-reviewed /retro result>

---

## Publication evidence

- **<YYYY-MM-DD>** | Published from an author-reviewed Matt Pocock `/retro` result with `publish-company-brain-retro`.
```

## Create

Use the template as the complete page. The OAuth-derived person slug is the `author`; profile metadata cannot supply it. `created` is the first publication date and `published_at` is the latest publication date.

## Update

Read the existing exact slug with canonical full content before previewing. Render a complete page, never a partial patch:

1. preserve existing page identity fields (`title`, `type`, `kind`, `author`, and `created`) after confirming they are compatible with the OAuth-derived destination;
2. replace only the compiled retro body and mutable presentation/period fields;
3. preserve the complete `Publication evidence` section when present, or create it when absent;
4. append exactly one new dated publication-evidence entry for the approved write;
5. set `published_at` to the current publication date.

If existing identity conflicts with the derived slug or canonical page kind, block for manual remediation. Never create a numbered correction slug.

## Rendering and comparison

- Preserve the source body's headings and language; do not add a duplicate title.
- Use `collaborating_squads: []` when empty and lowercase kebab-case squad values.
- Exclude conversations, removal details, review markers, secret values, and publishing instructions from the page.
- Compute an internal approval content hash from the exact UTF-8 bytes of the complete Markdown sent to `put_page`; the author does not need to repeat or inspect the hash to approve.
- Successful readback must request canonical full content and return the intended slug.
- Compare the compiled retro body and complete `Publication evidence` text exactly.
- Compare frontmatter as structured field values. Key order, YAML quoting, and a date-only value normalized to the equivalent midnight UTC ISO timestamp are semantically equal. No other value transformation is automatically accepted.
- Any substantive body, evidence, frontmatter, or slug difference is `verification incomplete`.

## Receipt fields

Report destination slug, create/update operation, write-attempt count, readback status, and verification result. Include hashes or normalization details only for incomplete verification or requested diagnostics. A write response alone is not publication evidence.
