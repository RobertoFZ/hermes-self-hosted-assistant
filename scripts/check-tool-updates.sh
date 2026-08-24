#!/bin/sh
set -eu

command -v docker >/dev/null 2>&1 || {
  echo "Missing required command: docker" >&2
  exit 1
}
docker compose version >/dev/null

docker compose exec -T --user hermes paseo \
  env npm_config_cache=/tmp/paseo-npm-cache /bin/sh -eu -c '
    version_status() {
      installed="$1"
      latest="$2"

      if [ "$installed" = "$latest" ]; then
        printf "%s" "current"
      elif [ "$(printf "%s\n%s\n" "$installed" "$latest" | sort -V | tail -n 1)" = "$latest" ]; then
        printf "%s" "update available"
      else
        printf "%s" "installed newer"
      fi
    }

    codex_installed="$(codex --version)"
    codex_installed="${codex_installed#codex-cli }"
    paseo_installed="$(paseo --version)"
    codex_latest="$(npm view --silent "@openai/codex" dist-tags.latest)"
    paseo_latest="$(npm view --silent "@getpaseo/cli" dist-tags.latest)"

    test -n "$codex_installed"
    test -n "$paseo_installed"
    test -n "$codex_latest"
    test -n "$paseo_latest"

    printf "%-10s %-14s %-14s %s\n" "TOOL" "INSTALLED" "LATEST" "STATUS"
    printf "%-10s %-14s %-14s %s\n" \
      "Codex" "$codex_installed" "$codex_latest" \
      "$(version_status "$codex_installed" "$codex_latest")"
    printf "%-10s %-14s %-14s %s\n" \
      "Paseo" "$paseo_installed" "$paseo_latest" \
      "$(version_status "$paseo_installed" "$paseo_latest")"
  '
