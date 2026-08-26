from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from automation import review_automation as automation


class ReviewAutomationTests(unittest.TestCase):
    def test_exact_pr_urls_and_repository_allowlist_are_enforced(self):
        with patch.dict(
            os.environ,
            {"SLACK_REVIEW_ALLOWED_REPOSITORIES": "acme/api"},
            clear=False,
        ):
            self.assertEqual(
                automation.parse_pr_url("https://github.com/acme/api/pull/42"),
                ("acme/api", 42),
            )
            with self.assertRaises(automation.AutomationError):
                automation.parse_pr_url("https://github.com/acme/other/pull/42")
            with self.assertRaises(automation.AutomationError):
                automation.parse_pr_url("https://github.com/acme/api/pull/42/files")

    def test_verified_review_is_idempotent_and_available_to_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/42",
                repo="acme/api",
                number=42,
                title="Fix pricing boundary",
                body="Linear: REV-42",
                head_sha="a" * 40,
                base_ref="main",
                author_login="developer",
            )
            with automation.connect_db(database) as db:
                run_id = automation.insert_run(db, pr, "review-bot", "running")
                result = {
                    "summary": "Approved after verifying the boundary case.",
                    "findings": [
                        {
                            "category": "testing",
                            "severity": "low",
                            "path": "tests/test_price.py",
                            "line": 20,
                            "body": "The regression case is covered.",
                            "blocking": False,
                        }
                    ],
                    "linear": {
                        "fetch_status": "available",
                        "key": "REV-42",
                        "title": "Correct pricing boundary",
                        "url": "https://linear.app/acme/issue/REV-42",
                        "status": "In Review",
                        "project": "Pricing",
                        "product_summary": "Avoid an incorrect boundary fare.",
                        "acceptance_criteria": ["Boundary fare is stable"],
                        "labels": ["bug"],
                    },
                }
                publications = {
                    "reviews": [
                        {
                            "id": 101,
                            "state": "APPROVED",
                            "html_url": "https://github.com/acme/api/pull/42#pullrequestreview-101",
                            "submitted_at": "2026-08-26T20:00:00Z",
                        }
                    ],
                    "comments": [],
                }
                automation.persist_verified(db, run_id, result, publications)
                self.assertTrue(automation.verified_run_exists(db, pr, "review-bot"))

            digest = automation.digest_source(
                str(database),
                hours=24,
                timezone_name="America/Mexico_City",
                now=datetime.now(timezone.utc),
            )
            self.assertEqual(digest["review_count"], 1)
            self.assertEqual(digest["reviews"][0]["event"], "APPROVE")
            self.assertEqual(digest["reviews"][0]["linear"]["key"], "REV-42")
            self.assertEqual(digest["reviews"][0]["findings"][0]["category"], "testing")

    def test_digest_excludes_failed_and_external_skip_records(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/7",
                repo="acme/api",
                number=7,
                title="Unverified",
                body="",
                head_sha="b" * 40,
                base_ref="main",
                author_login="developer",
            )
            with automation.connect_db(database) as db:
                failed = automation.insert_run(db, pr, "review-bot", "running")
                automation.mark_failed(db, failed, "no publication")
                skipped = automation.insert_run(db, pr, "review-bot", "running")
                automation.finish_skipped(db, skipped, "skipped_existing_publication", "external")
            digest = automation.digest_source(str(database))
            self.assertEqual(digest["review_count"], 0)


if __name__ == "__main__":
    unittest.main()
