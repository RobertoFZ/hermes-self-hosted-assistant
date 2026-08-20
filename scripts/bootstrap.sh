#!/bin/sh
set -eu

repository_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
cd "$repository_root"

for command in docker openssl; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Missing required command: $command" >&2
    exit 1
  }
done
docker compose version >/dev/null

set_if_empty() {
  file="$1"
  key="$2"
  value="$3"
  current="$(sed -n "s/^${key}=//p" "$file" | tail -n 1)"
  [ -z "$current" ] || return 0

  temporary="$(mktemp "${file}.XXXXXX")"
  awk -v key="$key" -v value="$value" '
    BEGIN { replaced = 0 }
    index($0, key "=") == 1 { print key "=" value; replaced = 1; next }
    { print }
    END { if (!replaced) print key "=" value }
  ' "$file" > "$temporary"
  mv -- "$temporary" "$file"
}

umask 077
if [ ! -f .env ]; then
  cp .env.example .env
  set_if_empty .env HERMES_DASHBOARD_BASIC_AUTH_USERNAME admin
  set_if_empty .env HERMES_DASHBOARD_BASIC_AUTH_PASSWORD "$(openssl rand -hex 24)"
  set_if_empty .env HERMES_DASHBOARD_BASIC_AUTH_SECRET "$(openssl rand -hex 32)"
  echo "Created .env with generated dashboard credentials."
else
  echo "Keeping existing .env."
fi
chmod 600 .env

if [ ! -f .review.env ]; then
  cp .review.env.example .review.env
  echo "Created .review.env; fill in the Slack IDs before enabling Slack."
else
  echo "Keeping existing .review.env."
fi
chmod 600 .review.env

echo "Bootstrap files are ready. Run 'make build' and 'make up'."
