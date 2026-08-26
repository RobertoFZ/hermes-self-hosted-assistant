#!/bin/sh
set -eu

docker compose exec -T --user hermes hermes \
  python3 /opt/review-tooling/sync_crons.py
