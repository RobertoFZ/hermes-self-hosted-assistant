#!/bin/sh
set -eu

repository_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
source_skill="$repository_root/skills/pr-reviewer"
codex_root="${CODEX_HOME:-${HOME:?}/.codex}"
target="$codex_root/skills/pr-reviewer"

mkdir -p "$(dirname "$target")"
if [ -L "$target" ] && [ "$(readlink "$target")" = "$source_skill" ]; then
  echo "Global skill already points to $source_skill"
  exit 0
fi

if [ -e "$target" ] || [ -L "$target" ]; then
  backup="${target}.backup.$(date +%Y%m%d%H%M%S)"
  mv -- "$target" "$backup"
  echo "Preserved the previous global skill at $backup"
fi

ln -s "$source_skill" "$target"
echo "Installed global pr-reviewer symlink: $target"
