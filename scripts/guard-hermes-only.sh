#!/bin/sh
set -eu

if [ -f .review.env ] && grep -Eq '^REVIEW_MONOREPO_ROOT=.' .review.env; then
  echo "Cannot switch to Hermes-only while the PR review workspace is configured; review jobs and reminders require the Paseo service. Keep the full profile or disable the review setup and managed jobs first." >&2
  exit 1
fi

compose_config="$(docker compose --profile full config --format json)" || {
  echo "Could not resolve the Hermes data volume through Compose; refusing to stop Paseo." >&2
  exit 2
}
config_values="$(printf '%s\n' "$compose_config" | python3 -c 'import json,sys; config=json.load(sys.stdin); service=config["services"]["hermes"]; mount=next(item for item in service["volumes"] if item.get("target") == "/opt/data"); print(config["volumes"][mount["source"]]["name"]); print(service["image"])')" || {
  echo "Could not read the Hermes data volume from Compose; refusing to stop Paseo." >&2
  exit 2
}
volume="$(printf '%s\n' "$config_values" | sed -n '1p')"
image="$(printf '%s\n' "$config_values" | sed -n '2p')"
[ -n "$volume" ] && [ -n "$image" ] || {
  echo "Compose did not provide the Hermes data volume and image; refusing to stop Paseo." >&2
  exit 2
}

if ! docker info >/dev/null 2>&1; then
  echo "Could not reach Docker to inspect Hermes data; refusing to stop Paseo." >&2
  exit 2
fi

existing_volume="$(docker volume ls -q --filter "name=$volume")" || {
  echo "Could not list Docker volumes to inspect Hermes data; refusing to stop Paseo." >&2
  exit 2
}

if printf '%s\n' "$existing_volume" | grep -Fxq "$volume"; then
  if docker run --rm --network none \
    --mount "type=volume,src=$volume,dst=/opt/data,readonly" \
    --entrypoint /bin/sh "$image" \
    -c 'test -s /opt/data/cron/repository-managed-jobs.json'; then
    echo "Cannot switch to Hermes-only while managed Hermes cron jobs are persisted; disable them before stopping Paseo." >&2
    exit 1
  else
    status=$?
    if [ "$status" -ne 1 ]; then
      echo "Could not inspect the persisted Hermes cron state; refusing to stop Paseo." >&2
      exit 2
    fi
  fi
fi
