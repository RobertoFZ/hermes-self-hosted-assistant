#!/usr/bin/env python3
"""Apply repository-managed Paseo settings without replacing local state."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


MANAGED_AGENT_PROVIDERS = ("codex-review",)


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def sync_managed_settings(defaults: dict[str, Any], current: dict[str, Any]) -> bool:
    default_providers = defaults["agents"]["providers"]
    current_providers = current.setdefault("agents", {}).setdefault("providers", {})
    changed = False
    for provider in MANAGED_AGENT_PROVIDERS:
        desired = default_providers[provider]
        if current_providers.get(provider) != desired:
            current_providers[provider] = desired
            changed = True
    return changed


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: sync-paseo-config.py DEFAULTS CURRENT")
    defaults_path = Path(sys.argv[1])
    current_path = Path(sys.argv[2])
    defaults = load_object(defaults_path)
    current = load_object(current_path)
    if sync_managed_settings(defaults, current):
        write_atomic(current_path, current)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
