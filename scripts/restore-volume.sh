#!/bin/sh
set -eu

archive="${1:-}"
if [ -z "$archive" ] || [ ! -f "$archive" ]; then
  echo "Usage: scripts/restore-volume.sh /absolute/path/hermes-data.tgz" >&2
  exit 2
fi
case "$archive" in
  /*) ;;
  *) echo "Backup path must be absolute." >&2; exit 2 ;;
esac

if [ -n "$(docker compose ps -q hermes 2>/dev/null || true)" ]; then
  echo "Stop Hermes with 'make down' before restoring a backup." >&2
  exit 1
fi

configured_volume="$(sed -n 's/^HERMES_DATA_VOLUME=//p' .env 2>/dev/null | tail -n 1)"
volume="${HERMES_DATA_VOLUME:-${configured_volume:-self-assistant-hermes-data}}"
case "$volume" in
  ""|*[!A-Za-z0-9_.-]*) echo "Invalid Docker volume name." >&2; exit 2 ;;
esac
docker volume inspect "$volume" >/dev/null 2>&1 || docker volume create "$volume" >/dev/null
if docker run --rm -v "$volume:/destination" alpine:3.22 \
  sh -c 'test -z "$(find /destination -mindepth 1 -print -quit)"'; then
  :
else
  echo "Refusing to restore into non-empty volume: $volume" >&2
  exit 1
fi

docker run --rm -i -v "$volume:/destination" alpine:3.22 \
  sh -c 'cd /destination && tar xzf -' < "$archive"
echo "Restored volume: $volume"
