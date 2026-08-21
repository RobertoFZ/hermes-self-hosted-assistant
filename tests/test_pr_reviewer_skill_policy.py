import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = (ROOT / "skills" / "pr-reviewer" / "SKILL.md").read_text(
    encoding="utf-8"
)
WORKFLOW = (
    ROOT / "skills" / "pr-reviewer" / "references" / "workflow.md"
).read_text(encoding="utf-8")
GH_RUNBOOK = (
    ROOT / "skills" / "pr-reviewer" / "references" / "gh-runbook.md"
).read_text(encoding="utf-8")


class PRReviewerSkillPolicyTests(unittest.TestCase):
    def test_scratch_artifacts_stay_inside_hermes_safe_root(self):
        for content in (SKILL, WORKFLOW, GH_RUNBOOK):
            self.assertIn("/opt/data/pr-reviewer-tmp", content)
            self.assertIn("/tmp", content)

    def test_runbook_does_not_weaken_write_boundary(self):
        self.assertIn("do not create a payload file", GH_RUNBOOK)
        self.assertIn("Do not unset or broaden", GH_RUNBOOK)
        self.assertNotIn("HERMES_WRITE_SAFE_ROOT=/opt/data:/tmp", GH_RUNBOOK)

    def test_openspec_reviews_validate_without_mutating(self):
        self.assertIn("run strict validation", SKILL)
        self.assertIn("openspec validate <change-name> --strict", WORKFLOW)
        for command in ("init", "update", "archive"):
            self.assertIn(f"`openspec {command}`", SKILL)
            self.assertIn(f"`openspec {command}`", WORKFLOW)


if __name__ == "__main__":
    unittest.main()
