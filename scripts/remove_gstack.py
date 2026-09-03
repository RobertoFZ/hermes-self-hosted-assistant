#!/usr/bin/env python3
"""Remove gstack skill registrations from explicitly selected skill roots."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DEFAULT_ROOTS = (
    Path("/opt/data/.codex/skills"),
    Path("/opt/data/.agents/skills"),
)


def is_gstack_entry(path: Path) -> bool:
    return path.name == "gstack" or path.name.startswith("gstack-")


def find_gstack_entries(roots: list[Path]) -> list[Path]:
    entries: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        entries.extend(path for path in root.iterdir() if is_gstack_entry(path))
    return sorted(entries, key=str)


def remove_entry(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        action="append",
        type=Path,
        dest="roots",
        help="Skill root to inspect; repeat to override the container defaults.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report remaining gstack entries without deleting them.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    roots = args.roots or list(DEFAULT_ROOTS)
    entries = find_gstack_entries(roots)

    if args.check:
        for path in entries:
            print(path)
        return 1 if entries else 0

    for path in entries:
        remove_entry(path)
        print(f"Removed {path}")

    noun = "entry" if len(entries) == 1 else "entries"
    print(f"Removed {len(entries)} gstack skill {noun}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
