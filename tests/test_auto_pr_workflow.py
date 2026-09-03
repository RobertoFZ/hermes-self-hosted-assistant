import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
AUTO_PR_SKILL = (ROOT / "skills" / "auto-pr-workflow" / "SKILL.md").read_text(
    encoding="utf-8"
)
AUTO_PR_WORKFLOW = (
    ROOT / "skills" / "auto-pr-workflow" / "references" / "workflow.md"
).read_text(encoding="utf-8")
PREPARE_BRANCH = (
    ROOT / "skills" / "prepare-branch-for-pr" / "SKILL.md"
).read_text(encoding="utf-8")

WORKFLOW_SKILLS = (
    "auto-pr-workflow",
    "linear-ticket-selection",
    "ticket-openspec-planning",
    "prepare-branch-for-pr",
    "publish-ready-pr",
    "merge-pr-and-clean-worktree",
    "codex-self-review",
    "pr-reviewer",
)


class AutoPRWorkflowTests(unittest.TestCase):
    def test_dependency_preflight_precedes_ticket_discovery(self):
        preflight = AUTO_PR_SKILL.index("dependency preflight")
        ticket_selection = AUTO_PR_SKILL.index("Invoke `$linear-ticket-selection`")
        self.assertLess(preflight, ticket_selection)
        for dependency in (
            "$openspec-propose",
            "$openspec-apply-change",
            "$codex-self-review",
            "$pr-reviewer",
            "$bootstrap",
            "$repo-git-workflow-guidance",
        ):
            self.assertIn(dependency, AUTO_PR_WORKFLOW)

    def test_prepare_branch_requests_explicit_local_review_handoff(self):
        self.assertIn("explicitly in read-only `local_pre_pr` mode", PREPARE_BRANCH)
        self.assertIn("required-check evidence", PREPARE_BRANCH)
        self.assertIn("structured `pre_pr_review`", PREPARE_BRANCH)
        self.assertIn("`reviewed_head` equals", PREPARE_BRANCH)

    def test_installer_links_complete_workflow_bundle_and_preserves_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / "codex-home"
            conflicting = codex_home / "skills" / "pr-reviewer"
            conflicting.mkdir(parents=True)
            (conflicting / "marker").write_text("preserve me", encoding="utf-8")

            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)
            result = subprocess.run(
                [str(ROOT / "scripts" / "install-global-skill.sh")],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            for skill_name in WORKFLOW_SKILLS:
                installed = codex_home / "skills" / skill_name
                self.assertTrue(installed.is_symlink(), skill_name)
                self.assertEqual(
                    installed.resolve(),
                    (ROOT / "skills" / skill_name).resolve(),
                )

            backups = list((codex_home / "skills").glob("pr-reviewer.backup.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(
                (backups[0] / "marker").read_text(encoding="utf-8"),
                "preserve me",
            )
            self.assertIn("Restart Codex", result.stdout)

            subprocess.run(
                [str(ROOT / "scripts" / "install-global-skill.sh")],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                len(list((codex_home / "skills").glob("*.backup.*"))),
                1,
            )


if __name__ == "__main__":
    unittest.main()
