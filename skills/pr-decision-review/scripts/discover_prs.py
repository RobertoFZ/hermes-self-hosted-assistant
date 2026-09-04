from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Sequence


PR_FIELDS = "number,title,author,url,reviewDecision,reviewRequests,isDraft,updatedAt,latestReviews"
OUTPUT_FIELDS = (
    "number",
    "title",
    "author",
    "url",
    "is_draft",
    "review_decision",
    "our_review_state",
    "default_selected",
)


def run(command: Sequence[str]) -> str:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"command exited {completed.returncode}")
    return completed.stdout


def run_json(command: Sequence[str]) -> Any:
    return json.loads(run(command))


def author_login(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        login = value.get("login")
        return login if isinstance(login, str) else None
    return None


def our_review_state(pull_request: dict[str, Any], viewer_login: str) -> str:
    reviews = pull_request.get("latestReviews")
    if not isinstance(reviews, list):
        return "not-reviewed-by-us"
    matching = [
        review
        for review in reviews
        if isinstance(review, dict) and author_login(review.get("author")) == viewer_login
    ]
    non_dismissed = [review for review in matching if str(review.get("state", "")).upper() != "DISMISSED"]
    if not non_dismissed:
        return "not-reviewed-by-us"
    state = str(non_dismissed[-1].get("state", "")).upper()
    return "approved-by-us" if state == "APPROVED" else "reviewed-by-us"


def normalize_pull_request(pull_request: dict[str, Any], viewer_login: str) -> dict[str, Any] | None:
    author = author_login(pull_request.get("author"))
    if author == viewer_login:
        return None
    review_state = our_review_state(pull_request, viewer_login)
    is_draft = bool(pull_request.get("isDraft"))
    row = {
        "number": pull_request.get("number"),
        "title": pull_request.get("title"),
        "author": author,
        "url": pull_request.get("url"),
        "is_draft": is_draft,
        "review_decision": pull_request.get("reviewDecision"),
        "our_review_state": review_state,
        "default_selected": not is_draft and review_state != "approved-by-us",
    }
    return {field: row[field] for field in OUTPUT_FIELDS}


def sort_key(row: dict[str, Any]) -> tuple[int, int]:
    if row["is_draft"]:
        group = 3
    elif row["our_review_state"] == "not-reviewed-by-us":
        group = 0
    elif row["our_review_state"] == "reviewed-by-us":
        group = 1
    else:
        group = 2
    number = row.get("number")
    return group, int(number) if isinstance(number, int) else 0


def build_result(repository: str, viewer_login: str, pull_requests: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [normalize_pull_request(pull_request, viewer_login) for pull_request in pull_requests]
    rows = sorted((row for row in normalized if row is not None), key=sort_key)
    return {
        "schema_version": 1,
        "repository": repository,
        "viewer_login": viewer_login,
        "pull_requests": rows,
        "default_selection": [row["number"] for row in rows if row["default_selected"]],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def load_live(repository: str | None, limit: int) -> tuple[str, str, list[dict[str, Any]]]:
    resolved_repository = repository
    if not resolved_repository:
        payload = run_json(["gh", "repo", "view", "--json", "nameWithOwner"])
        resolved_repository = payload["nameWithOwner"]
    viewer_login = run(["gh", "api", "user", "--jq", ".login"]).strip()
    pull_requests = run_json(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            resolved_repository,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            PR_FIELDS,
        ]
    )
    return resolved_repository, viewer_login, pull_requests


def load_fixture(path: Path) -> tuple[str, str, list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["repository"], payload["viewer_login"], payload["pull_requests"]


def main() -> int:
    args = parse_args()
    repository, viewer_login, pull_requests = (
        load_fixture(args.fixture) if args.fixture else load_live(args.repository, args.limit)
    )
    result = build_result(repository, viewer_login, pull_requests)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
