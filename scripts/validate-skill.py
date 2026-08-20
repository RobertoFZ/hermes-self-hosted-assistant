#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


skill_file = Path(__file__).parents[1] / "skills" / "pr-reviewer" / "SKILL.md"
content = skill_file.read_text(encoding="utf-8")
match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
if not match:
    raise SystemExit("Invalid or missing SKILL.md frontmatter")

fields: dict[str, str] = {}
for line in match.group(1).splitlines():
    key, separator, value = line.partition(":")
    if not separator:
        raise SystemExit(f"Invalid frontmatter line: {line}")
    fields[key.strip()] = value.strip()

if set(fields) != {"name", "description"}:
    raise SystemExit("SKILL.md frontmatter must contain only name and description")
if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fields["name"]):
    raise SystemExit("Skill name must use hyphen-case")
if len(fields["name"]) > 64:
    raise SystemExit("Skill name exceeds 64 characters")
if not fields["description"] or len(fields["description"]) > 1024:
    raise SystemExit("Skill description must contain 1-1024 characters")

print("Skill is valid!")
