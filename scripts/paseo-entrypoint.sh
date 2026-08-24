#!/bin/sh
set -eu

: "${HERMES_UID:=10000}"
: "${HERMES_GID:=10000}"
: "${PASEO_HOME:=/opt/data/.paseo}"
: "${PASEO_PASSWORD:?set PASEO_PASSWORD in .env}"

case "$HERMES_UID:$HERMES_GID" in
  *[!0-9:]*|:*|*:) echo "HERMES_UID and HERMES_GID must be numeric." >&2; exit 2 ;;
esac

# Prepare only Paseo's state directory. Hermes remains responsible for the
# rest of the shared volume, and the daemon itself never runs as root.
install -d -m 0700 -o "$HERMES_UID" -g "$HERMES_GID" "$PASEO_HOME"
if [ ! -f "$PASEO_HOME/config.json" ]; then
  install -m 0600 -o "$HERMES_UID" -g "$HERMES_GID" \
    /usr/local/share/paseo/config.json "$PASEO_HOME/config.json"
fi

exec setpriv \
  --reuid="$HERMES_UID" \
  --regid="$HERMES_GID" \
  --clear-groups \
  paseo daemon start \
    --foreground \
    --web-ui \
    --listen 0.0.0.0:6767 \
    --home "$PASEO_HOME"
