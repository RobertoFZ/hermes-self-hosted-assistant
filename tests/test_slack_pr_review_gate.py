from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


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
    "SLACK_REVIEW_ALLOWED_REPOSITORIES": "acme/api,acme/web",
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
        thread_id="",
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

    def test_reviewer_can_submit_only_allowed_pr_urls_in_dm(self):
        result = self.plugin._review_only_policy(
            event(
                "U_REVIEWER",
                "D_DIRECT",
                "please do this https://github.com/acme/api/pull/42",
            )
        )
        self.assertEqual(result["action"], "rewrite")
        self.assertIn("codex-pr-review", result["text"])
        self.assertIn("https://github.com/acme/api/pull/42", result["text"])
        self.assertNotIn("please do this", result["text"])
        self.assertIn("Self-review authorization: denied", result["text"])

    def test_owner_bot_mention_authorizes_self_review(self):
        with patch.object(self.plugin, "_schedule_review_started"):
            result = self.plugin._review_only_policy(
                event(
                    "U_OWNER",
                    "C_REVIEW",
                    "<@U_BOT> les comparto estos PRs para que revisen "
                    "https://github.com/acme/api/pull/42",
                ),
                gateway=gateway(),
            )
        self.assertEqual(result["action"], "rewrite")
        self.assertIn("Self-review authorization: allowed", result["text"])
        self.assertIn("--allow-self-review", result["text"])

    def test_owner_without_bot_mention_does_not_authorize_self_review(self):
        result = self.plugin._review_only_policy(
            event(
                "U_OWNER",
                "C_REVIEW",
                "Les comparto estos PRs para que revisen "
                "https://github.com/acme/api/pull/42",
            )
        )
        self.assertEqual(result["action"], "rewrite")
        self.assertIn("Self-review authorization: denied", result["text"])

    def test_slack_app_mention_event_authorizes_owner_without_configured_id(self):
        result = self.plugin._review_only_policy(
            event(
                "U_OWNER",
                "C_REVIEW",
                "Hermes https://github.com/acme/api/pull/42",
                raw_message={"type": "app_mention"},
            )
        )
        self.assertEqual(result["action"], "rewrite")
        self.assertIn("Self-review authorization: allowed", result["text"])

    def test_reviewer_cannot_authorize_self_review_by_mentioning_bot(self):
        with patch.object(self.plugin, "_schedule_review_started"):
            result = self.plugin._review_only_policy(
                event(
                    "U_REVIEWER",
                    "C_REVIEW",
                    "<@U_BOT> https://github.com/acme/api/pull/42",
                ),
                gateway=gateway(),
            )
        self.assertEqual(result["action"], "rewrite")
        self.assertIn("Self-review authorization: denied", result["text"])

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

    def test_unknown_user_is_rejected(self):
        result = self.plugin._review_only_policy(
            event("U_UNKNOWN", "C_REVIEW", "https://github.com/acme/api/pull/1")
        )
        self.assertEqual(result["reason"], "review-user-not-allowed")


if __name__ == "__main__":
    unittest.main()
