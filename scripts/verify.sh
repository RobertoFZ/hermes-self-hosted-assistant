#!/bin/sh
set -eu

docker compose config --quiet
docker compose exec -T --user hermes hermes /bin/sh -eu -c '
  : "${REVIEW_MONOREPO_ROOT:?set it in .review.env}"
  : "${SLACK_REVIEW_CHANNEL_ID:?set it in .review.env}"

  python -c "import os,sys; values=lambda name: {item.strip() for item in os.environ.get(name, \"\").split(\",\") if item.strip()}; allowed=values(\"SLACK_ALLOWED_USERS\"); required=values(\"SLACK_REVIEW_OWNER_USER_IDS\") | values(\"SLACK_REVIEWER_USER_IDS\"); sys.exit(0 if required <= allowed else \"Slack policy users are missing from SLACK_ALLOWED_USERS\")"

  hermes auth status openai-codex
  gh auth status --active --hostname github.com
  git config --global --get-regexp "^credential\\.https://github\\.com\\.helper$" | grep -F "gh auth git-credential" >/dev/null
  GIT_TERMINAL_PROMPT=0 git -C "$REVIEW_MONOREPO_ROOT" ls-remote --exit-code origin HEAD >/dev/null
  command -v bwrap >/dev/null
  test "$(codex --version)" = "codex-cli $CODEX_VERSION"
  codex login status
  test "$(openspec --version)" = "$OPENSPEC_VERSION"
  hermes skills list | grep -F pr-reviewer >/dev/null
  hermes plugins list | grep -F slack-pr-review-gate >/dev/null
  python -c "import os,subprocess,sys,yaml; get=lambda key: yaml.safe_load(subprocess.check_output([\"hermes\", \"config\", \"get\", key], text=True)); expected={value.strip() for value in os.environ[\"SLACK_REVIEW_OWNER_USER_IDS\"].split(\",\") if value.strip()}; valid=set(get(\"gateway.platforms.slack.extra.allow_admin_from\") or []) == expected and get(\"gateway.platforms.slack.extra.user_allowed_commands\") == [] and set(get(\"gateway.platforms.slack.extra.group_allow_admin_from\") or []) == expected and get(\"gateway.platforms.slack.extra.group_user_allowed_commands\") == []; sys.exit(0 if valid else \"Slack slash-command access policy is not applied\")"
  /opt/data/skills/custom/pr-reviewer/scripts/prepare-workspace.sh --check
  test "$(hermes config get terminal.cwd)" = "$REVIEW_MONOREPO_ROOT"
'

docker compose exec -T --user hermes paseo /bin/sh -eu -c '
  : "${REVIEW_MONOREPO_ROOT:?set it in .review.env}"
  test "$(paseo --version)" = "$PASEO_VERSION"
  codex login status
  curl --fail --silent --show-error http://127.0.0.1:6767/api/health >/dev/null
  paseo provider diagnostic --host 127.0.0.1:6767 --json codex >/dev/null
  paseo project ls --host 127.0.0.1:6767 --json | grep -F "$REVIEW_MONOREPO_ROOT" >/dev/null
'

echo "Hermes, Codex CLI, Paseo, GitHub, OpenSpec, skill, plugin, and workspace are ready."
