from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def load_module() -> ModuleType:
    path = ROOT / "scripts" / "resolve_gitlink_prs.py"
    spec = importlib.util.spec_from_file_location("resolve_gitlink_prs", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResolveGitlinkPrsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = load_module()

    def test_resolves_common_github_remote_forms_without_entering_submodule(self) -> None:
        self.assertEqual(
            self.resolver.github_repository("git@github.com:acme/payments.git", "acme/platform"),
            "acme/payments",
        )
        self.assertEqual(
            self.resolver.github_repository("https://github.com/acme/web.git", "acme/platform"),
            "acme/web",
        )
        self.assertEqual(
            self.resolver.github_repository("../contracts.git", "acme/platform"),
            "acme/contracts",
        )

    def test_related_pr_output_contains_metadata_only(self) -> None:
        pull_request = {
            "number": 72,
            "title": "Add retry backfill",
            "html_url": "https://github.com/acme/payments/pull/72",
            "state": "open",
            "draft": False,
            "body": "Must not be copied",
            "diff_url": "https://example.test/diff",
            "head": {"sha": "a" * 40},
        }

        result = self.resolver.minimal_pull_request(pull_request)

        self.assertEqual(
            result,
            {
                "number": 72,
                "title": "Add retry backfill",
                "url": "https://github.com/acme/payments/pull/72",
                "state": "OPEN",
                "is_draft": False,
                "head_oid": "a" * 40,
            },
        )


if __name__ == "__main__":
    unittest.main()
