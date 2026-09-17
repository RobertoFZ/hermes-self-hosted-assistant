"""Private-confirmation Slack policy for the Hermes PR reviewer."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import os
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any, Awaitable


logger = logging.getLogger(__name__)


def _csv_values(name: str) -> frozenset[str]:
    return frozenset(
        value.strip()
        for value in os.environ.get(name, "").split(",")
        if value.strip()
    )


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _repository_values(name: str) -> frozenset[tuple[str, str]]:
    repositories: set[tuple[str, str]] = set()
    for value in _csv_values(name):
        owner, separator, repository = value.partition("/")
        if separator and owner and repository and "/" not in repository:
            repositories.add((owner.lower(), repository.lower()))
    return frozenset(repositories)


REVIEW_CHANNEL_ID = os.environ.get("SLACK_REVIEW_CHANNEL_ID", "").strip()
OWNER_USER_IDS = _csv_values("SLACK_REVIEW_OWNER_USER_IDS")
REVIEWER_USER_IDS = _csv_values("SLACK_REVIEWER_USER_IDS")
REVIEW_BOT_USER_IDS = _csv_values("SLACK_REVIEW_BOT_USER_IDS")
COMPETING_BOT_USER_IDS = _csv_values("SLACK_REVIEW_COMPETING_BOT_USER_IDS")
ALLOWED_REPOSITORIES = _repository_values("SLACK_REVIEW_ALLOWED_REPOSITORIES")
_configured_owner = os.environ.get("SLACK_REVIEW_DIGEST_USER_ID", "").strip()
if not _configured_owner and len(OWNER_USER_IDS) == 1:
    _configured_owner = next(iter(OWNER_USER_IDS))
DECISION_OWNER_USER_ID = (
    _configured_owner if _configured_owner in OWNER_USER_IDS else ""
)

MAX_URLS_PER_MESSAGE = _positive_int("SLACK_REVIEW_MAX_URLS_PER_MESSAGE", 5)
MAX_ACTIVE_PER_REQUESTER = _positive_int(
    "SLACK_REVIEW_MAX_ACTIVE_PER_REQUESTER", 5
)
MAX_QUEUED = _positive_int("SLACK_REVIEW_MAX_QUEUED", 50)
PROPOSAL_CONCURRENCY = _positive_int("SLACK_REVIEW_PROPOSAL_CONCURRENCY", 3)

if (
    not REVIEW_CHANNEL_ID
    or not OWNER_USER_IDS
    or not ALLOWED_REPOSITORIES
    or not DECISION_OWNER_USER_ID
):
    logger.warning(
        "Slack review confirmation policy is incomplete and will fail closed"
    )

_PR_URL_RE = re.compile(
    r"https://github\.com/"
    r"(?P<owner>[A-Za-z0-9_.-]+)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/pull/"
    r"(?P<number>[1-9][0-9]*)(?![0-9])",
    re.IGNORECASE,
)
_BOT_REVIEW_INTENT_RE = re.compile(
    r"\b(?:"
    r"solicitud(?:es)?\s+de\s+revision|"
    r"(?:listo|lista|listos|listas)\s+para\s+(?:la\s+)?revision|"
    r"(?:revisa|revisar|revisen)\s+(?:este|esta|estos|estas|el|la|los|las)?\s*"
    r"(?:pr|prs|pull\s+request|pull\s+requests)|"
    r"review\s+request|ready\s+for\s+review|please\s+review"
    r")\b",
    re.IGNORECASE,
)
_USER_MENTION_RE = re.compile(r"<@(?P<user>[A-Z0-9_]+)(?:\|[^>]+)?>")
_COMMAND_RE = re.compile(
    r"(?:approve P[1-9][0-9]*|skip P[1-9][0-9]*|"
    r"(?:publish|dismiss) P[1-9][0-9]*(?: C[1-9][0-9]*)+|"
    r"edit P[1-9][0-9]* C[1-9][0-9]*: \S(?:.*\S)?)$"
)

_DISPATCHED_EVENT_KEYS: set[tuple[str, str, str]] = set()
_DISPATCHED_EVENT_ORDER: list[tuple[str, str, str]] = []
_DISPATCH_CACHE_LIMIT = 2048
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
_REQUESTER_ACTIVE: dict[str, int] = {}
_PROPOSAL_SEMAPHORE: asyncio.Semaphore | None = None
_AUTOMATION: Any | None = None


def _platform_name(source: Any) -> str:
    platform = getattr(source, "platform", "")
    return str(getattr(platform, "value", platform)).lower()


def _extract_allowed_pr_urls(text: str) -> tuple[list[str], bool]:
    urls: list[str] = []
    seen: set[str] = set()
    unsupported = False
    for match in _PR_URL_RE.finditer(text or ""):
        owner = match.group("owner")
        repo = match.group("repo")
        number = match.group("number")
        if (owner.lower(), repo.lower()) not in ALLOWED_REPOSITORIES:
            unsupported = True
            continue
        url = f"https://github.com/{owner}/{repo}/pull/{number}"
        normalized = url.lower()
        if normalized not in seen:
            seen.add(normalized)
            urls.append(url)
    return urls, unsupported


def _iter_slack_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_slack_strings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_slack_strings(nested)


def _slack_message_content(event: Any) -> str:
    raw_message = getattr(event, "raw_message", None)
    if isinstance(raw_message, dict):
        parts: list[str] = []
        for key in ("text", "blocks", "attachments"):
            parts.extend(_iter_slack_strings(raw_message.get(key)))
        current = "\n".join(dict.fromkeys(part for part in parts if part))
        if current:
            return current
    return str(getattr(event, "text", "") or "")


def _has_bot_review_intent(text: str) -> bool:
    normalized = unicodedata.normalize("NFKD", text or "")
    folded = "".join(char for char in normalized if not unicodedata.combining(char))
    return _BOT_REVIEW_INTENT_RE.search(folded) is not None


def _remember_dispatch_event(source: Any, event: Any) -> bool:
    key = (
        str(getattr(source, "scope_id", "") or ""),
        str(getattr(source, "chat_id", "") or ""),
        str(getattr(event, "message_id", "") or ""),
    )
    if not key[2]:
        return True
    if key in _DISPATCHED_EVENT_KEYS:
        return False
    _DISPATCHED_EVENT_KEYS.add(key)
    _DISPATCHED_EVENT_ORDER.append(key)
    overflow = len(_DISPATCHED_EVENT_ORDER) - _DISPATCH_CACHE_LIMIT
    if overflow > 0:
        for expired in _DISPATCHED_EVENT_ORDER[:overflow]:
            _DISPATCHED_EVENT_KEYS.discard(expired)
        del _DISPATCHED_EVENT_ORDER[:overflow]
    return True


def _gateway_bot_user_id(event: Any, gateway: Any = None) -> str:
    source = getattr(event, "source", None)
    adapter = (getattr(gateway, "adapters", {}) or {}).get(
        getattr(source, "platform", None)
    )
    if adapter is None:
        return ""
    scope_id = str(getattr(source, "scope_id", "") or "")
    team_bot_ids = getattr(adapter, "_team_bot_user_ids", {}) or {}
    return str(team_bot_ids.get(scope_id) or getattr(adapter, "_bot_user_id", "") or "")


def _mentioned_user_ids(text: str) -> set[str]:
    return {match.group("user") for match in _USER_MENTION_RE.finditer(text or "")}


def _mentions_this_bot(event: Any, gateway: Any = None) -> bool:
    raw_message = getattr(event, "raw_message", None)
    if isinstance(raw_message, dict) and raw_message.get("type") == "app_mention":
        return True
    bot_user_id = _gateway_bot_user_id(event, gateway)
    return bool(bot_user_id and bot_user_id in _mentioned_user_ids(_slack_message_content(event)))


def _targets_competing_bot(event: Any, gateway: Any = None) -> bool:
    mentions = _mentioned_user_ids(_slack_message_content(event))
    return bool(mentions & COMPETING_BOT_USER_IDS) and not _mentions_this_bot(event, gateway)


def _owner_mentioned_bot(user_id: str, event: Any, gateway: Any = None) -> bool:
    return user_id in OWNER_USER_IDS and _mentions_this_bot(event, gateway)


def _automation_module() -> Any:
    global _AUTOMATION
    if _AUTOMATION is not None:
        return _AUTOMATION
    configured = os.environ.get("REVIEW_AUTOMATION_PATH", "").strip()
    candidates = [
        Path(configured) if configured else Path("/opt/review-automation/review_automation.py"),
        Path(__file__).resolve().parents[2] / "automation" / "review_automation.py",
    ]
    path = next((item for item in candidates if item.is_file()), None)
    if path is None:
        raise RuntimeError("review automation module is unavailable")
    name = "hermes_private_review_automation"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load review automation module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    _AUTOMATION = module
    return module


def _lookup_private_route(source: Any) -> dict[str, Any] | None:
    workspace_id = str(getattr(source, "scope_id", "") or "")
    channel_id = str(getattr(source, "chat_id", "") or "")
    thread_ts = str(getattr(source, "thread_id", "") or "")
    if not (workspace_id and channel_id.startswith("D") and thread_ts):
        return None
    try:
        automation = _automation_module()
        with automation.connect_db() as db:
            return automation.conversation_for_slack_thread(
                db,
                workspace_id=workspace_id,
                dm_channel_id=channel_id,
                thread_ts=thread_ts,
            )
    except Exception:
        logger.warning("Unable to resolve private review thread", exc_info=True)
        return None


def _is_exact_command(text: str) -> bool:
    return _COMMAND_RE.fullmatch((text or "").strip()) is not None


def _intake_capacity_reason(user_id: str, url_count: int) -> str | None:
    if _REQUESTER_ACTIVE.get(user_id, 0) >= MAX_ACTIVE_PER_REQUESTER:
        return "review-requester-limit-exceeded"
    if len(_BACKGROUND_TASKS) + url_count > MAX_QUEUED:
        return "review-queue-full"
    db_path = os.environ.get("REVIEW_HISTORY_DB", "").strip()
    if not db_path:
        return None
    try:
        automation = _automation_module()
        with automation.connect_db(db_path) as db:
            requester_count = db.execute(
                "SELECT COUNT(*) FROM workflow_source_requests "
                "WHERE requester_user_id = ? AND state = 'pending'",
                (user_id,),
            ).fetchone()[0]
            queued = db.execute(
                "SELECT COUNT(*) FROM proposal_revisions WHERE state IN "
                "('queued','analyzing','output_pending','awaiting_decision','publishing')"
            ).fetchone()[0]
        if requester_count >= MAX_ACTIVE_PER_REQUESTER:
            return "review-requester-limit-exceeded"
        if queued + url_count > MAX_QUEUED:
            return "review-queue-full"
    except Exception:
        logger.warning("Unable to inspect durable review queue", exc_info=True)
        return "review-workflow-unavailable"
    return None


def _adapter_for(gateway: Any, source: Any) -> Any | None:
    return (getattr(gateway, "adapters", {}) or {}).get(
        getattr(source, "platform", None)
    )


def _track_task(coro: Awaitable[Any]) -> None:
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        logger.warning("No running event loop for private PR review task")
        if inspect.iscoroutine(coro):
            coro.close()
        return
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def _set_request_reaction(
    adapter: Any, channel_id: str, message_ts: str, team_id: str, reaction: str
) -> None:
    for current in ("warning", "eyes", "white_check_mark"):
        if current != reaction and hasattr(adapter, "_remove_reaction"):
            await adapter._remove_reaction(channel_id, message_ts, current, team_id)
    if hasattr(adapter, "_add_reaction"):
        await adapter._add_reaction(channel_id, message_ts, reaction, team_id)


def _format_proposal(context: dict[str, Any]) -> str:
    conversation = context.get("conversation") or {}
    token = str(context.get("revision_token") or "")
    head = str(context.get("head_sha") or "")
    action = str(context.get("proposed_action") or "comment").upper()
    lines = [
        f"*{conversation.get('repo')} #{conversation.get('pr_number')} — {token}*",
        f"Head: `{head[:12]}`",
        f"Objective: {context.get('objective') or 'Not provided'}",
        f"Proposal: {action}",
        str(context.get("summary") or "Review proposal ready."),
    ]
    delta = {}
    try:
        structured = context.get("structured_result")
        if isinstance(structured, str):
            import json
            structured = json.loads(structured)
        delta = (structured or {}).get("delta") or {}
    except (TypeError, ValueError):
        delta = {}
    if delta and str(delta.get("status")) != "initial":
        lines.append(
            "Delta: "
            + str(delta.get("status")).replace("_", " ")
            + f" (baseline `{str(context.get('baseline_head_sha') or '')[:12]}`)"
        )
    findings = [item for item in context.get("findings", []) if item.get("active", True)]
    if findings:
        lines.append("\n*Candidate comments*")
        for finding in findings:
            location = str(finding.get("path") or "general")
            if finding.get("line") is not None:
                location += f":{finding['line']}"
            edited = " (edited)" if finding.get("edited") else ""
            lines.append(
                f"• `{finding.get('candidate_id')}` {finding.get('severity')} "
                f"{location}{edited} — {finding.get('body')}"
            )
    else:
        lines.append("No material candidate comments.")
    commands = [f"`skip {token}`"]
    if action == "APPROVE":
        commands.insert(0, f"`approve {token}`")
    if findings:
        ids = " ".join(str(item["candidate_id"]) for item in findings)
        commands.insert(0, f"`publish {token} {ids}`")
    lines.append("Reply in this thread with questions, or use " + ", ".join(commands) + ".")
    return "\n".join(lines)


async def _reconcile_delivery(
    adapter: Any, channel_id: str, thread_ts: str | None, workflow_key: str
) -> str | None:
    finder = getattr(adapter, "find_message_by_workflow_key", None)
    if finder is None:
        return None
    result = finder(channel_id, thread_ts, workflow_key)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, dict):
        return str(result.get("ts") or result.get("message_ts") or "") or None
    return str(result or "") or None


async def _deliver_proposal(adapter: Any, workspace_id: str, result: dict[str, Any]) -> None:
    automation = _automation_module()
    proposal_id = str(result.get("proposal_id") or "")
    conversation_id = str(result.get("conversation_id") or "")
    if not proposal_id or not conversation_id:
        return
    with automation.connect_db() as db:
        conversation = dict(
            db.execute(
                "SELECT * FROM workflow_pr_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        )
        context = automation.proposal_context(
            db,
            conversation_id=conversation_id,
            revision_token=str(result.get("revision_token") or ""),
        )
        context["conversation"] = conversation
    content = _format_proposal(context)
    metadata = {"scope_id": workspace_id, "workflow_key": f"proposal:{proposal_id}"}
    channel_id = str(conversation.get("dm_channel_id") or "")
    thread_ts = str(conversation.get("thread_ts") or "") or None
    if not channel_id:
        resolver = getattr(adapter, "_dm_target", None)
        if resolver is not None:
            channel_id = str(await resolver(DECISION_OWNER_USER_ID, metadata))
        else:
            channel_id = DECISION_OWNER_USER_ID
    workflow_key = f"proposal:{proposal_id}:summary"
    with automation.connect_db() as db:
        existing_delivery = db.execute(
            "SELECT state FROM slack_deliveries WHERE delivery_key = ?",
            (workflow_key,),
        ).fetchone()
        if existing_delivery is not None:
            # A root delivery is intentionally bound to thread_ts=NULL forever.
            # Once its receipt exists, the now-bound conversation must not turn
            # a replay into a differently routed delivery attempt.
            return
        delivery_id, state = automation.claim_slack_delivery(
            db,
            delivery_key=workflow_key,
            kind="proposal_summary" if thread_ts is None else "proposal_revision",
            workspace_id=workspace_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            claimant="slack-review-gate",
            conversation_id=conversation_id,
            proposal_id=proposal_id,
            metadata_key=workflow_key,
        )
    if state != "claimed":
        return
    send_metadata = {
        **metadata,
        "thread_id": thread_ts or "",
        "thread_ts": thread_ts or "",
    }
    response = await adapter.send(
        channel_id,
        content,
        reply_to=thread_ts,
        metadata=send_metadata,
    )
    message_ts = str(getattr(response, "message_id", "") or "")
    raw = getattr(response, "raw_response", None)
    if isinstance(raw, dict):
        channel_id = str(raw.get("channel") or channel_id)
        message_ts = str(raw.get("ts") or message_ts)
    if not getattr(response, "success", False) or not message_ts:
        message_ts = await _reconcile_delivery(
            adapter, channel_id, thread_ts, workflow_key
        ) or ""
    with automation.connect_db() as db:
        if message_ts:
            automation.complete_slack_delivery(
                db,
                delivery_id=delivery_id,
                claimant="slack-review-gate",
                message_ts=message_ts,
            )
            if thread_ts is None:
                automation.bind_pr_conversation_thread(
                    db,
                    conversation_id,
                    dm_channel_id=channel_id,
                    thread_ts=message_ts,
                )
        else:
            automation.block_slack_delivery(
                db,
                delivery_id=delivery_id,
                claimant="slack-review-gate",
                error=str(getattr(response, "error", "ambiguous Slack delivery")),
            )


def _render_verdict(projection: dict[str, Any]) -> str:
    lines = ["*PR review verdict*"]
    for member in projection.get("members", []):
        outcome = str(member.get("outcome") or "pending").replace("_", " ")
        head = str(member.get("reviewed_head") or "")
        count = int(member.get("published_comment_count") or 0)
        suffix = f" · `{head[:12]}`" if head else ""
        if count:
            suffix += f" · {count} comment{'s' if count != 1 else ''}"
        lines.append(f"• {member.get('repo')}#{member.get('pr_number')} — {outcome}{suffix}")
    return "\n".join(lines)


async def _project_request(adapter: Any, request_id: str) -> None:
    automation = _automation_module()
    with automation.connect_db() as db:
        projection = automation.source_request_projection(db, request_id)
    members = projection.get("members", [])
    if not any(str(item.get("state")) in automation.TERMINAL_MEMBER_OUTCOMES for item in members):
        return
    channel_id = str(projection["channel_id"])
    message_ts = str(projection["message_ts"])
    workspace_id = str(projection["workspace_id"])
    content = _render_verdict(projection)
    verdict_ts = str(projection.get("verdict_message_ts") or "")
    metadata = {"scope_id": workspace_id, "thread_id": message_ts, "thread_ts": message_ts}
    if verdict_ts:
        response = await adapter.edit_message(
            channel_id, verdict_ts, content, finalize=True, metadata=metadata
        )
    else:
        response = await adapter.send(
            channel_id, content, reply_to=message_ts, metadata=metadata
        )
        verdict_ts = str(getattr(response, "message_id", "") or "")
        if getattr(response, "success", False) and verdict_ts:
            with automation.connect_db() as db:
                automation.bind_source_verdict(
                    db, request_id=request_id, verdict_message_ts=verdict_ts
                )
    if not getattr(response, "success", False):
        logger.warning("Unable to project source review verdict")
    await _set_request_reaction(
        adapter,
        channel_id,
        message_ts,
        workspace_id,
        str(projection.get("reaction_name") or "eyes"),
    )


async def _run_source_request(
    adapter: Any,
    source: Any,
    event: Any,
    urls: list[str],
    _allow_self_review: bool,
) -> None:
    user_id = str(getattr(source, "user_id", "") or "")
    workspace_id = str(getattr(source, "scope_id", "") or "")
    channel_id = str(getattr(source, "chat_id", "") or "")
    message_ts = str(getattr(event, "message_id", "") or "")
    _REQUESTER_ACTIVE[user_id] = _REQUESTER_ACTIVE.get(user_id, 0) + 1
    try:
        await _set_request_reaction(adapter, channel_id, message_ts, workspace_id, "eyes")
        automation = _automation_module()

        def prepare() -> tuple[str, str]:
            with automation.connect_db() as db:
                request_id, _ = automation.get_or_create_source_request(
                    db,
                    workspace_id=workspace_id,
                    channel_id=channel_id,
                    message_ts=message_ts,
                    requester_user_id=user_id,
                )
            return request_id, automation.reviewer_login()

        request_id, login = await asyncio.to_thread(prepare)
        global _PROPOSAL_SEMAPHORE
        if _PROPOSAL_SEMAPHORE is None:
            _PROPOSAL_SEMAPHORE = asyncio.Semaphore(PROPOSAL_CONCURRENCY)

        async def analyze(position: int, url: str) -> dict[str, Any]:
            async with _PROPOSAL_SEMAPHORE:
                def run_one() -> dict[str, Any]:
                    with automation.connect_db() as db:
                        return automation.propose_one(
                            db,
                            url,
                            login,
                            request_id=request_id,
                            workspace_id=workspace_id,
                            owner_user_id=DECISION_OWNER_USER_ID,
                            position=position,
                            claimant=f"slack:{workspace_id}:{message_ts}:{position}",
                        )
                return await asyncio.to_thread(run_one)

        results = await asyncio.gather(
            *(analyze(position, url) for position, url in enumerate(urls)),
            return_exceptions=True,
        )
        failed = False
        for result in results:
            if isinstance(result, Exception):
                failed = True
                logger.warning("Private PR proposal failed: %s", result)
                continue
            await _deliver_proposal(adapter, workspace_id, result)
        if failed:
            await _set_request_reaction(adapter, channel_id, message_ts, workspace_id, "warning")
        else:
            await _project_request(adapter, request_id)
    finally:
        remaining = _REQUESTER_ACTIVE.get(user_id, 1) - 1
        if remaining > 0:
            _REQUESTER_ACTIVE[user_id] = remaining
        else:
            _REQUESTER_ACTIVE.pop(user_id, None)


async def _run_owner_command(adapter: Any, source: Any, event: Any) -> None:
    automation = _automation_module()
    workspace_id = str(getattr(source, "scope_id", "") or "")
    channel_id = str(getattr(source, "chat_id", "") or "")
    thread_ts = str(getattr(source, "thread_id", "") or "")
    message_ts = str(getattr(event, "message_id", "") or "")
    command_text = _slack_message_content(event).strip()
    try:
        result = await asyncio.to_thread(
            automation.decide_thread_command,
            workspace_id=workspace_id,
            dm_channel_id=channel_id,
            thread_ts=thread_ts,
            owner_user_id=DECISION_OWNER_USER_ID,
            command_text=command_text,
            idempotency_key=f"{workspace_id}:{channel_id}:{message_ts}",
        )
        status = str(result.get("status") or "unknown")
        if status == "updated":
            text = f"Draft updated for {result['proposal']['revision_token']}."
        elif status == "stale_head":
            text = "That command targeted an older head. I invalidated it and prepared a new re-review."
        elif status == "completed":
            receipt = result.get("receipt") or {}
            text = (
                f"Done: {str(receipt.get('action') or 'review').replace('_', ' ')} "
                f"for `{str(receipt.get('head_sha') or '')[:12]}`."
            )
        elif status in {"blocked", "failed", "recovery_required"}:
            text = f"Review action {status.replace('_', ' ')}: {result.get('reason') or result.get('error') or 'operator recovery is required'}."
        else:
            text = f"Review action status: {status.replace('_', ' ')}."
        await adapter.send(
            channel_id,
            text,
            reply_to=thread_ts,
            metadata={"scope_id": workspace_id, "thread_id": thread_ts, "thread_ts": thread_ts},
        )
        re_review = result.get("re_review")
        if isinstance(re_review, dict) and re_review.get("proposal_id"):
            await _deliver_proposal(adapter, workspace_id, re_review)
        route = _lookup_private_route(source)
        conversation_id = str((route or {}).get("id") or "")
        if conversation_id and status in {"completed", "pr_merged", "pr_closed"}:
            with automation.connect_db() as db:
                request_ids = [
                    str(row["id"])
                    for row in automation.source_requests_for_conversation(
                        db, conversation_id
                    )
                ]
            for request_id in request_ids:
                await _project_request(adapter, request_id)
    except Exception as exc:
        logger.warning("Owner PR review command failed", exc_info=True)
        await adapter.send(
            channel_id,
            f"Review command failed safely: {exc}",
            reply_to=thread_ts,
            metadata={"scope_id": workspace_id, "thread_id": thread_ts, "thread_ts": thread_ts},
        )


def _schedule_source_request(
    gateway: Any, source: Any, event: Any, urls: list[str], allow_self_review: bool
) -> None:
    adapter = _adapter_for(gateway, source)
    if adapter is None:
        logger.warning("Slack adapter unavailable for private PR proposal")
        return
    _track_task(_run_source_request(adapter, source, event, urls, allow_self_review))


def _schedule_owner_command(gateway: Any, source: Any, event: Any) -> None:
    adapter = _adapter_for(gateway, source)
    if adapter is None:
        logger.warning("Slack adapter unavailable for owner PR command")
        return
    _track_task(_run_owner_command(adapter, source, event))


def _private_question_rewrite(source: Any, event: Any, route: dict[str, Any]) -> dict[str, str]:
    text = _slack_message_content(event)
    return {
        "action": "rewrite",
        "text": (
            "Use the codex-pr-review skill for a read-only clarification in the "
            "mapped private PR thread. Use only the durable proposal loaded from "
            "these trusted routing identities; do not write to GitHub or move "
            "private content to another channel.\n"
            f"workspace_id={getattr(source, 'scope_id', '')}\n"
            f"dm_channel_id={getattr(source, 'chat_id', '')}\n"
            f"thread_ts={getattr(source, 'thread_id', '')}\n"
            f"owner_user_id={DECISION_OWNER_USER_ID}\n"
            f"conversation_id={route.get('id')}\n"
            f"proposal_id={route.get('proposal_id')}\n"
            f"Owner question: {text}"
        ),
    }


def _review_only_policy(event: Any, gateway: Any = None, **_kwargs: Any):
    source = getattr(event, "source", None)
    if source is None or _platform_name(source) != "slack":
        return None
    user_id = str(getattr(source, "user_id", "") or "")
    chat_id = str(getattr(source, "chat_id", "") or "")
    is_review_channel = chat_id == REVIEW_CHANNEL_ID
    is_direct_message = chat_id.startswith("D")
    is_review_bot = user_id in REVIEW_BOT_USER_IDS

    if user_id == DECISION_OWNER_USER_ID and is_direct_message:
        route = _lookup_private_route(source)
        if route is not None:
            if _is_exact_command(_slack_message_content(event)):
                _schedule_owner_command(gateway, source, event)
                return {"action": "skip", "reason": "review-command-scheduled"}
            return _private_question_rewrite(source, event, route)

    if user_id in OWNER_USER_IDS and not is_review_channel:
        return None
    if is_review_bot:
        if not is_review_channel:
            return {"action": "skip", "reason": "review-bot-surface-not-allowed"}
    elif user_id in REVIEWER_USER_IDS:
        if not is_review_channel and not is_direct_message:
            return {"action": "skip", "reason": "reviewer-surface-not-allowed"}
    elif user_id not in OWNER_USER_IDS:
        return {"action": "skip", "reason": "review-user-not-allowed"}

    if not DECISION_OWNER_USER_ID:
        return {"action": "skip", "reason": "review-decision-owner-not-configured"}
    message_content = _slack_message_content(event)
    if _targets_competing_bot(event, gateway):
        return {"action": "skip", "reason": "review-addressed-to-competing-bot"}
    if is_review_bot and not _has_bot_review_intent(message_content):
        return {"action": "skip", "reason": "review-bot-message-has-no-intent"}
    urls, contains_unsupported_pr = _extract_allowed_pr_urls(message_content)
    if not urls:
        return {"action": "skip", "reason": "review-message-has-no-approved-pr"}
    if contains_unsupported_pr:
        return {"action": "skip", "reason": "review-message-mixes-unsupported-pr"}
    if len(urls) > MAX_URLS_PER_MESSAGE:
        return {"action": "skip", "reason": "review-url-limit-exceeded"}
    capacity_reason = _intake_capacity_reason(user_id, len(urls))
    if capacity_reason:
        return {"action": "skip", "reason": capacity_reason}
    if not _remember_dispatch_event(source, event):
        return {"action": "skip", "reason": "duplicate-review-message"}
    _schedule_source_request(
        gateway,
        source,
        event,
        urls,
        _owner_mentioned_bot(user_id, event, gateway),
    )
    return {"action": "skip", "reason": "review-scheduled"}


def register(ctx: Any) -> None:
    ctx.register_hook("pre_gateway_dispatch", _review_only_policy)
