from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence


PR_FIELDS = ",".join(
    (
        "number",
        "title",
        "body",
        "author",
        "url",
        "isDraft",
        "reviewDecision",
        "additions",
        "deletions",
        "changedFiles",
        "headRefOid",
        "baseRefOid",
        "baseRefName",
        "headRefName",
        "labels",
        "files",
        "commits",
        "closingIssuesReferences",
    )
)
DISCUSSION_FIELDS = "number,title,url,headRefOid"
THREADS_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviewThreads(first:100,after:$cursor){
        nodes{
          id isResolved isOutdated path line startLine diffSide
          comments(first:100){
            nodes{id databaseId body url createdAt author{login} replyTo{databaseId}}
            pageInfo{hasNextPage endCursor}
          }
        }
        pageInfo{hasNextPage endCursor}
      }
    }
  }
}
""".strip()
THREAD_COMMENTS_QUERY = """
query($threadId:ID!,$cursor:String){
  node(id:$threadId){
    ... on PullRequestReviewThread{
      comments(first:100,after:$cursor){
        nodes{id databaseId body url createdAt author{login} replyTo{databaseId}}
        pageInfo{hasNextPage endCursor}
      }
    }
  }
}
""".strip()
REVIEWS_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      reviews(first:100,after:$cursor){
        nodes{id databaseId state body url submittedAt author{login} commit{oid}}
        pageInfo{hasNextPage endCursor}
      }
    }
  }
}
""".strip()
PR_COMMENTS_QUERY = """
query($owner:String!,$name:String!,$number:Int!,$cursor:String){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      comments(first:100,after:$cursor){
        nodes{id databaseId body url createdAt author{login}}
        pageInfo{hasNextPage endCursor}
      }
    }
  }
}
""".strip()
GITLINK_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
SUBPROJECT_COMMIT = re.compile(r"^([+-])Subproject commit ([0-9a-fA-F]{40}|[0-9a-fA-F]{64})")
PULL_REQUEST_PATTERN = re.compile(r"/pull/(\d+)(?:/|$)")


def run(command: Sequence[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"command exited {completed.returncode}")
    return completed.stdout


def run_json(command: Sequence[str], cwd: Path | None = None) -> Any:
    return json.loads(run(command, cwd))


def safe_collection(
    label: str,
    operation: Callable[[], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        return operation(), []
    except (KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        reason = " ".join(str(error).split())[:200]
        return [], [f"{label}-unavailable:{reason}"]


def split_repository(repository: str) -> tuple[str, str]:
    parts = repository.split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise ValueError("repository must use owner/name format")
    return parts[0], parts[1]


def normalize_comment(comment: dict[str, Any]) -> dict[str, Any]:
    author = comment.get("author")
    reply_to = comment.get("replyTo")
    return {
        "node_id": comment.get("id"),
        "database_id": comment.get("databaseId"),
        "body": comment.get("body"),
        "url": comment.get("url"),
        "created_at": comment.get("createdAt"),
        "author": author.get("login") if isinstance(author, dict) else None,
        "reply_to_database_id": reply_to.get("databaseId") if isinstance(reply_to, dict) else None,
    }


def normalize_review(review: dict[str, Any]) -> dict[str, Any]:
    author = review.get("author")
    commit = review.get("commit")
    return {
        "node_id": review.get("id"),
        "database_id": review.get("databaseId"),
        "state": review.get("state"),
        "body": review.get("body"),
        "url": review.get("url"),
        "submitted_at": review.get("submittedAt"),
        "author": author.get("login") if isinstance(author, dict) else None,
        "commit_oid": commit.get("oid") if isinstance(commit, dict) else None,
    }


def normalize_pr_comment(comment: dict[str, Any]) -> dict[str, Any]:
    author = comment.get("author")
    return {
        "node_id": comment.get("id"),
        "database_id": comment.get("databaseId"),
        "body": comment.get("body"),
        "url": comment.get("url"),
        "created_at": comment.get("createdAt"),
        "author": author.get("login") if isinstance(author, dict) else None,
    }


def normalize_discussions(
    threads: list[dict[str, Any]],
    reviews: list[dict[str, Any]] | None = None,
    pr_comments: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    normalized = []
    normalized_limitations = list(limitations or [])
    for thread in threads:
        comments = thread.get("comments")
        comment_container = comments if isinstance(comments, dict) else {}
        page_info = comment_container.get("pageInfo")
        page_info = page_info if isinstance(page_info, dict) else {}
        if page_info.get("hasNextPage"):
            normalized_limitations.append(f"thread-comments-incomplete:{thread.get('id')}")
        nodes = comment_container.get("nodes")
        nodes = nodes if isinstance(nodes, list) else []
        normalized.append(
            {
                "thread_id": thread.get("id"),
                "is_resolved": bool(thread.get("isResolved")),
                "is_outdated": bool(thread.get("isOutdated")),
                "path": thread.get("path"),
                "line": thread.get("line"),
                "start_line": thread.get("startLine"),
                "diff_side": thread.get("diffSide"),
                "comments": [normalize_comment(node) for node in nodes if isinstance(node, dict)],
            }
        )
    return {
        "complete": not normalized_limitations,
        "limitations": normalized_limitations,
        "review_threads": normalized,
        "reviews": [normalize_review(review) for review in reviews or [] if isinstance(review, dict)],
        "pr_comments": [
            normalize_pr_comment(comment) for comment in pr_comments or [] if isinstance(comment, dict)
        ],
    }


def extract_gitlink_changes(diff: str) -> list[dict[str, str]]:
    changes = []
    current_path: str | None = None
    old_oid: str | None = None
    new_oid: str | None = None

    def append_current() -> None:
        if current_path and old_oid and new_oid:
            changes.append({"path": current_path, "old_oid": old_oid, "new_oid": new_oid})

    for line in diff.splitlines():
        header = GITLINK_HEADER.match(line)
        if header:
            append_current()
            current_path = header.group(2) if header.group(1) == header.group(2) else None
            old_oid = None
            new_oid = None
            continue
        commit = SUBPROJECT_COMMIT.match(line)
        if not current_path or not commit:
            continue
        if commit.group(1) == "-":
            old_oid = commit.group(2).lower()
        else:
            new_oid = commit.group(2).lower()
    append_current()
    return changes


def patch_change_counts(diff: str) -> tuple[int, int, int]:
    additions = 0
    deletions = 0
    changed_files = 0
    for line in diff.splitlines():
        if GITLINK_HEADER.match(line):
            changed_files += 1
        elif line.startswith("+") and not line.startswith("+++ "):
            additions += 1
        elif line.startswith("-") and not line.startswith("--- "):
            deletions += 1
    return additions, deletions, changed_files


def nonnegative_integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def build_change_summary(metadata: dict[str, Any], diff: str) -> dict[str, Any]:
    patch_additions, patch_deletions, patch_files = patch_change_counts(diff)
    additions = nonnegative_integer(metadata.get("additions"))
    deletions = nonnegative_integer(metadata.get("deletions"))
    changed_files = nonnegative_integer(metadata.get("changedFiles"))
    metadata_counts_complete = additions is not None and deletions is not None
    additions = additions if additions is not None else patch_additions
    deletions = deletions if deletions is not None else patch_deletions
    if changed_files is None:
        files = metadata.get("files")
        changed_files = len(files) if isinstance(files, list) else patch_files
    changed_lines = additions + deletions
    small_change = changed_lines <= 50
    return {
        "additions": additions,
        "deletions": deletions,
        "changed_lines": changed_lines,
        "changed_files": changed_files,
        "small_change": small_change,
        "show_code_by_default": small_change and changed_lines > 0,
        "source": "github-metadata" if metadata_counts_complete else "patch",
    }


def target_pr_number(target: str | None) -> int | None:
    if target is None:
        return None
    if target.isdigit():
        return int(target)
    match = PULL_REQUEST_PATTERN.search(target)
    return int(match.group(1)) if match else None


def normalize_stack(payload: dict[str, Any], target: str | None, scope: str = "target-layer") -> dict[str, Any]:
    branches = payload.get("branches")
    if not isinstance(branches, list):
        raise ValueError("gh stack payload must contain a branches array")
    layers = []
    for index, branch in enumerate(branches):
        if not isinstance(branch, dict):
            continue
        pr = branch.get("pr")
        pr = pr if isinstance(pr, dict) else {}
        layers.append(
            {
                "stack_index": index,
                "branch": branch.get("name"),
                "is_current": bool(branch.get("isCurrent")),
                "needs_rebase": bool(branch.get("needsRebase")),
                "pr_number": pr.get("number"),
                "pr_url": pr.get("url"),
                "pr_state": str(pr.get("state", "NONE")).upper(),
            }
        )
    requested_number = target_pr_number(target)
    matched = next(
        (
            layer
            for layer in layers
            if (requested_number is not None and layer["pr_number"] == requested_number)
            or (target is not None and target in {layer["branch"], layer["pr_url"]})
            or (target is None and layer["is_current"])
        ),
        None,
    )
    return {
        "schema_version": 1,
        "status": "stack" if matched else "target-not-in-current-stack",
        "scope": scope,
        "trunk": payload.get("trunk"),
        "current_branch": payload.get("currentBranch"),
        "target": {
            "requested": target,
            "branch": matched.get("branch") if matched else None,
            "pr_number": matched.get("pr_number") if matched else None,
            "pr_url": matched.get("pr_url") if matched else None,
        },
        "layers": layers,
    }


def graphql_threads(repository: str, number: int) -> list[dict[str, Any]]:
    owner, name = split_repository(repository)
    threads = []
    cursor: str | None = None
    while True:
        command = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={THREADS_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
        if cursor:
            command.extend(("-F", f"cursor={cursor}"))
        payload = run_json(command)
        connection = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads.extend(connection.get("nodes") or [])
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            raise RuntimeError("review thread pagination returned no end cursor")
    for thread in threads:
        complete_thread_comments(thread)
    return threads


def graphql_connection(repository: str, number: int, query: str, connection_name: str) -> list[dict[str, Any]]:
    owner, name = split_repository(repository)
    nodes = []
    cursor: str | None = None
    while True:
        command = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
        if cursor:
            command.extend(("-F", f"cursor={cursor}"))
        payload = run_json(command)
        connection = payload["data"]["repository"]["pullRequest"][connection_name]
        nodes.extend(connection.get("nodes") or [])
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return nodes
        cursor = page_info.get("endCursor")
        if not cursor:
            raise RuntimeError(f"{connection_name} pagination returned no end cursor")


def complete_thread_comments(thread: dict[str, Any]) -> None:
    connection = thread.get("comments")
    if not isinstance(connection, dict):
        return
    page_info = connection.get("pageInfo") or {}
    cursor = page_info.get("endCursor")
    while page_info.get("hasNextPage"):
        if not cursor:
            raise RuntimeError(f"thread {thread.get('id')} comment pagination returned no end cursor")
        payload = run_json(
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={THREAD_COMMENTS_QUERY}",
                "-F",
                f"threadId={thread['id']}",
                "-F",
                f"cursor={cursor}",
            ]
        )
        next_connection = payload["data"]["node"]["comments"]
        connection.setdefault("nodes", []).extend(next_connection.get("nodes") or [])
        page_info = next_connection.get("pageInfo") or {}
        connection["pageInfo"] = page_info
        cursor = page_info.get("endCursor")


def unavailable_stack(reason: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "unavailable",
        "scope": "target-layer",
        "reason": " ".join(reason.split())[:240],
        "layers": [],
    }


def collect_stack(repository_root: Path, target: str, scope: str) -> dict[str, Any]:
    gh = shutil.which("gh")
    if gh is None:
        return unavailable_stack("gh executable not found")
    completed = subprocess.run(
        [gh, "stack", "view", "--json"],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        return unavailable_stack(completed.stderr or f"gh stack view exited {completed.returncode}")
    try:
        return normalize_stack(json.loads(completed.stdout), target, scope)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return unavailable_stack(str(error))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository")
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--stack-scope", choices=("target-layer", "stack-wide"), default="target-layer")
    parser.add_argument("--metadata-fixture", type=Path)
    parser.add_argument("--threads-fixture", type=Path)
    parser.add_argument("--reviews-fixture", type=Path)
    parser.add_argument("--pr-comments-fixture", type=Path)
    parser.add_argument("--diff-fixture", type=Path)
    parser.add_argument("--stack-fixture", type=Path)
    parser.add_argument("--discussion-only", action="store_true")
    return parser.parse_args()


def fixture_json(path: Path | None) -> Any | None:
    return json.loads(path.read_text(encoding="utf-8")) if path else None


def resolve_repository(repository: str | None) -> str:
    if repository:
        return repository
    payload = run_json(["gh", "repo", "view", "--json", "nameWithOwner"])
    return payload["nameWithOwner"]


def main() -> int:
    args = parse_args()
    repository = resolve_repository(args.repository)
    metadata = fixture_json(args.metadata_fixture)
    if metadata is None:
        fields = DISCUSSION_FIELDS if args.discussion_only else PR_FIELDS
        metadata = run_json(["gh", "pr", "view", str(args.pr), "--repo", repository, "--json", fields])
    limitations = []
    raw_threads = fixture_json(args.threads_fixture)
    if raw_threads is None:
        raw_threads, source_limitations = safe_collection(
            "review-threads", lambda: graphql_threads(repository, args.pr)
        )
        limitations.extend(source_limitations)
    raw_reviews = fixture_json(args.reviews_fixture)
    if raw_reviews is None:
        if args.metadata_fixture:
            raw_reviews = metadata.get("reviews", [])
        else:
            raw_reviews, source_limitations = safe_collection(
                "reviews", lambda: graphql_connection(repository, args.pr, REVIEWS_QUERY, "reviews")
            )
            limitations.extend(source_limitations)
    raw_pr_comments = fixture_json(args.pr_comments_fixture)
    if raw_pr_comments is None:
        if args.metadata_fixture:
            raw_pr_comments = metadata.get("comments", [])
        else:
            raw_pr_comments, source_limitations = safe_collection(
                "pr-comments", lambda: graphql_connection(repository, args.pr, PR_COMMENTS_QUERY, "comments")
            )
            limitations.extend(source_limitations)
    if args.discussion_only:
        diff = None
        change_summary = None
        stack = {
            "schema_version": 1,
            "status": "not-collected",
            "scope": "target-layer",
            "layers": [],
        }
    else:
        diff = args.diff_fixture.read_text(encoding="utf-8") if args.diff_fixture else run(
            ["gh", "pr", "diff", str(args.pr), "--repo", repository]
        )
        change_summary = build_change_summary(metadata, diff)
        raw_stack = fixture_json(args.stack_fixture)
        stack = (
            normalize_stack(raw_stack, str(args.pr), args.stack_scope)
            if raw_stack is not None
            else collect_stack(args.repository_root.resolve(), str(args.pr), args.stack_scope)
        )
    discussions = normalize_discussions(raw_threads, raw_reviews, raw_pr_comments, limitations)
    context = {
        "schema_version": 1,
        "collection_mode": "discussion-only" if args.discussion_only else "target",
        "repository": repository,
        "pr": args.pr,
        "head_ref_oid": metadata.get("headRefOid"),
        "base_ref_oid": metadata.get("baseRefOid"),
        "metadata": metadata,
        "change_summary": change_summary,
        "discussions": discussions,
        "gitlinks": extract_gitlink_changes(diff) if diff is not None else [],
        "stack": stack,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    context_path = args.output_dir / "context.json"
    context_path.write_text(json.dumps(context, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    diff_path = args.output_dir / "diff.patch" if diff is not None else None
    if diff_path is not None:
        diff_path.write_text(diff, encoding="utf-8")
    print(
        json.dumps(
            {
                "context_path": str(context_path.resolve()),
                "diff_path": str(diff_path.resolve()) if diff_path is not None else None,
                "head_ref_oid": context["head_ref_oid"],
                "discussion_complete": discussions["complete"],
                "change_summary": context["change_summary"],
                "gitlink_count": len(context["gitlinks"]),
                "stack_status": stack["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
