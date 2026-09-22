#!/usr/bin/env python3
"""Verify Linear's write tool inventory without invoking any MCP tool."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections.abc import Mapping
from typing import Any, TextIO


REQUEST_TIMEOUT_SECONDS = 60


class CapabilityCheckError(RuntimeError):
    pass


def read_messages(stream: TextIO, messages: queue.Queue[dict[str, Any]]) -> None:
    for line in stream:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            messages.put(message)


def request(
    process: subprocess.Popen[str],
    messages: queue.Queue[dict[str, Any]],
    request_id: int,
    method: str,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    if process.stdin is None:
        raise CapabilityCheckError("Codex app-server stdin is unavailable")
    payload = {
        "id": request_id,
        "method": method,
        "params": dict(params),
    }
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()
    deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CapabilityCheckError(f"Codex app-server timed out during {method}")
        try:
            response = messages.get(timeout=remaining)
        except queue.Empty as exc:
            raise CapabilityCheckError(
                f"Codex app-server timed out during {method}"
            ) from exc
        if response.get("id") != request_id:
            continue
        if "error" in response:
            raise CapabilityCheckError(f"Codex app-server rejected {method}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise CapabilityCheckError(f"Codex app-server returned no result for {method}")
        return result


def check_linear_issue_updates() -> None:
    process = subprocess.Popen(
        ["codex", "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    messages: queue.Queue[dict[str, Any]] = queue.Queue()
    if process.stdout is None:
        process.terminate()
        raise CapabilityCheckError("Codex app-server stdout is unavailable")
    reader = threading.Thread(
        target=read_messages,
        args=(process.stdout, messages),
        daemon=True,
    )
    reader.start()
    try:
        request(
            process,
            messages,
            1,
            "initialize",
            {
                "clientInfo": {
                    "name": "linear-capability-check",
                    "version": "1.0.0",
                },
                "capabilities": None,
            },
        )
        inventory = request(
            process,
            messages,
            2,
            "mcpServerStatus/list",
            {"detail": "toolsAndAuthOnly", "limit": 100},
        )
        servers = inventory.get("data")
        if not isinstance(servers, list):
            raise CapabilityCheckError("Codex returned an invalid MCP inventory")
        linear = next(
            (
                server
                for server in servers
                if isinstance(server, dict) and server.get("name") == "linear"
            ),
            None,
        )
        if linear is None:
            raise CapabilityCheckError("Linear MCP is missing from Codex inventory")
        tools = linear.get("tools")
        save_issue = tools.get("save_issue") if isinstance(tools, dict) else None
        if not isinstance(save_issue, dict):
            raise CapabilityCheckError(
                "Linear MCP does not expose the required save_issue capability"
            )
        input_schema = save_issue.get("inputSchema")
        properties = (
            input_schema.get("properties")
            if isinstance(input_schema, dict)
            else None
        )
        required_fields = {"id", "description", "state"}
        if not isinstance(properties, dict) or not required_fields <= properties.keys():
            raise CapabilityCheckError(
                "Linear save_issue cannot update descriptions and states"
            )
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    try:
        check_linear_issue_updates()
    except (CapabilityCheckError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print("Linear MCP capability check passed: issue updates are available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
