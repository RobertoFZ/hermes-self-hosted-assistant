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
    path = ROOT / "scripts" / "prepare_review_actions.py"
    spec = importlib.util.spec_from_file_location("prepare_review_actions", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrepareReviewActionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = load_module()
        self.head = "c" * 40
        self.context = {
            "repository": "acme/payments",
            "pr": 103,
            "head_ref_oid": self.head,
        }
        self.validation = {
            "repository": "acme/payments",
            "review_pr": 103,
            "briefed_head_oid": self.head,
            "duplicate_protection": "complete",
            "candidate_decisions": [
                {
                    "candidate_id": "acme/payments#103:E1",
                    "local_id": "E1",
                    "classification": "new-topic",
                    "owning_repository": "acme/payments",
                    "owning_pr": 103,
                    "suggested_action": "new-comment",
                    "thread_id": None,
                    "thread_url": None,
                }
            ],
        }

    def prepare(self, selectors: list[str], action: str = "new-comment", **options: object) -> dict[str, object]:
        return self.guard.prepare_action_plan(
            self.context,
            self.validation,
            selectors,
            action,
            "acme/payments#103",
            self.head,
            **options,
        )

    def test_resolves_qualified_candidate_only_inside_active_pr(self) -> None:
        result = self.prepare(["acme/payments#103:E1"])

        self.assertEqual(result["review_target"], {"repository": "acme/payments", "pr": 103})
        self.assertEqual(result["publication_target"], {"repository": "acme/payments", "pr": 103})
        self.assertEqual(result["items"][0]["candidate_id"], "acme/payments#103:E1")
        self.assertRegex(result["action_id"], r"^[0-9a-f]{16}$")

    def test_rejects_bare_candidate_for_publication(self) -> None:
        with self.assertRaisesRegex(self.guard.ActionPlanError, "qualified"):
            self.prepare(["E1"])

    def test_rejects_same_candidate_number_from_previous_pr(self) -> None:
        with self.assertRaisesRegex(self.guard.ActionPlanError, "active review target"):
            self.prepare(["acme/payments#102:E1"])

    def test_rejects_validation_artifact_from_previous_pr(self) -> None:
        self.validation["review_pr"] = 102

        with self.assertRaisesRegex(self.guard.ActionPlanError, "validation review target"):
            self.prepare(["acme/payments#103:E1"])

    def test_rejects_head_drift_before_planning_write(self) -> None:
        with self.assertRaisesRegex(self.guard.ActionPlanError, "head changed"):
            self.guard.prepare_action_plan(
                self.context,
                self.validation,
                ["acme/payments#103:E1"],
                "new-comment",
                "acme/payments#103",
                "d" * 40,
            )

    def test_open_thread_requires_exact_reply_route(self) -> None:
        candidate = self.validation["candidate_decisions"][0]
        candidate.update(
            {
                "classification": "open-existing-thread",
                "suggested_action": "reply-thread",
                "thread_id": "RT_103",
                "thread_url": "https://example.test/pr/103#discussion_r1",
            }
        )

        with self.assertRaisesRegex(self.guard.ActionPlanError, "requires reply-thread"):
            self.prepare(["acme/payments#103:E1"], "new-comment")

        result = self.prepare(["acme/payments#103:E1"], "reply-thread")

        self.assertEqual(result["items"][0]["thread_id"], "RT_103")
        self.assertEqual(result["publication_target"]["pr"], 103)

    def test_cross_pr_thread_requires_explicit_publication_target(self) -> None:
        candidate = self.validation["candidate_decisions"][0]
        candidate.update(
            {
                "classification": "open-existing-thread",
                "owning_pr": 102,
                "suggested_action": "reply-thread",
                "thread_id": "RT_102",
                "thread_url": "https://example.test/pr/102#discussion_r1",
            }
        )

        with self.assertRaisesRegex(self.guard.ActionPlanError, "cross-PR"):
            self.prepare(["acme/payments#103:E1"], "reply-thread")

        result = self.prepare(
            ["acme/payments#103:E1"],
            "reply-thread",
            allow_cross_pr=True,
            expected_publication_target="acme/payments#102",
        )

        self.assertEqual(result["review_target"]["pr"], 103)
        self.assertEqual(result["publication_target"]["pr"], 102)
        self.assertEqual(result["items"][0]["thread_id"], "RT_102")

    def test_review_decision_without_candidates_is_bound_to_active_pr(self) -> None:
        result = self.prepare([], "approve")

        self.assertEqual(result["action"], "approve")
        self.assertEqual(result["review_target"], {"repository": "acme/payments", "pr": 103})
        self.assertEqual(result["publication_target"], result["review_target"])
        self.assertEqual(result["items"], [])

    def test_cli_writes_only_a_current_pr_action_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path = root / "context.json"
            validation_path = root / "validation.json"
            valid_plan_path = root / "valid-plan.json"
            stale_plan_path = root / "stale-plan.json"
            context_path.write_text(json.dumps(self.context), encoding="utf-8")
            validation_path.write_text(json.dumps(self.validation), encoding="utf-8")
            base_command = [
                "python3",
                str(ROOT / "scripts" / "prepare_review_actions.py"),
                "--context",
                str(context_path),
                "--validation",
                str(validation_path),
                "--action",
                "new-comment",
                "--expected-active",
                "acme/payments#103",
                "--current-head",
                self.head,
            ]

            valid = subprocess.run(
                base_command
                + [
                    "--selector",
                    "acme/payments#103:E1",
                    "--output",
                    str(valid_plan_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            stale = subprocess.run(
                base_command
                + [
                    "--selector",
                    "acme/payments#102:E1",
                    "--output",
                    str(stale_plan_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(
                json.loads(valid_plan_path.read_text(encoding="utf-8"))["publication_target"],
                {"repository": "acme/payments", "pr": 103},
            )
            self.assertEqual(stale.returncode, 2)
            self.assertIn("active review target", stale.stderr)
            self.assertFalse(stale_plan_path.exists())


if __name__ == "__main__":
    unittest.main()
