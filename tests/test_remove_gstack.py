import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "remove_gstack.py"


class RemoveGstackTests(unittest.TestCase):
    def test_removes_only_gstack_entries_from_selected_roots(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            codex_root = base / ".codex" / "skills"
            agents_root = base / ".agents" / "skills"
            codex_root.mkdir(parents=True)
            agents_root.mkdir(parents=True)

            (codex_root / "gstack").mkdir()
            (codex_root / "gstack-review").mkdir()
            (agents_root / "gstack-plan").symlink_to(base / "missing-gstack-plan")
            (codex_root / "pr-reviewer").mkdir()
            (agents_root / "compound-engineering").mkdir()

            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--root",
                    str(codex_root),
                    "--root",
                    str(agents_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((codex_root / "gstack").exists())
            self.assertFalse((codex_root / "gstack-review").exists())
            self.assertFalse((agents_root / "gstack-plan").is_symlink())
            self.assertTrue((codex_root / "pr-reviewer").is_dir())
            self.assertTrue((agents_root / "compound-engineering").is_dir())

            check = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--check",
                    "--root",
                    str(codex_root),
                    "--root",
                    str(agents_root),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 0, check.stdout)

    def test_check_reports_gstack_without_removing_it(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            entry = root / "gstack-qa"
            entry.mkdir()

            result = subprocess.run(
                ["python3", str(SCRIPT), "--check", "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn(str(entry), result.stdout)
            self.assertTrue(entry.is_dir())


if __name__ == "__main__":
    unittest.main()
