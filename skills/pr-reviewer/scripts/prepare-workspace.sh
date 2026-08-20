#!/bin/sh

set -eu

expected_repository="${REVIEW_MONOREPO_REPOSITORY:-reservamos/reserhub-revenue-full}"
monorepo_name="${expected_repository##*/}"
expected_submodules_csv="${REVIEW_SUBMODULES:-price-engine-python,reserhub-intelligence-api,reserhub-revenue-admin,reserhub-revenue-web,scrapers-swarm}"
EXPECTED_SUBMODULES="$(printf '%s' "$expected_submodules_csv" | tr ',' ' ')"

usage() {
  echo "Usage: prepare-workspace.sh [--check|--fetch] [--root PATH]" >&2
  exit 2
}

mode="--check"
explicit_root=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --check|--fetch)
      mode="$1"
      shift
      ;;
    --root)
      [ "$#" -ge 2 ] || usage
      explicit_root="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

is_expected_root() {
  candidate="$1"
  [ -d "$candidate/.git" ] || return 1
  origin="$(git -C "$candidate" remote get-url origin 2>/dev/null || true)"
  case "$origin" in
    "https://github.com/$expected_repository"|\
    "https://github.com/$expected_repository.git"|\
    "git@github.com:$expected_repository"|\
    "git@github.com:$expected_repository.git"|\
    "ssh://git@github.com/$expected_repository"|\
    "ssh://git@github.com/$expected_repository.git")
      return 0
      ;;
  esac
  return 1
}

resolve_root() {
  if [ -n "$explicit_root" ]; then
    is_expected_root "$explicit_root" || {
      echo "Invalid monorepo root: $explicit_root" >&2
      exit 1
    }
    (cd "$explicit_root" && pwd -P)
    return
  fi

  configured_root="${REVIEW_MONOREPO_ROOT:-${RESERHUB_MONOREPO_ROOT:-}}"
  if [ -n "$configured_root" ] && is_expected_root "$configured_root"; then
    (cd "$configured_root" && pwd -P)
    return
  fi

  current_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  while [ -n "$current_root" ]; do
    if is_expected_root "$current_root"; then
      (cd "$current_root" && pwd -P)
      return
    fi
    parent="$(dirname "$current_root")"
    [ "$parent" != "$current_root" ] || break
    current_root="$parent"
  done

  for candidate in \
    "/opt/data/repos/$monorepo_name" \
    "${HOME:-}/code/$expected_repository"
  do
    if [ -n "$candidate" ] && is_expected_root "$candidate"; then
      (cd "$candidate" && pwd -P)
      return
    fi
  done

  echo "Could not resolve the Reserhub Revenue monorepo." >&2
  echo "Set REVIEW_MONOREPO_ROOT to its absolute path." >&2
  exit 1
}

remote_ref() {
  repo="$1"
  symbolic="$(git -C "$repo" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
  if [ -n "$symbolic" ] && git -C "$repo" rev-parse --verify --quiet "$symbolic^{commit}" >/dev/null; then
    echo "$symbolic"
    return
  fi
  for candidate in origin/develop origin/main origin/master; do
    if git -C "$repo" rev-parse --verify --quiet "$candidate^{commit}" >/dev/null; then
      echo "$candidate"
      return
    fi
  done
  echo "WORKTREE"
}

root="$(resolve_root)"

for submodule in $EXPECTED_SUBMODULES; do
  path="$root/$submodule"
  if [ ! -d "$path" ] || ! git -C "$path" rev-parse --git-dir >/dev/null 2>&1; then
    echo "Missing or uninitialized submodule: $path" >&2
    exit 1
  fi
done

if [ "$mode" = "--fetch" ]; then
  git -C "$root" fetch --prune origin
  for submodule in $EXPECTED_SUBMODULES; do
    git -C "$root/$submodule" fetch --prune origin
  done
fi

echo "MONOREPO_ROOT=$root"
echo "reserhub-revenue-full=$(remote_ref "$root")"
for submodule in $EXPECTED_SUBMODULES; do
  echo "$submodule=$(remote_ref "$root/$submodule")"
done
