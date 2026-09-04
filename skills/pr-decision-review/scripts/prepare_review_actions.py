from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


TARGET_PATTERN = re.compile(
    r"^(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<pr>[1-9][0-9]*)$"
)
SELECTOR_PATTERN = re.compile(
    r"^(?P<repository>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(?P<pr>[1-9][0-9]*):(?P<local_id>E[1-9][0-9]*)$"
)
ACTION_CLASSIFICATIONS = {
    "new-comment": {
        "new-topic",
        "related-but-distinct",
        "outdated-thread",
        "unverifiable-incomplete-history",
    },
    "reply-thread": {"open-existing-thread"},
    "reopen-and-reply": {"resolved-but-recurring"},
}
REVIEW_ACTIONS = {"approve", "request-changes"}
PUBLICATION_ACTIONS = set(ACTION_CLASSIFICATIONS) | REVIEW_ACTIONS


class ActionPlanError(ValueError):
    pass


def target(repository: str, pr: int) -> dict[str, Any]:
    return {"repository": repository, "pr": pr}


def parse_target(value: str, label: str) -> dict[str, Any]:
    match = TARGET_PATTERN.fullmatch(value)
    if not match:
        raise ActionPlanError(f"{label} must use owner/repo#123")
    return target(match.group("repository"), int(match.group("pr")))


def parse_selector(value: str) -> dict[str, Any]:
    match = SELECTOR_PATTERN.fullmatch(value)
    if not match:
        raise ActionPlanError(
            f"publication selectors must be qualified as owner/repo#123:E1; received {value!r}"
        )
    return {
        "repository": match.group("repository"),
        "pr": int(match.group("pr")),
        "local_id": match.group("local_id"),
        "candidate_id": value,
    }


def require_integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ActionPlanError(f"{label} must be a positive integer")
    return value


def artifact_target(payload: dict[str, Any], pr_field: str, label: str) -> dict[str, Any]:
    repository = payload.get("repository")
    if not isinstance(repository, str) or not repository:
        raise ActionPlanError(f"{label} repository is missing")
    return target(repository, require_integer(payload.get(pr_field), f"{label} {pr_field}"))


def candidate_index(validation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    decisions = validation.get("candidate_decisions")
    if not isinstance(decisions, list):
        raise ActionPlanError("validation candidate_decisions is missing")
    indexed = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ActionPlanError("validation candidate_decisions contains a non-object")
        candidate_id = decision.get("candidate_id")
        if not isinstance(candidate_id, str) or not SELECTOR_PATTERN.fullmatch(candidate_id):
            raise ActionPlanError("validation candidate IDs must use owner/repo#123:E1")
        if candidate_id in indexed:
            raise ActionPlanError(f"validation contains duplicate candidate {candidate_id}")
        indexed[candidate_id] = decision
    return indexed


def candidate_publication_target(candidate: dict[str, Any]) -> dict[str, Any]:
    repository = candidate.get("owning_repository")
    if not isinstance(repository, str) or not repository:
        raise ActionPlanError("candidate owning_repository is missing")
    return target(repository, require_integer(candidate.get("owning_pr"), "candidate owning_pr"))


def require_candidate_route(candidate: dict[str, Any], action: str) -> None:
    classification = candidate.get("classification")
    suggested_action = candidate.get("suggested_action")
    if classification not in ACTION_CLASSIFICATIONS[action] or suggested_action != action:
        required = suggested_action if isinstance(suggested_action, str) else "no publication"
        raise ActionPlanError(
            f"candidate classification {classification!r} requires {required}, not {action}"
        )
    if action in {"reply-thread", "reopen-and-reply"}:
        thread_id = candidate.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise ActionPlanError(f"{action} requires an exact thread_id")


def prepare_action_plan(
    context: dict[str, Any],
    validation: dict[str, Any],
    selectors: list[str],
    action: str,
    expected_active: str,
    current_head: str,
    allow_cross_pr: bool = False,
    expected_publication_target: str | None = None,
    allow_incomplete_history: bool = False,
) -> dict[str, Any]:
    if action not in PUBLICATION_ACTIONS:
        raise ActionPlanError(f"unsupported publication action {action!r}")
    candidate_action = action in ACTION_CLASSIFICATIONS
    if candidate_action and not selectors:
        raise ActionPlanError("at least one qualified candidate selector is required")
    if not candidate_action and selectors:
        raise ActionPlanError(f"{action} does not accept candidate selectors")

    active_target = artifact_target(context, "pr", "context")
    expected_active_target = parse_target(expected_active, "expected active review target")
    if active_target != expected_active_target:
        raise ActionPlanError(
            f"context does not match active review target {expected_active}; found "
            f"{active_target['repository']}#{active_target['pr']}"
        )

    validation_target = artifact_target(validation, "review_pr", "validation")
    if validation_target != active_target:
        raise ActionPlanError("validation review target does not match the active review target")

    briefed_head = context.get("head_ref_oid")
    validation_head = validation.get("briefed_head_oid")
    if not isinstance(briefed_head, str) or not briefed_head:
        raise ActionPlanError("context head_ref_oid is missing")
    if validation_head != briefed_head:
        raise ActionPlanError("validation head does not match the active context head")
    if current_head != briefed_head:
        raise ActionPlanError("PR head changed after briefing; recollect and revalidate before publication")

    if (
        candidate_action
        and validation.get("duplicate_protection") != "complete"
        and not allow_incomplete_history
    ):
        raise ActionPlanError(
            "discussion history is incomplete; explicit incomplete-history confirmation is required"
        )

    items = []
    publication_targets = []
    if candidate_action:
        decisions = candidate_index(validation)
        for raw_selector in selectors:
            selector = parse_selector(raw_selector)
            selector_target = target(selector["repository"], selector["pr"])
            if selector_target != active_target:
                raise ActionPlanError(
                    f"selector {raw_selector} does not belong to the active review target "
                    f"{active_target['repository']}#{active_target['pr']}"
                )
            candidate = decisions.get(raw_selector)
            if candidate is None:
                raise ActionPlanError(f"candidate {raw_selector} is absent from active validation")
            if candidate.get("local_id") != selector["local_id"]:
                raise ActionPlanError(f"candidate {raw_selector} has an inconsistent local_id")
            require_candidate_route(candidate, action)
            item_target = candidate_publication_target(candidate)
            publication_targets.append(item_target)
            items.append(
                {
                    "candidate_id": raw_selector,
                    "local_id": selector["local_id"],
                    "classification": candidate.get("classification"),
                    "suggested_action": action,
                    "thread_id": candidate.get("thread_id"),
                    "thread_url": candidate.get("thread_url"),
                }
            )

    first_target = publication_targets[0] if publication_targets else active_target
    if any(item_target != first_target for item_target in publication_targets[1:]):
        raise ActionPlanError("one publication plan cannot span multiple PR targets")
    if first_target != active_target:
        if not allow_cross_pr:
            raise ActionPlanError(
                "cross-PR thread routing requires explicit cross-PR confirmation and publication target"
            )
        if expected_publication_target is None:
            raise ActionPlanError("expected publication target is required for a cross-PR action")
        if parse_target(expected_publication_target, "expected publication target") != first_target:
            raise ActionPlanError("expected publication target does not match the owning thread PR")
    elif expected_publication_target is not None:
        if parse_target(expected_publication_target, "expected publication target") != first_target:
            raise ActionPlanError("expected publication target does not match the active PR")

    plan = {
        "schema_version": 1,
        "action": action,
        "review_target": active_target,
        "publication_target": first_target,
        "briefed_head_oid": briefed_head,
        "current_head_oid": current_head,
        "duplicate_protection": validation.get("duplicate_protection"),
        "items": items,
    }
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    plan["action_id"] = hashlib.sha256(canonical).hexdigest()[:16]
    return plan


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ActionPlanError(f"{path} must contain a JSON object")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--selector", action="append", default=[])
    parser.add_argument("--action", choices=tuple(sorted(PUBLICATION_ACTIONS)), required=True)
    parser.add_argument("--expected-active", required=True)
    parser.add_argument("--current-head", required=True)
    parser.add_argument("--allow-cross-pr", action="store_true")
    parser.add_argument("--expected-publication-target")
    parser.add_argument("--allow-incomplete-history", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        plan = prepare_action_plan(
            load_json(args.context),
            load_json(args.validation),
            args.selector,
            args.action,
            args.expected_active,
            args.current_head,
            allow_cross_pr=args.allow_cross_pr,
            expected_publication_target=args.expected_publication_target,
            allow_incomplete_history=args.allow_incomplete_history,
        )
    except (ActionPlanError, json.JSONDecodeError, OSError) as error:
        print(f"publication blocked: {error}", file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
