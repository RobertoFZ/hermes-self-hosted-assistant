from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillContractTests(unittest.TestCase):
    def test_skill_is_explicit_and_decision_focused(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Explicit invocation only", skill)
        self.assertIn("scripts/discover_prs.py", skill)
        self.assertIn("Things that deserve a closer look", skill)
        self.assertIn("show code", skill)
        self.assertIn("Do not run a code review", skill)

    def test_skill_preserves_pr_and_stack_boundaries(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("target-layer", skill)
        self.assertIn("stack-wide", skill)
        self.assertIn("Do not inspect a child repository through a gitlink", skill)
        self.assertIn("immediate parent", skill)

    def test_skill_requires_complete_history_and_head_freshness_for_writes(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        validator = (ROOT / "references" / "discussion-validator.md").read_text(encoding="utf-8")

        self.assertIn("duplicate protection incomplete", skill)
        self.assertIn("head_ref_oid", skill)
        self.assertIn("resolved-but-recurring", validator)
        self.assertIn("related-but-distinct", validator)
        self.assertIn("explicit human action", validator)

    def test_skill_treats_missing_openspec_by_change_intent(self) -> None:
        briefing = (ROOT / "references" / "briefing-agent.md").read_text(encoding="utf-8")

        self.assertIn("restorative bug fix", briefing)
        self.assertIn("behavior-changing", briefing)
        self.assertIn("OpenSpec", briefing)

    def test_skill_explains_change_shape_and_small_diffs(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        briefing = (ROOT / "references" / "briefing-agent.md").read_text(encoding="utf-8")

        self.assertIn("Lines changed", skill)
        self.assertIn("50", skill)
        self.assertIn("show the code", skill)
        self.assertIn("Classes and structural units", skill)
        self.assertIn("added", briefing)
        self.assertIn("modified", briefing)
        self.assertIn("deleted", briefing)

    def test_skill_requires_inline_database_changes_and_focused_mermaid(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        briefing = (ROOT / "references" / "briefing-agent.md").read_text(encoding="utf-8")

        self.assertIn("Database changes", skill)
        self.assertIn("Mermaid", skill)
        self.assertIn("tables", briefing)
        self.assertIn("columns", briefing)
        self.assertIn("indexes", briefing)
        self.assertIn("foreign keys", briefing)
        self.assertIn("Omit `Database changes`", skill)

    def test_publication_ids_and_routes_are_pr_scoped_and_deterministic(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        validator = (ROOT / "references" / "discussion-validator.md").read_text(encoding="utf-8")

        self.assertIn("scripts/prepare_review_actions.py", skill)
        self.assertIn("owner/repo#123:E1", skill)
        self.assertIn("Bare candidate IDs", skill)
        self.assertIn("active review target", skill)
        self.assertIn("thread_id", validator)
        self.assertIn("review_pr", validator)
        self.assertIn("owning_repository", validator)


if __name__ == "__main__":
    unittest.main()
