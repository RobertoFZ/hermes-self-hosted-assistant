#!/bin/sh
set -eu

: "${HERMES_UID:=10000}"
: "${HERMES_GID:=10000}"
: "${PASEO_HOME:=/opt/data/.paseo}"
: "${PASEO_PASSWORD:?set PASEO_PASSWORD in .env}"
: "${PASEO_DOCKER_CERT_SOURCE:=/run/paseo-docker-certs}"
: "${DOCKER_HOST:=tcp://paseo-docker:2376}"
: "${DOCKER_TLS_VERIFY:=1}"
: "${DOCKER_CERT_PATH:=$PASEO_HOME/docker-certs}"
export DOCKER_HOST DOCKER_TLS_VERIFY DOCKER_CERT_PATH

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

if [ -S /var/run/docker.sock ]; then
  echo "Refusing to start Paseo with the host Docker socket mounted." >&2
  exit 2
fi

install -d -m 0700 -o "$HERMES_UID" -g "$HERMES_GID" "$DOCKER_CERT_PATH"
for certificate in ca.pem cert.pem key.pem; do
  if [ ! -f "$PASEO_DOCKER_CERT_SOURCE/$certificate" ]; then
    echo "Missing isolated Docker TLS certificate: $certificate" >&2
    exit 2
  fi
  install -m 0400 -o "$HERMES_UID" -g "$HERMES_GID" \
    "$PASEO_DOCKER_CERT_SOURCE/$certificate" "$DOCKER_CERT_PATH/$certificate"
done

setpriv \
  --reuid="$HERMES_UID" \
  --regid="$HERMES_GID" \
  --clear-groups \
  docker info >/dev/null

exec setpriv \
  --reuid="$HERMES_UID" \
  --regid="$HERMES_GID" \
  --clear-groups \
  paseo daemon start \
    --foreground \
    --web-ui \
    --listen 0.0.0.0:6767 \
    --home "$PASEO_HOME"
