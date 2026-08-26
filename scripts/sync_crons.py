#!/usr/bin/env python3
"""Reconcile repository-owned cron definitions through the Hermes cron CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


DEFAULT_CONFIG = "/opt/review-config/crons.json"
DEFAULT_STATE = "/opt/data/cron/repository-managed-jobs.json"
ENV_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
JOB_ID_RE = re.compile(r"Created job:\s*([A-Za-z0-9_-]+)")


class CronConfigError(RuntimeError):
    pass


def deployment_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(source or os.environ)
    if not env.get("TZ", "").strip():
        env["TZ"] = "America/Mexico_City"
    if not env.get("SLACK_REVIEW_DIGEST_USER_ID", "").strip():
        owners = [item.strip() for item in env.get("SLACK_REVIEW_OWNER_USER_IDS", "").split(",") if item.strip()]
        if len(owners) != 1:
            raise CronConfigError(
                "set SLACK_REVIEW_DIGEST_USER_ID or configure exactly one SLACK_REVIEW_OWNER_USER_IDS value"
            )
        env["SLACK_REVIEW_DIGEST_USER_ID"] = owners[0]
    return env


def expand(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            replacement = env.get(name, "").strip()
            if not replacement:
                raise CronConfigError(f"missing environment value for {name}")
            return replacement
        return ENV_RE.sub(replace, value)
    if isinstance(value, list):
        return [expand(item, env) for item in value]
    if isinstance(value, dict):
        return {key: expand(item, env) for key, item in value.items()}
    return value


def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CronConfigError(f"cannot read cron configuration: {exc}") from exc
    config = expand(raw, deployment_env(env))
    if config.get("version") != 1:
        raise CronConfigError("config/crons.json version must be 1")
    timezone_name = str(config.get("timezone") or "").strip()
    if not timezone_name:
        raise CronConfigError("cron timezone is required")
    jobs = config.get("jobs")
    if not isinstance(jobs, list):
        raise CronConfigError("cron jobs must be a list")
    seen: set[str] = set()
    for job in jobs:
        if not isinstance(job, dict):
            raise CronConfigError("every cron job must be an object")
        required = {"key", "name", "schedule", "prompt", "skills", "deliver", "workdir"}
        missing = required - set(job)
        if missing:
            raise CronConfigError(f"cron job is missing: {', '.join(sorted(missing))}")
        key = str(job["key"])
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", key) or key in seen:
            raise CronConfigError(f"invalid or duplicate cron key: {key}")
        seen.add(key)
        if len(str(job["schedule"]).split()) != 5:
            raise CronConfigError(f"cron schedule must have five fields: {key}")
        if not isinstance(job["skills"], list) or not job["skills"]:
            raise CronConfigError(f"cron job must declare at least one skill: {key}")
        if not str(job["deliver"]).startswith("slack:"):
            raise CronConfigError(f"cron delivery must be a Slack target: {key}")
    return config


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CronConfigError(f"cannot read managed cron state: {exc}") from exc
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise CronConfigError("managed cron state must map repository keys to Hermes job IDs")
    return value


def save_state(path: Path, state: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(sorted(state.items())), handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def execute(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), check=False, capture_output=True, text=True)


def common_arguments(job: Mapping[str, Any]) -> list[str]:
    arguments = [
        "--schedule", str(job["schedule"]),
        "--prompt", str(job["prompt"]),
        "--name", str(job["name"]),
        "--deliver", str(job["deliver"]),
        "--workdir", str(job["workdir"]),
    ]
    for skill in job["skills"]:
        arguments.extend(["--skill", str(skill)])
    return arguments


def create_job(job: Mapping[str, Any]) -> str:
    command = [
        "hermes", "cron", "create", str(job["schedule"]), str(job["prompt"]),
        "--name", str(job["name"]),
        "--deliver", str(job["deliver"]),
        "--workdir", str(job["workdir"]),
    ]
    for skill in job["skills"]:
        command.extend(["--skill", str(skill)])
    result = execute(command)
    if result.returncode:
        raise CronConfigError(result.stderr.strip() or result.stdout.strip() or "Hermes cron create failed")
    match = JOB_ID_RE.search(f"{result.stdout}\n{result.stderr}")
    if not match:
        raise CronConfigError("Hermes created a cron job but did not return its ID")
    return match.group(1)


def edit_job(job_id: str, job: Mapping[str, Any]) -> bool:
    result = execute(["hermes", "cron", "edit", job_id, *common_arguments(job)])
    if result.returncode == 0:
        return True
    detail = (result.stderr or result.stdout).strip()
    if "not found" in detail.lower():
        return False
    raise CronConfigError(detail or f"unable to edit cron job {job_id}")


def remove_job(job_id: str) -> None:
    result = execute(["hermes", "cron", "remove", job_id])
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        if "not found" in detail.lower():
            return
        raise CronConfigError(detail or f"unable to remove cron job {job_id}")


def reconcile(config: Mapping[str, Any], state_path: Path) -> dict[str, str]:
    configured_timezone = str(config["timezone"])
    runtime_timezone = os.environ.get("TZ", "").strip()
    if runtime_timezone != configured_timezone:
        raise CronConfigError(
            f"Hermes TZ is {runtime_timezone or 'unset'}, but config/crons.json requests {configured_timezone}; recreate the service after updating .review.env"
        )
    previous = load_state(state_path)
    current: dict[str, str] = {}
    for job in config["jobs"]:
        key = str(job["key"])
        job_id = previous.get(key)
        if not job_id or not edit_job(job_id, job):
            job_id = create_job(job)
        current[key] = job_id
    for key, job_id in previous.items():
        if key not in current:
            remove_job(job_id)
    save_state(state_path, current)
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("REVIEW_CRON_CONFIG", DEFAULT_CONFIG))
    parser.add_argument("--state", default=os.environ.get("REVIEW_CRON_STATE", DEFAULT_STATE))
    parser.add_argument("--check", action="store_true", help="validate without changing Hermes")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.check:
            print(f"Cron configuration is valid: {len(config['jobs'])} job(s), timezone {config['timezone']}")
            return 0
        state = reconcile(config, Path(args.state))
        print(f"Synchronized {len(state)} repository-managed Hermes cron job(s).")
        return 0
    except CronConfigError as exc:
        print(f"Cron configuration error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
