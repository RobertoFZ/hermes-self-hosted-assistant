from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import sync_crons


ROOT = Path(__file__).parents[1]


class CronConfigTests(unittest.TestCase):
    def test_repository_config_expands_owner_fallback_and_mexico_timezone(self):
        config = sync_crons.load_config(
            ROOT / "config" / "crons.json",
            {
                "TZ": "America/Mexico_City",
                "SLACK_REVIEW_OWNER_USER_IDS": "U_OWNER",
                "SLACK_REVIEW_DIGEST_USER_ID": "",
                "REVIEW_MONOREPO_ROOT": "/opt/data/repos/product",
            },
        )
        self.assertEqual(config["timezone"], "America/Mexico_City")
        self.assertEqual(config["jobs"][0]["schedule"], "0 17 * * *")
        self.assertEqual(config["jobs"][0]["deliver"], "slack:U_OWNER")
        self.assertEqual(config["jobs"][0]["skills"], ["review-digest"])

    def test_ambiguous_owner_requires_explicit_digest_recipient(self):
        with self.assertRaises(sync_crons.CronConfigError):
            sync_crons.load_config(
                ROOT / "config" / "crons.json",
                {
                    "TZ": "America/Mexico_City",
                    "SLACK_REVIEW_OWNER_USER_IDS": "U_ONE,U_TWO",
                    "REVIEW_MONOREPO_ROOT": "/workspace",
                },
            )

    def test_reconcile_creates_then_edits_only_managed_job(self):
        config = {
            "version": 1,
            "timezone": "America/Mexico_City",
            "jobs": [
                {
                    "key": "daily-review-digest",
                    "name": "Daily PR review digest",
                    "schedule": "0 17 * * *",
                    "prompt": "digest",
                    "skills": ["review-digest"],
                    "deliver": "slack:U_OWNER",
                    "workdir": "/workspace",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            created = subprocess.CompletedProcess([], 0, "Created job: abc123\n", "")
            edited = subprocess.CompletedProcess([], 0, "Updated job\n", "")
            with patch.dict(os.environ, {"TZ": "America/Mexico_City"}, clear=False):
                with patch.object(sync_crons, "execute", return_value=created) as execute:
                    self.assertEqual(
                        sync_crons.reconcile(config, state),
                        {"daily-review-digest": "abc123"},
                    )
                    self.assertIn("create", execute.call_args.args[0])
                with patch.object(sync_crons, "execute", return_value=edited) as execute:
                    sync_crons.reconcile(config, state)
                    self.assertIn("edit", execute.call_args.args[0])
            self.assertEqual(
                json.loads(state.read_text(encoding="utf-8")),
                {"daily-review-digest": "abc123"},
            )

    def test_edit_failure_does_not_create_a_duplicate_job(self):
        job = {
            "name": "Daily PR review digest",
            "schedule": "0 17 * * *",
            "prompt": "digest",
            "skills": ["review-digest"],
            "deliver": "slack:U_OWNER",
            "workdir": "/workspace",
        }
        failed = subprocess.CompletedProcess([], 1, "", "daemon unavailable")
        with patch.object(sync_crons, "execute", return_value=failed):
            with self.assertRaises(sync_crons.CronConfigError):
                sync_crons.edit_job("abc123", job)


if __name__ == "__main__":
    unittest.main()
