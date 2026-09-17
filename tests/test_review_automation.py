from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from automation import review_automation as automation


class ReviewAutomationTests(unittest.TestCase):
    def _ready_proposal(
        self,
        db,
        *,
        owner_user_id="U_OWNER",
        dm_channel_id="D1",
        thread_ts="1720000000.000100",
        head_sha="a" * 40,
    ):
        conversation_id, _ = automation.get_or_create_pr_conversation(
            db,
            workspace_id="T1",
            owner_user_id=owner_user_id,
            repo="acme/api",
            pr_number=42,
            pr_url="https://github.com/acme/api/pull/42",
        )
        automation.bind_pr_conversation_thread(
            db,
            conversation_id,
            dm_channel_id=dm_channel_id,
            thread_ts=thread_ts,
        )
        proposal = automation.create_proposal_revision(
            db, conversation_id, head_sha=head_sha
        )
        _, attempt_id = automation.claim_analysis_attempt(
            db, proposal["id"], claimant="test"
        )
        result = {
            "repo": "acme/api",
            "pr_number": 42,
            "head_sha": head_sha,
            "baseline_head_sha": None,
            "event": "COMMENT",
            "published": False,
            "objective": "Protect persisted prices",
            "summary": "Two material issues",
            "findings": [
                {
                    "candidate_id": "C1",
                    "category": "correctness",
                    "severity": "major",
                    "path": "price.py",
                    "line": 42,
                    "start_line": None,
                    "side": "RIGHT",
                    "start_side": None,
                    "body": "Original first comment",
                    "evidence": "The persisted price is overwritten.",
                    "blocking": True,
                },
                {
                    "candidate_id": "C2",
                    "category": "error_handling",
                    "severity": "major",
                    "path": "worker.py",
                    "line": 17,
                    "start_line": None,
                    "side": "RIGHT",
                    "start_side": None,
                    "body": "Original second comment",
                    "evidence": "Failures are returned as successes.",
                    "blocking": True,
                },
            ],
            "delta": {
                "status": "initial",
                "summary": None,
                "addressed_candidate_ids": [],
                "still_open_candidate_ids": [],
                "new_candidate_ids": ["C1", "C2"],
            },
            "linear": {
                "fetch_status": "missing",
                "key": None,
                "title": None,
                "url": None,
                "status": None,
                "project": None,
                "product_summary": None,
                "acceptance_criteria": [],
                "labels": [],
            },
            "limitations": [],
        }
        automation.record_analysis_output(
            db, attempt_id=attempt_id, output=result
        )
        automation.persist_proposal_result(
            db,
            proposal_id=proposal["id"],
            attempt_id=attempt_id,
            reviewed_head=head_sha,
            objective=result["objective"],
            proposed_action="publish",
            summary=result["summary"],
            structured_result=result,
            findings=result["findings"],
        )
        return conversation_id, proposal, result

    def test_revision_bound_command_parser_accepts_only_exact_mutations(self):
        approve = automation.parse_decision_command("approve P3")
        publish = automation.parse_decision_command("publish P3 C1 C3")
        edit = automation.parse_decision_command("edit P3 C1: Better wording")
        dismiss = automation.parse_decision_command("dismiss P3 C2")

        self.assertEqual((approve.action, approve.revision_token), ("approve", "P3"))
        self.assertEqual(publish.candidate_ids, ("C1", "C3"))
        self.assertEqual((edit.candidate_ids, edit.body), (("C1",), "Better wording"))
        self.assertEqual(dismiss.candidate_ids, ("C2",))
        for text in (
            "approve",
            "please approve P3",
            "publish P3",
            "publish P3 C1, C3",
            "edit P3 C1 Better wording",
            "dismiss P3",
            "approve P03",
        ):
            self.assertIsNone(automation.parse_decision_command(text), text)

    def test_propose_persists_read_only_result_without_github_write(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/42",
                repo="acme/api",
                number=42,
                title="Fix persisted prices",
                body="",
                head_sha="a" * 40,
                base_ref="main",
                author_login="developer",
            )
            result = {
                "repo": pr.repo,
                "pr_number": pr.number,
                "head_sha": pr.head_sha,
                "baseline_head_sha": None,
                "event": "APPROVE",
                "published": False,
                "objective": "Keep price writes safe",
                "summary": "No material findings.",
                "findings": [],
                "delta": {
                    "status": "initial",
                    "summary": None,
                    "addressed_candidate_ids": [],
                    "still_open_candidate_ids": [],
                    "new_candidate_ids": [],
                },
                "linear": {"fetch_status": "missing"},
                "limitations": [],
            }
            with patch.object(automation, "load_pr", return_value=pr), patch.object(
                automation, "reviewer_login", return_value="review-bot"
            ), patch.object(
                automation, "invoke_codex", return_value=result
            ), patch.object(
                automation, "github_json_request"
            ) as github_write, patch.object(
                automation, "cleanup_paseo_review_agent", return_value=[]
            ):
                proposed = automation.propose_urls(
                    [pr.url],
                    db_path=str(database),
                    workspace_id="T1",
                    source_channel_id="C1",
                    source_message_ts="1720000000.000100",
                    requester_user_id="U_REQUESTER",
                    owner_user_id="U_OWNER",
                )

            self.assertEqual(proposed["results"][0]["status"], "awaiting_decision")
            self.assertEqual(proposed["results"][0]["revision_token"], "P1")
            github_write.assert_not_called()
            with automation.connect_db(database) as db:
                row = db.execute(
                    "SELECT state, structured_result FROM proposal_revisions"
                ).fetchone()
            self.assertEqual(row["state"], "awaiting_decision")
            self.assertFalse(json.loads(row["structured_result"])["published"])

    def test_thread_command_guards_owner_thread_revision_and_head(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                self._ready_proposal(db)
                row_count = db.execute(
                    "SELECT COUNT(*) FROM proposal_decisions"
                ).fetchone()[0]
                read_only = automation.execute_thread_command(
                    db,
                    workspace_id="T1",
                    dm_channel_id="D1",
                    thread_ts="1720000000.000100",
                    owner_user_id="U_OWNER",
                    command_text="can you explain C1?",
                    idempotency_key="msg-question",
                )
                with self.assertRaisesRegex(automation.AutomationError, "owner"):
                    automation.execute_thread_command(
                        db,
                        workspace_id="T1",
                        dm_channel_id="D1",
                        thread_ts="1720000000.000100",
                        owner_user_id="U_OTHER",
                        command_text="skip P1",
                        idempotency_key="msg-wrong-owner",
                    )
                with self.assertRaisesRegex(automation.AutomationError, "thread"):
                    automation.execute_thread_command(
                        db,
                        workspace_id="T1",
                        dm_channel_id="D1",
                        thread_ts="wrong",
                        owner_user_id="U_OWNER",
                        command_text="skip P1",
                        idempotency_key="msg-wrong-thread",
                    )
                with self.assertRaisesRegex(automation.AutomationError, "revision"):
                    automation.execute_thread_command(
                        db,
                        workspace_id="T1",
                        dm_channel_id="D1",
                        thread_ts="1720000000.000100",
                        owner_user_id="U_OWNER",
                        command_text="skip P2",
                        idempotency_key="msg-wrong-revision",
                    )
                after_count = db.execute(
                    "SELECT COUNT(*) FROM proposal_decisions"
                ).fetchone()[0]

            self.assertEqual(read_only["status"], "read_only")
            self.assertEqual(after_count, row_count)

    def test_publish_uses_only_selected_edited_active_candidate_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            current_pr = automation.PullRequest(
                url="https://github.com/acme/api/pull/42",
                repo="acme/api",
                number=42,
                title="Fix persisted prices",
                body="",
                head_sha="a" * 40,
                base_ref="main",
                author_login="developer",
            )
            with automation.connect_db(database) as db:
                self._ready_proposal(db)
                automation.execute_thread_command(
                    db,
                    workspace_id="T1",
                    dm_channel_id="D1",
                    thread_ts="1720000000.000100",
                    owner_user_id="U_OWNER",
                    command_text="edit P1 C1: Edited first comment",
                    idempotency_key="msg-edit",
                )
                automation.execute_thread_command(
                    db,
                    workspace_id="T1",
                    dm_channel_id="D1",
                    thread_ts="1720000000.000100",
                    owner_user_id="U_OWNER",
                    command_text="dismiss P1 C2",
                    idempotency_key="msg-dismiss",
                )
                marker_comment = {
                    "id": 301,
                    "user": {"login": "review-bot"},
                    "commit_id": current_pr.head_sha,
                    "original_commit_id": current_pr.head_sha,
                    "body": "Edited first comment\n\n<!-- hermes-review-action:ACTION:C1 -->",
                    "html_url": "https://github.com/acme/api/pull/42#discussion_r301",
                }
                with patch.object(
                    automation, "load_pr", return_value=current_pr
                ), patch.object(
                    automation, "reviewer_login", return_value="review-bot"
                ), patch.object(
                    automation, "github_publications",
                    side_effect=[
                        {"reviews": [], "comments": []},
                        {"reviews": [], "comments": [marker_comment]},
                    ],
                ), patch.object(
                    automation, "github_json_request", return_value={"id": 201}
                ) as github_write, patch.object(
                    automation, "action_marker",
                    side_effect=lambda action_id, candidate_id=None: (
                        "<!-- hermes-review-action:ACTION"
                        + (f":{candidate_id}" if candidate_id else "")
                        + " -->"
                    ),
                ):
                    published = automation.execute_thread_command(
                        db,
                        workspace_id="T1",
                        dm_channel_id="D1",
                        thread_ts="1720000000.000100",
                        owner_user_id="U_OWNER",
                        command_text="publish P1 C1",
                        idempotency_key="msg-publish",
                    )
                    replayed = automation.execute_thread_command(
                        db,
                        workspace_id="T1",
                        dm_channel_id="D1",
                        thread_ts="1720000000.000100",
                        owner_user_id="U_OWNER",
                        command_text="publish P1 C1",
                        idempotency_key="msg-publish",
                    )

            payload = github_write.call_args.args[2]
            self.assertEqual(payload["event"], "COMMENT")
            self.assertEqual(len(payload["comments"]), 1)
            self.assertIn("Edited first comment", payload["comments"][0]["body"])
            self.assertEqual(published["status"], "completed")
            self.assertEqual(replayed["status"], "completed")
            github_write.assert_called_once()

    def test_stale_head_and_unsafe_or_self_approval_never_write(self):
        cases = (
            ("b" * 40, "developer", True, "stale_head"),
            ("a" * 40, "developer", False, "stale approvals"),
            ("a" * 40, "review-bot", True, "self-authored"),
        )
        for current_head, author, safe, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                database = Path(directory) / "reviews.sqlite3"
                with automation.connect_db(database) as db:
                    self._ready_proposal(db)
                    current_pr = automation.PullRequest(
                        url="https://github.com/acme/api/pull/42",
                        repo="acme/api",
                        number=42,
                        title="Fix persisted prices",
                        body="",
                        head_sha=current_head,
                        base_ref="main",
                        author_login=author,
                    )
                    with patch.object(
                        automation, "load_pr", return_value=current_pr
                    ), patch.object(
                        automation, "reviewer_login", return_value="review-bot"
                    ), patch.object(
                        automation, "approval_dismisses_stale_reviews", return_value=safe
                    ), patch.object(
                        automation, "github_json_request"
                    ) as github_write:
                        result = automation.execute_thread_command(
                            db,
                            workspace_id="T1",
                            dm_channel_id="D1",
                            thread_ts="1720000000.000100",
                            owner_user_id="U_OWNER",
                            command_text="approve P1",
                            idempotency_key=f"msg-{expected}",
                        )

                self.assertIn(expected, result.get("reason", result["status"]))
                github_write.assert_not_called()

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

        self.assertEqual(version, 3)
        self.assertTrue(
            {
                "cleanup_status",
                "cleanup_attempted_at",
                "cleaned_at",
                "cleanup_error",
            }
            <= columns
        )

    def test_workflow_request_and_conversation_are_reused_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                request_id, request_created = automation.get_or_create_source_request(
                    db,
                    workspace_id="T1",
                    channel_id="C1",
                    message_ts="1720000000.000100",
                    requester_user_id="U_REQUESTER",
                )
                conversation_id, conversation_created = (
                    automation.get_or_create_pr_conversation(
                        db,
                        workspace_id="T1",
                        owner_user_id="U_OWNER",
                        repo="acme/api",
                        pr_number=42,
                        pr_url="https://github.com/acme/api/pull/42",
                    )
                )
                automation.associate_request_conversation(
                    db, request_id, conversation_id, position=0
                )

            with automation.connect_db(database) as db:
                replayed_request_id, replayed_request_created = (
                    automation.get_or_create_source_request(
                        db,
                        workspace_id="T1",
                        channel_id="C1",
                        message_ts="1720000000.000100",
                        requester_user_id="U_REQUESTER",
                    )
                )
                second_request_id, second_request_created = (
                    automation.get_or_create_source_request(
                        db,
                        workspace_id="T1",
                        channel_id="C1",
                        message_ts="1720000100.000100",
                        requester_user_id="U_REQUESTER",
                    )
                )
                replayed_conversation_id, replayed_conversation_created = (
                    automation.get_or_create_pr_conversation(
                        db,
                        workspace_id="T1",
                        owner_user_id="U_OWNER",
                        repo="acme/api",
                        pr_number=42,
                        pr_url="https://github.com/acme/api/pull/42",
                    )
                )
                automation.associate_request_conversation(
                    db, second_request_id, replayed_conversation_id, position=0
                )
                member_count = db.execute(
                    "SELECT COUNT(*) FROM workflow_request_members "
                    "WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]

        self.assertTrue(request_created)
        self.assertTrue(conversation_created)
        self.assertFalse(replayed_request_created)
        self.assertFalse(replayed_conversation_created)
        self.assertTrue(second_request_created)
        self.assertEqual(replayed_request_id, request_id)
        self.assertEqual(replayed_conversation_id, conversation_id)
        self.assertNotEqual(second_request_id, request_id)
        self.assertEqual(member_count, 2)

    def test_linked_requests_and_projection_derive_one_shared_status(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                request_id, _ = automation.get_or_create_source_request(
                    db,
                    workspace_id="T1",
                    channel_id="C1",
                    message_ts="1720000000.000100",
                    requester_user_id="U_REQUESTER",
                )
                conversations = []
                for position, number in enumerate((41, 42)):
                    conversation_id, _ = automation.get_or_create_pr_conversation(
                        db,
                        workspace_id="T1",
                        owner_user_id="U_OWNER",
                        repo="acme/api",
                        pr_number=number,
                        pr_url=f"https://github.com/acme/api/pull/{number}",
                    )
                    automation.associate_request_conversation(
                        db, request_id, conversation_id, position=position
                    )
                    conversations.append(conversation_id)

                linked = automation.source_requests_for_conversation(
                    db, conversations[0]
                )
                automation.update_request_member_outcome(
                    db,
                    conversation_id=conversations[0],
                    outcome="approved",
                    reviewed_head="a" * 40,
                )
                pending_projection = automation.source_request_projection(db, request_id)
                automation.update_request_member_outcome(
                    db,
                    conversation_id=conversations[1],
                    outcome="comments_published",
                    reviewed_head="b" * 40,
                    published_comment_count=2,
                )
                complete_projection = automation.source_request_projection(
                    db, request_id
                )
                automation.bind_source_verdict(
                    db, request_id=request_id, verdict_message_ts="1720000200.000100"
                )
                bound_projection = automation.source_request_projection(db, request_id)

        self.assertEqual([item["id"] for item in linked], [request_id])
        self.assertEqual(pending_projection["reaction_name"], "eyes")
        self.assertEqual(pending_projection["state"], "pending")
        self.assertEqual(complete_projection["reaction_name"], "white_check_mark")
        self.assertEqual(complete_projection["state"], "completed")
        self.assertEqual(complete_projection["members"][1]["published_comment_count"], 2)
        self.assertEqual(
            bound_projection["verdict_message_ts"], "1720000200.000100"
        )

    def test_new_proposal_supersedes_old_revision_and_rejects_stale_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                conversation_id, _ = automation.get_or_create_pr_conversation(
                    db,
                    workspace_id="T1",
                    owner_user_id="U_OWNER",
                    repo="acme/api",
                    pr_number=42,
                    pr_url="https://github.com/acme/api/pull/42",
                )
                first = automation.create_proposal_revision(
                    db, conversation_id, head_sha="a" * 40
                )
                second = automation.create_proposal_revision(
                    db,
                    conversation_id,
                    head_sha="b" * 40,
                    baseline_head_sha="a" * 40,
                )
                first_state = db.execute(
                    "SELECT state FROM proposal_revisions WHERE id = ?",
                    (first["id"],),
                ).fetchone()[0]

                with self.assertRaisesRegex(
                    automation.AutomationError, "superseded|not active"
                ):
                    automation.record_proposal_decision(
                        db,
                        conversation_id=conversation_id,
                        revision_token=first["revision_token"],
                        owner_user_id="U_OWNER",
                        action="skip",
                        idempotency_key="decision-old",
                    )
                decision_id, decision_created = automation.record_proposal_decision(
                    db,
                    conversation_id=conversation_id,
                    revision_token=second["revision_token"],
                    owner_user_id="U_OWNER",
                    action="skip",
                    idempotency_key="decision-current",
                )
                replayed_id, replayed_created = automation.record_proposal_decision(
                    db,
                    conversation_id=conversation_id,
                    revision_token=second["revision_token"],
                    owner_user_id="U_OWNER",
                    action="skip",
                    idempotency_key="decision-current",
                )

        self.assertEqual(first["revision_token"], "P1")
        self.assertEqual(second["revision_token"], "P2")
        self.assertEqual(first_state, "superseded")
        self.assertTrue(decision_created)
        self.assertFalse(replayed_created)
        self.assertEqual(replayed_id, decision_id)

    def test_proposal_result_persists_immutable_candidate_findings(self):
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                conversation_id, _ = automation.get_or_create_pr_conversation(
                    db,
                    workspace_id="T1",
                    owner_user_id="U_OWNER",
                    repo="acme/api",
                    pr_number=42,
                    pr_url="https://github.com/acme/api/pull/42",
                )
                proposal = automation.create_proposal_revision(
                    db, conversation_id, head_sha="a" * 40
                )
                _, attempt_id = automation.claim_analysis_attempt(
                    db, proposal["id"], claimant="worker", now=now
                )
                automation.record_analysis_output(
                    db,
                    attempt_id=attempt_id,
                    output={"summary": "One material issue"},
                    now=now,
                )
                automation.persist_proposal_result(
                    db,
                    proposal_id=proposal["id"],
                    attempt_id=attempt_id,
                    reviewed_head="a" * 40,
                    objective="Protect persisted prices",
                    proposed_action="publish",
                    summary="One material issue",
                    structured_result={"published": False},
                    findings=[
                        {
                            "candidate_id": "C1",
                            "category": "correctness",
                            "severity": "high",
                            "path": "price.py",
                            "line": 42,
                            "body": "This can overwrite a persisted price.",
                            "blocking": True,
                        }
                    ],
                    now=now,
                )
                finding = db.execute(
                    "SELECT candidate_id, body FROM proposal_findings "
                    "WHERE proposal_id = ?",
                    (proposal["id"],),
                ).fetchone()
                with self.assertRaisesRegex(
                    automation.AutomationError, "already persisted"
                ):
                    automation.persist_proposal_result(
                        db,
                        proposal_id=proposal["id"],
                        attempt_id=attempt_id,
                        reviewed_head="a" * 40,
                        objective="Changed objective",
                        proposed_action="approve",
                        summary="Changed",
                        structured_result={},
                        findings=[],
                        now=now,
                    )

        self.assertEqual(finding["candidate_id"], "C1")
        self.assertEqual(finding["body"], "This can overwrite a persisted price.")

    def test_delivery_and_reminder_claims_have_one_owner(self):
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                conversation_id, _ = automation.get_or_create_pr_conversation(
                    db,
                    workspace_id="T1",
                    owner_user_id="U_OWNER",
                    repo="acme/api",
                    pr_number=42,
                    pr_url="https://github.com/acme/api/pull/42",
                )
                proposal = automation.create_proposal_revision(
                    db, conversation_id, head_sha="a" * 40
                )
                automation.schedule_proposal_reminder(
                    db, proposal["id"], due_at=now - timedelta(minutes=1)
                )
                delivery_id, delivery_state = automation.claim_slack_delivery(
                    db,
                    delivery_key="proposal:42:P1",
                    kind="proposal_summary",
                    workspace_id="T1",
                    channel_id="D1",
                    thread_ts=None,
                    claimant="worker-1",
                    now=now,
                )
                replayed_delivery_id, replayed_delivery_state = (
                    automation.claim_slack_delivery(
                        db,
                        delivery_key="proposal:42:P1",
                        kind="proposal_summary",
                        workspace_id="T1",
                        channel_id="D1",
                        thread_ts=None,
                        claimant="worker-2",
                        now=now,
                    )
                )
                first_claim = automation.claim_due_reminders(
                    db, claimant="worker-1", now=now, limit=10
                )
                second_claim = automation.claim_due_reminders(
                    db, claimant="worker-2", now=now, limit=10
                )

        self.assertEqual(delivery_state, "claimed")
        self.assertEqual(replayed_delivery_state, "in_progress")
        self.assertEqual(replayed_delivery_id, delivery_id)
        self.assertEqual(len(first_claim), 1)
        self.assertEqual(first_claim[0]["proposal_id"], proposal["id"])
        self.assertEqual(second_claim, [])

    def test_expired_analysis_reclaims_retry_output_and_head_drift(self):
        now = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                conversations = []
                proposals = []
                for number, head in ((1, "a" * 40), (2, "b" * 40), (3, "c" * 40)):
                    conversation_id, _ = automation.get_or_create_pr_conversation(
                        db,
                        workspace_id="T1",
                        owner_user_id="U_OWNER",
                        repo="acme/api",
                        pr_number=number,
                        pr_url=f"https://github.com/acme/api/pull/{number}",
                    )
                    proposal = automation.create_proposal_revision(
                        db, conversation_id, head_sha=head
                    )
                    state, attempt_id = automation.claim_analysis_attempt(
                        db,
                        proposal["id"],
                        claimant="worker",
                        now=now - timedelta(minutes=10),
                        lease_seconds=60,
                    )
                    self.assertEqual(state, "claimed")
                    conversations.append(conversation_id)
                    proposals.append((proposal, attempt_id))

                automation.record_analysis_output(
                    db,
                    attempt_id=proposals[1][1],
                    output={"summary": "complete but not persisted"},
                    now=now - timedelta(minutes=8),
                )
                reclaimed = automation.reclaim_expired_analysis(
                    db,
                    current_heads={
                        ("acme/api", 1): "a" * 40,
                        ("acme/api", 2): "b" * 40,
                        ("acme/api", 3): "d" * 40,
                    },
                    now=now,
                )
                third_state = db.execute(
                    "SELECT state FROM proposal_revisions WHERE id = ?",
                    (proposals[2][0]["id"],),
                ).fetchone()[0]
                latest_third = db.execute(
                    "SELECT revision_token, head_sha, baseline_head_sha, state "
                    "FROM proposal_revisions WHERE conversation_id = ? "
                    "ORDER BY revision_number DESC LIMIT 1",
                    (conversations[2],),
                ).fetchone()

        self.assertEqual(
            [item["outcome"] for item in reclaimed],
            ["retry", "persist_output", "head_changed"],
        )
        self.assertEqual(third_state, "superseded")
        self.assertEqual(latest_third["revision_token"], "P2")
        self.assertEqual(latest_third["head_sha"], "d" * 40)
        self.assertEqual(latest_third["baseline_head_sha"], "c" * 40)
        self.assertEqual(latest_third["state"], "queued")

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

    def test_repositioned_inline_comment_does_not_cover_current_head(self):
        previous_head = "4a41d961a916b539c270c31dd63645e5338a2ceb"
        current_head = "2ecaead28c4e094ea4650f212a03e11be14d92e5"
        pr = automation.PullRequest(
            url="https://github.com/acme/api/pull/219",
            repo="acme/api",
            number=219,
            title="Update pricing rules",
            body="",
            head_sha=current_head,
            base_ref="main",
            author_login="developer",
        )
        reviews = [
            {
                "id": 101,
                "user": {"login": "review-bot"},
                "commit_id": current_head,
                "state": "COMMENTED",
            },
            {
                "id": 102,
                "user": {"login": "review-bot"},
                "commit_id": previous_head,
                "state": "APPROVED",
            },
        ]
        comments = [
            {
                "id": 201,
                "user": {"login": "review-bot"},
                "commit_id": current_head,
                "original_commit_id": previous_head,
            },
            {
                "id": 202,
                "user": {"login": "review-bot"},
                "commit_id": current_head,
                "original_commit_id": current_head,
            },
            {
                "id": 203,
                "user": {"login": "review-bot"},
                "commit_id": current_head,
            },
        ]

        with patch.object(
            automation,
            "gh_paginated",
            side_effect=[reviews, comments],
        ):
            publications = automation.github_publications(pr, "review-bot")

        self.assertEqual([item["id"] for item in publications["reviews"]], [101])
        self.assertEqual([item["id"] for item in publications["comments"]], [202])

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
