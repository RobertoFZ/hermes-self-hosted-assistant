#!/usr/bin/env python3
"""Prepare private PR proposals and execute explicitly confirmed review actions."""

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
REVISION_TOKEN_PATTERN = r"P[1-9][0-9]*"
CANDIDATE_TOKEN_PATTERN = r"C[1-9][0-9]*"
TERMINAL_COMMAND_RE = re.compile(
    rf"^(?P<action>approve|skip) (?P<revision>{REVISION_TOKEN_PATTERN})$"
)
SELECTION_COMMAND_RE = re.compile(
    rf"^(?P<action>publish|dismiss) (?P<revision>{REVISION_TOKEN_PATTERN}) "
    rf"(?P<candidates>{CANDIDATE_TOKEN_PATTERN}(?: {CANDIDATE_TOKEN_PATTERN})*)$"
)
EDIT_COMMAND_RE = re.compile(
    rf"^edit (?P<revision>{REVISION_TOKEN_PATTERN}) "
    rf"(?P<candidate>{CANDIDATE_TOKEN_PATTERN}): (?P<body>\S(?:.*\S)?)$"
)


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
    state: str = "OPEN"


@dataclass(frozen=True)
class DecisionCommand:
    action: str
    revision_token: str
    candidate_ids: tuple[str, ...] = ()
    body: str | None = None


def parse_decision_command(text: str) -> DecisionCommand | None:
    """Parse only the documented revision-bound mutation language."""
    value = text.strip()
    match = TERMINAL_COMMAND_RE.fullmatch(value)
    if match:
        return DecisionCommand(match["action"], match["revision"])
    match = SELECTION_COMMAND_RE.fullmatch(value)
    if match:
        candidates = tuple(match["candidates"].split(" "))
        if len(set(candidates)) != len(candidates):
            return None
        return DecisionCommand(match["action"], match["revision"], candidates)
    match = EDIT_COMMAND_RE.fullmatch(value)
    if match:
        return DecisionCommand(
            "edit",
            match["revision"],
            (match["candidate"],),
            match["body"],
        )
    return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _weekday_start(value: datetime, zone: ZoneInfo, *, strictly_next: bool) -> datetime:
    local = value.astimezone(zone)
    candidate = local.date() + timedelta(days=1 if strictly_next else 0)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return datetime(
        candidate.year,
        candidate.month,
        candidate.day,
        9,
        tzinfo=zone,
    )


def next_weekday_start(value: datetime, timezone_name: str) -> datetime:
    """Return 09:00 on the next Monday-Friday in the configured timezone."""
    return _weekday_start(value, ZoneInfo(timezone_name), strictly_next=True)


def add_working_minutes(
    value: datetime,
    minutes: int,
    timezone_name: str,
) -> datetime:
    """Add Monday-Friday 09:00-18:00 working minutes (no holiday calendar)."""
    if minutes < 0:
        raise AutomationError("working minutes cannot be negative")
    zone = ZoneInfo(timezone_name)
    cursor = value.astimezone(zone)
    remaining = minutes
    while True:
        if cursor.weekday() >= 5:
            cursor = _weekday_start(cursor, zone, strictly_next=False)
        day_start = cursor.replace(hour=9, minute=0, second=0, microsecond=0)
        day_end = cursor.replace(hour=18, minute=0, second=0, microsecond=0)
        if cursor < day_start:
            cursor = day_start
        elif cursor >= day_end:
            cursor = _weekday_start(cursor, zone, strictly_next=True)
            continue
        available = int((day_end - cursor).total_seconds() // 60)
        if remaining <= available:
            return cursor + timedelta(minutes=remaining)
        remaining -= available
        cursor = _weekday_start(cursor, zone, strictly_next=True)


def emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run(
    command: Sequence[str],
    *,
    timeout: int | None = None,
    check: bool = True,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        input=input_text,
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


def github_json_request(method: str, endpoint: str, payload: Mapping[str, Any]) -> Any:
    """Send one JSON GitHub API request without shell interpolation."""
    result = run(
        ["gh", "api", "--method", method, endpoint, "--input", "-"],
        input_text=json.dumps(dict(payload), sort_keys=True),
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AutomationError("GitHub API returned invalid JSON") from exc


def gh_paginated(endpoint: str) -> list[dict[str, Any]]:
    pages = gh_json(["api", "--paginate", "--slurp", endpoint])
    if not isinstance(pages, list):
        raise AutomationError("GitHub paginated response is not a list")
    if pages and all(isinstance(page, list) for page in pages):
        return [item for page in pages for item in page if isinstance(item, dict)]
    return [item for item in pages if isinstance(item, dict)]


def github_compare_context(
    pr: PullRequest,
    baseline_head_sha: str,
) -> dict[str, Any]:
    """Read the exact baseline-to-target comparison, or describe why it is unavailable."""
    owner, repo = pr.repo.split("/", 1)
    endpoint = (
        f"repos/{owner}/{repo}/compare/{baseline_head_sha}...{pr.head_sha}"
    )
    try:
        completed = run(
            ["gh", "api", endpoint],
            timeout=60,
            check=False,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "reason": str(exc)}
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return {
            "status": "unavailable",
            "reason": detail or "GitHub could not compare the exact baseline",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "unavailable",
            "reason": "GitHub returned an invalid comparison response",
        }
    if not isinstance(payload, dict) or not isinstance(payload.get("merge_base_commit"), dict):
        return {
            "status": "unavailable",
            "reason": "GitHub did not establish a merge base for the exact baseline",
        }
    return {
        "status": "available",
        "comparison_status": str(payload.get("status") or ""),
        "ahead_by": int(payload.get("ahead_by") or 0),
        "behind_by": int(payload.get("behind_by") or 0),
        "merge_base_sha": str((payload.get("merge_base_commit") or {}).get("sha") or ""),
        "commits": [
            str(item.get("sha") or "")
            for item in payload.get("commits") or []
            if isinstance(item, dict) and item.get("sha")
        ],
        "changed_files": [
            {
                "path": str(item.get("filename") or ""),
                "status": str(item.get("status") or ""),
                "additions": int(item.get("additions") or 0),
                "deletions": int(item.get("deletions") or 0),
            }
            for item in payload.get("files") or []
            if isinstance(item, dict) and item.get("filename")
        ],
    }


def load_pr(url: str) -> PullRequest:
    expected_repo, expected_number = parse_pr_url(url)
    data = gh_json(
        [
            "pr",
            "view",
            url,
            "--json",
            "url,number,title,body,headRefOid,baseRefName,author,state",
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
        state=str(data.get("state") or "OPEN").upper(),
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
        # GitHub can retarget commit_id when an old inline comment still maps to
        # the new diff. original_commit_id identifies the revision it reviewed.
        "comments": [
            item
            for item in comments
            if str((item.get("user") or {}).get("login") or "").lower() == normalized_login
            and str(item.get("commit_id") or "") == pr.head_sha
            and str(item.get("original_commit_id") or "") == pr.head_sha
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
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS workflow_source_requests (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            message_ts TEXT NOT NULL,
            requester_user_id TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            verdict_message_ts TEXT,
            reaction_name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(workspace_id, channel_id, message_ts)
        );
        CREATE TABLE IF NOT EXISTS workflow_pr_conversations (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            owner_user_id TEXT NOT NULL,
            repo TEXT NOT NULL,
            pr_number INTEGER NOT NULL,
            pr_url TEXT NOT NULL,
            dm_channel_id TEXT,
            thread_ts TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(workspace_id, owner_user_id, repo, pr_number)
        );
        CREATE TABLE IF NOT EXISTS workflow_request_members (
            request_id TEXT NOT NULL
                REFERENCES workflow_source_requests(id) ON DELETE CASCADE,
            conversation_id TEXT NOT NULL
                REFERENCES workflow_pr_conversations(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            outcome TEXT,
            reviewed_head TEXT,
            published_comment_count INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(request_id, conversation_id),
            UNIQUE(request_id, position)
        );
        CREATE INDEX IF NOT EXISTS workflow_request_members_conversation_idx
            ON workflow_request_members(conversation_id, request_id);
        CREATE TABLE IF NOT EXISTS proposal_revisions (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL
                REFERENCES workflow_pr_conversations(id) ON DELETE CASCADE,
            revision_number INTEGER NOT NULL,
            revision_token TEXT NOT NULL,
            head_sha TEXT NOT NULL,
            baseline_head_sha TEXT,
            state TEXT NOT NULL,
            objective TEXT,
            proposed_action TEXT,
            summary TEXT,
            delta_available INTEGER,
            structured_result TEXT,
            created_at TEXT NOT NULL,
            ready_at TEXT,
            superseded_at TEXT,
            terminal_at TEXT,
            UNIQUE(conversation_id, revision_number),
            UNIQUE(conversation_id, revision_token)
        );
        CREATE INDEX IF NOT EXISTS proposal_revisions_current_idx
            ON proposal_revisions(conversation_id, state, revision_number DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS proposal_revisions_one_active_idx
            ON proposal_revisions(conversation_id)
            WHERE state IN (
                'queued', 'analyzing', 'output_pending',
                'awaiting_decision', 'publishing'
            );
        CREATE TABLE IF NOT EXISTS proposal_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id TEXT NOT NULL
                REFERENCES proposal_revisions(id) ON DELETE CASCADE,
            candidate_id TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            path TEXT,
            line INTEGER,
            start_line INTEGER,
            side TEXT,
            start_side TEXT,
            body TEXT NOT NULL,
            blocking INTEGER NOT NULL,
            evidence TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(proposal_id, candidate_id)
        );
        CREATE TABLE IF NOT EXISTS proposal_decisions (
            id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL
                REFERENCES proposal_revisions(id) ON DELETE CASCADE,
            owner_user_id TEXT NOT NULL,
            action TEXT NOT NULL,
            selected_candidate_ids TEXT NOT NULL DEFAULT '[]',
            payload TEXT NOT NULL DEFAULT '{}',
            idempotency_key TEXT NOT NULL UNIQUE,
            state TEXT NOT NULL DEFAULT 'accepted',
            created_at TEXT NOT NULL,
            completed_at TEXT,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS proposal_decisions_proposal_idx
            ON proposal_decisions(proposal_id, created_at);
        CREATE TABLE IF NOT EXISTS workflow_actions (
            id TEXT PRIMARY KEY,
            decision_id TEXT NOT NULL
                REFERENCES proposal_decisions(id) ON DELETE CASCADE,
            action_type TEXT NOT NULL,
            expected_head TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending',
            claimant TEXT,
            lease_expires_at TEXT,
            receipt TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(decision_id, action_type)
        );
        CREATE INDEX IF NOT EXISTS workflow_actions_claim_idx
            ON workflow_actions(state, lease_expires_at);
        CREATE TABLE IF NOT EXISTS action_publications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id TEXT NOT NULL
                REFERENCES workflow_actions(id) ON DELETE CASCADE,
            candidate_id TEXT,
            kind TEXT NOT NULL,
            github_id INTEGER NOT NULL,
            state TEXT,
            url TEXT,
            published_at TEXT,
            UNIQUE(kind, github_id),
            UNIQUE(action_id, candidate_id, kind)
        );
        CREATE TABLE IF NOT EXISTS slack_deliveries (
            id TEXT PRIMARY KEY,
            delivery_key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            thread_ts TEXT,
            request_id TEXT REFERENCES workflow_source_requests(id) ON DELETE CASCADE,
            conversation_id TEXT
                REFERENCES workflow_pr_conversations(id) ON DELETE CASCADE,
            proposal_id TEXT REFERENCES proposal_revisions(id) ON DELETE CASCADE,
            metadata_key TEXT,
            state TEXT NOT NULL DEFAULT 'pending',
            claimant TEXT,
            lease_expires_at TEXT,
            message_ts TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS slack_deliveries_claim_idx
            ON slack_deliveries(state, lease_expires_at);
        CREATE TABLE IF NOT EXISTS proposal_reminders (
            id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL UNIQUE
                REFERENCES proposal_revisions(id) ON DELETE CASCADE,
            stage INTEGER NOT NULL DEFAULT 1,
            state TEXT NOT NULL DEFAULT 'scheduled',
            due_at TEXT,
            claimant TEXT,
            lease_expires_at TEXT,
            delivery_id TEXT REFERENCES slack_deliveries(id),
            last_sent_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS proposal_reminders_due_idx
            ON proposal_reminders(state, due_at, lease_expires_at);
        CREATE TABLE IF NOT EXISTS analysis_attempts (
            id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL
                REFERENCES proposal_revisions(id) ON DELETE CASCADE,
            claimant TEXT NOT NULL,
            state TEXT NOT NULL,
            expected_head TEXT NOT NULL,
            lease_expires_at TEXT,
            heartbeat_at TEXT NOT NULL,
            output TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error TEXT
        );
        CREATE INDEX IF NOT EXISTS analysis_attempts_reclaim_idx
            ON analysis_attempts(state, lease_expires_at);
        CREATE UNIQUE INDEX IF NOT EXISTS analysis_attempts_one_active_idx
            ON analysis_attempts(proposal_id)
            WHERE state IN ('running', 'output_received', 'ready_to_persist');
        """
    )
    db.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (3, ?)",
        (iso(utc_now()),),
    )
    db.commit()


ACTIVE_PROPOSAL_STATES = {
    "queued",
    "analyzing",
    "output_pending",
    "awaiting_decision",
    "publishing",
}


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _begin_immediate(db: sqlite3.Connection) -> None:
    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")


def get_or_create_source_request(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    channel_id: str,
    message_ts: str,
    requester_user_id: str,
) -> tuple[str, bool]:
    """Return the durable source request for one exact Slack message."""
    if not all((workspace_id, channel_id, message_ts, requester_user_id)):
        raise AutomationError("source request identity is incomplete")
    now = iso(utc_now())
    request_id = str(uuid.uuid4())
    try:
        _begin_immediate(db)
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO workflow_source_requests(
                id, workspace_id, channel_id, message_ts, requester_user_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                workspace_id,
                channel_id,
                message_ts,
                requester_user_id,
                now,
                now,
            ),
        )
        created = cursor.rowcount == 1
        row = db.execute(
            """
            SELECT id, requester_user_id
            FROM workflow_source_requests
            WHERE workspace_id = ? AND channel_id = ? AND message_ts = ?
            """,
            (workspace_id, channel_id, message_ts),
        ).fetchone()
        if row is None:
            raise AutomationError("failed to persist source request")
        if str(row["requester_user_id"]) != requester_user_id:
            raise AutomationError("source request identity belongs to another requester")
        db.commit()
        return str(row["id"]), created
    except Exception:
        db.rollback()
        raise


def get_or_create_pr_conversation(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    owner_user_id: str,
    repo: str,
    pr_number: int,
    pr_url: str,
) -> tuple[str, bool]:
    """Reuse one private conversation for a PR across requests and heads."""
    if not all((workspace_id, owner_user_id, repo, pr_url)) or pr_number < 1:
        raise AutomationError("PR conversation identity is incomplete")
    now = iso(utc_now())
    conversation_id = str(uuid.uuid4())
    try:
        _begin_immediate(db)
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO workflow_pr_conversations(
                id, workspace_id, owner_user_id, repo, pr_number, pr_url,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                workspace_id,
                owner_user_id,
                repo,
                pr_number,
                pr_url,
                now,
                now,
            ),
        )
        created = cursor.rowcount == 1
        row = db.execute(
            """
            SELECT id, pr_url
            FROM workflow_pr_conversations
            WHERE workspace_id = ? AND owner_user_id = ?
              AND repo = ? AND pr_number = ?
            """,
            (workspace_id, owner_user_id, repo, pr_number),
        ).fetchone()
        if row is None:
            raise AutomationError("failed to persist PR conversation")
        if str(row["pr_url"]) != pr_url:
            db.execute(
                """
                UPDATE workflow_pr_conversations
                SET pr_url = ?, updated_at = ? WHERE id = ?
                """,
                (pr_url, now, row["id"]),
            )
        db.commit()
        return str(row["id"]), created
    except Exception:
        db.rollback()
        raise


def bind_pr_conversation_thread(
    db: sqlite3.Connection,
    conversation_id: str,
    *,
    dm_channel_id: str,
    thread_ts: str,
) -> None:
    """Bind a stable conversation once; reject an attempt to move its thread."""
    try:
        _begin_immediate(db)
        row = db.execute(
            """
            SELECT dm_channel_id, thread_ts
            FROM workflow_pr_conversations WHERE id = ?
            """,
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise AutomationError("unknown PR conversation")
        existing = (row["dm_channel_id"], row["thread_ts"])
        requested = (dm_channel_id, thread_ts)
        if existing != (None, None) and existing != requested:
            raise AutomationError("PR conversation is already bound to another thread")
        db.execute(
            """
            UPDATE workflow_pr_conversations
            SET dm_channel_id = ?, thread_ts = ?, updated_at = ?
            WHERE id = ?
            """,
            (dm_channel_id, thread_ts, iso(utc_now()), conversation_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def associate_request_conversation(
    db: sqlite3.Connection,
    request_id: str,
    conversation_id: str,
    *,
    position: int,
) -> bool:
    """Idempotently attach a PR conversation to one source request."""
    if position < 0:
        raise AutomationError("request member position cannot be negative")
    try:
        _begin_immediate(db)
        existing = db.execute(
            """
            SELECT position FROM workflow_request_members
            WHERE request_id = ? AND conversation_id = ?
            """,
            (request_id, conversation_id),
        ).fetchone()
        if existing is not None:
            if int(existing["position"]) != position:
                raise AutomationError("request member already has another position")
            db.commit()
            return False
        db.execute(
            """
            INSERT INTO workflow_request_members(
                request_id, conversation_id, position, updated_at
            ) VALUES (?, ?, ?, ?)
            """,
            (request_id, conversation_id, position, iso(utc_now())),
        )
        db.commit()
        return True
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise AutomationError("request member conflicts with persisted ordering") from exc
    except Exception:
        db.rollback()
        raise


def source_requests_for_conversation(
    db: sqlite3.Connection,
    conversation_id: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT r.*, m.position, m.state AS member_state, m.outcome,
               m.reviewed_head, m.published_comment_count, m.error AS member_error
        FROM workflow_source_requests r
        JOIN workflow_request_members m ON m.request_id = r.id
        WHERE m.conversation_id = ?
        ORDER BY r.created_at, r.id
        """,
        (conversation_id,),
    ).fetchall()
    return [_row_dict(row) for row in rows]


def conversation_for_slack_thread(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    dm_channel_id: str,
    thread_ts: str,
) -> dict[str, Any] | None:
    """Resolve an owner reply to its stable PR conversation and active proposal."""
    row = db.execute(
        """
        SELECT c.*, p.id AS proposal_id, p.revision_token,
               p.head_sha AS proposal_head, p.state AS proposal_state
        FROM workflow_pr_conversations c
        LEFT JOIN proposal_revisions p
          ON p.id = (
              SELECT latest.id FROM proposal_revisions latest
              WHERE latest.conversation_id = c.id
                AND latest.state IN ('queued', 'analyzing', 'output_pending',
                                     'awaiting_decision', 'publishing')
              ORDER BY latest.revision_number DESC LIMIT 1
          )
        WHERE c.workspace_id = ? AND c.dm_channel_id = ? AND c.thread_ts = ?
        """,
        (workspace_id, dm_channel_id, thread_ts),
    ).fetchone()
    return _row_dict(row) if row is not None else None


TERMINAL_MEMBER_OUTCOMES = {
    "approved",
    "comments_published",
    "skipped",
    "merged_externally",
    "closed_externally",
    "failed",
    "operator_blocked",
}


def _refresh_source_request_locked(
    db: sqlite3.Connection,
    request_id: str,
    *,
    stamp: str,
) -> tuple[str, str]:
    member_states = [
        str(row["state"])
        for row in db.execute(
            "SELECT state FROM workflow_request_members WHERE request_id = ?",
            (request_id,),
        ).fetchall()
    ]
    if not member_states or any(
        state in {"failed", "operator_blocked"} for state in member_states
    ):
        request_state = "failed"
        reaction = "warning"
    elif any(state not in TERMINAL_MEMBER_OUTCOMES for state in member_states):
        request_state = "pending"
        reaction = "eyes"
    else:
        request_state = "completed"
        reaction = "white_check_mark"
    db.execute(
        """
        UPDATE workflow_source_requests
        SET state = ?, reaction_name = ?, updated_at = ? WHERE id = ?
        """,
        (request_state, reaction, stamp, request_id),
    )
    return request_state, reaction


def update_request_member_outcome(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    outcome: str,
    reviewed_head: str,
    published_comment_count: int = 0,
    error: str | None = None,
) -> list[str]:
    """Project one PR outcome to every source request that references it."""
    if outcome not in TERMINAL_MEMBER_OUTCOMES:
        raise AutomationError("request member outcome is not terminal")
    if published_comment_count < 0:
        raise AutomationError("published comment count cannot be negative")
    stamp = iso(utc_now())
    try:
        _begin_immediate(db)
        request_ids = [
            str(row["request_id"])
            for row in db.execute(
                """
                SELECT request_id FROM workflow_request_members
                WHERE conversation_id = ? ORDER BY request_id
                """,
                (conversation_id,),
            ).fetchall()
        ]
        if not request_ids:
            raise AutomationError("PR conversation has no linked source requests")
        db.execute(
            """
            UPDATE workflow_request_members
            SET state = ?, outcome = ?, reviewed_head = ?,
                published_comment_count = ?, error = ?, updated_at = ?
            WHERE conversation_id = ?
            """,
            (
                outcome,
                outcome,
                reviewed_head,
                published_comment_count,
                error,
                stamp,
                conversation_id,
            ),
        )
        for request_id in request_ids:
            _refresh_source_request_locked(db, request_id, stamp=stamp)
        db.commit()
        return request_ids
    except Exception:
        db.rollback()
        raise


def source_request_projection(
    db: sqlite3.Connection,
    request_id: str,
) -> dict[str, Any]:
    request = db.execute(
        "SELECT * FROM workflow_source_requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    if request is None:
        raise AutomationError("unknown source request")
    members = db.execute(
        """
        SELECT m.*, c.repo, c.pr_number, c.pr_url
        FROM workflow_request_members m
        JOIN workflow_pr_conversations c ON c.id = m.conversation_id
        WHERE m.request_id = ? ORDER BY m.position
        """,
        (request_id,),
    ).fetchall()
    result = _row_dict(request)
    result["members"] = [_row_dict(row) for row in members]
    return result


def bind_source_verdict(
    db: sqlite3.Connection,
    *,
    request_id: str,
    verdict_message_ts: str,
) -> None:
    """Persist the single verdict message used for all later source updates."""
    try:
        _begin_immediate(db)
        row = db.execute(
            "SELECT verdict_message_ts FROM workflow_source_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise AutomationError("unknown source request")
        existing = row["verdict_message_ts"]
        if existing is not None and str(existing) != verdict_message_ts:
            raise AutomationError("source request already has another verdict message")
        db.execute(
            """
            UPDATE workflow_source_requests
            SET verdict_message_ts = ?, updated_at = ? WHERE id = ?
            """,
            (verdict_message_ts, iso(utc_now()), request_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def _create_proposal_revision_locked(
    db: sqlite3.Connection,
    conversation_id: str,
    *,
    head_sha: str,
    baseline_head_sha: str | None,
    state: str,
    now: datetime,
) -> dict[str, Any]:
    existing = db.execute(
        """
        SELECT * FROM proposal_revisions
        WHERE conversation_id = ? AND head_sha = ?
          AND state IN ('queued', 'analyzing', 'output_pending',
                        'awaiting_decision', 'publishing')
        ORDER BY revision_number DESC LIMIT 1
        """,
        (conversation_id, head_sha),
    ).fetchone()
    if existing is not None:
        result = _row_dict(existing)
        result["created"] = False
        return result

    conversation = db.execute(
        "SELECT id FROM workflow_pr_conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if conversation is None:
        raise AutomationError("unknown PR conversation")

    stamp = iso(now)
    db.execute(
        """
        UPDATE proposal_revisions
        SET state = 'superseded', superseded_at = ?
        WHERE conversation_id = ?
          AND state IN ('queued', 'analyzing', 'output_pending',
                        'awaiting_decision', 'publishing')
        """,
        (stamp, conversation_id),
    )
    db.execute(
        """
        UPDATE proposal_reminders
        SET state = 'completed', due_at = NULL, claimant = NULL,
            lease_expires_at = NULL, updated_at = ?
        WHERE proposal_id IN (
            SELECT id FROM proposal_revisions
            WHERE conversation_id = ? AND state = 'superseded'
        ) AND state NOT IN ('completed', 'digest_only')
        """,
        (stamp, conversation_id),
    )
    db.execute(
        """
        UPDATE proposal_decisions
        SET state = 'rejected_stale', completed_at = ?,
            error = 'proposal superseded by a newer revision'
        WHERE proposal_id IN (
            SELECT id FROM proposal_revisions
            WHERE conversation_id = ? AND state = 'superseded'
        ) AND state IN ('accepted', 'executing')
        """,
        (stamp, conversation_id),
    )
    next_number = int(
        db.execute(
            """
            SELECT COALESCE(MAX(revision_number), 0) + 1
            FROM proposal_revisions WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()[0]
    )
    proposal_id = str(uuid.uuid4())
    token = f"P{next_number}"
    db.execute(
        """
        INSERT INTO proposal_revisions(
            id, conversation_id, revision_number, revision_token,
            head_sha, baseline_head_sha, state, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            proposal_id,
            conversation_id,
            next_number,
            token,
            head_sha,
            baseline_head_sha,
            state,
            stamp,
        ),
    )
    db.execute(
        """
        UPDATE workflow_request_members
        SET state = 'analyzing', reviewed_head = ?, updated_at = ?
        WHERE conversation_id = ? AND state NOT IN (
            'approved', 'comments_published', 'skipped',
            'merged_externally', 'closed_externally'
        )
        """,
        (head_sha, stamp, conversation_id),
    )
    return {
        "id": proposal_id,
        "conversation_id": conversation_id,
        "revision_number": next_number,
        "revision_token": token,
        "head_sha": head_sha,
        "baseline_head_sha": baseline_head_sha,
        "state": state,
        "created_at": stamp,
        "created": True,
    }


def create_proposal_revision(
    db: sqlite3.Connection,
    conversation_id: str,
    *,
    head_sha: str,
    baseline_head_sha: str | None = None,
    state: str = "queued",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create the next immutable, head-bound proposal revision."""
    if not head_sha:
        raise AutomationError("proposal head is required")
    if state not in ACTIVE_PROPOSAL_STATES:
        raise AutomationError("new proposal must start in an active state")
    try:
        _begin_immediate(db)
        result = _create_proposal_revision_locked(
            db,
            conversation_id,
            head_sha=head_sha,
            baseline_head_sha=baseline_head_sha,
            state=state,
            now=now or utc_now(),
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def active_proposal(
    db: sqlite3.Connection,
    conversation_id: str,
) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT * FROM proposal_revisions
        WHERE conversation_id = ?
          AND state IN ('queued', 'analyzing', 'output_pending',
                        'awaiting_decision', 'publishing')
        ORDER BY revision_number DESC LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()
    return _row_dict(row) if row is not None else None


def latest_proposal(
    db: sqlite3.Connection,
    conversation_id: str,
) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT * FROM proposal_revisions
        WHERE conversation_id = ?
        ORDER BY revision_number DESC LIMIT 1
        """,
        (conversation_id,),
    ).fetchone()
    return _row_dict(row) if row is not None else None


def _effective_reviewed_baseline(proposal: Mapping[str, Any] | None) -> str | None:
    """Keep the last completed review as baseline while newer analysis is in flight."""
    if proposal is None:
        return None
    if proposal.get("structured_result") is not None:
        return str(proposal["head_sha"])
    baseline = proposal.get("baseline_head_sha")
    return str(baseline) if baseline else None


def finalize_external_pr(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    pr: PullRequest,
) -> dict[str, Any]:
    """Terminalize every workflow projection when GitHub reports merge or close."""
    if pr.state not in {"MERGED", "CLOSED"}:
        raise AutomationError("external PR completion requires MERGED or CLOSED state")
    outcome = "merged_externally" if pr.state == "MERGED" else "closed_externally"
    stamp = iso(utc_now())
    try:
        _begin_immediate(db)
        request_ids = [
            str(row["request_id"])
            for row in db.execute(
                "SELECT request_id FROM workflow_request_members "
                "WHERE conversation_id = ? ORDER BY request_id",
                (conversation_id,),
            ).fetchall()
        ]
        proposal_ids = [
            str(row["id"])
            for row in db.execute(
                "SELECT id FROM proposal_revisions WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()
        ]
        db.execute(
            """
            UPDATE proposal_revisions
            SET state = ?, terminal_at = COALESCE(terminal_at, ?),
                superseded_at = CASE
                    WHEN state IN ('queued', 'analyzing', 'output_pending',
                                   'awaiting_decision', 'publishing')
                    THEN COALESCE(superseded_at, ?) ELSE superseded_at END
            WHERE conversation_id = ?
              AND state NOT IN ('completed', 'merged_externally', 'closed_externally')
            """,
            (outcome, stamp, stamp, conversation_id),
        )
        if proposal_ids:
            placeholders = ",".join("?" for _ in proposal_ids)
            db.execute(
                f"""
                UPDATE proposal_decisions
                SET state = 'rejected_external', completed_at = COALESCE(completed_at, ?),
                    error = ?
                WHERE proposal_id IN ({placeholders})
                  AND state IN ('accepted', 'executing')
                """,
                (stamp, f"pull request {pr.state.lower()} externally", *proposal_ids),
            )
            db.execute(
                f"""
                UPDATE proposal_reminders
                SET state = 'completed', due_at = NULL, claimant = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE proposal_id IN ({placeholders}) AND state != 'completed'
                """,
                (stamp, *proposal_ids),
            )
            db.execute(
                f"""
                UPDATE analysis_attempts
                SET state = 'abandoned_external', completed_at = COALESCE(completed_at, ?),
                    lease_expires_at = NULL,
                    error = ?
                WHERE proposal_id IN ({placeholders})
                  AND state IN ('running', 'output_received', 'ready_to_persist')
                """,
                (stamp, f"pull request {pr.state.lower()} externally", *proposal_ids),
            )
            db.execute(
                f"""
                UPDATE workflow_actions
                SET state = 'blocked', completed_at = COALESCE(completed_at, ?),
                    lease_expires_at = NULL, error = ?
                WHERE decision_id IN (
                    SELECT id FROM proposal_decisions
                    WHERE proposal_id IN ({placeholders})
                ) AND state NOT IN ('completed', 'blocked', 'failed')
                """,
                (stamp, f"pull request {pr.state.lower()} externally", *proposal_ids),
            )
        db.execute(
            """
            UPDATE workflow_request_members
            SET state = ?, outcome = ?, reviewed_head = ?,
                published_comment_count = 0, error = NULL, updated_at = ?
            WHERE conversation_id = ?
            """,
            (outcome, outcome, pr.head_sha, stamp, conversation_id),
        )
        for request_id in request_ids:
            _refresh_source_request_locked(db, request_id, stamp=stamp)
        db.commit()
        return {
            "status": outcome,
            "conversation_id": conversation_id,
            "head_sha": pr.head_sha,
            "request_ids": request_ids,
            "projection_updates": request_ids,
        }
    except Exception:
        db.rollback()
        raise


def validate_proposal_revision(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    revision_token: str,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    row = db.execute(
        """
        SELECT p.*, c.owner_user_id
        FROM proposal_revisions p
        JOIN workflow_pr_conversations c ON c.id = p.conversation_id
        WHERE p.conversation_id = ? AND p.revision_token = ?
        """,
        (conversation_id, revision_token),
    ).fetchone()
    if row is None:
        raise AutomationError("unknown proposal revision")
    if str(row["state"]) not in ACTIVE_PROPOSAL_STATES:
        raise AutomationError(f"proposal revision is {row['state']}, not active")
    if owner_user_id is not None and str(row["owner_user_id"]) != owner_user_id:
        raise AutomationError("decision owner does not match the PR conversation")
    return _row_dict(row)


def claim_analysis_attempt(
    db: sqlite3.Connection,
    proposal_id: str,
    *,
    claimant: str,
    now: datetime | None = None,
    lease_seconds: int = 900,
) -> tuple[str, str]:
    """Claim one analysis lease, returning (claim state, attempt id)."""
    moment = now or utc_now()
    stamp = iso(moment)
    expires = iso(moment + timedelta(seconds=lease_seconds))
    try:
        _begin_immediate(db)
        proposal = db.execute(
            "SELECT id, head_sha, state FROM proposal_revisions WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise AutomationError("unknown proposal")
        if str(proposal["state"]) not in {"queued", "analyzing", "output_pending"}:
            raise AutomationError("proposal is not eligible for analysis")
        existing = db.execute(
            """
            SELECT id, state, lease_expires_at FROM analysis_attempts
            WHERE proposal_id = ?
              AND state IN ('running', 'output_received', 'ready_to_persist')
            ORDER BY started_at DESC LIMIT 1
            """,
            (proposal_id,),
        ).fetchone()
        if existing is not None:
            existing_state = str(existing["state"])
            if existing_state in {"output_received", "ready_to_persist"}:
                db.commit()
                return "output_ready", str(existing["id"])
            lease_expires_at = str(existing["lease_expires_at"] or "")
            if lease_expires_at > stamp:
                db.commit()
                return "in_progress", str(existing["id"])
            db.execute(
                """
                UPDATE analysis_attempts
                SET state = 'expired', completed_at = ?,
                    error = 'analysis lease expired'
                WHERE id = ?
                """,
                (stamp, existing["id"]),
            )
        attempt_id = str(uuid.uuid4())
        db.execute(
            """
            INSERT INTO analysis_attempts(
                id, proposal_id, claimant, state, expected_head,
                lease_expires_at, heartbeat_at, started_at
            ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)
            """,
            (
                attempt_id,
                proposal_id,
                claimant,
                proposal["head_sha"],
                expires,
                stamp,
                stamp,
            ),
        )
        db.execute(
            "UPDATE proposal_revisions SET state = 'analyzing' WHERE id = ?",
            (proposal_id,),
        )
        db.commit()
        return "claimed", attempt_id
    except Exception:
        db.rollback()
        raise


def heartbeat_analysis_attempt(
    db: sqlite3.Connection,
    *,
    attempt_id: str,
    claimant: str,
    now: datetime | None = None,
    lease_seconds: int = 900,
) -> None:
    moment = now or utc_now()
    cursor = db.execute(
        """
        UPDATE analysis_attempts
        SET heartbeat_at = ?, lease_expires_at = ?
        WHERE id = ? AND claimant = ? AND state = 'running'
        """,
        (
            iso(moment),
            iso(moment + timedelta(seconds=lease_seconds)),
            attempt_id,
            claimant,
        ),
    )
    if cursor.rowcount != 1:
        db.rollback()
        raise AutomationError("analysis lease is no longer owned by claimant")
    db.commit()


def record_analysis_output(
    db: sqlite3.Connection,
    *,
    attempt_id: str,
    output: Mapping[str, Any],
    now: datetime | None = None,
) -> None:
    """Durably retain Codex output before parsing/persisting the proposal."""
    stamp = iso(now or utc_now())
    cursor = db.execute(
        """
        UPDATE analysis_attempts
        SET state = 'output_received', output = ?, heartbeat_at = ?
        WHERE id = ? AND state = 'running'
        """,
        (json.dumps(output, sort_keys=True), stamp, attempt_id),
    )
    if cursor.rowcount != 1:
        db.rollback()
        raise AutomationError("analysis attempt is not accepting output")
    db.commit()


def persist_proposal_result(
    db: sqlite3.Connection,
    *,
    proposal_id: str,
    attempt_id: str,
    reviewed_head: str,
    objective: str,
    proposed_action: str,
    summary: str,
    structured_result: Mapping[str, Any],
    findings: Sequence[Mapping[str, Any]],
    delta_available: bool | None = None,
    now: datetime | None = None,
) -> None:
    """Persist a proposal payload once; later edits belong to newer revisions."""
    moment = now or utc_now()
    stamp = iso(moment)
    try:
        _begin_immediate(db)
        row = db.execute(
            """
            SELECT p.head_sha, p.structured_result, p.state, a.state AS attempt_state
            FROM proposal_revisions p
            JOIN analysis_attempts a ON a.proposal_id = p.id
            WHERE p.id = ? AND a.id = ?
            """,
            (proposal_id, attempt_id),
        ).fetchone()
        if row is None:
            raise AutomationError("analysis attempt does not belong to proposal")
        if row["structured_result"] is not None:
            raise AutomationError("proposal result is already persisted")
        if str(row["head_sha"]) != reviewed_head:
            raise AutomationError("proposal output does not match its reviewed head")
        if str(row["state"]) not in ACTIVE_PROPOSAL_STATES:
            raise AutomationError("proposal was superseded before output persistence")
        if str(row["attempt_state"]) not in {"output_received", "ready_to_persist"}:
            raise AutomationError("analysis output is not ready to persist")
        seen_candidates: set[str] = set()
        for finding in findings:
            candidate_id = str(finding.get("candidate_id") or "").strip()
            if not candidate_id or candidate_id in seen_candidates:
                raise AutomationError("candidate findings require unique candidate IDs")
            seen_candidates.add(candidate_id)
            db.execute(
                """
                INSERT INTO proposal_findings(
                    proposal_id, candidate_id, category, severity, path, line,
                    start_line, side, start_side, body, blocking, evidence,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    candidate_id,
                    str(finding.get("category") or "other"),
                    str(finding.get("severity") or "medium"),
                    finding.get("path"),
                    finding.get("line"),
                    finding.get("start_line"),
                    finding.get("side"),
                    finding.get("start_side"),
                    str(finding.get("body") or ""),
                    int(bool(finding.get("blocking"))),
                    json.dumps(finding.get("evidence"), sort_keys=True)
                    if finding.get("evidence") is not None
                    else None,
                    stamp,
                ),
            )
        db.execute(
            """
            UPDATE proposal_revisions
            SET state = 'awaiting_decision', objective = ?, proposed_action = ?,
                summary = ?, delta_available = ?, structured_result = ?, ready_at = ?
            WHERE id = ?
            """,
            (
                objective,
                proposed_action,
                summary,
                int(delta_available) if delta_available is not None else None,
                json.dumps(structured_result, sort_keys=True),
                stamp,
                proposal_id,
            ),
        )
        db.execute(
            """
            UPDATE analysis_attempts
            SET state = 'completed', completed_at = ?, lease_expires_at = NULL
            WHERE id = ?
            """,
            (stamp, attempt_id),
        )
        db.execute(
            """
            UPDATE workflow_request_members
            SET state = 'awaiting_decision', reviewed_head = ?, updated_at = ?
            WHERE conversation_id = (
                SELECT conversation_id FROM proposal_revisions WHERE id = ?
            ) AND state NOT IN (
                'approved', 'comments_published', 'skipped',
                'merged_externally', 'closed_externally'
            )
            """,
            (reviewed_head, stamp, proposal_id),
        )
        _schedule_ready_reminder_locked(
            db,
            proposal_id,
            ready_at=moment,
            timezone_name=os.environ.get("TZ", "America/Mexico_City"),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise AutomationError("proposal candidate findings conflict") from exc
    except Exception:
        db.rollback()
        raise


def record_proposal_decision(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    revision_token: str,
    owner_user_id: str,
    action: str,
    idempotency_key: str,
    selected_candidate_ids: Sequence[str] = (),
    payload: Mapping[str, Any] | None = None,
) -> tuple[str, bool]:
    """Validate a revision-bound owner command and persist it exactly once."""
    normalized_action = action.strip().lower()
    if normalized_action not in {"approve", "publish", "skip", "edit", "dismiss"}:
        raise AutomationError("unsupported proposal decision")
    selected_json = json.dumps(list(selected_candidate_ids), sort_keys=True)
    payload_json = json.dumps(dict(payload or {}), sort_keys=True)
    try:
        _begin_immediate(db)
        existing = db.execute(
            """
            SELECT id, proposal_id, owner_user_id, action,
                   selected_candidate_ids, payload
            FROM proposal_decisions WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            proposal = db.execute(
                "SELECT conversation_id, revision_token FROM proposal_revisions WHERE id = ?",
                (existing["proposal_id"],),
            ).fetchone()
            matches = (
                proposal is not None
                and str(proposal["conversation_id"]) == conversation_id
                and str(proposal["revision_token"]) == revision_token
                and str(existing["owner_user_id"]) == owner_user_id
                and str(existing["action"]) == normalized_action
                and str(existing["selected_candidate_ids"]) == selected_json
                and str(existing["payload"]) == payload_json
            )
            if not matches:
                raise AutomationError("decision idempotency key has conflicting content")
            db.commit()
            return str(existing["id"]), False

        proposal = validate_proposal_revision(
            db,
            conversation_id=conversation_id,
            revision_token=revision_token,
            owner_user_id=owner_user_id,
        )
        decision_id = str(uuid.uuid4())
        stamp = iso(utc_now())
        db.execute(
            """
            INSERT INTO proposal_decisions(
                id, proposal_id, owner_user_id, action, selected_candidate_ids,
                payload, idempotency_key, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                proposal["id"],
                owner_user_id,
                normalized_action,
                selected_json,
                payload_json,
                idempotency_key,
                stamp,
            ),
        )
        if normalized_action in {"approve", "publish", "skip"}:
            db.execute(
                """
                INSERT INTO workflow_actions(
                    id, decision_id, action_type, expected_head, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    decision_id,
                    normalized_action,
                    proposal["head_sha"],
                    stamp,
                ),
            )
        db.commit()
        return decision_id, True
    except Exception:
        db.rollback()
        raise


def claim_decision_action(
    db: sqlite3.Connection,
    *,
    decision_id: str,
    claimant: str,
    now: datetime | None = None,
    lease_seconds: int = 300,
) -> tuple[str, str]:
    """Claim the deterministic side effect authorized by a proposal decision."""
    moment = now or utc_now()
    stamp = iso(moment)
    try:
        _begin_immediate(db)
        row = db.execute(
            """
            SELECT a.id, a.state, a.lease_expires_at, p.state AS proposal_state
            FROM workflow_actions a
            JOIN proposal_decisions d ON d.id = a.decision_id
            JOIN proposal_revisions p ON p.id = d.proposal_id
            WHERE a.decision_id = ?
            """,
            (decision_id,),
        ).fetchone()
        if row is None:
            raise AutomationError("decision has no executable action")
        action_id = str(row["id"])
        state = str(row["state"])
        if state in {"completed", "blocked", "failed"}:
            db.commit()
            return state, action_id
        if str(row["proposal_state"]) not in ACTIVE_PROPOSAL_STATES:
            raise AutomationError("proposal is no longer active")
        if state == "executing" and str(row["lease_expires_at"] or "") > stamp:
            db.commit()
            return "in_progress", action_id
        db.execute(
            """
            UPDATE workflow_actions
            SET state = 'executing', claimant = ?, lease_expires_at = ?
            WHERE id = ?
            """,
            (claimant, iso(moment + timedelta(seconds=lease_seconds)), action_id),
        )
        db.execute(
            "UPDATE proposal_decisions SET state = 'executing' WHERE id = ?",
            (decision_id,),
        )
        db.execute(
            """
            UPDATE proposal_revisions SET state = 'publishing'
            WHERE id = (SELECT proposal_id FROM proposal_decisions WHERE id = ?)
            """,
            (decision_id,),
        )
        db.commit()
        return "claimed", action_id
    except Exception:
        db.rollback()
        raise


def claim_slack_delivery(
    db: sqlite3.Connection,
    *,
    delivery_key: str,
    kind: str,
    workspace_id: str,
    channel_id: str,
    thread_ts: str | None,
    claimant: str,
    now: datetime | None = None,
    lease_seconds: int = 300,
    request_id: str | None = None,
    conversation_id: str | None = None,
    proposal_id: str | None = None,
    metadata_key: str | None = None,
) -> tuple[str, str]:
    """Claim a send-once Slack delivery using a stable workflow key."""
    moment = now or utc_now()
    stamp = iso(moment)
    expires = iso(moment + timedelta(seconds=lease_seconds))
    try:
        _begin_immediate(db)
        row = db.execute(
            "SELECT * FROM slack_deliveries WHERE delivery_key = ?",
            (delivery_key,),
        ).fetchone()
        if row is None:
            delivery_id = str(uuid.uuid4())
            db.execute(
                """
                INSERT INTO slack_deliveries(
                    id, delivery_key, kind, workspace_id, channel_id, thread_ts,
                    request_id, conversation_id, proposal_id, metadata_key,
                    state, claimant, lease_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sending', ?, ?, ?, ?)
                """,
                (
                    delivery_id,
                    delivery_key,
                    kind,
                    workspace_id,
                    channel_id,
                    thread_ts,
                    request_id,
                    conversation_id,
                    proposal_id,
                    metadata_key,
                    claimant,
                    expires,
                    stamp,
                    stamp,
                ),
            )
            db.commit()
            return delivery_id, "claimed"

        delivery_id = str(row["id"])
        identity = (
            str(row["kind"]),
            str(row["workspace_id"]),
            str(row["channel_id"]),
            row["thread_ts"],
        )
        if identity != (kind, workspace_id, channel_id, thread_ts):
            raise AutomationError("delivery key is bound to another destination")
        state = str(row["state"])
        if state == "sent":
            db.commit()
            return delivery_id, "sent"
        if state == "blocked":
            db.commit()
            return delivery_id, "blocked"
        if state == "sending" and str(row["lease_expires_at"] or "") > stamp:
            db.commit()
            return delivery_id, "in_progress"
        db.execute(
            """
            UPDATE slack_deliveries
            SET state = 'sending', claimant = ?, lease_expires_at = ?,
                error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (claimant, expires, stamp, delivery_id),
        )
        db.commit()
        return delivery_id, "claimed"
    except Exception:
        db.rollback()
        raise


def complete_slack_delivery(
    db: sqlite3.Connection,
    *,
    delivery_id: str,
    claimant: str,
    message_ts: str,
    now: datetime | None = None,
) -> None:
    cursor = db.execute(
        """
        UPDATE slack_deliveries
        SET state = 'sent', message_ts = ?, lease_expires_at = NULL,
            updated_at = ?, error = NULL
        WHERE id = ? AND claimant = ? AND state = 'sending'
        """,
        (message_ts, iso(now or utc_now()), delivery_id, claimant),
    )
    if cursor.rowcount != 1:
        db.rollback()
        raise AutomationError("Slack delivery is not owned by claimant")
    db.commit()


def block_slack_delivery(
    db: sqlite3.Connection,
    *,
    delivery_id: str,
    claimant: str,
    error: str,
    now: datetime | None = None,
) -> None:
    cursor = db.execute(
        """
        UPDATE slack_deliveries
        SET state = 'blocked', error = ?, lease_expires_at = NULL, updated_at = ?
        WHERE id = ? AND claimant = ? AND state = 'sending'
        """,
        (error, iso(now or utc_now()), delivery_id, claimant),
    )
    if cursor.rowcount != 1:
        db.rollback()
        raise AutomationError("Slack delivery is not owned by claimant")
    db.commit()


def schedule_proposal_reminder(
    db: sqlite3.Connection,
    proposal_id: str,
    *,
    due_at: datetime,
    now: datetime | None = None,
) -> str:
    """Create or reset the bounded reminder schedule for a proposal revision."""
    stamp = iso(now or utc_now())
    due = iso(due_at)
    reminder_id = str(uuid.uuid4())
    try:
        _begin_immediate(db)
        proposal = db.execute(
            "SELECT state FROM proposal_revisions WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if proposal is None or str(proposal["state"]) not in ACTIVE_PROPOSAL_STATES:
            raise AutomationError("cannot schedule a reminder for an inactive proposal")
        row = db.execute(
            "SELECT id FROM proposal_reminders WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            db.execute(
                """
                INSERT INTO proposal_reminders(
                    id, proposal_id, stage, state, due_at, created_at, updated_at
                ) VALUES (?, ?, 1, 'scheduled', ?, ?, ?)
                """,
                (reminder_id, proposal_id, due, stamp, stamp),
            )
        else:
            reminder_id = str(row["id"])
            db.execute(
                """
                UPDATE proposal_reminders
                SET stage = 1, state = 'scheduled', due_at = ?, claimant = NULL,
                    lease_expires_at = NULL, delivery_id = NULL,
                    last_sent_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (due, stamp, reminder_id),
            )
        db.commit()
        return reminder_id
    except Exception:
        db.rollback()
        raise


def _schedule_ready_reminder_locked(
    db: sqlite3.Connection,
    proposal_id: str,
    *,
    ready_at: datetime,
    timezone_name: str,
) -> str:
    """Insert the first bounded reminder while the proposal transaction is open."""
    stamp = iso(ready_at)
    due = iso(add_working_minutes(ready_at, 120, timezone_name))
    reminder_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO proposal_reminders(
            id, proposal_id, stage, state, due_at, created_at, updated_at
        ) VALUES (?, ?, 1, 'scheduled', ?, ?, ?)
        ON CONFLICT(proposal_id) DO UPDATE SET
            stage = 1, state = 'scheduled', due_at = excluded.due_at,
            claimant = NULL, lease_expires_at = NULL, delivery_id = NULL,
            last_sent_at = NULL, updated_at = excluded.updated_at
        """,
        (reminder_id, proposal_id, due, stamp, stamp),
    )
    row = db.execute(
        "SELECT id FROM proposal_reminders WHERE proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise AutomationError("failed to schedule proposal reminder")
    return str(row["id"])


def claim_due_reminders(
    db: sqlite3.Connection,
    *,
    claimant: str,
    now: datetime | None = None,
    limit: int = 25,
    lease_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Claim due reminders in one write transaction for overlapping sweeps."""
    if limit < 1:
        return []
    moment = now or utc_now()
    stamp = iso(moment)
    expires = iso(moment + timedelta(seconds=lease_seconds))
    try:
        _begin_immediate(db)
        db.execute(
            """
            UPDATE proposal_reminders
            SET state = 'scheduled', claimant = NULL, lease_expires_at = NULL,
                updated_at = ?
            WHERE state = 'claimed' AND lease_expires_at <= ?
            """,
            (stamp, stamp),
        )
        rows = db.execute(
            """
            SELECT r.*, p.conversation_id, p.revision_token, p.head_sha,
                   c.workspace_id, c.owner_user_id, c.dm_channel_id, c.thread_ts,
                   c.repo, c.pr_number, c.pr_url
            FROM proposal_reminders r
            JOIN proposal_revisions p ON p.id = r.proposal_id
            JOIN workflow_pr_conversations c ON c.id = p.conversation_id
            WHERE r.state = 'scheduled' AND r.due_at <= ?
              AND p.state = 'awaiting_decision'
            ORDER BY r.due_at, r.id
            LIMIT ?
            """,
            (stamp, limit),
        ).fetchall()
        claimed: list[dict[str, Any]] = []
        for row in rows:
            cursor = db.execute(
                """
                UPDATE proposal_reminders
                SET state = 'claimed', claimant = ?, lease_expires_at = ?,
                    updated_at = ? WHERE id = ? AND state = 'scheduled'
                """,
                (claimant, expires, stamp, row["id"]),
            )
            if cursor.rowcount == 1:
                claimed.append(_row_dict(row))
        db.commit()
        return claimed
    except Exception:
        db.rollback()
        raise


def complete_reminder_claim(
    db: sqlite3.Connection,
    *,
    reminder_id: str,
    claimant: str,
    delivery_id: str,
    next_due_at: datetime | None,
    now: datetime | None = None,
) -> None:
    """Advance first reminder to second, then make it digest-only."""
    moment = now or utc_now()
    row = db.execute(
        """
        SELECT stage FROM proposal_reminders
        WHERE id = ? AND claimant = ? AND state = 'claimed'
        """,
        (reminder_id, claimant),
    ).fetchone()
    if row is None:
        raise AutomationError("reminder is not owned by claimant")
    if next_due_at is None:
        state = "digest_only"
        due = None
        stage = max(2, int(row["stage"]))
    else:
        state = "scheduled"
        due = iso(next_due_at)
        stage = int(row["stage"]) + 1
    db.execute(
        """
        UPDATE proposal_reminders
        SET stage = ?, state = ?, due_at = ?, claimant = NULL,
            lease_expires_at = NULL, delivery_id = ?, last_sent_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            stage,
            state,
            due,
            delivery_id,
            iso(moment),
            iso(moment),
            reminder_id,
        ),
    )
    db.commit()


def _release_reminder_claim(
    db: sqlite3.Connection,
    *,
    reminder_id: str,
    claimant: str,
    now: datetime,
) -> None:
    db.execute(
        """
        UPDATE proposal_reminders
        SET state = 'scheduled', claimant = NULL, lease_expires_at = NULL,
            updated_at = ?
        WHERE id = ? AND claimant = ? AND state = 'claimed'
        """,
        (iso(now), reminder_id, claimant),
    )
    db.commit()


def _block_claimed_reminder(
    db: sqlite3.Connection,
    *,
    reminder_id: str,
    claimant: str,
    now: datetime,
) -> None:
    db.execute(
        """
        UPDATE proposal_reminders
        SET state = 'blocked', due_at = NULL, claimant = NULL,
            lease_expires_at = NULL, updated_at = ?
        WHERE id = ? AND claimant = ? AND state = 'claimed'
        """,
        (iso(now), reminder_id, claimant),
    )
    db.commit()


def _prepare_reminder_delivery(
    db: sqlite3.Connection,
    *,
    reminder_id: str,
    claimant: str,
    now: datetime,
    lease_seconds: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """Bind one claimed reminder to one exact send; never replay ambiguity."""
    stamp = iso(now)
    expires = iso(now + timedelta(seconds=lease_seconds))
    try:
        _begin_immediate(db)
        row = db.execute(
            """
            SELECT r.*, p.conversation_id, p.revision_token, p.head_sha, p.summary,
                   c.workspace_id, c.dm_channel_id, c.thread_ts,
                   c.repo, c.pr_number, c.pr_url
            FROM proposal_reminders r
            JOIN proposal_revisions p ON p.id = r.proposal_id
            JOIN workflow_pr_conversations c ON c.id = p.conversation_id
            WHERE r.id = ? AND r.claimant = ? AND r.state = 'claimed'
              AND p.state = 'awaiting_decision'
            """,
            (reminder_id, claimant),
        ).fetchone()
        if row is None:
            db.commit()
            return None, "reminder is no longer awaiting a decision"
        if not row["dm_channel_id"] or not row["thread_ts"]:
            db.execute(
                """
                UPDATE proposal_reminders
                SET state = 'blocked', due_at = NULL, claimant = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (stamp, reminder_id),
            )
            db.commit()
            return None, "persisted DM channel/thread route is missing"

        stage = int(row["stage"])
        delivery_key = f"review-reminder:{row['proposal_id']}:{stage}"
        delivery = db.execute(
            "SELECT * FROM slack_deliveries WHERE delivery_key = ?",
            (delivery_key,),
        ).fetchone()
        if delivery is not None:
            # A send was previously handed to Slack without an acknowledgement.
            # Reposting could duplicate it, so require operator reconciliation.
            db.execute(
                """
                UPDATE slack_deliveries
                SET state = 'blocked', lease_expires_at = NULL,
                    error = 'ambiguous prior reminder send; reconcile before retry',
                    updated_at = ?
                WHERE id = ? AND state != 'sent'
                """,
                (stamp, delivery["id"]),
            )
            db.execute(
                """
                UPDATE proposal_reminders
                SET state = 'blocked', due_at = NULL, claimant = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (stamp, reminder_id),
            )
            db.commit()
            return None, "ambiguous prior reminder send"

        delivery_id = str(uuid.uuid4())
        db.execute(
            """
            INSERT INTO slack_deliveries(
                id, delivery_key, kind, workspace_id, channel_id, thread_ts,
                conversation_id, proposal_id, metadata_key, state, claimant,
                lease_expires_at, created_at, updated_at
            ) VALUES (?, ?, 'review_reminder', ?, ?, ?, ?, ?, ?, 'sending',
                      ?, ?, ?, ?)
            """,
            (
                delivery_id,
                delivery_key,
                row["workspace_id"],
                row["dm_channel_id"],
                row["thread_ts"],
                row["conversation_id"],
                row["proposal_id"],
                delivery_key,
                claimant,
                expires,
                stamp,
                stamp,
            ),
        )
        db.execute(
            "UPDATE proposal_reminders SET delivery_id = ?, updated_at = ? WHERE id = ?",
            (delivery_id, stamp, reminder_id),
        )
        prefix = "Reminder" if stage == 1 else "Final private reminder"
        suffix = (
            ""
            if stage == 1
            else " After this reminder, the proposal will appear only in the daily digest."
        )
        text = (
            f"{prefix}: {row['repo']}#{row['pr_number']} proposal "
            f"{row['revision_token']} is awaiting your decision.{suffix} "
            f"Reply in this thread with `approve {row['revision_token']}`, "
            f"`publish {row['revision_token']} <candidate IDs>`, or "
            f"`skip {row['revision_token']}`."
        )
        item = {
            "reminder_id": reminder_id,
            "delivery_id": delivery_id,
            "proposal_id": str(row["proposal_id"]),
            "revision_token": str(row["revision_token"]),
            "stage": stage,
            "workspace_id": str(row["workspace_id"]),
            "channel_id": str(row["dm_channel_id"]),
            "thread_ts": str(row["thread_ts"]),
            "repo": str(row["repo"]),
            "pr_number": int(row["pr_number"]),
            "pr_url": str(row["pr_url"]),
            "text": text,
        }
        db.commit()
        return item, None
    except Exception:
        db.rollback()
        raise


def ack_reminder_delivery(
    db_path: str | None,
    *,
    reminder_id: str,
    delivery_id: str,
    claimant: str,
    message_ts: str,
    timezone_name: str = "America/Mexico_City",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Atomically record Slack's receipt and advance the bounded schedule."""
    moment = now or utc_now()
    stamp = iso(moment)
    with connect_db(db_path) as db:
        try:
            _begin_immediate(db)
            row = db.execute(
                """
                SELECT r.stage, r.proposal_id
                FROM proposal_reminders r
                JOIN slack_deliveries d ON d.id = r.delivery_id
                WHERE r.id = ? AND r.delivery_id = ? AND r.claimant = ?
                  AND r.state = 'claimed' AND d.state = 'sending'
                  AND d.claimant = ?
                """,
                (reminder_id, delivery_id, claimant, claimant),
            ).fetchone()
            if row is None:
                raise AutomationError("reminder delivery is not owned by claimant")
            stage = int(row["stage"])
            if stage == 1:
                next_stage = 2
                state = "scheduled"
                due = iso(next_weekday_start(moment, timezone_name))
            else:
                next_stage = max(2, stage)
                state = "digest_only"
                due = None
            db.execute(
                """
                UPDATE slack_deliveries
                SET state = 'sent', message_ts = ?, lease_expires_at = NULL,
                    error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (message_ts, stamp, delivery_id),
            )
            db.execute(
                """
                UPDATE proposal_reminders
                SET stage = ?, state = ?, due_at = ?, claimant = NULL,
                    lease_expires_at = NULL, last_sent_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_stage, state, due, stamp, stamp, reminder_id),
            )
            db.commit()
            return {
                "status": "acknowledged",
                "reminder_id": reminder_id,
                "delivery_id": delivery_id,
                "proposal_id": str(row["proposal_id"]),
                "stage": next_stage,
                "state": state,
                "due_at": due,
            }
        except Exception:
            db.rollback()
            raise


def block_reminder_delivery(
    db_path: str | None,
    *,
    reminder_id: str,
    delivery_id: str,
    claimant: str,
    error: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist a definitive Slack send failure without scheduling another nudge."""
    stamp = iso(now or utc_now())
    with connect_db(db_path) as db:
        try:
            _begin_immediate(db)
            delivery = db.execute(
                """
                SELECT d.id FROM slack_deliveries d
                JOIN proposal_reminders r ON r.delivery_id = d.id
                WHERE r.id = ? AND d.id = ? AND r.claimant = ?
                  AND r.state = 'claimed' AND d.claimant = ?
                  AND d.state = 'sending'
                """,
                (reminder_id, delivery_id, claimant, claimant),
            ).fetchone()
            if delivery is None:
                raise AutomationError("reminder delivery is not owned by claimant")
            db.execute(
                """
                UPDATE slack_deliveries
                SET state = 'blocked', error = ?, lease_expires_at = NULL,
                    updated_at = ? WHERE id = ?
                """,
                (error[:4000], stamp, delivery_id),
            )
            db.execute(
                """
                UPDATE proposal_reminders
                SET state = 'blocked', due_at = NULL, claimant = NULL,
                    lease_expires_at = NULL, updated_at = ? WHERE id = ?
                """,
                (stamp, reminder_id),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"status": "blocked", "reminder_id": reminder_id, "delivery_id": delivery_id}


def _reclaim_expired_analysis_live(
    db: sqlite3.Connection,
    *,
    now: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows = db.execute(
        """
        SELECT DISTINCT c.repo, c.pr_number, c.pr_url, c.id AS conversation_id
        FROM analysis_attempts a
        JOIN proposal_revisions p ON p.id = a.proposal_id
        JOIN workflow_pr_conversations c ON c.id = p.conversation_id
        WHERE a.state IN ('running', 'output_received')
          AND a.lease_expires_at <= ?
        ORDER BY c.repo, c.pr_number
        """,
        (iso(now),),
    ).fetchall()
    current_heads: dict[tuple[str, int], str] = {}
    errors: list[dict[str, str]] = []
    for row in rows:
        try:
            pr = load_pr(str(row["pr_url"]))
            if pr.state in {"MERGED", "CLOSED"}:
                finalize_external_pr(
                    db, conversation_id=str(row["conversation_id"]), pr=pr
                )
            else:
                current_heads[(str(row["repo"]), int(row["pr_number"]))] = pr.head_sha
        except (AutomationError, OSError, subprocess.TimeoutExpired) as exc:
            errors.append({"pr_url": str(row["pr_url"]), "error": str(exc)})
    reclaimed = reclaim_expired_analysis(db, current_heads=current_heads, now=now)
    return reclaimed, errors


def reminder_sweep(
    db_path: str | None = None,
    *,
    claimant: str,
    timezone_name: str = "America/Mexico_City",
    now: datetime | None = None,
    limit: int = 25,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    """Claim due private reminders and emit exact persisted Slack delivery work."""
    moment = now or utc_now()
    deliveries: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    lifecycle: list[dict[str, Any]] = []
    with connect_db(db_path) as db:
        reclaimed, reclaim_errors = _reclaim_expired_analysis_live(db, now=moment)
        errors.extend(reclaim_errors)
        claims = claim_due_reminders(
            db,
            claimant=claimant,
            now=moment,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        for claim in claims:
            reminder_id = str(claim["id"])
            try:
                pr = load_pr(str(claim["pr_url"]))
            except (AutomationError, OSError, subprocess.TimeoutExpired) as exc:
                _release_reminder_claim(
                    db, reminder_id=reminder_id, claimant=claimant, now=moment
                )
                errors.append({"pr_url": str(claim["pr_url"]), "error": str(exc)})
                continue
            if pr.state in {"MERGED", "CLOSED"}:
                lifecycle.append(
                    finalize_external_pr(
                        db,
                        conversation_id=str(claim["conversation_id"]),
                        pr=pr,
                    )
                )
                continue
            if pr.head_sha != str(claim["head_sha"]):
                _block_claimed_reminder(
                    db, reminder_id=reminder_id, claimant=claimant, now=moment
                )
                try:
                    lifecycle.append(
                        re_review_current_head(
                            db,
                            conversation_id=str(claim["conversation_id"]),
                            pr=pr,
                            login=reviewer_login(),
                            claimant=f"{claimant}:re-review",
                        )
                    )
                except (AutomationError, OSError, subprocess.TimeoutExpired) as exc:
                    errors.append({"pr_url": pr.url, "error": str(exc)})
                continue
            item, reason = _prepare_reminder_delivery(
                db,
                reminder_id=reminder_id,
                claimant=claimant,
                now=moment,
                lease_seconds=lease_seconds,
            )
            if item is not None:
                deliveries.append(item)
            else:
                blocked.append({"reminder_id": reminder_id, "reason": reason})
    return {
        "status": "ready",
        "claimant": claimant,
        "deliveries": deliveries,
        "delivery_count": len(deliveries),
        "blocked": blocked,
        "blocked_count": len(blocked),
        "reclaimed_analysis": reclaimed,
        "lifecycle": lifecycle,
        "errors": errors,
    }


def reclaim_expired_analysis(
    db: sqlite3.Connection,
    *,
    current_heads: Mapping[tuple[str, int], str],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Recover expired work only after comparing its PR's current head."""
    moment = now or utc_now()
    stamp = iso(moment)
    results: list[dict[str, Any]] = []
    try:
        _begin_immediate(db)
        rows = db.execute(
            """
            SELECT a.*, p.conversation_id, p.revision_token, p.state AS proposal_state,
                   p.head_sha, c.repo, c.pr_number
            FROM analysis_attempts a
            JOIN proposal_revisions p ON p.id = a.proposal_id
            JOIN workflow_pr_conversations c ON c.id = p.conversation_id
            WHERE a.state IN ('running', 'output_received')
              AND a.lease_expires_at <= ?
            ORDER BY c.repo, c.pr_number, a.started_at, a.id
            """,
            (stamp,),
        ).fetchall()
        for row in rows:
            key = (str(row["repo"]), int(row["pr_number"]))
            current_head = current_heads.get(key)
            if not current_head:
                continue
            attempt_id = str(row["id"])
            proposal_id = str(row["proposal_id"])
            reviewed_head = str(row["head_sha"])
            if current_head != reviewed_head:
                db.execute(
                    """
                    UPDATE analysis_attempts
                    SET state = 'abandoned_head_changed', completed_at = ?,
                        lease_expires_at = NULL,
                        error = 'PR head changed while analysis was leased'
                    WHERE id = ?
                    """,
                    (stamp, attempt_id),
                )
                next_proposal = _create_proposal_revision_locked(
                    db,
                    str(row["conversation_id"]),
                    head_sha=current_head,
                    baseline_head_sha=reviewed_head,
                    state="queued",
                    now=moment,
                )
                results.append(
                    {
                        "attempt_id": attempt_id,
                        "proposal_id": proposal_id,
                        "outcome": "head_changed",
                        "new_proposal_id": next_proposal["id"],
                        "current_head": current_head,
                    }
                )
            elif str(row["state"]) == "output_received":
                db.execute(
                    """
                    UPDATE analysis_attempts
                    SET state = 'ready_to_persist', lease_expires_at = NULL
                    WHERE id = ?
                    """,
                    (attempt_id,),
                )
                db.execute(
                    "UPDATE proposal_revisions SET state = 'output_pending' WHERE id = ?",
                    (proposal_id,),
                )
                results.append(
                    {
                        "attempt_id": attempt_id,
                        "proposal_id": proposal_id,
                        "outcome": "persist_output",
                    }
                )
            else:
                db.execute(
                    """
                    UPDATE analysis_attempts
                    SET state = 'expired', completed_at = ?, lease_expires_at = NULL,
                        error = 'analysis lease expired before output'
                    WHERE id = ?
                    """,
                    (stamp, attempt_id),
                )
                db.execute(
                    "UPDATE proposal_revisions SET state = 'queued' WHERE id = ?",
                    (proposal_id,),
                )
                results.append(
                    {
                        "attempt_id": attempt_id,
                        "proposal_id": proposal_id,
                        "outcome": "retry",
                    }
                )
        db.commit()
        return results
    except Exception:
        db.rollback()
        raise


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


def invoke_codex(
    pr: PullRequest,
    *,
    run_id: str,
    baseline_head_sha: str | None = None,
    prior_findings: Sequence[Mapping[str, Any]] = (),
    compare_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    host = paseo_host()
    workspace = os.environ.get("REVIEW_MONOREPO_ROOT", "").strip()
    if not workspace:
        raise AutomationError("REVIEW_MONOREPO_ROOT is required")
    timeout_value = os.environ.get("REVIEW_PASEO_TIMEOUT", "45m")
    schema = os.environ.get("REVIEW_RESULT_SCHEMA", DEFAULT_SCHEMA)
    prompt = (
        "$pr-reviewer Analyze exactly this pull request and return a read-only proposal: "
        f"{pr.url}\n"
        "Do not discover or review any other pull request. Do not submit a review, approve, "
        "comment, merge, close, or call any GitHub write endpoint. Bind the proposal to head "
        f"{pr.head_sha}. Include related Linear context when it can be derived and fetched. "
        "Return only the structured result required by the supplied output schema with "
        "published set to false."
    )
    if baseline_head_sha is not None:
        prior_payload = [
            {
                key: finding.get(key)
                for key in (
                    "candidate_id",
                    "category",
                    "severity",
                    "path",
                    "line",
                    "start_line",
                    "side",
                    "start_side",
                    "body",
                    "evidence",
                    "blocking",
                )
            }
            for finding in prior_findings
        ]
        comparison = dict(compare_context or {"status": "unavailable"})
        prompt += (
            "\nThis is a re-review in the existing PR conversation. Compare the exact "
            f"baseline {baseline_head_sha} with target {pr.head_sha}. The persisted prior "
            "candidate set and comparison preflight follow as JSON. Preserve still-open "
            "candidate IDs and classify addressed, still-open, and new findings. "
            f"PRIOR_FINDINGS={json.dumps(prior_payload, sort_keys=True)}\n"
            f"COMPARE_CONTEXT={json.dumps(comparison, sort_keys=True)}"
        )
        if str(comparison.get("status")) == "unavailable":
            prompt += (
                "\nThe exact comparison could not be established. Perform a full review of "
                "the latest head, set delta.status to unavailable, label the delta summary "
                "with 'delta unavailable', and do not guess which prior findings were addressed."
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


def validate_proposal_result(result: Mapping[str, Any], pr: PullRequest) -> None:
    validate_result(result, pr)
    if result.get("published") is not False:
        raise AutomationError("Codex result must be a read-only unpublished proposal")
    if str(result.get("event") or "") not in {"APPROVE", "COMMENT"}:
        raise AutomationError("Codex proposal event is invalid")
    if not str(result.get("objective") or "").strip():
        raise AutomationError("Codex proposal objective is required")
    if not isinstance(result.get("findings"), list):
        raise AutomationError("Codex proposal findings must be a list")


def validate_delta_result(
    result: Mapping[str, Any],
    pr: PullRequest,
    *,
    baseline_head_sha: str | None,
    prior_findings: Sequence[Mapping[str, Any]],
    compare_context: Mapping[str, Any] | None,
) -> None:
    """Validate Codex lineage so an inconsistent delta never becomes actionable."""
    validate_proposal_result(result, pr)
    actual_baseline = result.get("baseline_head_sha")
    if (str(actual_baseline) if actual_baseline is not None else None) != baseline_head_sha:
        raise AutomationError("Codex result baseline SHA does not match persisted lineage")
    delta = result.get("delta")
    if not isinstance(delta, Mapping):
        raise AutomationError("Codex proposal delta is required")
    status = str(delta.get("status") or "")
    if baseline_head_sha is None:
        if status != "initial":
            raise AutomationError("initial proposal must have initial delta status")
        return

    expected_status = (
        "available"
        if str((compare_context or {}).get("status")) == "available"
        else "unavailable"
    )
    if status != expected_status:
        raise AutomationError(
            f"Codex delta status {status or 'missing'} does not match {expected_status} comparison"
        )
    groups: dict[str, list[str]] = {}
    for key in (
        "addressed_candidate_ids",
        "still_open_candidate_ids",
        "new_candidate_ids",
    ):
        value = delta.get(key)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or re.fullmatch(CANDIDATE_TOKEN_PATTERN, item) is None
            for item in value
        ):
            raise AutomationError(f"Codex delta {key} is invalid")
        if len(value) != len(set(value)):
            raise AutomationError(f"Codex delta {key} contains duplicates")
        groups[key] = value
    classified = [item for value in groups.values() for item in value]
    if len(classified) != len(set(classified)):
        raise AutomationError("Codex delta candidate classifications overlap")

    prior_ids = {str(item.get("candidate_id") or "") for item in prior_findings}
    current_ids = {
        str(item.get("candidate_id") or "") for item in result.get("findings") or []
    }
    if status == "unavailable":
        if groups["addressed_candidate_ids"] or groups["still_open_candidate_ids"]:
            raise AutomationError("unavailable delta must not guess prior finding outcomes")
        summary = str(delta.get("summary") or "").lower()
        if "delta unavailable" not in summary:
            raise AutomationError("unavailable delta must be clearly labeled")
        return

    addressed = set(groups["addressed_candidate_ids"])
    still_open = set(groups["still_open_candidate_ids"])
    new = set(groups["new_candidate_ids"])
    if addressed | still_open != prior_ids:
        raise AutomationError("available delta must classify every prior finding")
    if still_open | new != current_ids:
        raise AutomationError("available delta must classify every current finding")
    if not still_open <= prior_ids or new & prior_ids:
        raise AutomationError("available delta does not preserve prior candidate identity")
    highest_prior = max(
        (int(item[1:]) for item in prior_ids if re.fullmatch(CANDIDATE_TOKEN_PATTERN, item)),
        default=0,
    )
    if any(int(item[1:]) <= highest_prior for item in new):
        raise AutomationError("new delta candidates must follow prior candidate IDs")


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


def proposal_context(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    revision_token: str | None = None,
) -> dict[str, Any]:
    """Render persisted proposal state, including durable edits and dismissals."""
    if revision_token is None:
        proposal = active_proposal(db, conversation_id)
        if proposal is None:
            raise AutomationError("PR conversation has no active proposal")
    else:
        row = db.execute(
            "SELECT * FROM proposal_revisions WHERE conversation_id = ? "
            "AND revision_token = ?",
            (conversation_id, revision_token),
        ).fetchone()
        if row is None:
            raise AutomationError("unknown proposal revision")
        proposal = _row_dict(row)

    findings = [
        _row_dict(row)
        for row in db.execute(
            "SELECT * FROM proposal_findings WHERE proposal_id = ? ORDER BY id",
            (proposal["id"],),
        ).fetchall()
    ]
    finding_by_id = {str(item["candidate_id"]): item for item in findings}
    for item in finding_by_id.values():
        item["active"] = True
        item["edited"] = False
    decisions = db.execute(
        "SELECT action, selected_candidate_ids, payload FROM proposal_decisions "
        "WHERE proposal_id = ? AND action IN ('edit', 'dismiss') "
        "AND state IN ('accepted', 'completed') ORDER BY created_at, id",
        (proposal["id"],),
    ).fetchall()
    for decision in decisions:
        selected = json.loads(str(decision["selected_candidate_ids"] or "[]"))
        payload = json.loads(str(decision["payload"] or "{}"))
        if str(decision["action"]) == "dismiss":
            for candidate_id in selected:
                if candidate_id in finding_by_id:
                    finding_by_id[candidate_id]["active"] = False
        elif selected and selected[0] in finding_by_id:
            finding_by_id[selected[0]]["body"] = str(payload.get("body") or "")
            finding_by_id[selected[0]]["edited"] = True
    result = dict(proposal)
    result["findings"] = list(finding_by_id.values())
    structured = json.loads(str(proposal["structured_result"])) if proposal.get("structured_result") else {}
    result["delta"] = structured.get("delta") or {
        "status": "pending",
        "summary": None,
        "addressed_candidate_ids": [],
        "still_open_candidate_ids": [],
        "new_candidate_ids": [],
    }
    result["limitations"] = list(structured.get("limitations") or [])
    return result


def thread_context(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    dm_channel_id: str,
    thread_ts: str,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    conversation = conversation_for_slack_thread(
        db,
        workspace_id=workspace_id,
        dm_channel_id=dm_channel_id,
        thread_ts=thread_ts,
    )
    if conversation is None:
        raise AutomationError("Slack thread is not mapped to a PR conversation")
    if owner_user_id is not None and str(conversation["owner_user_id"]) != owner_user_id:
        raise AutomationError("decision owner does not match the PR conversation")
    if conversation.get("proposal_id") is None:
        latest = db.execute(
            "SELECT id, revision_token, head_sha, state FROM proposal_revisions "
            "WHERE conversation_id = ? ORDER BY revision_number DESC LIMIT 1",
            (conversation["id"],),
        ).fetchone()
        if latest is None:
            raise AutomationError("PR conversation has no proposal")
        conversation["proposal_id"] = latest["id"]
        conversation["revision_token"] = latest["revision_token"]
        conversation["proposal_head"] = latest["head_sha"]
        conversation["proposal_state"] = latest["state"]
    context = proposal_context(
        db,
        conversation_id=str(conversation["id"]),
        revision_token=str(conversation["revision_token"]),
    )
    context["conversation"] = conversation
    return context


def _proposal_for_baseline(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    baseline_head_sha: str | None,
) -> dict[str, Any] | None:
    if baseline_head_sha is None:
        return None
    row = db.execute(
        """
        SELECT * FROM proposal_revisions
        WHERE conversation_id = ? AND head_sha = ? AND structured_result IS NOT NULL
        ORDER BY revision_number DESC LIMIT 1
        """,
        (conversation_id, baseline_head_sha),
    ).fetchone()
    return _row_dict(row) if row is not None else None


def _queue_latest_head_after_drift(
    db: sqlite3.Connection,
    *,
    proposal: Mapping[str, Any],
    attempt_id: str,
    latest_pr: PullRequest,
) -> dict[str, Any]:
    stamp = iso(utc_now())
    baseline = _effective_reviewed_baseline(proposal)
    try:
        _begin_immediate(db)
        db.execute(
            """
            UPDATE analysis_attempts
            SET state = 'abandoned_head_changed', completed_at = ?,
                lease_expires_at = NULL,
                error = 'PR head changed before proposal persistence'
            WHERE id = ?
            """,
            (stamp, attempt_id),
        )
        queued = _create_proposal_revision_locked(
            db,
            str(proposal["conversation_id"]),
            head_sha=latest_pr.head_sha,
            baseline_head_sha=baseline,
            state="queued",
            now=utc_now(),
        )
        db.commit()
        return queued
    except Exception:
        db.rollback()
        raise


def analyze_proposal_revision(
    db: sqlite3.Connection,
    *,
    pr: PullRequest,
    login: str,
    proposal: Mapping[str, Any],
    claimant: str,
) -> dict[str, Any]:
    """Run one read-only analysis and persist it only if the target head stays current."""
    conversation_id = str(proposal["conversation_id"])
    baseline = (
        str(proposal["baseline_head_sha"])
        if proposal.get("baseline_head_sha")
        else None
    )
    baseline_proposal = _proposal_for_baseline(
        db,
        conversation_id=conversation_id,
        baseline_head_sha=baseline,
    )
    prior_findings: list[dict[str, Any]] = []
    if baseline_proposal is not None:
        prior_context = proposal_context(
            db,
            conversation_id=conversation_id,
            revision_token=str(baseline_proposal["revision_token"]),
        )
        prior_findings = list(prior_context["findings"])
    compare_context = (
        github_compare_context(pr, baseline) if baseline is not None else None
    )
    claim_state, attempt_id = claim_analysis_attempt(
        db, str(proposal["id"]), claimant=claimant
    )
    if claim_state != "claimed":
        return {
            "url": pr.url,
            "status": "in_progress",
            "conversation_id": conversation_id,
            "proposal_id": str(proposal["id"]),
            "revision_token": str(proposal["revision_token"]),
            "head_sha": pr.head_sha,
        }
    cleanup_warnings: list[str] = []
    try:
        result = invoke_codex(
            pr,
            run_id=str(proposal["id"]),
            baseline_head_sha=baseline,
            prior_findings=prior_findings,
            compare_context=compare_context,
        )
        if pr.author_login.lower() == login.lower() and result.get("event") == "APPROVE":
            result = dict(result)
            result["event"] = "COMMENT"
            result["summary"] = (
                str(result.get("summary") or "")
                + " Self-authored pull requests cannot be approved by this reviewer."
            ).strip()
        validate_delta_result(
            result,
            pr,
            baseline_head_sha=baseline,
            prior_findings=prior_findings,
            compare_context=compare_context,
        )
        record_analysis_output(db, attempt_id=attempt_id, output=result)

        latest_pr = load_pr(pr.url)
        if (
            latest_pr.repo.lower() != pr.repo.lower()
            or latest_pr.number != pr.number
        ):
            raise AutomationError("GitHub returned a different PR during proposal analysis")
        if latest_pr.state in {"MERGED", "CLOSED"}:
            return finalize_external_pr(
                db,
                conversation_id=conversation_id,
                pr=latest_pr,
            )
        if latest_pr.head_sha != pr.head_sha:
            queued = _queue_latest_head_after_drift(
                db,
                proposal=proposal,
                attempt_id=attempt_id,
                latest_pr=latest_pr,
            )
            return {
                "url": latest_pr.url,
                "status": "head_changed_during_analysis",
                "conversation_id": conversation_id,
                "superseded_head": pr.head_sha,
                "re_review": {
                    "status": "queued",
                    "proposal_id": str(queued["id"]),
                    "revision_token": str(queued["revision_token"]),
                    "baseline_head_sha": queued["baseline_head_sha"],
                    "head_sha": latest_pr.head_sha,
                },
            }

        delta = result.get("delta") or {}
        persist_proposal_result(
            db,
            proposal_id=str(proposal["id"]),
            attempt_id=attempt_id,
            reviewed_head=pr.head_sha,
            objective=str(result["objective"]),
            proposed_action=str(result["event"]).lower(),
            summary=str(result["summary"]),
            structured_result=result,
            findings=list(result.get("findings") or []),
            delta_available=(
                str(delta.get("status")) == "available"
                if str(delta.get("status")) != "initial"
                else None
            ),
        )
        return {
            "url": pr.url,
            "status": "awaiting_decision",
            "conversation_id": conversation_id,
            "proposal_id": str(proposal["id"]),
            "revision_token": str(proposal["revision_token"]),
            "baseline_head_sha": baseline,
            "head_sha": pr.head_sha,
            "objective": result["objective"],
            "event": result["event"],
            "summary": result["summary"],
            "finding_count": len(result.get("findings") or []),
            "delta_status": str(delta.get("status") or "initial"),
            "delta": dict(delta),
        }
    finally:
        cleanup_warnings.extend(cleanup_paseo_review_agent(str(proposal["id"])))
        if cleanup_warnings:
            print("; ".join(cleanup_warnings), file=sys.stderr)


def propose_one(
    db: sqlite3.Connection,
    url: str,
    login: str,
    *,
    request_id: str,
    workspace_id: str,
    owner_user_id: str,
    position: int,
    claimant: str = "proposal-cli",
) -> dict[str, Any]:
    """Generate and persist one read-only, head-bound proposal."""
    pr = load_pr(url)
    conversation_id, _ = get_or_create_pr_conversation(
        db,
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        repo=pr.repo,
        pr_number=pr.number,
        pr_url=pr.url,
    )
    associate_request_conversation(db, request_id, conversation_id, position=position)
    if pr.state in {"MERGED", "CLOSED"}:
        return finalize_external_pr(db, conversation_id=conversation_id, pr=pr)
    if pr.state != "OPEN":
        return {"url": pr.url, "status": f"pr_{pr.state.lower()}", "head_sha": pr.head_sha}
    current = active_proposal(db, conversation_id)
    if current is not None and str(current["head_sha"]) == pr.head_sha:
        if str(current["state"]) == "queued":
            return analyze_proposal_revision(
                db,
                pr=pr,
                login=login,
                proposal=current,
                claimant=claimant,
            )
        return {
            "url": pr.url,
            "status": str(current["state"]),
            "conversation_id": conversation_id,
            "proposal_id": str(current["id"]),
            "revision_token": str(current["revision_token"]),
            "head_sha": pr.head_sha,
            "reused": True,
        }
    previous = latest_proposal(db, conversation_id)
    baseline = _effective_reviewed_baseline(previous)
    proposal = create_proposal_revision(
        db,
        conversation_id,
        head_sha=pr.head_sha,
        baseline_head_sha=baseline,
    )
    return analyze_proposal_revision(
        db,
        pr=pr,
        login=login,
        proposal=proposal,
        claimant=claimant,
    )


def propose_urls(
    urls: Iterable[str],
    *,
    workspace_id: str,
    source_channel_id: str,
    source_message_ts: str,
    requester_user_id: str,
    owner_user_id: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    unique_urls = list(dict.fromkeys(url.strip() for url in urls if url.strip()))
    if not unique_urls:
        raise AutomationError("at least one exact GitHub pull request URL is required")
    for url in unique_urls:
        parse_pr_url(url)
    login = reviewer_login()
    with connect_db(db_path) as db:
        request_id, _ = get_or_create_source_request(
            db,
            workspace_id=workspace_id,
            channel_id=source_channel_id,
            message_ts=source_message_ts,
            requester_user_id=requester_user_id,
        )
        results = [
            propose_one(
                db,
                url,
                login,
                request_id=request_id,
                workspace_id=workspace_id,
                owner_user_id=owner_user_id,
                position=position,
            )
            for position, url in enumerate(unique_urls)
        ]
    return {
        "reviewer": login,
        "request_id": request_id,
        "requested": len(unique_urls),
        "awaiting_decision": sum(
            item["status"] == "awaiting_decision" for item in results
        ),
        "results": results,
    }


def action_marker(action_id: str, candidate_id: str | None = None) -> str:
    suffix = f":{candidate_id}" if candidate_id is not None else ""
    return f"<!-- hermes-review-action:{action_id}{suffix} -->"


def approval_dismisses_stale_reviews(pr: PullRequest) -> bool:
    """Fail closed unless branch protection invalidates raced stale approvals."""
    owner, repo = pr.repo.split("/", 1)
    try:
        protection = gh_json(
            ["api", f"repos/{owner}/{repo}/branches/{pr.base_ref}/protection"]
        )
    except AutomationError:
        return False
    required = protection.get("required_pull_request_reviews") or {}
    return required.get("dismiss_stale_reviews") is True


def _decision_action_row(
    db: sqlite3.Connection, decision_id: str
) -> dict[str, Any]:
    row = db.execute(
        """
        SELECT a.*, d.action, d.selected_candidate_ids, d.payload,
               d.proposal_id, d.state AS decision_state,
               p.conversation_id, p.revision_token, p.head_sha,
               c.repo, c.pr_number, c.pr_url, c.owner_user_id
        FROM workflow_actions a
        JOIN proposal_decisions d ON d.id = a.decision_id
        JOIN proposal_revisions p ON p.id = d.proposal_id
        JOIN workflow_pr_conversations c ON c.id = p.conversation_id
        WHERE d.id = ?
        """,
        (decision_id,),
    ).fetchone()
    if row is None:
        raise AutomationError("decision has no executable action")
    return _row_dict(row)


def _record_action_publications(
    db: sqlite3.Connection,
    *,
    action_id: str,
    publications: Mapping[str, Sequence[Mapping[str, Any]]],
) -> int:
    marker = action_marker(action_id)
    recorded_candidates: set[str] = set()
    for review in publications.get("reviews", []):
        if marker not in str(review.get("body") or ""):
            continue
        db.execute(
            """
            INSERT OR IGNORE INTO action_publications(
                action_id, candidate_id, kind, github_id, state, url, published_at
            ) VALUES (?, NULL, 'review', ?, ?, ?, ?)
            """,
            (
                action_id,
                int(review["id"]),
                str(review.get("state") or ""),
                str(review.get("html_url") or ""),
                str(review.get("submitted_at") or review.get("created_at") or ""),
            ),
        )
    for comment in publications.get("comments", []):
        body = str(comment.get("body") or "")
        if marker[:-4] + ":" not in body:
            continue
        match = re.search(
            re.escape(marker[:-4] + ":") + rf"({CANDIDATE_TOKEN_PATTERN}) -->",
            body,
        )
        if match is None:
            continue
        candidate_id = match.group(1)
        recorded_candidates.add(candidate_id)
        db.execute(
            """
            INSERT OR IGNORE INTO action_publications(
                action_id, candidate_id, kind, github_id, state, url, published_at
            ) VALUES (?, ?, 'inline_comment', ?, 'COMMENTED', ?, ?)
            """,
            (
                action_id,
                candidate_id,
                int(comment["id"]),
                str(comment.get("html_url") or ""),
                str(comment.get("created_at") or ""),
            ),
        )
    db.commit()
    return len(recorded_candidates)


def _action_receipt(db: sqlite3.Connection, action_id: str) -> dict[str, Any]:
    row = db.execute(
        "SELECT state, receipt, error FROM workflow_actions WHERE id = ?",
        (action_id,),
    ).fetchone()
    publications = db.execute(
        "SELECT candidate_id, kind, github_id, state, url FROM action_publications "
        "WHERE action_id = ? ORDER BY id",
        (action_id,),
    ).fetchall()
    return {
        "status": str(row["state"]),
        "action_id": action_id,
        "receipt": json.loads(str(row["receipt"])) if row["receipt"] else None,
        "error": row["error"],
        "publications": [_row_dict(item) for item in publications],
    }


def _finish_workflow_action(
    db: sqlite3.Connection,
    *,
    decision_id: str,
    action_id: str,
    action: str,
    proposal_id: str,
    conversation_id: str,
    head_sha: str,
    comment_count: int,
    receipt: Mapping[str, Any],
) -> None:
    stamp = iso(utc_now())
    with db:
        db.execute(
            "UPDATE workflow_actions SET state = 'completed', receipt = ?, "
            "completed_at = ?, lease_expires_at = NULL, error = NULL WHERE id = ?",
            (json.dumps(dict(receipt), sort_keys=True), stamp, action_id),
        )
        db.execute(
            "UPDATE proposal_decisions SET state = 'completed', completed_at = ?, "
            "error = NULL WHERE id = ?",
            (stamp, decision_id),
        )
        db.execute(
            "UPDATE proposal_revisions SET state = 'completed', terminal_at = ? "
            "WHERE id = ?",
            (stamp, proposal_id),
        )
        db.execute(
            "UPDATE proposal_reminders SET state = 'completed', updated_at = ? "
            "WHERE proposal_id = ?",
            (stamp, proposal_id),
        )
    linked = db.execute(
        "SELECT COUNT(*) FROM workflow_request_members WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()[0]
    if linked:
        outcome = {
            "approve": "approved",
            "publish": "comments_published",
            "skip": "skipped",
        }[action]
        update_request_member_outcome(
            db,
            conversation_id=conversation_id,
            outcome=outcome,
            reviewed_head=head_sha,
            published_comment_count=comment_count,
        )


def _block_workflow_action(
    db: sqlite3.Connection,
    *,
    decision_id: str,
    action_id: str,
    proposal_id: str,
    reason: str,
    stale: bool = False,
) -> dict[str, Any]:
    stamp = iso(utc_now())
    with db:
        db.execute(
            "UPDATE workflow_actions SET state = 'blocked', error = ?, "
            "completed_at = ?, lease_expires_at = NULL WHERE id = ?",
            (reason, stamp, action_id),
        )
        db.execute(
            "UPDATE proposal_decisions SET state = ?, error = ?, completed_at = ? "
            "WHERE id = ?",
            ("rejected_stale" if stale else "blocked", reason, stamp, decision_id),
        )
        db.execute(
            "UPDATE proposal_revisions SET state = ?, superseded_at = ? WHERE id = ?",
            ("superseded" if stale else "awaiting_decision", stamp if stale else None, proposal_id),
        )
    return {
        "status": "stale_head" if stale else "blocked",
        "reason": reason,
        "action_id": action_id,
    }


def re_review_current_head(
    db: sqlite3.Connection,
    *,
    conversation_id: str,
    pr: PullRequest,
    login: str,
    claimant: str = "re-review",
) -> dict[str, Any]:
    """Create or resume exactly one latest-head proposal in the stable conversation."""
    previous = latest_proposal(db, conversation_id)
    baseline = _effective_reviewed_baseline(previous)
    proposal = create_proposal_revision(
        db,
        conversation_id,
        head_sha=pr.head_sha,
        baseline_head_sha=baseline,
    )
    if not proposal.get("created") and str(proposal["state"]) != "queued":
        return {
            "url": pr.url,
            "status": str(proposal["state"]),
            "conversation_id": conversation_id,
            "proposal_id": str(proposal["id"]),
            "revision_token": str(proposal["revision_token"]),
            "baseline_head_sha": proposal.get("baseline_head_sha"),
            "head_sha": pr.head_sha,
            "reused": True,
        }
    return analyze_proposal_revision(
        db,
        pr=pr,
        login=login,
        proposal=proposal,
        claimant=claimant,
    )


def _publishable_candidates(
    context: Mapping[str, Any], selected: Sequence[str]
) -> list[dict[str, Any]]:
    available = {str(item["candidate_id"]): item for item in context["findings"]}
    result: list[dict[str, Any]] = []
    for candidate_id in selected:
        finding = available.get(candidate_id)
        if finding is None:
            raise AutomationError(f"unknown proposal candidate {candidate_id}")
        if not bool(finding["active"]):
            raise AutomationError(f"proposal candidate {candidate_id} is dismissed")
        if not all((finding.get("path"), finding.get("line"), finding.get("side"))):
            raise AutomationError(
                f"proposal candidate {candidate_id} lacks executable inline coordinates"
            )
        result.append(finding)
    return result


def execute_thread_command(
    db: sqlite3.Connection,
    *,
    workspace_id: str,
    dm_channel_id: str,
    thread_ts: str,
    owner_user_id: str,
    command_text: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Apply an exact owner command, with all GitHub writes behind fresh guards."""
    context = thread_context(
        db,
        workspace_id=workspace_id,
        dm_channel_id=dm_channel_id,
        thread_ts=thread_ts,
        owner_user_id=owner_user_id,
    )
    command = parse_decision_command(command_text)
    if command is None:
        return {
            "status": "read_only",
            "conversation_id": context["conversation_id"],
            "revision_token": context["revision_token"],
        }
    if command.revision_token != str(context["revision_token"]):
        raise AutomationError("proposal revision does not match the current thread revision")
    candidate_ids = {str(item["candidate_id"]) for item in context["findings"]}
    missing = [item for item in command.candidate_ids if item not in candidate_ids]
    if missing:
        raise AutomationError(f"unknown proposal candidate {missing[0]}")
    selected_findings = (
        _publishable_candidates(context, command.candidate_ids)
        if command.action == "publish"
        else []
    )
    payload = {"body": command.body} if command.body is not None else {}
    decision_id, created = record_proposal_decision(
        db,
        conversation_id=str(context["conversation_id"]),
        revision_token=command.revision_token,
        owner_user_id=owner_user_id,
        action=command.action,
        selected_candidate_ids=command.candidate_ids,
        payload=payload,
        idempotency_key=idempotency_key,
    )
    if command.action in {"edit", "dismiss"}:
        if command.action == "edit" and not str(command.body or "").strip():
            raise AutomationError("edited comment body cannot be empty")
        db.execute(
            "UPDATE proposal_decisions SET state = 'completed', completed_at = ? "
            "WHERE id = ?",
            (iso(utc_now()), decision_id),
        )
        db.commit()
        return {
            "status": "updated",
            "action": command.action,
            "created": created,
            "proposal": proposal_context(
                db,
                conversation_id=str(context["conversation_id"]),
                revision_token=command.revision_token,
            ),
        }

    claim_state, action_id = claim_decision_action(
        db, decision_id=decision_id, claimant="decision-cli"
    )
    if claim_state == "completed":
        return _action_receipt(db, action_id)
    if claim_state in {"blocked", "failed", "in_progress"}:
        return _action_receipt(db, action_id)
    action_row = _decision_action_row(db, decision_id)
    pr = load_pr(str(action_row["pr_url"]))
    if (
        pr.repo.lower() != str(action_row["repo"]).lower()
        or pr.number != int(action_row["pr_number"])
    ):
        return _block_workflow_action(
            db,
            decision_id=decision_id,
            action_id=action_id,
            proposal_id=str(action_row["proposal_id"]),
            reason="GitHub returned a different pull request target",
        )
    if pr.state != "OPEN":
        if pr.state in {"MERGED", "CLOSED"}:
            return finalize_external_pr(
                db,
                conversation_id=str(action_row["conversation_id"]),
                pr=pr,
            )
        return _block_workflow_action(
            db,
            decision_id=decision_id,
            action_id=action_id,
            proposal_id=str(action_row["proposal_id"]),
            reason=f"pull request is {pr.state.lower()}",
        )
    expected_head = str(action_row["expected_head"])
    if pr.head_sha != expected_head:
        stale_result = _block_workflow_action(
            db,
            decision_id=decision_id,
            action_id=action_id,
            proposal_id=str(action_row["proposal_id"]),
            reason=f"stale_head: expected {expected_head}, current {pr.head_sha}",
            stale=True,
        )
        try:
            stale_result["re_review"] = re_review_current_head(
                db,
                conversation_id=str(action_row["conversation_id"]),
                pr=pr,
                login=reviewer_login(),
                claimant="stale-action-re-review",
            )
        except (AutomationError, OSError, subprocess.TimeoutExpired) as exc:
            queued = active_proposal(db, str(action_row["conversation_id"]))
            stale_result["re_review"] = {
                "status": str(queued["state"]) if queued is not None else "failed",
                "conversation_id": str(action_row["conversation_id"]),
                "proposal_id": str(queued["id"]) if queued is not None else None,
                "revision_token": (
                    str(queued["revision_token"]) if queued is not None else None
                ),
                "baseline_head_sha": (
                    queued.get("baseline_head_sha") if queued is not None else expected_head
                ),
                "head_sha": pr.head_sha,
                "error": str(exc),
            }
        return stale_result
    if command.action == "skip":
        receipt = {"action": "skip", "head_sha": expected_head}
        _finish_workflow_action(
            db,
            decision_id=decision_id,
            action_id=action_id,
            action="skip",
            proposal_id=str(action_row["proposal_id"]),
            conversation_id=str(action_row["conversation_id"]),
            head_sha=expected_head,
            comment_count=0,
            receipt=receipt,
        )
        return _action_receipt(db, action_id)

    login = reviewer_login()
    if command.action == "approve":
        if pr.author_login.lower() == login.lower():
            return _block_workflow_action(
                db,
                decision_id=decision_id,
                action_id=action_id,
                proposal_id=str(action_row["proposal_id"]),
                reason="self-authored pull requests cannot be approved",
            )
        if not approval_dismisses_stale_reviews(pr):
            return _block_workflow_action(
                db,
                decision_id=decision_id,
                action_id=action_id,
                proposal_id=str(action_row["proposal_id"]),
                reason="branch protection does not prove stale approvals are dismissed",
            )

    before = github_publications(pr, login)
    recovered_count = _record_action_publications(
        db, action_id=action_id, publications=before
    )
    if command.action == "approve":
        recovered = db.execute(
            "SELECT COUNT(*) FROM action_publications WHERE action_id = ? "
            "AND kind = 'review'",
            (action_id,),
        ).fetchone()[0] > 0
    else:
        recovered = recovered_count == len(command.candidate_ids)
    owner, repo = pr.repo.split("/", 1)
    if not recovered:
        if command.action == "approve":
            payload: dict[str, Any] = {
                "commit_id": expected_head,
                "event": "APPROVE",
                "body": action_marker(action_id),
            }
        else:
            recorded_candidate_ids = {
                str(row["candidate_id"])
                for row in db.execute(
                    "SELECT candidate_id FROM action_publications "
                    "WHERE action_id = ? AND kind = 'inline_comment'",
                    (action_id,),
                ).fetchall()
            }
            comments = []
            for finding in selected_findings:
                if str(finding["candidate_id"]) in recorded_candidate_ids:
                    continue
                comment = {
                    "path": finding["path"],
                    "line": int(finding["line"]),
                    "side": finding["side"],
                    "body": str(finding["body"]).rstrip()
                    + "\n\n"
                    + action_marker(action_id, str(finding["candidate_id"])),
                }
                if finding.get("start_line") is not None:
                    comment["start_line"] = int(finding["start_line"])
                    comment["start_side"] = finding["start_side"]
                comments.append(comment)
            payload = {
                "commit_id": expected_head,
                "event": "COMMENT",
                "body": action_marker(action_id),
                "comments": comments,
            }
        github_json_request(
            "POST", f"repos/{owner}/{repo}/pulls/{pr.number}/reviews", payload
        )
        after = github_publications(pr, login)
        recovered_count = _record_action_publications(
            db, action_id=action_id, publications=after
        )
        if command.action == "approve":
            recovered = any(
                action_marker(action_id) in str(item.get("body") or "")
                and str(item.get("state") or "").upper() == "APPROVED"
                for item in after.get("reviews", [])
            )
        else:
            recovered = recovered_count == len(command.candidate_ids)
    if not recovered:
        db.execute(
            "UPDATE workflow_actions SET state = 'executing', error = ?, "
            "lease_expires_at = NULL WHERE id = ?",
            ("GitHub write receipt is not yet reconcilable", action_id),
        )
        db.commit()
        return {
            "status": "recovery_required",
            "reason": "GitHub write receipt is not yet reconcilable; retry the exact command",
            "action_id": action_id,
        }

    post_write = load_pr(pr.url)
    receipt = {
        "action": command.action,
        "head_sha": expected_head,
        "comment_count": 0 if command.action == "approve" else len(command.candidate_ids),
        "head_changed_after_write": post_write.head_sha != expected_head,
    }
    _finish_workflow_action(
        db,
        decision_id=decision_id,
        action_id=action_id,
        action=command.action,
        proposal_id=str(action_row["proposal_id"]),
        conversation_id=str(action_row["conversation_id"]),
        head_sha=expected_head,
        comment_count=receipt["comment_count"],
        receipt=receipt,
    )
    return _action_receipt(db, action_id)


def decide_thread_command(
    *,
    workspace_id: str,
    dm_channel_id: str,
    thread_ts: str,
    owner_user_id: str,
    command_text: str,
    idempotency_key: str,
    db_path: str | None = None,
) -> dict[str, Any]:
    with connect_db(db_path) as db:
        return execute_thread_command(
            db,
            workspace_id=workspace_id,
            dm_channel_id=dm_channel_id,
            thread_ts=thread_ts,
            owner_user_id=owner_user_id,
            command_text=command_text,
            idempotency_key=idempotency_key,
        )


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
        pending_rows = db.execute(
            """
            SELECT p.id AS proposal_id, p.revision_token, p.head_sha,
                   p.objective, p.summary, p.ready_at, r.last_sent_at,
                   c.repo, c.pr_number, c.pr_url
            FROM proposal_reminders r
            JOIN proposal_revisions p ON p.id = r.proposal_id
            JOIN workflow_pr_conversations c ON c.id = p.conversation_id
            WHERE r.state = 'digest_only' AND p.state = 'awaiting_decision'
            ORDER BY r.last_sent_at, c.repo, c.pr_number
            """
        ).fetchall()
        pending_reviews = [
            {
                "proposal_id": str(row["proposal_id"]),
                "revision_token": str(row["revision_token"]),
                "repo": str(row["repo"]),
                "pr_number": int(row["pr_number"]),
                "pr_url": str(row["pr_url"]),
                "head_sha": str(row["head_sha"]),
                "objective": row["objective"],
                "summary": row["summary"],
                "ready_at": row["ready_at"],
                "last_reminded_at": row["last_sent_at"],
            }
            for row in pending_rows
        ]
    return {
        "timezone": timezone_name,
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "review_count": len(reviews),
        "reviews": reviews,
        "pending_review_count": len(pending_reviews),
        "pending_reviews": pending_reviews,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="override the SQLite database path")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="initialize or migrate the database")
    def add_proposal_arguments(command: argparse.ArgumentParser) -> None:
        command.add_argument("--workspace-id", required=True)
        command.add_argument("--source-channel-id", required=True)
        command.add_argument("--source-message-ts", required=True)
        command.add_argument("--requester-user-id", required=True)
        command.add_argument("--owner-user-id", required=True)
        command.add_argument("urls", nargs="+")

    propose = subparsers.add_parser(
        "propose", help="generate read-only proposals for exact PR URLs"
    )
    add_proposal_arguments(propose)
    review = subparsers.add_parser(
        "review", help="compatibility alias for read-only proposal generation"
    )
    add_proposal_arguments(review)
    context = subparsers.add_parser(
        "thread-context", help="load the proposal mapped to one private Slack thread"
    )
    context.add_argument("--workspace-id", required=True)
    context.add_argument("--dm-channel-id", required=True)
    context.add_argument("--thread-ts", required=True)
    context.add_argument("--owner-user-id")
    decide = subparsers.add_parser(
        "decide", help="apply one exact revision-bound owner command"
    )
    decide.add_argument("--workspace-id", required=True)
    decide.add_argument("--dm-channel-id", required=True)
    decide.add_argument("--thread-ts", required=True)
    decide.add_argument("--owner-user-id", required=True)
    decide.add_argument("--idempotency-key", required=True)
    decide.add_argument("--command-text", required=True)
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
    reminders = subparsers.add_parser(
        "reminder-sweep",
        help="claim due private reminders and emit exact Slack thread deliveries",
    )
    reminders.add_argument("--claimant", default=f"reminder-{uuid.uuid4()}")
    reminders.add_argument("--limit", type=int, default=25)
    reminders.add_argument("--lease-seconds", type=int, default=300)
    reminders.add_argument(
        "--timezone", default=os.environ.get("TZ", "America/Mexico_City")
    )
    reminder_ack = subparsers.add_parser(
        "reminder-ack", help="acknowledge one persisted Slack reminder receipt"
    )
    reminder_ack.add_argument("--reminder-id", required=True)
    reminder_ack.add_argument("--delivery-id", required=True)
    reminder_ack.add_argument("--claimant", required=True)
    reminder_ack.add_argument("--message-ts", required=True)
    reminder_ack.add_argument(
        "--timezone", default=os.environ.get("TZ", "America/Mexico_City")
    )
    reminder_block = subparsers.add_parser(
        "reminder-block", help="record one definitive Slack reminder failure"
    )
    reminder_block.add_argument("--reminder-id", required=True)
    reminder_block.add_argument("--delivery-id", required=True)
    reminder_block.add_argument("--claimant", required=True)
    reminder_block.add_argument("--error", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            with connect_db(args.db) as db:
                version = db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            emit({"status": "ready", "schema_version": version, "database": args.db or os.environ.get("REVIEW_HISTORY_DB", DEFAULT_DB)})
        elif args.command in {"propose", "review"}:
            emit(
                propose_urls(
                    args.urls,
                    db_path=args.db,
                    workspace_id=args.workspace_id,
                    source_channel_id=args.source_channel_id,
                    source_message_ts=args.source_message_ts,
                    requester_user_id=args.requester_user_id,
                    owner_user_id=args.owner_user_id,
                )
            )
        elif args.command == "thread-context":
            with connect_db(args.db) as db:
                emit(
                    thread_context(
                        db,
                        workspace_id=args.workspace_id,
                        dm_channel_id=args.dm_channel_id,
                        thread_ts=args.thread_ts,
                        owner_user_id=args.owner_user_id,
                    )
                )
        elif args.command == "decide":
            emit(
                decide_thread_command(
                    db_path=args.db,
                    workspace_id=args.workspace_id,
                    dm_channel_id=args.dm_channel_id,
                    thread_ts=args.thread_ts,
                    owner_user_id=args.owner_user_id,
                    command_text=args.command_text,
                    idempotency_key=args.idempotency_key,
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
        elif args.command == "reminder-sweep":
            emit(
                reminder_sweep(
                    args.db,
                    claimant=args.claimant,
                    timezone_name=args.timezone,
                    limit=args.limit,
                    lease_seconds=args.lease_seconds,
                )
            )
        elif args.command == "reminder-ack":
            emit(
                ack_reminder_delivery(
                    args.db,
                    reminder_id=args.reminder_id,
                    delivery_id=args.delivery_id,
                    claimant=args.claimant,
                    message_ts=args.message_ts,
                    timezone_name=args.timezone,
                )
            )
        elif args.command == "reminder-block":
            emit(
                block_reminder_delivery(
                    args.db,
                    reminder_id=args.reminder_id,
                    delivery_id=args.delivery_id,
                    claimant=args.claimant,
                    error=args.error,
                )
            )
        return 0
    except (AutomationError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        emit({"status": "error", "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
