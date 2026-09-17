#!/usr/bin/env python3
"""Eval harness for the pr-reviewer skill.

Three layers, matching the project skill-creator pattern:

1. Deterministic assertions  - the read-only proposal contract, gate, stable
   candidate IDs, executable coordinates, materiality boundary, Spanish text,
   and valid severity/category tags are obeyed exactly.
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
POLICY_EVALS_DIR = SKILL_DIR / "evals"
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
MECHANICAL_PATTERNS = re.compile(
    r"(assert(?:ion)?\s+(?:phase|placement|constant)|magic\s+(?:value|number)"
    r"|one[- ]use\s+helper|single[- ]use\s+helper|extract(?:ing)?\s+(?:this\s+)?"
    r"(?:into|to)\s+(?:a\s+)?helper|speculative\s+abstraction|"
    r"por\s+claridad\s+(?:podr[ií]as|conviene)\s+extraer)",
    re.IGNORECASE,
)
CANDIDATE_ID = re.compile(r"^C[1-9][0-9]*$")


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
        expected = json.loads((path / "expected.json").read_text())
        overrides_path = POLICY_EVALS_DIR / "expectations.json"
        if overrides_path.is_file():
            overrides = json.loads(overrides_path.read_text())
            expected.update(overrides.get(path.name, {}))
        return cls(
            name=path.name,
            pr=json.loads((path / "pr.json").read_text()),
            diff=(path / "diff.patch").read_text(),
            expected=expected,
        )


def load_skill_bundle() -> str:
    """Concatenate SKILL.md + every reference so the reviewer is self-contained."""
    parts = [f"===== SKILL.md =====\n{(SKILL_DIR / 'SKILL.md').read_text()}"]
    for ref in sorted((SKILL_DIR / "references").glob("*.md")):
        parts.append(f"===== references/{ref.name} =====\n{ref.read_text()}")
    corpus = POLICY_EVALS_DIR / "materiality-corpus.json"
    if corpus.is_file():
        parts.append(
            "===== labeled materiality corpus =====\n"
            "Apply these labels as policy examples, not as candidate text.\n"
            + corpus.read_text()
        )
    return "\n\n".join(parts)


def build_review_prompt(bundle: str, fx: Fixture) -> str:
    return f"""You are the `pr-reviewer` skill. Follow it exactly. This is proposal /
eval mode: do NOT call gh, do NOT post anything, do NOT merge. Analyze the diff
below and emit ONLY the proposal output contract (a single fenced ```json block)
described in SKILL.md. No prose before or after the json block.

{bundle}

===== PR METADATA =====
repo: {fx.pr['repo']}
pr_number: {fx.pr['number']}
head_sha: 0123456789abcdef0123456789abcdef01234567
baseline_head_sha: null
title: {fx.pr['title']}
body: {fx.pr.get('body', '')}

===== DIFF UNDER REVIEW =====
{fx.diff}

Now output only the json read-only proposal per the proposal output contract.
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
        event = self.review.get("event")
        return event == "APPROVE" if event in VALID_EVENTS else None


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

    if review.get("published") is not False:
        fails.append("published must be false; analysis is read-only")
    if review.get("repo") != fx.pr["repo"]:
        fails.append(f"repo {review.get('repo')!r} != fixture repo {fx.pr['repo']!r}")
    if review.get("pr_number") != fx.pr["number"]:
        fails.append("pr_number does not match fixture")
    if not isinstance(review.get("head_sha"), str) or len(review["head_sha"]) < 7:
        fails.append("head_sha must identify the analyzed revision")
    if review.get("baseline_head_sha") is not None:
        fails.append("initial fixture proposal must use baseline_head_sha=null")
    for field_name in ("objective", "summary"):
        if not str(review.get(field_name, "")).strip():
            fails.append(f"{field_name} must be a non-empty string")

    findings = review.get("findings") or []
    if not isinstance(findings, list):
        fails.append("findings must be a list")
        findings = []

    categories_found: set[str] = set()
    candidate_ids: list[str] = []
    for i, c in enumerate(findings):
        prefix = f"finding[{i}]"
        candidate_id = c.get("candidate_id")
        if not isinstance(candidate_id, str) or not CANDIDATE_ID.fullmatch(candidate_id):
            fails.append(f"{prefix} candidate_id {candidate_id!r} invalid")
        else:
            candidate_ids.append(candidate_id)
        sev = c.get("severity")
        cat = c.get("category")
        body = c.get("body", "")
        if sev not in VALID_SEVERITIES:
            fails.append(f"{prefix} severity {sev!r} invalid")
        if cat not in VALID_CATEGORIES:
            fails.append(f"{prefix} category {cat!r} invalid")
        else:
            categories_found.add(cat)
        if not SPANISH_HINTS.search(body):
            fails.append(f"{prefix} body does not look like Spanish: {body[:60]!r}")
        if re.match(r"\s*(nit|bloqueante|blocker|major|minor)\s*:", body, re.IGNORECASE):
            fails.append(f"{prefix} uses a forbidden severity prefix")
        evidence = str(c.get("evidence", ""))
        if not evidence.strip():
            fails.append(f"{prefix} missing evidence")
        if MECHANICAL_PATTERNS.search(f"{body}\n{evidence}"):
            fails.append(f"{prefix} is mechanical or speculative and must be withheld")

        path = c.get("path")
        coordinates = ("line", "side", "start_line", "start_side")
        if isinstance(path, str) and path.strip():
            if not isinstance(c.get("line"), int) or c["line"] < 1:
                fails.append(f"{prefix} inline coordinate needs a positive line")
            if c.get("side") not in {"LEFT", "RIGHT"}:
                fails.append(f"{prefix} inline coordinate needs LEFT/RIGHT side")
            has_start_line = c.get("start_line") is not None
            has_start_side = c.get("start_side") is not None
            if has_start_line != has_start_side:
                fails.append(f"{prefix} start_line/start_side must be paired")
            if has_start_line and (
                not isinstance(c["start_line"], int)
                or c["start_line"] < 1
                or c["start_side"] not in {"LEFT", "RIGHT"}
            ):
                fails.append(f"{prefix} has invalid range coordinates")
        elif path is None:
            if any(c.get(name) is not None for name in coordinates):
                fails.append(f"{prefix} non-inline coordinates must all be null")
        else:
            fails.append(f"{prefix} path must be a non-empty string or null")

        should_block = cat in CRITICAL_CATEGORIES or sev in {"blocker", "major"}
        if c.get("blocking") is not should_block:
            fails.append(f"{prefix} blocking must be {should_block}")

    if len(candidate_ids) != len(set(candidate_ids)):
        fails.append("candidate_id values must be unique")
    expected_ids = [f"C{i}" for i in range(1, len(findings) + 1)]
    if candidate_ids != expected_ids:
        fails.append(f"candidate IDs must be stable sequential order {expected_ids}")

    # A "blocking" finding: critical category at any severity, or blocker/major anywhere.
    blocking = [
        c
        for c in findings
        if c.get("category") in CRITICAL_CATEGORIES
        or c.get("severity") in {"blocker", "major"}
    ]

    # Gate self-consistency: APPROVE requires zero blocking findings.
    gate_should_approve = len(blocking) == 0
    if event in VALID_EVENTS and (event == "APPROVE") != gate_should_approve:
        fails.append(
            f"gate violation: event={event} but {len(blocking)} blocking "
            f"finding(s) present "
            f"(critical={sorted(categories_found & CRITICAL_CATEGORIES)})"
        )

    min_blocking = exp.get("min_blocking_findings")
    if min_blocking is not None and len(blocking) < min_blocking:
        fails.append(f"{len(blocking)} blocking findings < expected min {min_blocking}")

    delta = review.get("delta")
    if not isinstance(delta, dict):
        fails.append("delta must be an object")
    else:
        if delta.get("status") != "initial":
            fails.append("initial fixture proposal must use delta.status=initial")
        if delta.get("addressed_candidate_ids") != []:
            fails.append("initial proposal cannot have addressed candidate IDs")
        if delta.get("still_open_candidate_ids") != []:
            fails.append("initial proposal cannot have still-open candidate IDs")
        if delta.get("new_candidate_ids") != candidate_ids:
            fails.append("delta.new_candidate_ids must list every initial candidate")

    for cat in exp.get("must_find_categories", []):
        if cat not in categories_found:
            fails.append(f"expected a finding in category {cat!r}, none present")
    for cat in exp.get("forbidden_categories", []):
        if cat in categories_found:
            fails.append(f"unexpected finding in critical category {cat!r}")

    if "min_comments" in exp and len(findings) < exp["min_comments"]:
        fails.append(f"{len(findings)} findings < min {exp['min_comments']}")
    if "max_comments" in exp and len(findings) > exp["max_comments"]:
        fails.append(f"{len(findings)} findings > max {exp['max_comments']}")

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
        decision = review.get("event", "INVALID")
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
    policy_rubric = POLICY_EVALS_DIR / "rubric.md"
    rubric = (policy_rubric if policy_rubric.is_file() else EVALS_DIR / "rubric.md").read_text()

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
