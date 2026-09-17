from __future__ import annotations

import importlib.util
import asyncio
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from automation import review_automation as automation


PLUGIN_PATH = (
    Path(__file__).parents[1]
    / "plugins"
    / "slack-pr-review-gate"
    / "__init__.py"
)
POLICY_ENV = {
    "SLACK_REVIEW_CHANNEL_ID": "C_REVIEW",
    "SLACK_REVIEW_OWNER_USER_IDS": "U_OWNER",
    "SLACK_REVIEWER_USER_IDS": "U_REVIEWER,U_SECOND",
    "SLACK_REVIEW_BOT_USER_IDS": "U_AGENT_BOT",
    "SLACK_REVIEW_COMPETING_BOT_USER_IDS": "U_NACHO_BOT",
    "SLACK_REVIEW_ALLOWED_REPOSITORIES": "acme/api,acme/web",
    "SLACK_REVIEW_DIGEST_USER_ID": "U_OWNER",
    "SLACK_REVIEW_MAX_URLS_PER_MESSAGE": "5",
    "SLACK_REVIEW_MAX_ACTIVE_PER_REQUESTER": "3",
    "SLACK_REVIEW_MAX_QUEUED": "20",
    "SLACK_REVIEW_PROPOSAL_CONCURRENCY": "2",
}


def load_plugin():
    spec = importlib.util.spec_from_file_location("slack_pr_review_gate", PLUGIN_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(user_id: str, chat_id: str, text: str, *, raw_message=None):
    source = SimpleNamespace(
        platform="slack",
        user_id=user_id,
        chat_id=chat_id,
        scope_id="T_TEST",
        thread_id=str((raw_message or {}).get("thread_ts", "")),
    )
    return SimpleNamespace(
        source=source,
        text=text,
        message_id="1",
        raw_message=raw_message,
    )


def gateway(bot_user_id: str = "U_BOT"):
    adapter = SimpleNamespace(
        _bot_user_id=bot_user_id,
        _team_bot_user_ids={"T_TEST": bot_user_id},
    )
    return SimpleNamespace(adapters={"slack": adapter})


class FakeSlackAdapter:
    def __init__(self, *, fail_send: bool = False):
        self.fail_send = fail_send
        self.sent = []
        self.edited = []
        self.added_reactions = []
        self.removed_reactions = []

    async def _dm_target(self, _user_id, _metadata):
        return "D_OWNER"

    async def send(self, channel_id, content, reply_to=None, metadata=None):
        self.sent.append((channel_id, content, reply_to, metadata))
        if self.fail_send:
            return SimpleNamespace(success=False, message_id=None, error="timeout")
        message_id = f"200.{len(self.sent)}"
        return SimpleNamespace(
            success=True,
            message_id=message_id,
            raw_response={"channel": channel_id, "ts": message_id},
        )

    async def edit_message(
        self, channel_id, message_id, content, *, finalize=False, metadata=None
    ):
        self.edited.append(
            (channel_id, message_id, content, finalize, metadata)
        )
        return SimpleNamespace(success=True, message_id=message_id)

    async def _add_reaction(self, channel, timestamp, emoji, team_id=""):
        self.added_reactions.append((channel, timestamp, emoji, team_id))
        return True

    async def _remove_reaction(self, channel, timestamp, emoji, team_id=""):
        self.removed_reactions.append((channel, timestamp, emoji, team_id))
        return True


class SlackReviewPolicyTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, POLICY_ENV, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.plugin = load_plugin()

    def test_configuration_is_loaded_from_environment(self):
        self.assertEqual(self.plugin.REVIEW_CHANNEL_ID, "C_REVIEW")
        self.assertEqual(
            self.plugin.ALLOWED_REPOSITORIES,
            frozenset({("acme", "api"), ("acme", "web")}),
        )
        self.assertEqual(self.plugin.REVIEW_BOT_USER_IDS, frozenset({"U_AGENT_BOT"}))
        self.assertEqual(
            self.plugin.COMPETING_BOT_USER_IDS, frozenset({"U_NACHO_BOT"})
        )
        self.assertEqual(self.plugin.DECISION_OWNER_USER_ID, "U_OWNER")

    def test_owner_configuration_fails_closed_when_digest_owner_is_ambiguous(self):
        with patch.dict(
            os.environ,
            {
                **POLICY_ENV,
                "SLACK_REVIEW_OWNER_USER_IDS": "U_OWNER,U_OTHER",
                "SLACK_REVIEW_DIGEST_USER_ID": "",
            },
            clear=False,
        ):
            plugin = load_plugin()
        self.assertEqual(plugin.DECISION_OWNER_USER_ID, "")
        result = plugin._review_only_policy(
            event("U_REVIEWER", "C_REVIEW", "https://github.com/acme/api/pull/42")
        )
        self.assertEqual(result["reason"], "review-decision-owner-not-configured")

    def test_thread_context_url_is_not_inherited_by_current_message(self):
        result = self.plugin._review_only_policy(
            event(
                "U_REVIEWER",
                "C_REVIEW",
                "Thread context https://github.com/acme/api/pull/42",
                raw_message={"text": "thanks, I am checking it"},
            )
        )

        self.assertEqual(result["reason"], "review-message-has-no-approved-pr")

    def test_message_addressed_only_to_competing_bot_is_ignored(self):
        result = self.plugin._review_only_policy(
            event(
                "U_REVIEWER",
                "C_REVIEW",
                "<@U_NACHO_BOT> revisa el PR pls "
                "https://github.com/acme/api/pull/42",
            ),
            gateway=gateway(),
        )

        self.assertEqual(result["reason"], "review-addressed-to-competing-bot")

    def test_message_addressed_to_both_bots_is_accepted(self):
        with patch.object(self.plugin, "_schedule_source_request") as scheduled:
            result = self.plugin._review_only_policy(
                event(
                    "U_REVIEWER",
                    "C_REVIEW",
                    "<@U_NACHO_BOT> <@U_BOT> revisen "
                    "https://github.com/acme/api/pull/42",
                ),
                gateway=gateway(),
            )

        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "review-scheduled")
        scheduled.assert_called_once()

    def test_duplicate_slack_delivery_is_not_dispatched_twice(self):
        request = event(
            "U_REVIEWER",
            "C_REVIEW",
            "https://github.com/acme/api/pull/42",
        )
        with patch.object(self.plugin, "_schedule_source_request"):
            first = self.plugin._review_only_policy(request)
            second = self.plugin._review_only_policy(request)

        self.assertEqual(first["action"], "skip")
        self.assertEqual(second["reason"], "duplicate-review-message")

    def test_reviewer_can_submit_only_allowed_pr_urls_in_dm(self):
        with patch.object(self.plugin, "_schedule_source_request") as scheduled:
            result = self.plugin._review_only_policy(
                event(
                    "U_REVIEWER",
                    "D_DIRECT",
                    "please do this https://github.com/acme/api/pull/42",
                )
            )
        self.assertEqual(result["action"], "skip")
        scheduled.assert_called_once()

    def test_owner_bot_mention_schedules_review(self):
        with patch.object(self.plugin, "_schedule_source_request") as scheduled:
            result = self.plugin._review_only_policy(
                event(
                    "U_OWNER",
                    "C_REVIEW",
                    "<@U_BOT> les comparto estos PRs para que revisen "
                    "https://github.com/acme/api/pull/42",
                ),
                gateway=gateway(),
            )
        self.assertEqual(result["action"], "skip")
        scheduled.assert_called_once()
        self.assertEqual(len(scheduled.call_args.args), 4)

    def test_owner_without_bot_mention_schedules_review(self):
        with patch.object(self.plugin, "_schedule_source_request") as scheduled:
            result = self.plugin._review_only_policy(
                event(
                    "U_OWNER",
                    "C_REVIEW",
                    "Les comparto estos PRs para que revisen "
                    "https://github.com/acme/api/pull/42",
                )
            )
        self.assertEqual(result["action"], "skip")
        scheduled.assert_called_once()
        self.assertEqual(len(scheduled.call_args.args), 4)

    def test_slack_app_mention_event_schedules_owner_review(self):
        with patch.object(self.plugin, "_schedule_source_request") as scheduled:
            result = self.plugin._review_only_policy(
                event(
                    "U_OWNER",
                    "C_REVIEW",
                    "Hermes https://github.com/acme/api/pull/42",
                    raw_message={"type": "app_mention"},
                )
            )
        self.assertEqual(result["action"], "skip")
        scheduled.assert_called_once()
        self.assertEqual(len(scheduled.call_args.args), 4)

    def test_reviewer_bot_mention_schedules_review_without_special_authority(self):
        with patch.object(self.plugin, "_schedule_source_request") as scheduled:
            result = self.plugin._review_only_policy(
                event(
                    "U_REVIEWER",
                    "C_REVIEW",
                    "<@U_BOT> https://github.com/acme/api/pull/42",
                ),
                gateway=gateway(),
            )
        self.assertEqual(result["action"], "skip")
        scheduled.assert_called_once()
        self.assertEqual(len(scheduled.call_args.args), 4)

    def test_reviewer_non_review_dm_is_rejected(self):
        result = self.plugin._review_only_policy(
            event("U_REVIEWER", "D_DIRECT", "show me the server files")
        )
        self.assertEqual(result["action"], "skip")

    def test_unsupported_repository_rejects_entire_message(self):
        result = self.plugin._review_only_policy(
            event(
                "U_REVIEWER",
                "C_REVIEW",
                "https://github.com/acme/api/pull/1 "
                "https://github.com/other/private/pull/2",
            )
        )
        self.assertEqual(result["reason"], "review-message-mixes-unsupported-pr")

    def test_owner_keeps_normal_access_outside_review_channel(self):
        result = self.plugin._review_only_policy(
            event("U_OWNER", "D_OWNER", "normal assistant request")
        )
        self.assertIsNone(result)

    def test_mapped_owner_dm_is_resolved_before_normal_owner_bypass(self):
        request = event(
            "U_OWNER",
            "D_OWNER",
            "why is C1 material?",
            raw_message={"thread_ts": "100.2"},
        )
        route = {"id": "conversation-1", "proposal_id": "proposal-1"}
        with patch.object(self.plugin, "_lookup_private_route", return_value=route):
            result = self.plugin._review_only_policy(request)
        self.assertEqual(result["action"], "rewrite")
        self.assertIn("conversation-1", result["text"])
        self.assertIn("proposal-1", result["text"])
        self.assertIn("why is C1 material?", result["text"])

    def test_unrelated_owner_dm_keeps_normal_access(self):
        request = event(
            "U_OWNER",
            "D_OWNER",
            "normal assistant request",
            raw_message={"thread_ts": "100.2"},
        )
        with patch.object(self.plugin, "_lookup_private_route", return_value=None):
            self.assertIsNone(self.plugin._review_only_policy(request))

    def test_exact_owner_command_is_handled_in_background(self):
        request = event(
            "U_OWNER",
            "D_OWNER",
            "approve P2",
            raw_message={"thread_ts": "100.2"},
        )
        route = {"id": "conversation-1", "proposal_id": "proposal-1"}
        with (
            patch.object(self.plugin, "_lookup_private_route", return_value=route),
            patch.object(self.plugin, "_is_exact_command", return_value=True),
            patch.object(self.plugin, "_schedule_owner_command") as scheduled,
        ):
            result = self.plugin._review_only_policy(request, gateway=gateway())
        self.assertEqual(result["action"], "skip")
        self.assertEqual(result["reason"], "review-command-scheduled")
        scheduled.assert_called_once()

    def test_exact_owner_command_uses_canonical_parser(self):
        self.plugin._AUTOMATION = automation
        self.assertTrue(self.plugin._is_exact_command("publish P2 C1 C3"))
        self.assertFalse(self.plugin._is_exact_command("publish P2 C1 C1"))
        self.assertFalse(self.plugin._is_exact_command("please approve P2"))

    def test_three_pr_request_schedules_one_private_summary_each_without_public_text(self):
        request = event(
            "U_REVIEWER",
            "C_REVIEW",
            " ".join(
                f"https://github.com/acme/api/pull/{number}"
                for number in (1, 2, 3)
            ),
        )
        with patch.object(self.plugin, "_schedule_source_request") as scheduled:
            result = self.plugin._review_only_policy(request, gateway=gateway())
        self.assertEqual(result, {"action": "skip", "reason": "review-scheduled"})
        self.assertEqual(len(scheduled.call_args.args[3]), 3)

    def test_url_and_queue_caps_fail_closed(self):
        with patch.object(self.plugin, "MAX_URLS_PER_MESSAGE", 1):
            result = self.plugin._review_only_policy(
                event(
                    "U_REVIEWER",
                    "C_REVIEW",
                    "https://github.com/acme/api/pull/1 "
                    "https://github.com/acme/api/pull/2",
                )
            )
        self.assertEqual(result["reason"], "review-url-limit-exceeded")

        with patch.object(self.plugin, "_intake_capacity_reason", return_value="review-queue-full"):
            result = self.plugin._review_only_policy(
                event("U_REVIEWER", "C_REVIEW", "https://github.com/acme/api/pull/3")
            )
        self.assertEqual(result["reason"], "review-queue-full")

    def test_unknown_user_is_rejected(self):
        result = self.plugin._review_only_policy(
            event("U_UNKNOWN", "C_REVIEW", "https://github.com/acme/api/pull/1")
        )
        self.assertEqual(result["reason"], "review-user-not-allowed")

    def test_trusted_bot_review_request_reads_url_from_block_kit(self):
        with patch.object(self.plugin, "_schedule_source_request") as scheduled:
            result = self.plugin._review_only_policy(event(
                "U_AGENT_BOT",
                "C_REVIEW",
                "",
                raw_message={
                    "subtype": "bot_message",
                    "blocks": [
                        {
                            "type": "rich_text",
                            "elements": [
                                {
                                    "type": "rich_text_section",
                                    "elements": [
                                        {
                                            "type": "text",
                                            "text": "Solicitud de revisión: "
                                            "estos PRs están listos para revisión ",
                                        },
                                        {
                                            "type": "link",
                                            "url": "https://github.com/acme/api/pull/210",
                                            "text": "acme/api #210",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                },
            ))
        self.assertEqual(result["action"], "skip")
        self.assertIn("https://github.com/acme/api/pull/210", scheduled.call_args.args[3])

    def test_trusted_bot_url_without_review_intent_is_ignored(self):
        result = self.plugin._review_only_policy(
            event(
                "U_AGENT_BOT",
                "C_REVIEW",
                "Build completed for https://github.com/acme/api/pull/210",
                raw_message={"subtype": "bot_message"},
            )
        )
        self.assertEqual(result["reason"], "review-bot-message-has-no-intent")

    def test_untrusted_bot_review_request_is_rejected(self):
        result = self.plugin._review_only_policy(
            event(
                "U_OTHER_BOT",
                "C_REVIEW",
                "Review request https://github.com/acme/api/pull/210",
                raw_message={"subtype": "bot_message"},
            )
        )
        self.assertEqual(result["reason"], "review-user-not-allowed")

    def test_trusted_bot_is_restricted_to_review_channel(self):
        result = self.plugin._review_only_policy(
            event(
                "U_AGENT_BOT",
                "D_DIRECT",
                "Review request https://github.com/acme/api/pull/210",
                raw_message={"subtype": "bot_message"},
            )
        )
        self.assertEqual(result["reason"], "review-bot-surface-not-allowed")

    def _persist_ready_proposal(self, database: Path):
        with automation.connect_db(database) as db:
            request_id, _ = automation.get_or_create_source_request(
                db,
                workspace_id="T_TEST",
                channel_id="C_REVIEW",
                message_ts="100.1",
                requester_user_id="U_REVIEWER",
            )
            conversation_id, _ = automation.get_or_create_pr_conversation(
                db,
                workspace_id="T_TEST",
                owner_user_id="U_OWNER",
                repo="acme/api",
                pr_number=42,
                pr_url="https://github.com/acme/api/pull/42",
            )
            automation.associate_request_conversation(
                db, request_id, conversation_id, position=0
            )
            proposal = automation.create_proposal_revision(
                db, conversation_id, head_sha="a" * 40
            )
            _, attempt_id = automation.claim_analysis_attempt(
                db, proposal["id"], claimant="test"
            )
            result = {
                "repo": "acme/api",
                "pr_number": 42,
                "head_sha": "a" * 40,
                "baseline_head_sha": None,
                "published": False,
                "event": "COMMENT",
                "objective": "Protect checkout totals",
                "summary": "One material issue needs confirmation.",
                "findings": [],
                "delta": {
                    "status": "initial",
                    "summary": "Initial review.",
                    "addressed_candidate_ids": [],
                    "still_open_candidate_ids": [],
                    "new_candidate_ids": [],
                },
                "linear": {"fetch_status": "missing"},
                "limitations": [],
            }
            automation.record_analysis_output(
                db, attempt_id=attempt_id, output=result
            )
            automation.persist_proposal_result(
                db,
                proposal_id=proposal["id"],
                attempt_id=attempt_id,
                reviewed_head="a" * 40,
                objective=result["objective"],
                proposed_action="comment",
                summary=result["summary"],
                structured_result=result,
                findings=[],
            )
        return request_id, conversation_id, proposal

    def test_private_summary_delivery_is_persisted_and_reused_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            request_id, conversation_id, proposal = self._persist_ready_proposal(
                database
            )
            adapter = FakeSlackAdapter()
            self.plugin._AUTOMATION = automation
            result = {
                "conversation_id": conversation_id,
                "proposal_id": proposal["id"],
                "revision_token": proposal["revision_token"],
            }
            with patch.dict(
                os.environ, {"REVIEW_HISTORY_DB": str(database)}, clear=False
            ):
                asyncio.run(self.plugin._deliver_proposal(adapter, "T_TEST", result))
                asyncio.run(self.plugin._deliver_proposal(adapter, "T_TEST", result))
            with automation.connect_db(database) as db:
                conversation = db.execute(
                    "SELECT dm_channel_id, thread_ts FROM workflow_pr_conversations "
                    "WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                delivery = db.execute(
                    "SELECT state, message_ts FROM slack_deliveries"
                ).fetchone()

        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(conversation["dm_channel_id"], "D_OWNER")
        self.assertEqual(conversation["thread_ts"], "200.1")
        self.assertEqual(delivery["state"], "sent")
        self.assertEqual(delivery["message_ts"], "200.1")
        self.assertTrue(request_id)

    def test_ambiguous_private_delivery_blocks_instead_of_reposting(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            _, conversation_id, proposal = self._persist_ready_proposal(database)
            adapter = FakeSlackAdapter(fail_send=True)
            self.plugin._AUTOMATION = automation
            result = {
                "conversation_id": conversation_id,
                "proposal_id": proposal["id"],
                "revision_token": proposal["revision_token"],
            }
            with patch.dict(
                os.environ, {"REVIEW_HISTORY_DB": str(database)}, clear=False
            ):
                asyncio.run(self.plugin._deliver_proposal(adapter, "T_TEST", result))
                asyncio.run(self.plugin._deliver_proposal(adapter, "T_TEST", result))
            with automation.connect_db(database) as db:
                state = db.execute("SELECT state FROM slack_deliveries").fetchone()[0]

        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(state, "blocked")

    def test_only_persisted_ready_proposals_are_deliverable(self):
        self.assertIsNone(
            self.plugin._ready_proposal_result(
                {"status": "analyzing", "proposal_id": "proposal-1"}
            )
        )
        ready = {
            "status": "awaiting_decision",
            "proposal_id": "proposal-2",
            "revision_token": "P2",
        }
        self.assertIs(self.plugin._ready_proposal_result(ready), ready)
        wrapped = {"status": "head_changed_during_analysis", "re_review": ready}
        self.assertIs(self.plugin._ready_proposal_result(wrapped), ready)

    def test_expired_private_delivery_reconciles_before_reposting(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            _, conversation_id, proposal = self._persist_ready_proposal(database)
            adapter = FakeSlackAdapter()

            async def find_message(_channel_id, _thread_ts, _workflow_key):
                return "200.9"

            adapter.find_message_by_workflow_key = find_message
            self.plugin._AUTOMATION = automation
            delivery_key = f"proposal:{proposal['id']}:summary"
            with automation.connect_db(database) as db:
                automation.claim_slack_delivery(
                    db,
                    delivery_key=delivery_key,
                    kind="proposal_summary",
                    workspace_id="T_TEST",
                    channel_id="D_OWNER",
                    thread_ts=None,
                    claimant="crashed-worker",
                    lease_seconds=-1,
                    conversation_id=conversation_id,
                    proposal_id=proposal["id"],
                    metadata_key=delivery_key,
                )
            result = {
                "conversation_id": conversation_id,
                "proposal_id": proposal["id"],
                "revision_token": proposal["revision_token"],
            }
            with patch.dict(
                os.environ, {"REVIEW_HISTORY_DB": str(database)}, clear=False
            ):
                asyncio.run(self.plugin._deliver_proposal(adapter, "T_TEST", result))
            with automation.connect_db(database) as db:
                delivery = db.execute(
                    "SELECT state, message_ts FROM slack_deliveries"
                ).fetchone()
                conversation = db.execute(
                    "SELECT thread_ts FROM workflow_pr_conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()

        self.assertEqual(adapter.sent, [])
        self.assertEqual(delivery["state"], "sent")
        self.assertEqual(delivery["message_ts"], "200.9")
        self.assertEqual(conversation["thread_ts"], "200.9")

    def test_public_verdict_is_created_once_then_edited_with_derived_reaction(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                request_id, _ = automation.get_or_create_source_request(
                    db,
                    workspace_id="T_TEST",
                    channel_id="C_REVIEW",
                    message_ts="100.1",
                    requester_user_id="U_REVIEWER",
                )
                conversations = []
                for position, repo in enumerate(("acme/api", "acme/web")):
                    conversation_id, _ = automation.get_or_create_pr_conversation(
                        db,
                        workspace_id="T_TEST",
                        owner_user_id="U_OWNER",
                        repo=repo,
                        pr_number=position + 1,
                        pr_url=f"https://github.com/{repo}/pull/{position + 1}",
                    )
                    automation.associate_request_conversation(
                        db, request_id, conversation_id, position=position
                    )
                    conversations.append(conversation_id)
                automation.update_request_member_outcome(
                    db,
                    conversation_id=conversations[0],
                    outcome="approved",
                    reviewed_head="a" * 40,
                )
            adapter = FakeSlackAdapter()
            self.plugin._AUTOMATION = automation
            with patch.dict(
                os.environ, {"REVIEW_HISTORY_DB": str(database)}, clear=False
            ):
                asyncio.run(self.plugin._project_request(adapter, request_id))
                with automation.connect_db(database) as db:
                    automation.update_request_member_outcome(
                        db,
                        conversation_id=conversations[1],
                        outcome="comments_published",
                        reviewed_head="b" * 40,
                        published_comment_count=2,
                    )
                asyncio.run(self.plugin._project_request(adapter, request_id))

        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(len(adapter.edited), 1)
        self.assertIn("pending", adapter.sent[0][1])
        self.assertIn("2 comments", adapter.edited[0][2])
        self.assertIn("eyes", [item[2] for item in adapter.added_reactions])
        self.assertIn("white_check_mark", [item[2] for item in adapter.added_reactions])

    def test_sent_verdict_receipt_is_bound_without_reposting(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "reviews.sqlite3"
            with automation.connect_db(database) as db:
                request_id, _ = automation.get_or_create_source_request(
                    db,
                    workspace_id="T_TEST",
                    channel_id="C_REVIEW",
                    message_ts="100.1",
                    requester_user_id="U_REVIEWER",
                )
                conversation_id, _ = automation.get_or_create_pr_conversation(
                    db,
                    workspace_id="T_TEST",
                    owner_user_id="U_OWNER",
                    repo="acme/api",
                    pr_number=1,
                    pr_url="https://github.com/acme/api/pull/1",
                )
                automation.associate_request_conversation(
                    db, request_id, conversation_id, position=0
                )
                automation.update_request_member_outcome(
                    db,
                    conversation_id=conversation_id,
                    outcome="approved",
                    reviewed_head="a" * 40,
                )
                delivery_id, state = automation.claim_slack_delivery(
                    db,
                    delivery_key=f"request:{request_id}:verdict",
                    kind="source_verdict",
                    workspace_id="T_TEST",
                    channel_id="C_REVIEW",
                    thread_ts="100.1",
                    claimant="slack-review-gate",
                    request_id=request_id,
                    metadata_key=f"request:{request_id}:verdict",
                )
                self.assertEqual(state, "claimed")
                automation.complete_slack_delivery(
                    db,
                    delivery_id=delivery_id,
                    claimant="slack-review-gate",
                    message_ts="300.1",
                )
            adapter = FakeSlackAdapter()
            self.plugin._AUTOMATION = automation
            with patch.dict(
                os.environ, {"REVIEW_HISTORY_DB": str(database)}, clear=False
            ):
                asyncio.run(self.plugin._project_request(adapter, request_id))
            with automation.connect_db(database) as db:
                verdict_ts = db.execute(
                    "SELECT verdict_message_ts FROM workflow_source_requests "
                    "WHERE id = ?",
                    (request_id,),
                ).fetchone()[0]

        self.assertEqual(adapter.sent, [])
        self.assertEqual(verdict_ts, "300.1")


if __name__ == "__main__":
    unittest.main()
