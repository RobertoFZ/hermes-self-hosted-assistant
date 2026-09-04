from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def load_module() -> ModuleType:
    path = ROOT / "scripts" / "discover_prs.py"
    spec = importlib.util.spec_from_file_location("discover_prs", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DiscoverPrsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.discovery = load_module()

    def test_defaults_to_ready_pull_requests_without_our_approval(self) -> None:
        pull_requests = [
            {
                "number": 1,
                "title": "Own change",
                "author": {"login": "reviewer"},
                "url": "https://example.test/1",
                "isDraft": False,
                "reviewDecision": "REVIEW_REQUIRED",
                "latestReviews": [],
            },
            {
                "number": 2,
                "title": "Ready and new",
                "author": {"login": "ana"},
                "url": "https://example.test/2",
                "isDraft": False,
                "reviewDecision": "REVIEW_REQUIRED",
                "latestReviews": [],
            },
            {
                "number": 3,
                "title": "Ready and previously commented",
                "author": {"login": "luis"},
                "url": "https://example.test/3",
                "isDraft": False,
                "reviewDecision": "CHANGES_REQUESTED",
                "latestReviews": [{"author": {"login": "reviewer"}, "state": "COMMENTED"}],
            },
            {
                "number": 4,
                "title": "Already approved",
                "author": {"login": "marta"},
                "url": "https://example.test/4",
                "isDraft": False,
                "reviewDecision": "APPROVED",
                "latestReviews": [{"author": {"login": "reviewer"}, "state": "APPROVED"}],
            },
            {
                "number": 5,
                "title": "Draft",
                "author": {"login": "zoe"},
                "url": "https://example.test/5",
                "isDraft": True,
                "reviewDecision": None,
                "latestReviews": [],
            },
        ]

        result = self.discovery.build_result("acme/platform", "reviewer", pull_requests)

        self.assertEqual([row["number"] for row in result["pull_requests"]], [2, 3, 4, 5])
        self.assertEqual(result["default_selection"], [2, 3])
        self.assertEqual(result["pull_requests"][1]["our_review_state"], "reviewed-by-us")
        self.assertFalse(result["pull_requests"][2]["default_selected"])

    def test_emits_only_minimal_selection_fields(self) -> None:
        pull_request = {
            "number": 8,
            "title": "Add checkout retry",
            "body": "Large body that must not enter discovery output",
            "author": {"login": "ana"},
            "url": "https://example.test/8",
            "isDraft": False,
            "reviewDecision": "REVIEW_REQUIRED",
            "updatedAt": "2026-09-04T12:00:00Z",
            "reviewRequests": [{"login": "reviewer"}],
            "latestReviews": [],
            "files": [{"path": "src/retry.ts"}],
        }

        result = self.discovery.build_result("acme/platform", "reviewer", [pull_request])

        self.assertEqual(
            set(result["pull_requests"][0]),
            {
                "number",
                "title",
                "author",
                "url",
                "is_draft",
                "review_decision",
                "our_review_state",
                "default_selected",
            },
        )

    def test_dismissed_review_does_not_count_as_reviewed(self) -> None:
        pull_request = {
            "number": 9,
            "title": "Retry behavior",
            "author": {"login": "ana"},
            "url": "https://example.test/9",
            "isDraft": False,
            "reviewDecision": "REVIEW_REQUIRED",
            "latestReviews": [{"author": {"login": "reviewer"}, "state": "DISMISSED"}],
        }

        result = self.discovery.build_result("acme/platform", "reviewer", [pull_request])

        self.assertEqual(result["pull_requests"][0]["our_review_state"], "not-reviewed-by-us")
        self.assertTrue(result["pull_requests"][0]["default_selected"])


if __name__ == "__main__":
    unittest.main()
