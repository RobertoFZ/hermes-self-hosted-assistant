import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
CODEX_SKILLS = (
    "codex-self-review",
    "pr-reviewer",
    "pr-decision-review",
    "writing-for-agents",
    "retro",
    "setup-company-brain-retros",
    "publish-company-brain-retro",
)
RETIRED_CODEX_SKILLS = (
    "auto-pr-workflow",
    "linear-ticket-selection",
    "merge-pr-and-clean-worktree",
    "prepare-branch-for-pr",
    "publish-ready-pr",
    "ticket-openspec-planning",
)


class GlobalSkillInstallerTests(unittest.TestCase):
    def test_installer_links_repo_managed_skills_and_preserves_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / "codex-home"
            skills_home = codex_home / "skills"
            conflicting = codex_home / "skills" / "pr-reviewer"
            conflicting.mkdir(parents=True)
            (conflicting / "marker").write_text("preserve me", encoding="utf-8")
            for skill_name in RETIRED_CODEX_SKILLS:
                (skills_home / skill_name).symlink_to(ROOT / "skills" / skill_name)

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

            for skill_name in CODEX_SKILLS:
                installed = skills_home / skill_name
                self.assertTrue(installed.is_symlink(), skill_name)
                self.assertEqual(
                    installed.resolve(),
                    (ROOT / "skills" / skill_name).resolve(),
                )
            for skill_name in RETIRED_CODEX_SKILLS:
                retired = skills_home / skill_name
                self.assertFalse(retired.exists(), skill_name)
                self.assertFalse(retired.is_symlink(), skill_name)

            backups = list(skills_home.glob("pr-reviewer.backup.*"))
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
                len(list(skills_home.glob("*.backup.*"))),
                1,
            )
            for skill_name in CODEX_SKILLS:
                installed = skills_home / skill_name
                self.assertTrue(installed.is_symlink(), skill_name)
                self.assertEqual(
                    installed.resolve(),
                    (ROOT / "skills" / skill_name).resolve(),
                )
            for skill_name in RETIRED_CODEX_SKILLS:
                retired = skills_home / skill_name
                self.assertFalse(retired.exists(), skill_name)
                self.assertFalse(retired.is_symlink(), skill_name)

    def test_installer_preserves_non_repository_retired_name_installations(self):
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory) / "codex-home"
            skills_home = codex_home / "skills"
            skills_home.mkdir(parents=True)

            external_skill = Path(directory) / "external-skill"
            external_skill.mkdir()
            nonmatching_symlink = skills_home / "auto-pr-workflow"
            nonmatching_symlink.symlink_to(external_skill)

            real_directory = skills_home / "linear-ticket-selection"
            real_directory.mkdir()
            (real_directory / "marker").write_text("directory", encoding="utf-8")

            real_file = skills_home / "merge-pr-and-clean-worktree"
            real_file.write_text("file", encoding="utf-8")

            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)
            subprocess.run(
                [str(ROOT / "scripts" / "install-global-skill.sh")],
                cwd=ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertTrue(nonmatching_symlink.is_symlink())
            self.assertEqual(os.readlink(nonmatching_symlink), str(external_skill))
            self.assertEqual(
                (real_directory / "marker").read_text(encoding="utf-8"),
                "directory",
            )
            self.assertEqual(real_file.read_text(encoding="utf-8"), "file")


if __name__ == "__main__":
    unittest.main()
