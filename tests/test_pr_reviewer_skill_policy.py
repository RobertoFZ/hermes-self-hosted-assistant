import unittest
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILL = (ROOT / "skills" / "pr-reviewer" / "SKILL.md").read_text(
    encoding="utf-8"
)
WORKFLOW = (
    ROOT / "skills" / "pr-reviewer" / "references" / "workflow.md"
).read_text(encoding="utf-8")
GH_RUNBOOK = (
    ROOT / "skills" / "pr-reviewer" / "references" / "gh-runbook.md"
).read_text(encoding="utf-8")
SEVERITY_RUBRIC = (
    ROOT / "skills" / "pr-reviewer" / "references" / "severity-rubric.md"
).read_text(encoding="utf-8")
LOCAL_WORKFLOW = (
    ROOT / "skills" / "pr-reviewer" / "references" / "local-branch-workflow.md"
).read_text(encoding="utf-8")
REVIEW_RESULT_SCHEMA = json.loads(
    (ROOT / "automation" / "review-result.schema.json").read_text(encoding="utf-8")
)


class PRReviewerSkillPolicyTests(unittest.TestCase):
    def test_github_review_mode_is_read_only_until_owner_confirmation(self):
        for content in (SKILL, WORKFLOW):
            self.assertIn("read-only proposal", content)
            self.assertIn("published", content)
            self.assertIn("false", content)
            self.assertIn("explicit owner confirmation", content)
        self.assertNotIn("Publish GitHub reviews immediately", SKILL)
        self.assertNotIn("Publish by default", WORKFLOW)

    def test_materiality_boundary_withholds_mechanical_and_speculative_comments(self):
        for content in (SKILL, WORKFLOW, SEVERITY_RUBRIC):
            self.assertIn("assertion placement", content)
            self.assertIn("assertion constants", content)
            self.assertIn("one-use helper", content)
            self.assertIn("speculative abstraction", content)
        self.assertIn("persistent data", SEVERITY_RUBRIC)
        self.assertIn("rollout compatibility", SEVERITY_RUBRIC)
        self.assertIn("meaningful regression", SEVERITY_RUBRIC)

    def test_proposals_assign_stable_candidate_ids_and_executable_coordinates(self):
        for content in (SKILL, WORKFLOW):
            self.assertIn("candidate_id", content)
            self.assertIn("Never renumber", content)
            self.assertIn("start_side", content)
        finding = REVIEW_RESULT_SCHEMA["properties"]["findings"]["items"]
        self.assertIn("candidate_id", finding["required"])
        self.assertEqual(finding["properties"]["candidate_id"]["pattern"], r"^C[1-9][0-9]*$")
        for field in ("path", "line", "side", "start_line", "start_side"):
            self.assertIn(field, finding["required"])

    def test_proposal_delta_distinguishes_addressed_open_and_new_findings(self):
        for content in (SKILL, WORKFLOW):
            self.assertIn("addressed_candidate_ids", content)
            self.assertIn("still_open_candidate_ids", content)
            self.assertIn("new_candidate_ids", content)
        delta = REVIEW_RESULT_SCHEMA["properties"]["delta"]
        self.assertEqual(
            set(delta["required"]),
            {
                "status",
                "summary",
                "addressed_candidate_ids",
                "still_open_candidate_ids",
                "new_candidate_ids",
            },
        )

    def test_scratch_artifacts_stay_inside_hermes_safe_root(self):
        for content in (SKILL, WORKFLOW, GH_RUNBOOK):
            self.assertIn("/opt/data/pr-reviewer-tmp", content)
            self.assertIn("/tmp", content)

    def test_runbook_does_not_weaken_write_boundary(self):
        self.assertIn("do not create a payload file", GH_RUNBOOK)
        self.assertIn("Do not unset or broaden", GH_RUNBOOK)
        self.assertNotIn("HERMES_WRITE_SAFE_ROOT=/opt/data:/tmp", GH_RUNBOOK)

    def test_openspec_reviews_validate_without_mutating(self):
        self.assertIn("run strict validation", SKILL)
        self.assertIn("openspec validate <change-name> --strict", WORKFLOW)
        for command in ("init", "update", "archive"):
            self.assertIn(f"`openspec {command}`", SKILL)
            self.assertIn(f"`openspec {command}`", WORKFLOW)

    def test_default_discovery_skips_self_authored_prs(self):
        self.assertIn(
            "automatic/default discovery, exclude PRs authored by the authenticated",
            SKILL,
        )
        self.assertIn("keep only `author.login != ME`", WORKFLOW)
        self.assertIn("by default exclude your own PRs", GH_RUNBOOK)

    def test_explicit_target_allows_self_review(self):
        self.assertIn("A named PR number or URL", SKILL)
        self.assertIn("directly names one by PR number/URL", WORKFLOW)
        self.assertIn("direct PR number/URL", GH_RUNBOOK)

    def test_self_review_never_approves(self):
        self.assertIn("never submit `APPROVE`", SKILL)
        self.assertIn("Never attempt `APPROVE` when `author.login == ME`", WORKFLOW)
        self.assertIn("never send `event=APPROVE`", GH_RUNBOOK)
        self.assertIn("PR author.login != authenticated GitHub login", SEVERITY_RUBRIC)

    def test_zero_finding_self_review_posts_visible_comment(self):
        expected = (
            "Autorrevisión solicitada: no encontré hallazgos, pero GitHub no "
            "permite aprobar un PR propio."
        )
        self.assertIn(expected, WORKFLOW)
        self.assertIn(expected, GH_RUNBOOK)
        self.assertIn('self-authored PR always emits `"event": "COMMENT"`', WORKFLOW)

    def test_clean_feature_branch_with_committed_diff_is_reviewed(self):
        self.assertIn(
            "A clean working tree does not mean there is nothing to review",
            LOCAL_WORKFLOW,
        )
        self.assertIn(
            "aggregate diff from the merge base is non-empty",
            LOCAL_WORKFLOW,
        )
        self.assertNotIn(
            "If\n the tree is clean there is nothing to review",
            LOCAL_WORKFLOW,
        )

    def test_local_review_returns_stable_structured_handoff(self):
        self.assertIn("structured `pre_pr_review` handoff", LOCAL_WORKFLOW)
        self.assertIn("reviewed_head: <HEAD SHA from the stable snapshot>", LOCAL_WORKFLOW)
        self.assertIn("discard the result and restart", LOCAL_WORKFLOW)


if __name__ == "__main__":
    unittest.main()
