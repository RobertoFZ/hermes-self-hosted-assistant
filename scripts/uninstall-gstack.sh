#!/bin/sh
set -eu

docker compose exec -T --user hermes hermes \
  python3 /opt/review-tooling/remove_gstack.py

docker compose exec -T --user hermes hermes \
  python3 /opt/review-tooling/remove_gstack.py --check

echo "gstack skills are absent from the persistent container Codex profile."
