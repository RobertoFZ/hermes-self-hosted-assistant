#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


skills_root = Path(__file__).parents[1] / "skills"
validated = 0
for skill_file in sorted(skills_root.glob("*/SKILL.md")):
    content = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        raise SystemExit(f"Invalid or missing frontmatter: {skill_file}")

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            raise SystemExit(f"Invalid frontmatter line in {skill_file}: {line}")
        fields[key.strip()] = value.strip()

    if set(fields) != {"name", "description"}:
        raise SystemExit(f"Frontmatter must contain only name and description: {skill_file}")
    if fields["name"] != skill_file.parent.name:
        raise SystemExit(f"Skill name must match its directory: {skill_file}")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fields["name"]):
        raise SystemExit(f"Skill name must use hyphen-case: {skill_file}")
    if len(fields["name"]) > 64:
        raise SystemExit(f"Skill name exceeds 64 characters: {skill_file}")
    if not fields["description"] or len(fields["description"]) > 1024:
        raise SystemExit(f"Description must contain 1-1024 characters: {skill_file}")
    validated += 1

print(f"Validated {validated} skills.")
