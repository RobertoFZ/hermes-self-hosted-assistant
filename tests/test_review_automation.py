from __future__ import annotations

import json
import os
import subprocess
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

    def test_self_review_requires_explicit_automation_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/9",
                repo="acme/api",
                number=9,
                title="Owner change",
                body="",
                head_sha="c" * 40,
                base_ref="main",
                author_login="review-bot",
            )
            with automation.connect_db(database) as db, patch.object(
                automation, "load_pr", return_value=pr
            ), patch.object(automation, "invoke_codex") as invoke_codex:
                result = automation.review_one(db, pr.url, "review-bot")

            self.assertEqual(
                result["status"], "skipped_self_review_not_authorized"
            )
            invoke_codex.assert_not_called()

    def test_self_review_can_be_authorized_by_trusted_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/10",
                repo="acme/api",
                number=10,
                title="Owner change",
                body="",
                head_sha="d" * 40,
                base_ref="main",
                author_login="review-bot",
            )
            with automation.connect_db(database) as db, patch.object(
                automation, "load_pr", return_value=pr
            ), patch.object(
                automation,
                "github_publications",
                side_effect=[
                    {"reviews": [], "comments": []},
                    {"reviews": [], "comments": []},
                ],
            ), patch.object(
                automation,
                "invoke_codex",
                side_effect=automation.AutomationError("delegated test stop"),
            ) as invoke_codex, patch.object(
                automation,
                "cleanup_paseo_review_agent",
                return_value=[],
            ) as cleanup_agent:
                result = automation.review_one(
                    db,
                    pr.url,
                    "review-bot",
                    allow_self_review=True,
                )

            self.assertEqual(result["status"], "failed")
            delegated_run_id = invoke_codex.call_args.kwargs["run_id"]
            invoke_codex.assert_called_once_with(pr, run_id=delegated_run_id)
            cleanup_agent.assert_called_once_with(delegated_run_id)

    def test_cleanup_deletes_only_agents_with_the_review_run_label(self):
        listed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                [
                    {"id": "agent-one", "name": "review"},
                    {"id": "agent-two", "name": "review retry"},
                ]
            ),
            stderr="",
        )
        deleted = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="{}", stderr=""
        )
        with patch.dict(os.environ, {"PASEO_HOST": "paseo:6767"}), patch.object(
            automation,
            "run",
            side_effect=[listed, deleted, deleted],
        ) as run_command:
            warnings = automation.cleanup_paseo_review_agent("run-123")

        self.assertEqual(warnings, [])
        self.assertEqual(
            run_command.call_args_list[0].args[0],
            [
                "paseo",
                "ls",
                "--host",
                "paseo:6767",
                "--all",
                "--global",
                "--label",
                "hermes-review-run=run-123",
                "--json",
            ],
        )
        self.assertEqual(
            run_command.call_args_list[1].args[0],
            [
                "paseo",
                "delete",
                "--host",
                "paseo:6767",
                "--json",
                "agent-one",
            ],
        )
        self.assertEqual(
            run_command.call_args_list[2].args[0][-1],
            "agent-two",
        )

    def test_invoke_codex_labels_the_review_agent(self):
        pr = automation.PullRequest(
            url="https://github.com/acme/api/pull/11",
            repo="acme/api",
            number=11,
            title="Labeled review",
            body="",
            head_sha="e" * 40,
            base_ref="main",
            author_login="developer",
        )
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"repo": "acme/api"}', stderr=""
        )
        with patch.dict(
            os.environ,
            {
                "PASEO_HOST": "paseo:6767",
                "REVIEW_MONOREPO_ROOT": "/workspace",
                "REVIEW_PASEO_TIMEOUT": "45m",
            },
        ), patch.object(automation, "run", return_value=completed) as run_command:
            result = automation.invoke_codex(pr, run_id="run-456")

        self.assertEqual(result, {"repo": "acme/api"})
        command = run_command.call_args.args[0]
        label_index = command.index("--label")
        self.assertEqual(command[label_index + 1], "hermes-review-run=run-456")


if __name__ == "__main__":
    unittest.main()
