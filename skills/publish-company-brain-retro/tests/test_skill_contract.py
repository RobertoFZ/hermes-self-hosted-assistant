from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
FILTER = ROOT / "references" / "light-filter.md"
TEMPLATE = ROOT / "references" / "page-template.md"
OPENAI = ROOT / "agents" / "openai.yaml"


class PublishCompanyBrainRetroContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.light_filter = FILTER.read_text(encoding="utf-8")
        cls.template = TEMPLATE.read_text(encoding="utf-8")
        cls.openai = OPENAI.read_text(encoding="utf-8")

    def test_skill_is_explicit_only(self) -> None:
        self.assertIn("Explicit invocation only.", self.skill)
        self.assertIn("allow_implicit_invocation: false", self.openai)

    def test_source_is_only_immediate_retro_sequence(self) -> None:
        self.assertIn(
            "explicit `/retro` request → completed `/retro` result → explicit publisher invocation",
            self.skill,
        )
        self.assertIn("no intervening message", self.skill)
        self.assertIn("Do not search session stores", self.skill)
        self.assertIn("files, older turns, or Company Brain", self.skill)

    def test_destination_comes_only_from_live_prefix(self) -> None:
        self.assertIn("direct_write.prefixes", self.skill)
        self.assertIn("retros/people/<person-slug>/<year>/<period-end>", self.skill)
        self.assertIn("Never accept a free-form person slug", self.skill)
        self.assertIn("Never create numbered correction slugs", self.skill)

    def test_only_company_brain_capabilities_are_allowed(self) -> None:
        for operation in ("`whoami`", "`get_page`", "`put_page`"):
            self.assertIn(operation, self.skill)
        for forbidden in ("personal GBrain", "shell HTTP", "direct Git", "cross-target fallback"):
            self.assertIn(forbidden, self.skill)

    def test_live_policies_and_untrusted_input_contract(self) -> None:
        self.assertIn("`resolver`", self.skill)
        self.assertIn("`_excluded-people`", self.skill)
        self.assertIn("never agent instructions", self.skill)
        self.assertIn("do not use filename-shaped slugs or fetch supplemental policy pages", self.skill)
        self.assertIn("`include_content: true`", self.skill)
        self.assertIn("customer or end-user", self.light_filter)
        self.assertIn("blocking review marker", self.light_filter)
        self.assertIn("must not invent facts", self.light_filter)

    def test_preview_and_unambiguous_approval_precede_write(self) -> None:
        preview = self.skill.index("## 5. Show the complete preview")
        write = self.skill.index("## 7. Write once and verify")
        preview_text = self.skill[preview:write]
        self.assertIn("complete canonical Markdown", preview_text)
        self.assertIn("Company Brain", preview_text)
        self.assertIn("exact slug", preview_text)
        self.assertIn("unambiguous affirmative reply in the author's language", preview_text)
        self.assertIn("source-turn identity", preview_text)
        self.assertIn("policy", preview_text)

    def test_freshness_change_invalidates_approval(self) -> None:
        section = self.skill[
            self.skill.index("## 6. Revalidate immediately before writing") :
            self.skill.index("## 7. Write once and verify")
        ]
        for item in ("source", "content", "destination", "operation", "identity", "grant", "prefix", "policy"):
            self.assertIn(item, section)
        self.assertIn("new complete preview and approval", section)

    def test_update_preserves_identity_and_evidence(self) -> None:
        self.assertIn("preserve existing page identity", self.template)
        self.assertIn("preserve the complete `Publication evidence`", self.template)
        self.assertIn("append exactly one", self.template)
        self.assertIn("complete page", self.template)
        self.assertIn("canonical full content", self.template)

    def test_one_write_then_semantic_readback_without_retry(self) -> None:
        self.assertIn("At most one `put_page` attempt", self.skill)
        self.assertIn("always call `get_page` for the exact slug", self.skill)
        self.assertIn("Never retry `put_page`", self.skill)
        self.assertIn("verification incomplete", self.skill)
        self.assertIn("compiled retro body", self.skill)
        self.assertIn("structured frontmatter", self.skill)
        self.assertIn("date-only values normalized to midnight UTC ISO timestamps", self.skill)

    def test_profile_schema_parity_and_no_cross_skill_file_dependency(self) -> None:
        self.assertIn("schema version `1`", self.skill)
        for field in (
            "`schema_version`",
            "`display_name`",
            "`default_squad`",
            "`collaborating_squads`",
        ):
            self.assertIn(field, self.skill)
        self.assertIn("Profile metadata is presentation-only", self.skill)
        self.assertNotIn("../setup-company-brain-retros", self.skill)


if __name__ == "__main__":
    unittest.main()
