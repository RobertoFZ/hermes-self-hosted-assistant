#!/usr/bin/env python3
"""Eval harness for the pr-reviewer skill.

Three layers, matching the project skill-creator pattern:

1. Deterministic assertions  - the gate is obeyed exactly (correct event, no
   merge call ever, Spanish comments, top-level cause iff not approved, valid
   severity/category tags, expected critical categories present/absent).
2. LLM-as-judge               - comment quality, tone, reason present, concrete
   suggestion, severity correct, no CI-duplicated findings (rubric.md).
3. Variance                   - run each fixture N>=5 times; report decision
   stability and rubric-score variance. A fixture whose approve/no-approve
   decision FLIPS across runs is a gate-reliability bug and fails the harness.

The reviewer and judge are invoked through a CLI that reads a prompt on stdin
and writes the model response on stdout. Defaults to an ephemeral Codex run.
Override with:

    REVIEWER_CMD="codex exec --ephemeral -" \
    JUDGE_CMD="codex exec --ephemeral -" python eval.py
    REVIEWER_CMD="my-runner"   python eval.py --runs 5 --fixture 02-planted-blocker

Exit code is non-zero if any deterministic assertion fails or any decision flips.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import statistics
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
EVALS_DIR = SKILL_DIR / "references" / "evals"
FIXTURES_DIR = EVALS_DIR / "fixtures"

VALID_EVENTS = {"APPROVE", "COMMENT"}
VALID_SEVERITIES = {"blocker", "major", "minor", "nit"}
CRITICAL_CATEGORIES = {"correctness", "security", "migration_safety", "test_coverage"}
VALID_CATEGORIES = {
    "correctness",
    "security",
    "data_layer",
    "migration_safety",
    "architecture",
    "test_coverage",
    "error_handling",
    "scraper",
}
# Any of these appearing in the raw reviewer output is an instant, hard failure.
MERGE_PATTERNS = [
    r"\bgh\s+pr\s+merge\b",
    r"/merge\b",
    r"\bpulls/\d+/merge\b",
    r"\bmerge_method\b",
    r"\bmergePullRequest\b",
]
# Cheap heuristic that the comment bodies are Spanish, not English.
SPANISH_HINTS = re.compile(
    r"\b(el|la|los|las|que|para|con|este|esta|usa|sugiero|conviene|ojo|migraci|"
    r"índice|indice|sin|cambiar|comportamiento|puedes|podr)\b",
    re.IGNORECASE,
)
# Acknowledgments / filler that must NOT appear in the terse top-level comment.
ACK_PATTERNS = re.compile(
    r"(gracias|buen trabajo|buena pr|excelente|felicidades|enhorabuena|"
    r"no lo apruebo todav|aprecio|qué bueno|que bueno|sigue así|sigue asi|🙏|👍)",
    re.IGNORECASE,
)


def run_cli(cmd: str, prompt: str) -> str:
    """Run a prompt-on-stdin CLI and return its stdout, or raise on failure."""
    argv = shlex.split(cmd)
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            f"Could not run reviewer/judge command {argv!r}: {exc}. "
            "Set REVIEWER_CMD / JUDGE_CMD to a CLI that reads a prompt on stdin."
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(f"{argv!r} exited {proc.returncode}: {proc.stderr[:500]}")
    return proc.stdout


def extract_json_block(text: str) -> dict:
    """Pull the last JSON object out of a model response (fenced or bare)."""
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = fenced[:] if fenced else []
    if not candidates:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates = [text[start : end + 1]]
    for blob in reversed(candidates):
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            continue
    raise ValueError("No parseable JSON object found in model output")


@dataclass
class Fixture:
    name: str
    pr: dict
    diff: str
    expected: dict

    @classmethod
    def load(cls, path: Path) -> "Fixture":
        return cls(
            name=path.name,
            pr=json.loads((path / "pr.json").read_text()),
            diff=(path / "diff.patch").read_text(),
            expected=json.loads((path / "expected.json").read_text()),
        )


def load_skill_bundle() -> str:
    """Concatenate SKILL.md + every reference so the reviewer is self-contained."""
    parts = [f"===== SKILL.md =====\n{(SKILL_DIR / 'SKILL.md').read_text()}"]
    for ref in sorted((SKILL_DIR / "references").glob("*.md")):
        parts.append(f"===== references/{ref.name} =====\n{ref.read_text()}")
    return "\n\n".join(parts)


def build_review_prompt(bundle: str, fx: Fixture) -> str:
    return f"""You are the `pr-reviewer` skill. Follow it exactly. This is DRY-RUN /
eval mode: do NOT call gh, do NOT post anything, do NOT merge. Review the diff
below and emit ONLY the dry-run output contract (a single fenced ```json block)
described in SKILL.md. No prose before or after the json block.

{bundle}

===== PR METADATA =====
repo: {fx.pr['repo']}
title: {fx.pr['title']}
body: {fx.pr.get('body', '')}

===== DIFF UNDER REVIEW =====
{fx.diff}

Now output only the json review object per the dry-run output contract.
"""


def build_judge_prompt(rubric: str, fx: Fixture, review: dict) -> str:
    return f"""You are grading a code review against the rubric below. Output ONLY
the strict JSON object the rubric specifies. Be strict and deterministic.

{rubric}

===== DIFF THAT WAS REVIEWED =====
{fx.diff}

===== THE REVIEW BEING GRADED (json) =====
{json.dumps(review, ensure_ascii=False, indent=2)}

Now output only the rubric json.
"""


@dataclass
class RunResult:
    review: dict | None
    raw: str
    det_failures: list[str] = field(default_factory=list)
    judge: dict | None = None

    @property
    def approved(self) -> bool | None:
        if self.review is None:
            return None
        return bool(self.review.get("approved"))


def deterministic_checks(fx: Fixture, review: dict, raw: str) -> list[str]:
    """Return a list of failure messages; empty list means all asserts passed."""
    fails: list[str] = []
    exp = fx.expected

    for pat in MERGE_PATTERNS:
        if re.search(pat, raw, re.IGNORECASE):
            fails.append(f"FORBIDDEN merge call matched /{pat}/ in reviewer output")

    event = review.get("event")
    if event not in VALID_EVENTS:
        fails.append(f"event {event!r} not in {VALID_EVENTS}")
    if event != exp["event"]:
        fails.append(f"event {event!r} != expected {exp['event']!r}")

    approved = review.get("approved")
    if not isinstance(approved, bool):
        fails.append("approved must be a boolean")
    elif approved != exp["approved"]:
        fails.append(f"approved {approved} != expected {exp['approved']}")
    if isinstance(approved, bool) and approved != (event == "APPROVE"):
        fails.append("approved and event disagree")

    comments = review.get("comments") or []
    if not isinstance(comments, list):
        fails.append("comments must be a list")
        comments = []

    categories_found: set[str] = set()
    for i, c in enumerate(comments):
        sev = c.get("severity")
        cat = c.get("category")
        body = c.get("body", "")
        if sev not in VALID_SEVERITIES:
            fails.append(f"comment[{i}] severity {sev!r} invalid")
        if cat not in VALID_CATEGORIES:
            fails.append(f"comment[{i}] category {cat!r} invalid")
        else:
            categories_found.add(cat)
        if not str(c.get("path", "")).strip():
            fails.append(f"comment[{i}] missing path")
        if not SPANISH_HINTS.search(body):
            fails.append(f"comment[{i}] body does not look like Spanish: {body[:60]!r}")
        if re.match(r"\s*(nit|bloqueante|blocker|major|minor)\s*:", body, re.IGNORECASE):
            fails.append(f"comment[{i}] uses a forbidden severity prefix")

    # A "blocking" finding: critical category at any severity, or blocker/major anywhere.
    blocking = [
        c
        for c in comments
        if c.get("category") in CRITICAL_CATEGORIES
        or c.get("severity") in {"blocker", "major"}
    ]

    # Gate self-consistency: APPROVE requires zero blocking findings.
    gate_should_approve = len(blocking) == 0
    if isinstance(approved, bool) and approved != gate_should_approve:
        fails.append(
            f"gate violation: approved={approved} but {len(blocking)} blocking "
            f"finding(s) present "
            f"(critical={sorted(categories_found & CRITICAL_CATEGORIES)})"
        )

    min_blocking = exp.get("min_blocking_findings")
    if min_blocking is not None and len(blocking) < min_blocking:
        fails.append(f"{len(blocking)} blocking findings < expected min {min_blocking}")

    # Top-level comment: present ONLY when not approved AND more than one blocking finding;
    # absent otherwise. When present it must be terse Spanish with no acknowledgments/filler.
    cause = review.get("top_level_comment")
    has_cause = isinstance(cause, str) and bool(cause.strip())
    should_have_cause = (not approved) and len(blocking) > 1

    if should_have_cause != exp["cause_required"]:
        fails.append(
            f"cause-branch mismatch: review implies should_have_cause={should_have_cause} "
            f"(approved={approved}, blocking={len(blocking)}) but fixture expects "
            f"cause_required={exp['cause_required']}"
        )
    if has_cause and not should_have_cause:
        fails.append(
            "top_level_comment present but not warranted "
            f"(approved={approved}, blocking={len(blocking)} — need >1 blocking)"
        )
    if should_have_cause and not has_cause:
        fails.append("more than one blocking finding requires a top_level_comment")
    if has_cause and should_have_cause:
        if not SPANISH_HINTS.search(cause):
            fails.append(f"top_level_comment not Spanish: {cause[:60]!r}")
        if ACK_PATTERNS.search(cause):
            fails.append(f"top_level_comment has acknowledgment/filler: {cause[:80]!r}")
        needles = exp.get("cause_must_mention_any")
        if needles and not any(n.lower() in cause.lower() for n in needles):
            fails.append(f"cause comment mentions none of {needles}")

    for cat in exp.get("must_find_categories", []):
        if cat not in categories_found:
            fails.append(f"expected a finding in category {cat!r}, none present")
    for cat in exp.get("forbidden_categories", []):
        if cat in categories_found:
            fails.append(f"unexpected finding in critical category {cat!r}")

    if "min_comments" in exp and len(comments) < exp["min_comments"]:
        fails.append(f"{len(comments)} comments < min {exp['min_comments']}")
    if "max_comments" in exp and len(comments) > exp["max_comments"]:
        fails.append(f"{len(comments)} comments > max {exp['max_comments']}")

    return fails


def evaluate_fixture(
    fx: Fixture, bundle: str, rubric: str, runs: int, reviewer_cmd: str,
    judge_cmd: str | None,
) -> list[RunResult]:
    results: list[RunResult] = []
    review_prompt = build_review_prompt(bundle, fx)
    for n in range(runs):
        raw = run_cli(reviewer_cmd, review_prompt)
        try:
            review = extract_json_block(raw)
        except ValueError as exc:
            results.append(RunResult(review=None, raw=raw, det_failures=[str(exc)]))
            print(f"    run {n + 1}/{runs}: PARSE-FAIL")
            continue
        det = deterministic_checks(fx, review, raw)
        judge = None
        if judge_cmd:
            try:
                judge = extract_json_block(run_cli(judge_cmd, build_judge_prompt(rubric, fx, review)))
            except (ValueError, RuntimeError) as exc:
                judge = {"overall": None, "notes": f"judge error: {exc}"}
        results.append(RunResult(review=review, raw=raw, det_failures=det, judge=judge))
        status = "ok" if not det else f"DET-FAIL({len(det)})"
        decision = "APPROVE" if review.get("approved") else "COMMENT"
        score = (judge or {}).get("overall") if judge else None
        print(f"    run {n + 1}/{runs}: {decision} {status}"
              + (f" judge={score}" if score is not None else ""))
    return results


def report_fixture(fx: Fixture, results: list[RunResult]) -> bool:
    """Print the per-fixture report. Return True if the fixture passes."""
    decisions = [r.approved for r in results if r.approved is not None]
    stable = len(set(decisions)) <= 1 if decisions else False
    flipped = not stable
    all_det_pass = all(not r.det_failures for r in results) and len(results) == len(decisions)

    scores = [
        r.judge["overall"]
        for r in results
        if r.judge and isinstance(r.judge.get("overall"), (int, float))
    ]
    print(f"\n  FIXTURE {fx.name}")
    print(f"    expected: event={fx.expected['event']} approved={fx.expected['approved']}")
    print(f"    decisions: {['APPROVE' if d else 'COMMENT' for d in decisions]}")
    print(f"    decision stability: {'STABLE' if stable else 'FLIPPED *** gate-reliability bug ***'}")
    print(f"    deterministic asserts: {'ALL PASS' if all_det_pass else 'FAILURES'}")
    if scores:
        var = statistics.pvariance(scores) if len(scores) > 1 else 0.0
        print(f"    judge overall: mean={statistics.mean(scores):.2f} "
              f"min={min(scores):.2f} max={max(scores):.2f} variance={var:.3f}")
    for i, r in enumerate(results):
        for f in r.det_failures:
            print(f"      run {i + 1} assert: {f}")
    return all_det_pass and not flipped


def main() -> int:
    ap = argparse.ArgumentParser(description="pr-reviewer eval harness")
    ap.add_argument("--runs", type=int, default=5, help="runs per fixture (>=5 for variance)")
    ap.add_argument("--fixture", help="run a single fixture by directory name")
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM-judge layer")
    ap.add_argument("--reviewer-cmd", default=None, help="override REVIEWER_CMD")
    ap.add_argument("--judge-cmd", default=None, help="override JUDGE_CMD")
    args = ap.parse_args()

    import os

    default_cmd = "codex exec --skip-git-repo-check --ephemeral -"
    reviewer_cmd = args.reviewer_cmd or os.environ.get("REVIEWER_CMD", default_cmd)
    judge_cmd = None if args.no_judge else (args.judge_cmd or os.environ.get("JUDGE_CMD", default_cmd))

    bundle = load_skill_bundle()
    rubric = (EVALS_DIR / "rubric.md").read_text()

    fixture_dirs = sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir())
    if args.fixture:
        fixture_dirs = [p for p in fixture_dirs if p.name == args.fixture]
        if not fixture_dirs:
            print(f"No fixture named {args.fixture!r}")
            return 2

    print(f"reviewer: {reviewer_cmd!r}  judge: {judge_cmd!r}  runs: {args.runs}")
    all_pass = True
    for path in fixture_dirs:
        fx = Fixture.load(path)
        print(f"\n=== {fx.name} ({fx.pr['repo']} #{fx.pr['number']}) ===")
        results = evaluate_fixture(fx, bundle, rubric, args.runs, reviewer_cmd, judge_cmd)
        all_pass &= report_fixture(fx, results)

    print("\n" + ("PASS" if all_pass else "FAIL"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
