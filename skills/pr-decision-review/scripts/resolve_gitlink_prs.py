from __future__ import annotations

import argparse
import configparser
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse


SCP_GITHUB_URL = re.compile(r"^(?:git@)?github\.com:(?P<repository>[^/]+/[^/]+?)(?:\.git)?$")


def run_json(command: Sequence[str]) -> Any:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or f"command exited {completed.returncode}")
    return json.loads(completed.stdout)


def without_git_suffix(value: str) -> str:
    return value[:-4] if value.endswith(".git") else value


def github_repository(remote: str, parent_repository: str) -> str | None:
    value = remote.strip()
    scp_match = SCP_GITHUB_URL.match(value)
    if scp_match:
        return without_git_suffix(scp_match.group("repository"))
    if value.startswith("../"):
        owner = parent_repository.split("/", 1)[0]
        name = without_git_suffix(value.rsplit("/", 1)[-1])
        return f"{owner}/{name}" if name else None
    parsed = urlparse(value)
    if parsed.hostname != "github.com":
        return None
    repository = without_git_suffix(parsed.path.strip("/"))
    return repository if repository.count("/") == 1 else None


def minimal_pull_request(pull_request: dict[str, Any]) -> dict[str, Any]:
    head = pull_request.get("head")
    return {
        "number": pull_request.get("number"),
        "title": pull_request.get("title"),
        "url": pull_request.get("html_url") or pull_request.get("url"),
        "state": str(pull_request.get("state", "")).upper(),
        "is_draft": bool(pull_request.get("draft")),
        "head_oid": head.get("sha") if isinstance(head, dict) else pull_request.get("head_oid"),
    }


def gitmodule_repositories(path: Path, parent_repository: str) -> dict[str, str]:
    if not path.exists():
        return {}
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    repositories = {}
    for section in parser.sections():
        child_path = parser.get(section, "path", fallback=None)
        remote = parser.get(section, "url", fallback=None)
        repository = github_repository(remote, parent_repository) if remote else None
        if child_path and repository:
            repositories[child_path] = repository
    return repositories


def fetch_associated_pull_requests(repository: str, oid: str) -> list[dict[str, Any]]:
    payload = run_json(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"repos/{repository}/commits/{oid}/pulls",
        ]
    )
    if not isinstance(payload, list):
        raise ValueError("associated pull request response must be an array")
    return [item for item in payload if isinstance(item, dict)]


def resolve(
    context: dict[str, Any],
    repository_root: Path,
    fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parent_repository = context["repository"]
    mappings = gitmodule_repositories(repository_root / ".gitmodules", parent_repository)
    rows = []
    for gitlink in context.get("gitlinks", []):
        path = gitlink.get("path")
        child_repository = mappings.get(path)
        if not child_repository:
            rows.append(
                {
                    "path": path,
                    "new_oid": gitlink.get("new_oid"),
                    "repository": None,
                    "status": "repository-unresolved",
                    "pull_requests": [],
                }
            )
            continue
        raw_pull_requests = (
            fixture.get(path, [])
            if fixture is not None
            else fetch_associated_pull_requests(child_repository, gitlink["new_oid"])
        )
        pull_requests = [minimal_pull_request(item) for item in raw_pull_requests]
        pull_requests.sort(key=lambda item: (item["state"] != "OPEN", item["number"] or 0))
        rows.append(
            {
                "path": path,
                "new_oid": gitlink.get("new_oid"),
                "repository": child_repository,
                "status": "resolved" if pull_requests else "pr-unresolved",
                "pull_requests": pull_requests,
            }
        )
    return {
        "schema_version": 1,
        "parent_repository": parent_repository,
        "gitlinks": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context = json.loads(args.context.read_text(encoding="utf-8"))
    fixture = json.loads(args.fixture.read_text(encoding="utf-8")) if args.fixture else None
    result = resolve(context, args.repository_root.resolve(), fixture)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "gitlink_count": len(result["gitlinks"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
