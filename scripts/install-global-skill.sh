#!/bin/sh
set -eu

repository_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
codex_root="${CODEX_HOME:-${HOME:?}/.codex}"

workflow_skills="
codex-self-review
pr-reviewer
pr-decision-review
writing-for-agents
retro
"
retired_workflow_skills="
auto-pr-workflow
linear-ticket-selection
merge-pr-and-clean-worktree
prepare-branch-for-pr
publish-ready-pr
ticket-openspec-planning
"

mkdir -p "$codex_root/skills"

for skill_name in $retired_workflow_skills; do
  former_source_skill="$repository_root/skills/$skill_name"
  target="$codex_root/skills/$skill_name"

  if [ -L "$target" ] && [ "$(readlink "$target")" = "$former_source_skill" ]; then
    rm -- "$target"
    echo "Removed retired repository skill symlink: $target"
  fi
done

for skill_name in $workflow_skills; do
  source_skill="$repository_root/skills/$skill_name"
  if [ ! -f "$source_skill/SKILL.md" ]; then
    echo "Missing repository skill: $source_skill/SKILL.md" >&2
    exit 1
  fi
done

for skill_name in $workflow_skills; do
  source_skill="$repository_root/skills/$skill_name"
  target="$codex_root/skills/$skill_name"

  if [ -L "$target" ] && [ "$(readlink "$target")" = "$source_skill" ]; then
    echo "Global skill already points to $source_skill"
    continue
  fi

  if [ -e "$target" ] || [ -L "$target" ]; then
    backup="${target}.backup.$(date +%Y%m%d%H%M%S)"
    while [ -e "$backup" ] || [ -L "$backup" ]; do
      backup="${backup}.next"
    done
    mv -- "$target" "$backup"
    echo "Preserved the previous global skill at $backup"
  fi

  ln -s "$source_skill" "$target"
  echo "Installed global skill symlink: $target"
done

echo "Restart Codex to refresh the discovered skill catalog."
