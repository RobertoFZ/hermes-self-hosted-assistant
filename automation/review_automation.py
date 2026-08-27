#!/usr/bin/env python3
"""Delegate PR reviews to Codex through Paseo and persist verified outcomes."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


PR_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/pull/(?P<number>[1-9][0-9]*)/?$",
    re.IGNORECASE,
)
DEFAULT_DB = "/opt/data/review-history/reviews.sqlite3"
DEFAULT_SCHEMA = "/opt/review-automation/review-result.schema.json"
PASEO_REVIEW_LABEL = "hermes-review-run"


class AutomationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PullRequest:
    url: str
    repo: str
    number: int
    title: str
    body: str
    head_sha: str
    base_ref: str
    author_login: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run(
    command: Sequence[str],
    *,
    timeout: int | None = None,
    check: bool = True,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise AutomationError(f"command failed ({command[0]}): {detail}")
    return completed


def csv_values(name: str) -> set[str]:
    return {item.strip().lower() for item in os.environ.get(name, "").split(",") if item.strip()}


def parse_pr_url(url: str) -> tuple[str, int]:
    match = PR_URL_RE.fullmatch(url.strip())
    if not match:
        raise AutomationError(f"unsupported pull request URL: {url}")
    repo = f"{match.group('owner')}/{match.group('repo')}"
    allowed = csv_values("SLACK_REVIEW_ALLOWED_REPOSITORIES")
    if allowed and repo.lower() not in allowed:
        raise AutomationError(f"repository is not allowlisted: {repo}")
    return repo, int(match.group("number"))


def gh_json(args: Sequence[str]) -> Any:
    result = run(["gh", *args])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AutomationError("GitHub CLI returned invalid JSON") from exc


def gh_paginated(endpoint: str) -> list[dict[str, Any]]:
    pages = gh_json(["api", "--paginate", "--slurp", endpoint])
    if not isinstance(pages, list):
        raise AutomationError("GitHub paginated response is not a list")
    if pages and all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page if isinstance(item, dict)]
    return [item for item in pages if isinstance(item, dict)]


def load_pr(url: str) -> PullRequest:
    expected_repo, expected_number = parse_pr_url(url)
    data = gh_json(
        [
            "pr",
            "view",
            url,
            "--json",
            "url,number,title,body,headRefOid,baseRefName,author",
        ]
    )
    if int(data["number"]) != expected_number:
        raise AutomationError("GitHub returned a different PR number")
    author = data.get("author") or {}
    return PullRequest(
        url=str(data.get("url") or url),
        repo=expected_repo,
        number=expected_number,
        title=str(data.get("title") or ""),
        body=str(data.get("body") or ""),
        head_sha=str(data["headRefOid"]),
        base_ref=str(data.get("baseRefName") or ""),
        author_login=str(author.get("login") or ""),
    )


def reviewer_login() -> str:
    data = gh_json(["api", "user"])
    login = str(data.get("login") or "").strip()
    if not login:
        raise AutomationError("unable to identify the authenticated GitHub user")
    return login


def github_publications(pr: PullRequest, login: str) -> dict[str, list[dict[str, Any]]]:
    owner, repo = pr.repo.split("/", 1)
    reviews = gh_paginated(f"repos/{owner}/{repo}/pulls/{pr.number}/reviews")
    comments = gh_paginated(f"repos/{owner}/{repo}/pulls/{pr.number}/comments")
    normalized_login = login.lower()
    return {
        "reviews": [
            item
            for item in reviews
            if str((item.get("user") or {}).get("login") or "").lower() == normalized_login
            and str(item.get("commit_id") or "") == pr.head_sha
            and str(item.get("state") or "").upper() in {"APPROVED", "COMMENTED"}
        ],
        "comments": [
            item
            for item in comments
            if str((item.get("user") or {}).get("login") or "").lower() == normalized_login
            and str(item.get("commit_id") or "") == pr.head_sha
        ],
    }


def publication_ids(snapshot: Mapping[str, Sequence[Mapping[str, Any]]]) -> set[tuple[str, int]]:
    result: set[tuple[str, int]] = set()
    for kind in ("reviews", "comments"):
        for item in snapshot.get(kind, []):
            if item.get("id") is not None:
                result.add((kind, int(item["id"])))
    return result


def connect_db(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path or os.environ.get("REVIEW_HISTORY_DB", DEFAULT_DB))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    migrate(connection)
    return connection


def migrate(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS review_runs (
            id TEXT PRIMARY KEY,
            requested_at TEXT NOT NULL,
            completed_at TEXT,
            repo TEXT NOT NULL,
            pr_number INTEGER NOT NULL,
            pr_url TEXT NOT NULL,
            pr_title TEXT NOT NULL,
            pr_author TEXT NOT NULL,
            base_ref TEXT NOT NULL,
            head_sha TEXT NOT NULL,
            reviewer_login TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'hermes-paseo-codex',
            status TEXT NOT NULL,
            event TEXT,
            summary TEXT,
            error TEXT,
            structured_result TEXT,
            cleanup_status TEXT NOT NULL DEFAULT 'pending',
            cleanup_attempted_at TEXT,
            cleaned_at TEXT,
            cleanup_error TEXT
        );
        CREATE INDEX IF NOT EXISTS review_runs_digest_idx
            ON review_runs(completed_at, status);
        CREATE INDEX IF NOT EXISTS review_runs_identity_idx
            ON review_runs(repo, pr_number, head_sha, reviewer_login, status);
        CREATE TABLE IF NOT EXISTS review_publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES review_runs(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            github_id INTEGER NOT NULL,
            state TEXT,
            url TEXT,
            published_at TEXT,
            UNIQUE(kind, github_id)
        );
        CREATE TABLE IF NOT EXISTS review_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES review_runs(id) ON DELETE CASCADE,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            path TEXT,
            line INTEGER,
            body TEXT NOT NULL,
            blocking INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS linear_snapshots (
            run_id TEXT PRIMARY KEY REFERENCES review_runs(id) ON DELETE CASCADE,
            fetch_status TEXT NOT NULL,
            issue_key TEXT,
            title TEXT,
            url TEXT,
            status TEXT,
            project TEXT,
            product_summary TEXT,
            acceptance_criteria TEXT NOT NULL,
            labels TEXT NOT NULL
        );
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, ?)",
        (iso(utc_now()),),
    )
    columns = {
        str(row["name"])
        for row in db.execute("PRAGMA table_info(review_runs)").fetchall()
    }
    additions = {
        "cleanup_status": "TEXT NOT NULL DEFAULT 'pending'",
        "cleanup_attempted_at": "TEXT",
        "cleaned_at": "TEXT",
        "cleanup_error": "TEXT",
    }
    for name, declaration in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE review_runs ADD COLUMN {name} {declaration}")
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS review_runs_cleanup_idx
        ON review_runs(status, cleanup_status, cleanup_attempted_at)
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (2, ?)",
        (iso(utc_now()),),
    )
    db.commit()


def verified_run_exists(db: sqlite3.Connection, pr: PullRequest, login: str) -> bool:
    row = db.execute(
        """
        SELECT 1 FROM review_runs
        WHERE repo = ? AND pr_number = ? AND head_sha = ?
          AND reviewer_login = ? AND status = 'published'
        LIMIT 1
        """,
        (pr.repo, pr.number, pr.head_sha, login),
    ).fetchone()
    return row is not None


def insert_run(db: sqlite3.Connection, pr: PullRequest, login: str, status: str) -> str:
    run_id = _insert_run(db, pr, login, status)
    db.commit()
    return run_id


def _insert_run(
    db: sqlite3.Connection,
    pr: PullRequest,
    login: str,
    status: str,
) -> str:
    run_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO review_runs(
            id, requested_at, repo, pr_number, pr_url, pr_title, pr_author,
            base_ref, head_sha, reviewer_login, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            iso(utc_now()),
            pr.repo,
            pr.number,
            pr.url,
            pr.title,
            pr.author_login,
            pr.base_ref,
            pr.head_sha,
            login,
            status,
        ),
    )
    return run_id


def claim_review_run(
    db: sqlite3.Connection,
    pr: PullRequest,
    login: str,
) -> tuple[str, str]:
    """Atomically return (state, run_id) for one PR head and reviewer."""
    try:
        db.execute("BEGIN IMMEDIATE")
        published = db.execute(
            """
            SELECT id FROM review_runs
            WHERE repo = ? AND pr_number = ? AND head_sha = ?
              AND reviewer_login = ? AND status = 'published'
            ORDER BY completed_at DESC LIMIT 1
            """,
            (pr.repo, pr.number, pr.head_sha, login),
        ).fetchone()
        if published:
            db.commit()
            return "published", str(published["id"])

        running = db.execute(
            """
            SELECT id FROM review_runs
            WHERE repo = ? AND pr_number = ? AND head_sha = ?
              AND reviewer_login = ? AND status = 'running'
            ORDER BY requested_at ASC LIMIT 1
            """,
            (pr.repo, pr.number, pr.head_sha, login),
        ).fetchone()
        if running:
            db.commit()
            return "running", str(running["id"])

        run_id = _insert_run(db, pr, login, "running")
        db.commit()
        return "claimed", run_id
    except Exception:
        db.rollback()
        raise


def finish_skipped(db: sqlite3.Connection, run_id: str, status: str, summary: str) -> None:
    completed_at = iso(utc_now())
    db.execute(
        """
        UPDATE review_runs
        SET completed_at = ?, status = ?, summary = ?, cleanup_status = 'not_needed',
            cleanup_attempted_at = ?, cleaned_at = ?, cleanup_error = NULL
        WHERE id = ?
        """,
        (completed_at, status, summary, completed_at, completed_at, run_id),
    )
    db.commit()


def paseo_timeout_seconds(value: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([smh])", value.strip().lower())
    if not match:
        raise AutomationError("REVIEW_PASEO_TIMEOUT must look like 30m, 1h, or 90s")
    multiplier = {"s": 1, "m": 60, "h": 3600}[match.group(2)]
    return int(match.group(1)) * multiplier


def paseo_host() -> str:
    return os.environ.get("PASEO_HOST", "paseo:6767")


def list_paseo_review_agents(run_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    """List only Paseo agents carrying this review run's unique label."""
    host = paseo_host()
    label = f"{PASEO_REVIEW_LABEL}={run_id}"
    try:
        listed = run(
            [
                "paseo",
                "ls",
                "--host",
                host,
                "--all",
                "--global",
                "--label",
                label,
                "--json",
            ],
            timeout=30,
            check=False,
            env=os.environ.copy(),
        )
        if listed.returncode:
            detail = listed.stderr.strip() or listed.stdout.strip() or "unknown error"
            return [], [f"unable to list the Paseo review agent: {detail}"]
        try:
            agents = json.loads(listed.stdout)
        except json.JSONDecodeError:
            return [], ["Paseo returned invalid JSON while locating the review agent"]
        if not isinstance(agents, list):
            return [], ["Paseo returned an unexpected agent-list response"]
        return [agent for agent in agents if isinstance(agent, dict)], []
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], [f"unable to list the Paseo review agent: {exc}"]


def _delete_result_verified(deleted: subprocess.CompletedProcess[str], agent_id: str) -> str | None:
    if deleted.returncode:
        return deleted.stderr.strip() or deleted.stdout.strip() or "unknown error"
    try:
        payload = json.loads(deleted.stdout)
    except json.JSONDecodeError:
        return "Paseo returned invalid JSON for the delete operation"
    if not isinstance(payload, dict):
        return "Paseo returned an unexpected delete response"
    deleted_ids = payload.get("agentIds")
    deleted_count = payload.get("deletedCount")
    if deleted_count != 1 or not isinstance(deleted_ids, list) or agent_id not in deleted_ids:
        detail = deleted.stderr.strip()
        suffix = f"; {detail}" if detail else ""
        return f"Paseo did not confirm hard deletion (deletedCount={deleted_count!r}){suffix}"
    return None


def cleanup_paseo_review_agent(run_id: str) -> list[str]:
    """Best-effort verified hard-delete of only this run's Paseo agents."""
    host = paseo_host()
    agents, warnings = list_paseo_review_agents(run_id)
    if warnings:
        return warnings

    try:
        for agent in agents:
            agent_id = str(agent.get("id") or "")
            if not agent_id:
                warnings.append("Paseo returned a labeled review agent without an ID")
                continue
            deleted = run(
                ["paseo", "delete", "--host", host, "--json", agent_id],
                timeout=30,
                check=False,
                env=os.environ.copy(),
            )
            detail = _delete_result_verified(deleted, agent_id)
            if detail:
                warnings.append(f"unable to delete Paseo agent {agent_id}: {detail}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        warnings.append(f"unable to clean up the Paseo review agent: {exc}")

    remaining, verify_warnings = list_paseo_review_agents(run_id)
    warnings.extend(verify_warnings)
    remaining_ids = [str(agent.get("id") or "") for agent in remaining]
    if remaining_ids:
        warnings.append(
            "Paseo review agent still exists after deletion: "
            + ", ".join(agent_id for agent_id in remaining_ids if agent_id)
        )
    return warnings


def cleanup_review_run(db: sqlite3.Connection, run_id: str) -> list[str]:
    """Clean one labeled agent and persist the cleanup outcome independently."""
    warnings = cleanup_paseo_review_agent(run_id)
    attempted_at = iso(utc_now())
    if warnings:
        db.execute(
            """
            UPDATE review_runs
            SET cleanup_status = 'failed', cleanup_attempted_at = ?,
                cleanup_error = ?, cleaned_at = NULL
            WHERE id = ?
            """,
            (attempted_at, "; ".join(warnings)[:4000], run_id),
        )
    else:
        db.execute(
            """
            UPDATE review_runs
            SET cleanup_status = 'clean', cleanup_attempted_at = ?,
                cleaned_at = ?, cleanup_error = NULL
            WHERE id = ?
            """,
            (attempted_at, attempted_at, run_id),
        )
    db.commit()
    return warnings


def reconcile_terminal_cleanup(
    db_path: str | None = None,
    *,
    run_ids: Iterable[str] = (),
    limit: int = 100,
) -> dict[str, Any]:
    """Retry cleanup for terminal runs without changing review outcomes."""
    if limit < 1 or limit > 1000:
        raise AutomationError("cleanup limit must be between 1 and 1000")
    requested_ids = list(
        dict.fromkeys(run_id.strip() for run_id in run_ids if run_id.strip())
    )
    results: list[dict[str, Any]] = []
    with connect_db(db_path) as db:
        if requested_ids:
            placeholders = ",".join("?" for _ in requested_ids)
            rows = db.execute(
                f"""
                SELECT * FROM review_runs
                WHERE id IN ({placeholders}) AND status != 'running'
                ORDER BY requested_at ASC
                """,
                requested_ids,
            ).fetchall()
            found = {str(row["id"]) for row in rows}
            results.extend(
                {"run_id": run_id, "status": "not_found_or_running"}
                for run_id in requested_ids
                if run_id not in found
            )
        else:
            rows = db.execute(
                """
                SELECT * FROM review_runs
                WHERE status != 'running'
                  AND cleanup_status NOT IN ('clean', 'not_needed')
                ORDER BY COALESCE(cleanup_attempted_at, requested_at) ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        for row in rows:
            run_id = str(row["id"])
            warnings = cleanup_review_run(db, run_id)
            item: dict[str, Any] = {
                "run_id": run_id,
                "url": str(row["pr_url"]),
                "review_status": str(row["status"]),
                "status": "cleanup_failed" if warnings else "clean",
            }
            if warnings:
                item["cleanup_warnings"] = warnings
            results.append(item)
    return {
        "requested": len(requested_ids) if requested_ids else len(results),
        "clean": sum(item["status"] == "clean" for item in results),
        "failed": sum(item["status"] == "cleanup_failed" for item in results),
        "results": results,
    }


def _json_objects(text: str) -> Iterable[dict[str, Any]]:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text or ""):
        try:
            value, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def load_paseo_structured_result(
    pr: PullRequest,
    agents: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Best-effort recovery of the final structured result from agent logs."""
    warnings: list[str] = []
    for agent in agents:
        agent_id = str(agent.get("id") or "")
        if not agent_id:
            continue
        try:
            logs = run(
                ["paseo", "logs", agent_id, "--host", paseo_host(), "--filter", "text"],
                timeout=30,
                check=False,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.append(f"unable to read Paseo agent {agent_id} logs: {exc}")
            continue
        if logs.returncode:
            detail = logs.stderr.strip() or logs.stdout.strip() or "unknown error"
            warnings.append(f"unable to read Paseo agent {agent_id} logs: {detail}")
            continue
        candidates = list(_json_objects(logs.stdout))
        for candidate in reversed(candidates):
            try:
                validate_result(candidate, pr)
            except (AutomationError, TypeError, ValueError):
                continue
            if (
                candidate.get("published") is True
                and isinstance(candidate.get("summary"), str)
                and isinstance(candidate.get("findings"), list)
                and isinstance(candidate.get("linear"), dict)
            ):
                return candidate, warnings
    return None, warnings


def invoke_codex(pr: PullRequest, *, run_id: str) -> dict[str, Any]:
    host = paseo_host()
    workspace = os.environ.get("REVIEW_MONOREPO_ROOT", "").strip()
    if not workspace:
        raise AutomationError("REVIEW_MONOREPO_ROOT is required")
    timeout_value = os.environ.get("REVIEW_PASEO_TIMEOUT", "45m")
    schema = os.environ.get("REVIEW_RESULT_SCHEMA", DEFAULT_SCHEMA)
    prompt = (
        "$pr-reviewer Review and publish the GitHub review for exactly this pull request: "
        f"{pr.url}\n"
        "Do not discover or review any other pull request. Preserve every decision and "
        "publication rule in the pr-reviewer skill. Include the related Linear issue context "
        "when it can be derived and fetched. After publishing, return only the structured "
        "result required by the supplied output schema."
    )
    command = [
        "paseo",
        "run",
        "--host",
        host,
        "--provider",
        "codex",
        "--mode",
        "full-access",
        "--cwd",
        workspace,
        "--wait-timeout",
        timeout_value,
        "--output-schema",
        schema,
        "--label",
        f"{PASEO_REVIEW_LABEL}={run_id}",
        "--json",
        "--title",
        f"PR review {pr.repo}#{pr.number}",
        prompt,
    ]
    completed = run(
        command,
        timeout=paseo_timeout_seconds(timeout_value) + 90,
        env=os.environ.copy(),
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AutomationError("Paseo returned invalid structured JSON") from exc
    if not isinstance(value, dict):
        raise AutomationError("Paseo structured result is not an object")
    return value


def validate_result(result: Mapping[str, Any], pr: PullRequest) -> None:
    if str(result.get("repo", "")).lower() != pr.repo.lower():
        raise AutomationError("Codex result repository does not match the requested PR")
    if int(result.get("pr_number", 0)) != pr.number:
        raise AutomationError("Codex result PR number does not match the requested PR")
    if str(result.get("head_sha", "")) != pr.head_sha:
        raise AutomationError("Codex result head SHA does not match GitHub")


def persist_verified(
    db: sqlite3.Connection,
    run_id: str,
    result: Mapping[str, Any],
    publications: Mapping[str, Sequence[Mapping[str, Any]]],
) -> bool:
    reviews = list(publications.get("reviews", []))
    comments = list(publications.get("comments", []))
    actual_event = None
    if reviews:
        actual_event = "APPROVE" if any(str(item.get("state", "")).upper() == "APPROVED" for item in reviews) else "COMMENT"
    elif comments:
        actual_event = "COMMENT"
    if not actual_event:
        raise AutomationError("Codex completed without a new verifiable GitHub publication")

    with db:
        updated = db.execute(
            """
            UPDATE review_runs
            SET completed_at = ?, status = 'published', event = ?, summary = ?,
                structured_result = ?, error = NULL
            WHERE id = ? AND status = 'running'
            """,
            (
                iso(utc_now()),
                actual_event,
                str(result.get("summary") or "Review published."),
                json.dumps(result, sort_keys=True),
                run_id,
            ),
        )
        if updated.rowcount == 0:
            existing = db.execute(
                "SELECT status FROM review_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if existing and existing["status"] == "published":
                return False
            raise AutomationError(f"review run {run_id} is not recoverable")

        db.execute("DELETE FROM review_findings WHERE run_id = ?", (run_id,))
        db.execute("DELETE FROM linear_snapshots WHERE run_id = ?", (run_id,))
        for kind, items in (("review", reviews), ("inline_comment", comments)):
            for item in items:
                db.execute(
                    """
                    INSERT OR IGNORE INTO review_publications(
                        run_id, kind, github_id, state, url, published_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        kind,
                        int(item["id"]),
                        str(item.get("state") or "COMMENTED"),
                        str(item.get("html_url") or ""),
                        str(item.get("submitted_at") or item.get("created_at") or ""),
                    ),
                )
        for finding in result.get("findings") or []:
            db.execute(
                """
                INSERT INTO review_findings(
                    run_id, category, severity, path, line, body, blocking
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    str(finding["category"]),
                    str(finding["severity"]),
                    finding.get("path"),
                    finding.get("line"),
                    str(finding["body"]),
                    int(bool(finding["blocking"])),
                ),
            )
        linear = result.get("linear") or {}
        db.execute(
            """
            INSERT INTO linear_snapshots(
                run_id, fetch_status, issue_key, title, url, status, project,
                product_summary, acceptance_criteria, labels
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                str(linear.get("fetch_status") or "missing"),
                linear.get("key"),
                linear.get("title"),
                linear.get("url"),
                linear.get("status"),
                linear.get("project"),
                linear.get("product_summary"),
                json.dumps(linear.get("acceptance_criteria") or []),
                json.dumps(linear.get("labels") or []),
            ),
        )
    return True


def mark_failed(db: sqlite3.Connection, run_id: str, error: str, result: Any = None) -> None:
    db.execute(
        """
        UPDATE review_runs SET completed_at = ?, status = 'failed', error = ?,
            structured_result = ? WHERE id = ?
        """,
        (
            iso(utc_now()),
            error[:4000],
            json.dumps(result, sort_keys=True) if result is not None else None,
            run_id,
        ),
    )
    db.commit()


def pull_request_from_run(row: Mapping[str, Any]) -> PullRequest:
    return PullRequest(
        url=str(row["pr_url"]),
        repo=str(row["repo"]),
        number=int(row["pr_number"]),
        title=str(row["pr_title"]),
        body="",
        head_sha=str(row["head_sha"]),
        base_ref=str(row["base_ref"]),
        author_login=str(row["pr_author"]),
    )


def recovered_result_fallback(
    pr: PullRequest,
    publications: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    reviews = list(publications.get("reviews", []))
    comments = list(publications.get("comments", []))
    event = "APPROVE" if any(
        str(item.get("state") or "").upper() == "APPROVED" for item in reviews
    ) else "COMMENT"
    bodies = [
        str(item.get("body") or "").strip()
        for item in [*reviews, *comments]
        if str(item.get("body") or "").strip()
    ]
    summary = bodies[0] if bodies else "GitHub publication recovered after an interrupted review run."
    return {
        "repo": pr.repo,
        "pr_number": pr.number,
        "head_sha": pr.head_sha,
        "event": event,
        "published": True,
        "summary": summary,
        "findings": [],
        "linear": {
            "fetch_status": "unavailable",
            "key": None,
            "title": None,
            "url": None,
            "status": None,
            "project": None,
            "product_summary": None,
            "acceptance_criteria": [],
            "labels": [],
        },
        "limitations": [
            "Recovered from GitHub after the original automation process was interrupted; "
            "structured Paseo output was unavailable."
        ],
    }


def running_run_is_stale(row: Mapping[str, Any]) -> bool:
    requested_at = datetime.fromisoformat(str(row["requested_at"]))
    if requested_at.tzinfo is None:
        requested_at = requested_at.replace(tzinfo=timezone.utc)
    timeout_value = os.environ.get("REVIEW_PASEO_TIMEOUT", "45m")
    stale_after = paseo_timeout_seconds(timeout_value) + 120
    return (utc_now() - requested_at.astimezone(timezone.utc)).total_seconds() > stale_after


def recover_running_run(
    db: sqlite3.Connection,
    row: Mapping[str, Any],
    publications: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    force: bool = False,
) -> dict[str, Any]:
    pr = pull_request_from_run(row)
    run_id = str(row["id"])
    if not publication_ids(publications):
        return {
            "url": pr.url,
            "status": "in_progress",
            "head_sha": pr.head_sha,
            "run_id": run_id,
        }

    agents, warnings = list_paseo_review_agents(run_id)
    active_ids = [
        str(agent.get("id") or "")
        for agent in agents
        if str(agent.get("status") or "").lower() == "running"
    ]
    if active_ids and not force:
        return {
            "url": pr.url,
            "status": "in_progress",
            "head_sha": pr.head_sha,
            "run_id": run_id,
            "publication_detected": True,
        }
    if warnings and not force:
        return {
            "url": pr.url,
            "status": "in_progress",
            "head_sha": pr.head_sha,
            "run_id": run_id,
            "recovery_warnings": warnings,
        }

    structured, log_warnings = load_paseo_structured_result(pr, agents)
    warnings.extend(log_warnings)
    if structured is None and agents and not force:
        response: dict[str, Any] = {
            "url": pr.url,
            "status": "in_progress",
            "head_sha": pr.head_sha,
            "run_id": run_id,
            "publication_detected": True,
        }
        if warnings:
            response["recovery_warnings"] = warnings
        return response
    if structured is None:
        structured = recovered_result_fallback(pr, publications)
    persist_verified(db, run_id, structured, publications)
    cleanup_warnings = cleanup_review_run(db, run_id)
    warnings.extend(cleanup_warnings)

    persisted = db.execute(
        "SELECT event, summary FROM review_runs WHERE id = ?", (run_id,)
    ).fetchone()
    response: dict[str, Any] = {
        "url": pr.url,
        "status": "published",
        "event": str(persisted["event"]),
        "head_sha": pr.head_sha,
        "run_id": run_id,
        "summary": str(persisted["summary"]),
        "recovered": True,
    }
    if warnings:
        response["recovery_warnings"] = warnings
    return response


def review_one(
    db: sqlite3.Connection,
    url: str,
    login: str,
    *,
    allow_self_review: bool = False,
) -> dict[str, Any]:
    pr = load_pr(url)
    if pr.author_login.lower() == login.lower() and not allow_self_review:
        return {
            "url": pr.url,
            "status": "skipped_self_review_not_authorized",
            "head_sha": pr.head_sha,
        }
    before = github_publications(pr, login)
    claim_state, run_id = claim_review_run(db, pr, login)
    if claim_state == "published":
        response = {
            "url": pr.url,
            "status": "skipped_verified",
            "head_sha": pr.head_sha,
            "run_id": run_id,
        }
        cleanup_warnings = cleanup_review_run(db, run_id)
        if cleanup_warnings:
            response["cleanup_warnings"] = cleanup_warnings
        return response
    if claim_state == "running":
        running = db.execute(
            "SELECT * FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if running is None:
            raise AutomationError(f"claimed review run disappeared: {run_id}")
        if publication_ids(before):
            return recover_running_run(
                db,
                running,
                before,
                force=running_run_is_stale(running),
            )
        if not running_run_is_stale(running):
            return {
                "url": pr.url,
                "status": "in_progress",
                "head_sha": pr.head_sha,
                "run_id": run_id,
            }

        mark_failed(
            db,
            run_id,
            "Interrupted review exceeded its Paseo timeout without a GitHub publication.",
        )
        cleanup_warnings = cleanup_review_run(db, run_id)
        if cleanup_warnings:
            print("; ".join(cleanup_warnings), file=sys.stderr)
        claim_state, run_id = claim_review_run(db, pr, login)
        if claim_state != "claimed":
            return {
                "url": pr.url,
                "status": "in_progress" if claim_state == "running" else "skipped_verified",
                "head_sha": pr.head_sha,
                "run_id": run_id,
            }

    if publication_ids(before):
        finish_skipped(
            db,
            run_id,
            "skipped_existing_publication",
            "A current-head GitHub publication already exists and was not imported.",
        )
        return {
            "url": pr.url,
            "status": "skipped_existing_publication",
            "head_sha": pr.head_sha,
            "run_id": run_id,
        }

    structured: dict[str, Any] | None = None
    invocation_error: Exception | None = None
    response: dict[str, Any] | None = None
    try:
        try:
            structured = invoke_codex(pr, run_id=run_id)
            validate_result(structured, pr)
        except Exception as exc:  # Reconciliation must still run after timeout/failure.
            invocation_error = exc
            structured = None

        try:
            after = github_publications(pr, login)
            old_ids = publication_ids(before)
            new_publications = {
                kind: [item for item in after[kind] if (kind, int(item["id"])) not in old_ids]
                for kind in ("reviews", "comments")
            }
            if publication_ids(new_publications):
                if structured is None:
                    structured = {
                        "summary": "GitHub publication verified after the delegated run ended without structured output.",
                        "findings": [],
                        "linear": {"fetch_status": "unavailable"},
                        "limitations": [str(invocation_error)] if invocation_error else [],
                    }
                persist_verified(db, run_id, structured, new_publications)
                response = {
                    "url": pr.url,
                    "status": "published",
                    "event": db.execute("SELECT event FROM review_runs WHERE id = ?", (run_id,)).fetchone()[0],
                    "head_sha": pr.head_sha,
                    "run_id": run_id,
                    "summary": structured.get("summary"),
                }
                return response
            error = str(invocation_error or "no new GitHub publication was found")
            mark_failed(db, run_id, error, structured)
            response = {"url": pr.url, "status": "failed", "head_sha": pr.head_sha, "error": error}
            return response
        except Exception as exc:
            mark_failed(db, run_id, str(exc), structured)
            response = {"url": pr.url, "status": "failed", "head_sha": pr.head_sha, "error": str(exc)}
            return response
    finally:
        cleanup_warnings = cleanup_review_run(db, run_id)
        if cleanup_warnings:
            if response is not None:
                response["cleanup_warnings"] = cleanup_warnings
            print("; ".join(cleanup_warnings), file=sys.stderr)


def review_urls(
    urls: Iterable[str],
    db_path: str | None = None,
    *,
    allow_self_review: bool = False,
) -> dict[str, Any]:
    unique_urls = list(dict.fromkeys(url.strip() for url in urls if url.strip()))
    if not unique_urls:
        raise AutomationError("at least one exact GitHub pull request URL is required")
    for url in unique_urls:
        parse_pr_url(url)
    login = reviewer_login()
    with connect_db(db_path) as db:
        results = [
            review_one(db, url, login, allow_self_review=allow_self_review)
            for url in unique_urls
        ]
    return {
        "reviewer": login,
        "requested": len(unique_urls),
        "published": sum(item["status"] == "published" for item in results),
        "in_progress": sum(item["status"] == "in_progress" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "results": results,
    }


def recover_run_ids(
    run_ids: Iterable[str],
    db_path: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    unique_ids = list(
        dict.fromkeys(run_id.strip() for run_id in run_ids if run_id.strip())
    )
    if not unique_ids:
        raise AutomationError("at least one review run ID is required")
    login = reviewer_login()
    results: list[dict[str, Any]] = []
    with connect_db(db_path) as db:
        for run_id in unique_ids:
            row = db.execute(
                "SELECT * FROM review_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                results.append({"run_id": run_id, "status": "not_found"})
                continue
            if str(row["reviewer_login"]).lower() != login.lower():
                results.append(
                    {
                        "run_id": run_id,
                        "status": "reviewer_mismatch",
                        "reviewer": str(row["reviewer_login"]),
                    }
                )
                continue
            if str(row["status"]) == "published":
                cleanup_warnings = cleanup_review_run(db, run_id)
                item: dict[str, Any] = {
                    "run_id": run_id,
                    "url": str(row["pr_url"]),
                    "head_sha": str(row["head_sha"]),
                    "status": "skipped_verified",
                    "cleanup_status": "failed" if cleanup_warnings else "clean",
                }
                if cleanup_warnings:
                    item["cleanup_warnings"] = cleanup_warnings
                results.append(item)
                continue
            if str(row["status"]) != "running":
                results.append(
                    {
                        "run_id": run_id,
                        "url": str(row["pr_url"]),
                        "head_sha": str(row["head_sha"]),
                        "status": "not_recoverable",
                        "current_status": str(row["status"]),
                    }
                )
                continue
            pr = pull_request_from_run(row)
            publications = github_publications(pr, login)
            results.append(recover_running_run(db, row, publications, force=force))
    return {
        "reviewer": login,
        "requested": len(unique_ids),
        "published": sum(item["status"] == "published" for item in results),
        "in_progress": sum(item["status"] == "in_progress" for item in results),
        "results": results,
    }


def digest_source(
    db_path: str | None = None,
    *,
    hours: int = 24,
    timezone_name: str = "America/Mexico_City",
    now: datetime | None = None,
) -> dict[str, Any]:
    if hours < 1 or hours > 168:
        raise AutomationError("digest hours must be between 1 and 168")
    zone = ZoneInfo(timezone_name)
    end = (now or utc_now()).astimezone(zone)
    start = end - timedelta(hours=hours)
    with connect_db(db_path) as db:
        rows = db.execute(
            """
            SELECT r.*, l.fetch_status, l.issue_key, l.title AS linear_title,
                   l.url AS linear_url, l.status AS linear_status, l.project,
                   l.product_summary, l.acceptance_criteria, l.labels
            FROM review_runs r
            LEFT JOIN linear_snapshots l ON l.run_id = r.id
            WHERE r.status = 'published' AND r.completed_at >= ? AND r.completed_at < ?
            ORDER BY r.completed_at ASC
            """,
            (iso(start), iso(end)),
        ).fetchall()
        reviews: list[dict[str, Any]] = []
        for row in rows:
            findings = [
                dict(item)
                for item in db.execute(
                    "SELECT category, severity, path, line, body, blocking FROM review_findings WHERE run_id = ? ORDER BY id",
                    (row["id"],),
                ).fetchall()
            ]
            reviews.append(
                {
                    "run_id": row["id"],
                    "completed_at": row["completed_at"],
                    "repo": row["repo"],
                    "pr_number": row["pr_number"],
                    "pr_url": row["pr_url"],
                    "pr_title": row["pr_title"],
                    "pr_author": row["pr_author"],
                    "head_sha": row["head_sha"],
                    "event": row["event"],
                    "summary": row["summary"],
                    "findings": findings,
                    "linear": {
                        "fetch_status": row["fetch_status"] or "missing",
                        "key": row["issue_key"],
                        "title": row["linear_title"],
                        "url": row["linear_url"],
                        "status": row["linear_status"],
                        "project": row["project"],
                        "product_summary": row["product_summary"],
                        "acceptance_criteria": json.loads(row["acceptance_criteria"] or "[]"),
                        "labels": json.loads(row["labels"] or "[]"),
                    },
                }
            )
    return {
        "timezone": timezone_name,
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "review_count": len(reviews),
        "reviews": reviews,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="override the SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="initialize or migrate the database")
    review = subparsers.add_parser("review", help="delegate and persist exact PR reviews")
    review.add_argument(
        "--allow-self-review",
        action="store_true",
        help="allow PRs authored by the authenticated GitHub user",
    )
    review.add_argument("urls", nargs="+")
    recover = subparsers.add_parser(
        "recover", help="reconcile interrupted review runs and clean their Paseo agents"
    )
    recover.add_argument(
        "--force",
        action="store_true",
        help="recover a published review even if Paseo still reports its agent as running",
    )
    recover.add_argument("run_ids", nargs="+")
    cleanup = subparsers.add_parser(
        "cleanup", help="retry cleanup for terminal review runs"
    )
    cleanup.add_argument("--limit", type=int, default=100)
    cleanup.add_argument("run_ids", nargs="*")
    digest = subparsers.add_parser("digest-source", help="emit verified review data for a digest")
    digest.add_argument("--hours", type=int, default=24)
    digest.add_argument("--timezone", default=os.environ.get("TZ", "America/Mexico_City"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            with connect_db(args.db) as db:
                version = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            emit({"status": "ready", "schema_version": version, "database": args.db or os.environ.get("REVIEW_HISTORY_DB", DEFAULT_DB)})
        elif args.command == "review":
            emit(
                review_urls(
                    args.urls,
                    args.db,
                    allow_self_review=args.allow_self_review,
                )
            )
        elif args.command == "recover":
            emit(recover_run_ids(args.run_ids, args.db, force=args.force))
        elif args.command == "cleanup":
            emit(
                reconcile_terminal_cleanup(
                    args.db,
                    run_ids=args.run_ids,
                    limit=args.limit,
                )
            )
        elif args.command == "digest-source":
            emit(digest_source(args.db, hours=args.hours, timezone_name=args.timezone))
        return 0
    except (AutomationError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        emit({"status": "error", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
