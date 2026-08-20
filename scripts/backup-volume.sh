#!/bin/sh
set -eu

archive="${1:-}"
if [ -z "$archive" ]; then
  echo "Usage: scripts/backup-volume.sh /absolute/path/hermes-data.tgz" >&2
  exit 2
fi
case "$archive" in
  /*) ;;
  *) echo "Backup path must be absolute." >&2; exit 2 ;;
esac

if [ -n "$(docker compose ps -q hermes 2>/dev/null || true)" ]; then
  echo "Stop Hermes with 'make down' before creating a consistent backup." >&2
  exit 1
fi

configured_volume="$(sed -n 's/^HERMES_DATA_VOLUME=//p' .env 2>/dev/null | tail -n 1)"
volume="${HERMES_DATA_VOLUME:-${configured_volume:-self-assistant-hermes-data}}"
case "$volume" in
  ""|*[!A-Za-z0-9_.-]*) echo "Invalid Docker volume name." >&2; exit 2 ;;
esac
docker volume inspect "$volume" >/dev/null
mkdir -p "$(dirname "$archive")"
umask 077
temporary="${archive}.partial.$$"
trap 'rm -f -- "$temporary"' EXIT HUP INT TERM
docker run --rm -v "$volume:/source:ro" alpine:3.22 \
  tar czf - -C /source . > "$temporary"
mv -- "$temporary" "$archive"
trap - EXIT HUP INT TERM
echo "Created secret-bearing volume backup: $archive"
