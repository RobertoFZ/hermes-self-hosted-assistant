#!/bin/sh
set -eu

docker compose exec -T --user hermes hermes /bin/sh -eu -c '
  repository="${REVIEW_MONOREPO_REPOSITORY:?set it in .review.env}"
  root="${REVIEW_MONOREPO_ROOT:?set it in .review.env}"
  helper=/opt/data/skills/custom/pr-reviewer/scripts/prepare-workspace.sh

  if [ -e "$root" ]; then
    "$helper" --check --root "$root"
    echo "Keeping existing review workspace: $root"
    exit 0
  fi

  gh auth status --active --hostname github.com >/dev/null
  mkdir -p "$(dirname "$root")"
  gh repo clone "$repository" "$root" -- --recurse-submodules
  "$helper" --check --root "$root"
'
