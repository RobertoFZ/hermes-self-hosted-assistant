from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from automation import review_automation as automation


class ReviewAutomationTests(unittest.TestCase):
    def test_existing_database_migrates_cleanup_state(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with sqlite3.connect(database) as db:
                db.executescript(
                    """
                    CREATE TABLE schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );
                    CREATE TABLE review_runs (
                        id TEXT PRIMARY KEY,
                        requested_at TEXT NOT NULL,
                        completed_at TEXT,
                        repo TEXT NOT NULL,
                        pr_number INTEGER NOT NULL,
                        pr_url TEXT NOT NULL,
                        pr_title TEXT NOT NULL,
                        pr_author TEXT NOT NULL,
                        base_ref TEXT NOT NULL,
                        head_sha TEXT NOT NULL,
                        reviewer_login TEXT NOT NULL,
                        origin TEXT NOT NULL DEFAULT 'hermes-paseo-codex',
                        status TEXT NOT NULL,
                        event TEXT,
                        summary TEXT,
                        error TEXT,
                        structured_result TEXT
                    );
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (1, '2026-08-27T00:00:00+00:00');
                    """
                )

            with automation.connect_db(database) as db:
                columns = {
                    row["name"]
                    for row in db.execute("PRAGMA table_info(review_runs)")
                }
                version = db.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]

        self.assertEqual(version, 2)
        self.assertTrue(
            {
                "cleanup_status",
                "cleanup_attempted_at",
                "cleaned_at",
                "cleanup_error",
            }
            <= columns
        )

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
        deleted_one = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"deletedCount": 1, "agentIds": ["agent-one"]}),
            stderr="",
        )
        deleted_two = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"deletedCount": 1, "agentIds": ["agent-two"]}),
            stderr="",
        )
        verified_empty = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr=""
        )
        with patch.dict(os.environ, {"PASEO_HOST": "paseo:6767"}), patch.object(
            automation,
            "run",
            side_effect=[listed, deleted_one, deleted_two, verified_empty],
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
        self.assertEqual(run_command.call_args_list[3].args[0][1], "ls")

    def test_cleanup_rejects_zero_delete_count_even_on_success_exit(self):
        listed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps([{"id": "agent-one", "status": "closed"}]),
            stderr="",
        )
        not_deleted = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"deletedCount": 0, "agentIds": []}),
            stderr="Warning: Failed to delete agent",
        )
        with patch.object(
            automation,
            "run",
            side_effect=[listed, not_deleted, listed],
        ):
            warnings = automation.cleanup_paseo_review_agent("run-123")

        self.assertTrue(any("did not confirm hard deletion" in item for item in warnings))
        self.assertTrue(any("still exists after deletion" in item for item in warnings))

    def test_cleanup_outcome_is_persisted_without_changing_review_status(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/16",
                repo="acme/api",
                number=16,
                title="Cleanup state",
                body="",
                head_sha="4" * 40,
                base_ref="main",
                author_login="developer",
            )
            with automation.connect_db(database) as db:
                run_id = automation.insert_run(db, pr, "review-bot", "running")
                automation.mark_failed(db, run_id, "review failure")
                with patch.object(
                    automation,
                    "cleanup_paseo_review_agent",
                    return_value=["delete failed"],
                ):
                    warnings = automation.cleanup_review_run(db, run_id)
                failed = db.execute(
                    "SELECT status, cleanup_status, cleanup_error "
                    "FROM review_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                with patch.object(
                    automation, "cleanup_paseo_review_agent", return_value=[]
                ):
                    automation.cleanup_review_run(db, run_id)
                cleaned = db.execute(
                    "SELECT status, cleanup_status, cleaned_at "
                    "FROM review_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()

        self.assertEqual(warnings, ["delete failed"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["cleanup_status"], "failed")
        self.assertIn("delete failed", failed["cleanup_error"])
        self.assertEqual(cleaned["status"], "failed")
        self.assertEqual(cleaned["cleanup_status"], "clean")
        self.assertIsNotNone(cleaned["cleaned_at"])

    def test_terminal_cleanup_reconciles_a_published_run(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/17",
                repo="acme/api",
                number=17,
                title="Published orphan",
                body="",
                head_sha="5" * 40,
                base_ref="main",
                author_login="developer",
            )
            with automation.connect_db(database) as db:
                run_id = automation.insert_run(db, pr, "review-bot", "running")
                db.execute(
                    "UPDATE review_runs SET status = 'published', completed_at = ? "
                    "WHERE id = ?",
                    (automation.iso(automation.utc_now()), run_id),
                )
                db.commit()
            with patch.object(
                automation, "cleanup_paseo_review_agent", return_value=[]
            ) as cleanup_agent:
                result = automation.reconcile_terminal_cleanup(str(database))
            with automation.connect_db(database) as db:
                cleanup_status = db.execute(
                    "SELECT cleanup_status FROM review_runs WHERE id = ?", (run_id,)
                ).fetchone()[0]

        self.assertEqual(result["clean"], 1)
        self.assertEqual(cleanup_status, "clean")
        cleanup_agent.assert_called_once_with(run_id)

    def test_duplicate_request_returns_in_progress_without_second_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/12",
                repo="acme/api",
                number=12,
                title="In-flight review",
                body="",
                head_sha="f" * 40,
                base_ref="main",
                author_login="developer",
            )
            with automation.connect_db(database) as db:
                run_id = automation.insert_run(db, pr, "review-bot", "running")
                with patch.object(automation, "load_pr", return_value=pr), patch.object(
                    automation,
                    "github_publications",
                    return_value={"reviews": [], "comments": []},
                ), patch.object(automation, "invoke_codex") as invoke_codex:
                    result = automation.review_one(db, pr.url, "review-bot")
                count = db.execute(
                    "SELECT COUNT(*) FROM review_runs WHERE head_sha = ?",
                    (pr.head_sha,),
                ).fetchone()[0]

        self.assertEqual(result["status"], "in_progress")
        self.assertEqual(result["run_id"], run_id)
        self.assertEqual(count, 1)
        invoke_codex.assert_not_called()

    def test_interrupted_run_recovers_publication_and_structured_result(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/13",
                repo="acme/api",
                number=13,
                title="Recover review",
                body="",
                head_sha="1" * 40,
                base_ref="main",
                author_login="developer",
            )
            publications = {
                "reviews": [
                    {
                        "id": 313,
                        "state": "COMMENTED",
                        "body": "Recovered review",
                        "html_url": "https://github.com/acme/api/pull/13#review-313",
                        "submitted_at": "2026-08-27T15:55:00Z",
                    }
                ],
                "comments": [],
            }
            structured = {
                "repo": pr.repo,
                "pr_number": pr.number,
                "head_sha": pr.head_sha,
                "event": "COMMENT",
                "published": True,
                "summary": "Recovered complete structured output.",
                "findings": [
                    {
                        "category": "correctness",
                        "severity": "high",
                        "path": "app.py",
                        "line": 13,
                        "body": "The interrupted finding is retained.",
                        "blocking": True,
                    }
                ],
                "linear": {
                    "fetch_status": "available",
                    "key": "REV-13",
                    "title": "Recovery",
                    "url": "https://linear.app/acme/issue/REV-13",
                    "status": "In Review",
                    "project": "Reliability",
                    "product_summary": "Recover interrupted reviews.",
                    "acceptance_criteria": ["Review is retained"],
                    "labels": ["reliability"],
                },
                "limitations": [],
            }
            with automation.connect_db(database) as db:
                run_id = automation.insert_run(db, pr, "review-bot", "running")
                with patch.object(automation, "load_pr", return_value=pr), patch.object(
                    automation,
                    "github_publications",
                    return_value=publications,
                ), patch.object(
                    automation,
                    "list_paseo_review_agents",
                    return_value=([{"id": "agent-13", "status": "closed"}], []),
                ), patch.object(
                    automation,
                    "load_paseo_structured_result",
                    return_value=(structured, []),
                ), patch.object(
                    automation,
                    "cleanup_paseo_review_agent",
                    return_value=[],
                ) as cleanup_agent, patch.object(
                    automation, "invoke_codex"
                ) as invoke_codex:
                    result = automation.review_one(db, pr.url, "review-bot")
                saved = db.execute(
                    "SELECT status, event, summary FROM review_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                finding_count = db.execute(
                    "SELECT COUNT(*) FROM review_findings WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]

        self.assertEqual(result["status"], "published")
        self.assertTrue(result["recovered"])
        self.assertEqual(saved["status"], "published")
        self.assertEqual(saved["event"], "COMMENT")
        self.assertEqual(saved["summary"], structured["summary"])
        self.assertEqual(finding_count, 1)
        cleanup_agent.assert_called_once_with(run_id)
        invoke_codex.assert_not_called()

    def test_recovery_waits_for_structured_output_before_deleting_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/15",
                repo="acme/api",
                number=15,
                title="Wait for terminal output",
                body="",
                head_sha="3" * 40,
                base_ref="main",
                author_login="developer",
            )
            publications = {
                "reviews": [
                    {
                        "id": 315,
                        "state": "COMMENTED",
                        "body": "Publication arrived before terminal output.",
                    }
                ],
                "comments": [],
            }
            with automation.connect_db(database) as db:
                run_id = automation.insert_run(db, pr, "review-bot", "running")
                row = db.execute(
                    "SELECT * FROM review_runs WHERE id = ?", (run_id,)
                ).fetchone()
                with patch.object(
                    automation,
                    "list_paseo_review_agents",
                    return_value=([{"id": "agent-15", "status": "idle"}], []),
                ), patch.object(
                    automation,
                    "load_paseo_structured_result",
                    return_value=(None, []),
                ), patch.object(
                    automation, "cleanup_paseo_review_agent"
                ) as cleanup_agent:
                    result = automation.recover_running_run(db, row, publications)
                status = db.execute(
                    "SELECT status FROM review_runs WHERE id = ?", (run_id,)
                ).fetchone()[0]

        self.assertEqual(result["status"], "in_progress")
        self.assertTrue(result["publication_detected"])
        self.assertEqual(status, "running")
        cleanup_agent.assert_not_called()

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

    def test_structured_result_can_be_recovered_from_paseo_logs(self):
        pr = automation.PullRequest(
            url="https://github.com/acme/api/pull/14",
            repo="acme/api",
            number=14,
            title="Log recovery",
            body="",
            head_sha="2" * 40,
            base_ref="main",
            author_login="developer",
        )
        structured = {
            "repo": pr.repo,
            "pr_number": pr.number,
            "head_sha": pr.head_sha,
            "event": "COMMENT",
            "published": True,
            "summary": "Recovered from the final assistant message.",
            "findings": [],
            "linear": {"fetch_status": "unavailable"},
            "limitations": [],
        }
        logs = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="Assistant final output:\n" + json.dumps(structured),
            stderr="",
        )
        with patch.object(automation, "run", return_value=logs):
            recovered, warnings = automation.load_paseo_structured_result(
                pr, [{"id": "agent-14", "status": "closed"}]
            )

        self.assertEqual(recovered, structured)
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
