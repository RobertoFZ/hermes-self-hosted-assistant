#!/bin/sh
set -eu

printf '%s\n' \
  "Choose what to install:" \
  "  1) Hermes assistant" \
  "  2) Codex + Paseo coding workspace" \
  "  3) Full stack with Slack PR reviews"
printf 'Selection [1-3]: '
IFS= read -r selection || {
  echo "No selection received." >&2
  exit 2
}

case "$selection" in
  1) target=bootstrap-hermes ;;
  2) target=bootstrap-paseo ;;
  3) target=bootstrap ;;
  *) echo "Choose 1, 2, or 3." >&2; exit 2 ;;
esac

exec make "$target"
