#!/bin/sh
set -eu

docker compose exec -T --user hermes hermes /bin/sh -eu -c '
  require_value() {
    name="$1"
    eval "value=\${$name:-}"
    if [ -z "$value" ]; then
      echo "Missing $name in .review.env" >&2
      exit 1
    fi
  }

  require_value SLACK_ALLOWED_USERS
  require_value SLACK_REVIEW_OWNER_USER_IDS
  require_value SLACK_REVIEW_CHANNEL_ID
  require_value SLACK_REVIEW_ALLOWED_REPOSITORIES
  require_value REVIEW_MONOREPO_ROOT

  python -c "import os,sys; values=lambda name: {item.strip() for item in os.environ.get(name, \"\").split(\",\") if item.strip()}; allowed=values(\"SLACK_ALLOWED_USERS\"); required=values(\"SLACK_REVIEW_OWNER_USER_IDS\") | values(\"SLACK_REVIEWER_USER_IDS\") | values(\"SLACK_REVIEW_BOT_USER_IDS\"); sys.exit(0 if required <= allowed else \"Every owner, reviewer, and review bot must also be present in SLACK_ALLOWED_USERS\")"

  case "$SLACK_REVIEW_CHANNEL_ID" in
    C[A-Z0-9]*|G[A-Z0-9]*) ;;
    *) echo "Invalid SLACK_REVIEW_CHANNEL_ID" >&2; exit 1 ;;
  esac

  python -c "import os; from hermes_cli.config import save_env_value; save_env_value(\"SLACK_ALLOWED_USERS\", os.environ[\"SLACK_ALLOWED_USERS\"])"

  channel_prompts="$(python -c "import json,os; print(json.dumps({os.environ[\"SLACK_REVIEW_CHANNEL_ID\"]: \"Delegate only exact pull request URLs from the current triggering message through codex-pr-review. Never inherit URLs from thread context or discover additional PRs. After the command finishes, send exactly one final response containing only GitHub-verified results.\"}))")"
  channel_bindings="$(python -c "import json,os; print(json.dumps([{\"id\": os.environ[\"SLACK_REVIEW_CHANNEL_ID\"], \"skill\": \"codex-pr-review\"}]))")"
  owner_ids="$(python -c "import json,os; print(json.dumps([value.strip() for value in os.environ[\"SLACK_REVIEW_OWNER_USER_IDS\"].split(\",\") if value.strip()]))")"

  hermes config set terminal.cwd "$REVIEW_MONOREPO_ROOT"
  hermes config set slack.require_mention true
  hermes config set slack.allowed_channels "$SLACK_REVIEW_CHANNEL_ID"
  hermes config set slack.free_response_channels "$SLACK_REVIEW_CHANNEL_ID"
  hermes config set slack.channel_prompts "$channel_prompts"
  hermes config set slack.channel_skill_bindings "$channel_bindings"
  hermes config set slack.ignore_other_user_mentions false
  hermes config set slack.thread_require_mention false
  hermes config set gateway.platforms.slack.extra.allow_bots all
  hermes config set gateway.platforms.slack.extra.allow_admin_from "$owner_ids"
  hermes config set gateway.platforms.slack.extra.user_allowed_commands "[]"
  hermes config set gateway.platforms.slack.extra.group_allow_admin_from "$owner_ids"
  hermes config set gateway.platforms.slack.extra.group_user_allowed_commands "[]"
  hermes config set display.platforms.slack.tool_progress off
  hermes config set display.platforms.slack.interim_assistant_messages false
  hermes config set display.platforms.slack.long_running_notifications false
  hermes config set display.platforms.slack.busy_ack_detail false
  hermes config set display.platforms.slack.live_status off
  hermes config set display.platforms.slack.thinking_progress false
  hermes plugins enable --no-allow-tool-override slack-pr-review-gate
'

echo "Applied the review-only Slack policy. Restart Hermes to reload it."
