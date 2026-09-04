from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def load_module() -> ModuleType:
    path = ROOT / "scripts" / "collect_pr_context.py"
    spec = importlib.util.spec_from_file_location("collect_pr_context", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CollectPrContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.collector = load_module()

    def test_preserves_complete_discussion_history_including_resolved_threads(self) -> None:
        threads = [
            {
                "id": "RT_open",
                "isResolved": False,
                "isOutdated": False,
                "path": "src/retry.ts",
                "line": 12,
                "comments": {
                    "nodes": [
                        {
                            "id": "RC_open",
                            "databaseId": 101,
                            "body": "Could this enqueue twice?",
                            "url": "https://example.test/open",
                            "createdAt": "2026-09-01T12:00:00Z",
                            "author": {"login": "ana"},
                            "replyTo": None,
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            },
            {
                "id": "RT_resolved",
                "isResolved": True,
                "isOutdated": True,
                "path": "src/retry.ts",
                "line": 8,
                "comments": {
                    "nodes": [
                        {
                            "id": "RC_resolved",
                            "databaseId": 102,
                            "body": "Use the existing retry policy.",
                            "url": "https://example.test/resolved",
                            "createdAt": "2026-08-31T12:00:00Z",
                            "author": {"login": "luis"},
                            "replyTo": None,
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            },
        ]

        result = self.collector.normalize_discussions(threads)

        self.assertEqual([row["thread_id"] for row in result["review_threads"]], ["RT_open", "RT_resolved"])
        self.assertFalse(result["review_threads"][0]["is_resolved"])
        self.assertTrue(result["review_threads"][1]["is_resolved"])
        self.assertTrue(result["complete"])

    def test_preserves_submitted_reviews_and_pr_level_comments(self) -> None:
        reviews = [
            {
                "id": "PRR_1",
                "databaseId": 201,
                "state": "COMMENTED",
                "body": "The migration order is intentional.",
                "url": "https://example.test/review",
                "submittedAt": "2026-09-01T12:00:00Z",
                "author": {"login": "ana"},
                "commit": {"oid": "a" * 40},
            }
        ]
        pr_comments = [
            {
                "id": "IC_1",
                "databaseId": 301,
                "body": "This follows OpenSpec change cancellation-reasons.",
                "url": "https://example.test/comment",
                "createdAt": "2026-09-01T13:00:00Z",
                "author": {"login": "luis"},
            }
        ]

        result = self.collector.normalize_discussions([], reviews, pr_comments)

        self.assertEqual(result["reviews"][0]["body"], "The migration order is intentional.")
        self.assertEqual(result["reviews"][0]["commit_oid"], "a" * 40)
        self.assertEqual(result["pr_comments"][0]["body"], "This follows OpenSpec change cancellation-reasons.")
        self.assertTrue(result["complete"])

    def test_marks_all_discussion_sources_incomplete(self) -> None:
        result = self.collector.normalize_discussions(
            [],
            [],
            [],
            limitations=["reviews-incomplete", "pr-comments-incomplete"],
        )

        self.assertFalse(result["complete"])
        self.assertEqual(result["limitations"], ["reviews-incomplete", "pr-comments-incomplete"])

    def test_unavailable_thread_api_reduces_duplicate_protection_instead_of_stopping(self) -> None:
        def unavailable() -> list[dict[str, object]]:
            raise RuntimeError("reviewThreads denied")

        rows, limitations = self.collector.safe_collection("review-threads", unavailable)

        self.assertEqual(rows, [])
        self.assertEqual(limitations, ["review-threads-unavailable:reviewThreads denied"])

    def test_marks_discussion_history_incomplete_when_thread_comments_are_truncated(self) -> None:
        threads = [
            {
                "id": "RT_large",
                "isResolved": False,
                "comments": {
                    "nodes": [],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                },
            }
        ]

        result = self.collector.normalize_discussions(threads)

        self.assertFalse(result["complete"])
        self.assertEqual(result["limitations"], ["thread-comments-incomplete:RT_large"])

    def test_extracts_gitlink_relationships_without_child_repository_content(self) -> None:
        diff = """diff --git a/services/payments b/services/payments
index 1111111..2222222 160000
--- a/services/payments
+++ b/services/payments
@@ -1 +1 @@
-Subproject commit 1111111111111111111111111111111111111111
+Subproject commit 2222222222222222222222222222222222222222
diff --git a/README.md b/README.md
index 3333333..4444444 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-Old
+New
"""

        result = self.collector.extract_gitlink_changes(diff)

        self.assertEqual(
            result,
            [
                {
                    "path": "services/payments",
                    "old_oid": "1" * 40,
                    "new_oid": "2" * 40,
                }
            ],
        )

    def test_builds_deterministic_line_counts_and_marks_exactly_fifty_lines_as_small(self) -> None:
        metadata = {
            "additions": 32,
            "deletions": 18,
            "changedFiles": 4,
            "files": [{"path": "ignored.py", "additions": 999, "deletions": 999}],
        }

        result = self.collector.build_change_summary(metadata, "")

        self.assertEqual(
            result,
            {
                "additions": 32,
                "deletions": 18,
                "changed_lines": 50,
                "changed_files": 4,
                "small_change": True,
                "show_code_by_default": True,
                "source": "github-metadata",
            },
        )

    def test_falls_back_to_patch_counts_and_keeps_larger_changes_private(self) -> None:
        diff = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,52 @@
-old_one
-old_two
""" + "\n".join(f"+new_{index}" for index in range(50)) + "\n"

        result = self.collector.build_change_summary({}, diff)

        self.assertEqual(result["additions"], 50)
        self.assertEqual(result["deletions"], 2)
        self.assertEqual(result["changed_lines"], 52)
        self.assertEqual(result["changed_files"], 1)
        self.assertFalse(result["small_change"])
        self.assertFalse(result["show_code_by_default"])
        self.assertEqual(result["source"], "patch")

    def test_stack_context_is_metadata_only_and_target_layer_by_default(self) -> None:
        payload = {
            "trunk": "main",
            "currentBranch": "backfill",
            "branches": [
                {"name": "migration", "isCurrent": False, "pr": {"number": 40, "url": "https://example.test/40", "state": "OPEN"}},
                {"name": "backfill", "isCurrent": True, "pr": {"number": 41, "url": "https://example.test/41", "state": "OPEN"}},
                {"name": "read-switch", "isCurrent": False, "pr": {"number": 42, "url": "https://example.test/42", "state": "OPEN"}},
            ],
        }

        result = self.collector.normalize_stack(payload, "41")

        self.assertEqual(result["scope"], "target-layer")
        self.assertEqual(result["target"]["pr_number"], 41)
        self.assertEqual([row["pr_number"] for row in result["layers"]], [40, 41, 42])
        self.assertNotIn("diff", result["layers"][0])
        self.assertNotIn("files", result["layers"][0])

    def test_discussion_only_collection_writes_no_diff_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata_path = root / "metadata.json"
            threads_path = root / "threads.json"
            output_dir = root / "output"
            metadata_path.write_text(
                json.dumps(
                    {
                        "number": 41,
                        "title": "Backfill cancellation reasons",
                        "url": "https://example.test/41",
                        "headRefOid": "a" * 40,
                        "reviews": [],
                        "comments": [],
                    }
                ),
                encoding="utf-8",
            )
            threads_path.write_text("[]", encoding="utf-8")

            completed = subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts" / "collect_pr_context.py"),
                    "--repository",
                    "acme/platform",
                    "--pr",
                    "41",
                    "--output-dir",
                    str(output_dir),
                    "--metadata-fixture",
                    str(metadata_path),
                    "--threads-fixture",
                    str(threads_path),
                    "--discussion-only",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse((output_dir / "diff.patch").exists())
            context = json.loads((output_dir / "context.json").read_text(encoding="utf-8"))
            self.assertEqual(context["collection_mode"], "discussion-only")
            self.assertEqual(context["gitlinks"], [])
            self.assertEqual(context["stack"]["status"], "not-collected")


if __name__ == "__main__":
    unittest.main()
