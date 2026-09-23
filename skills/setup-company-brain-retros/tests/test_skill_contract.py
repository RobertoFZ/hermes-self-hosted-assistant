from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
PROFILE = ROOT / "references" / "profile.md"
MCP_SETUP = ROOT / "references" / "company-brain-mcp-setup.md"
OPENAI = ROOT / "agents" / "openai.yaml"
README = ROOT / "README.md"


class SetupCompanyBrainRetrosContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.profile = PROFILE.read_text(encoding="utf-8")
        cls.mcp_setup = MCP_SETUP.read_text(encoding="utf-8")
        cls.openai = OPENAI.read_text(encoding="utf-8")
        cls.readme = README.read_text(encoding="utf-8")

    def test_skill_is_explicit_only_and_reports_one_terminal_state(self) -> None:
        self.assertIn("Explicit invocation only.", self.skill)
        self.assertIn("allow_implicit_invocation: false", self.openai)
        self.assertIn("READY", self.skill)
        self.assertIn("NOT READY", self.skill)

    def test_setup_checks_external_dependencies_without_invoking_them(self) -> None:
        for dependency in ("retro", "writing-for-agents"):
            command = f"mattpocock/skills --skill {dependency}"
            self.assertIn(command, self.skill)
            self.assertIn(command, self.readme)
        self.assertIn("publish-company-brain-retro", self.skill)
        self.assertIn("Do not invoke any dependency", self.skill)

    def test_missing_mcp_routes_to_portable_host_setup(self) -> None:
        endpoint = "https://company-brain.reservamos.com/mcp"

        self.assertIn("references/company-brain-mcp-setup.md", self.skill)
        self.assertIn("help the author register", self.skill)
        self.assertIn(endpoint, self.mcp_setup)
        self.assertIn(endpoint, self.readme)
        for host in ("Claude Code", "Codex", "Cursor", "OpenCode", "Kimi Code", "Pi"):
            self.assertIn(host, self.mcp_setup)
        self.assertIn("does not use generic MCP registration", self.mcp_setup)
        self.assertNotIn("automations-team", self.mcp_setup)

    def test_live_oauth_identity_is_the_only_authority(self) -> None:
        self.assertIn("OAuth transport", self.skill)
        self.assertIn("effective `read` and `write` scopes", self.skill)
        self.assertIn("direct_write.prefixes", self.skill)
        self.assertIn("exactly one", self.skill)
        self.assertIn("retros/people/<person-slug>/", self.skill)
        self.assertNotIn("person_slug:", self.profile)

    def test_policies_use_only_exact_live_slugs(self) -> None:
        self.assertIn("`resolver`", self.skill)
        self.assertIn("`_excluded-people`", self.skill)
        self.assertIn("`include_content: true`", self.skill)
        self.assertIn("Reject filename-shaped policy slugs", self.skill)
        self.assertIn("resolver allows the derived person-retro path", self.skill)
        self.assertNotIn("get_page(`RESOLVER.md`)", self.skill)
        self.assertNotIn("operator", self.skill.lower())
        self.assertNotIn("operator", self.mcp_setup.lower())

    def test_profile_contract_is_minimal_atomic_and_private(self) -> None:
        for field in (
            "schema_version",
            "display_name",
            "default_squad",
            "collaborating_squads",
        ):
            self.assertIn(field, self.profile)
        for forbidden in ("token", "credential", "retro body", "policy body", "write prefix"):
            self.assertIn(forbidden, self.profile.lower())
        self.assertIn("exact allowlist", self.profile)
        self.assertIn("atomic", self.profile.lower())
        self.assertIn("0600", self.profile)
        self.assertIn("never silently merge", self.profile.lower())
        self.assertIn("dependency-free YAML handling", self.profile)
        self.assertIn("do not leave helper scripts or scratchpad artifacts", self.profile)
        self.assertIn("may be retried once", self.profile)
        self.assertIn("destination bytes and mode are unchanged", self.profile)

    def test_ready_output_stays_user_facing(self) -> None:
        self.assertIn("Keep client IDs, policy hashes, and raw `whoami` remediation out", self.skill)
        self.assertIn("Do not infer that the user must reauthenticate from `expires_at` alone", self.skill)

    def test_setup_never_writes_company_brain(self) -> None:
        self.assertIn("zero Company Brain writes", self.skill)
        self.assertIn("Do not create a probe page", self.skill)


if __name__ == "__main__":
    unittest.main()
