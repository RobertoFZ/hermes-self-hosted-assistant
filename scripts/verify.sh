#!/bin/sh
set -eu

docker compose config --quiet
docker compose exec -T --user hermes hermes /bin/sh -eu -c '
  : "${REVIEW_MONOREPO_ROOT:?set it in .review.env}"
  : "${SLACK_REVIEW_CHANNEL_ID:?set it in .review.env}"
  : "${PASEO_HOST:?PASEO_HOST is not configured}"

  python -c "import os,sys; values=lambda name: {item.strip() for item in os.environ.get(name, \"\").split(\",\") if item.strip()}; allowed=values(\"SLACK_ALLOWED_USERS\"); required=values(\"SLACK_REVIEW_OWNER_USER_IDS\") | values(\"SLACK_REVIEWER_USER_IDS\") | values(\"SLACK_REVIEW_BOT_USER_IDS\"); sys.exit(0 if required <= allowed else \"Slack policy users or bots are missing from SLACK_ALLOWED_USERS\")"

  hermes auth status openai-codex
  gh auth status --active --hostname github.com
  git config --global --get-regexp "^credential\\.https://github\\.com\\.helper$" | grep -F "gh auth git-credential" >/dev/null
  GIT_TERMINAL_PROMPT=0 git -C "$REVIEW_MONOREPO_ROOT" ls-remote --exit-code origin HEAD >/dev/null
  # Exercise the same authenticated cross-container WebSocket path used by
  # codex-pr-review. A localhost-only check would miss hostname rejections.
  paseo project ls --host "$PASEO_HOST" --json | grep -F "$REVIEW_MONOREPO_ROOT" >/dev/null
  command -v bwrap >/dev/null
  test "$(codex --version)" = "codex-cli $CODEX_VERSION"
  codex login status
  codex plugin list --json | python3 -c "import json,sys; items=json.load(sys.stdin).get(\"installed\", []); sys.exit(\"Compound Engineering remains installed\" if any(x.get(\"name\") == \"compound-engineering\" for x in items) else 0)"
  test "$(openspec --version)" = "$OPENSPEC_VERSION"
  hermes skills list | grep -F codex-pr-review >/dev/null
  hermes skills list | grep -F review-digest >/dev/null
  test ! -e /opt/data/skills/custom/pr-reviewer
  hermes plugins list | grep -F slack-pr-review-gate >/dev/null
  python -c "import os,subprocess,sys,yaml; get=lambda key: yaml.safe_load(subprocess.check_output([\"hermes\", \"config\", \"get\", key], text=True)); expected={value.strip() for value in os.environ[\"SLACK_REVIEW_OWNER_USER_IDS\"].split(\",\") if value.strip()}; valid=get(\"gateway.platforms.slack.extra.allow_bots\") == \"all\" and set(get(\"gateway.platforms.slack.extra.allow_admin_from\") or []) == expected and get(\"gateway.platforms.slack.extra.user_allowed_commands\") == [] and set(get(\"gateway.platforms.slack.extra.group_allow_admin_from\") or []) == expected and get(\"gateway.platforms.slack.extra.group_user_allowed_commands\") == []; sys.exit(0 if valid else \"Slack review or slash-command access policy is not applied\")"
  /opt/review-workspace/prepare-workspace.sh --check
  python3 /opt/review-automation/review_automation.py init >/dev/null
  python3 /opt/review-tooling/sync_crons.py --check
  hermes cron list | grep -F "Daily PR review digest" >/dev/null
  test "$(hermes config get terminal.cwd)" = "$REVIEW_MONOREPO_ROOT"
'

docker compose exec -T --user hermes paseo /bin/sh -eu -c '
  : "${REVIEW_MONOREPO_ROOT:?set it in .review.env}"
  test "$DOCKER_HOST" = "tcp://paseo-docker:2376"
  test "$DOCKER_TLS_VERIFY" = "1"
  test ! -S /var/run/docker.sock
  docker info --format "{{.ServerVersion}}" >/dev/null
  docker compose version >/dev/null
  docker run --rm \
    --mount "type=bind,src=$REVIEW_MONOREPO_ROOT,dst=/workspace,readonly" \
    alpine:3.22 test -f /workspace/README.md
  test "$(paseo --version)" = "$PASEO_VERSION"
  test "$(openspec --version)" = "$OPENSPEC_VERSION"
  (cd "$REVIEW_MONOREPO_ROOT" && openspec context --json >/dev/null)
  codex login status
  codex plugin list --json | python3 -c "import json,sys; items=json.load(sys.stdin).get(\"installed\", []); sys.exit(\"Compound Engineering remains installed\" if any(x.get(\"name\") == \"compound-engineering\" for x in items) else 0)"
  curl --fail --silent --show-error http://127.0.0.1:6767/api/health >/dev/null
  paseo provider diagnostic --host 127.0.0.1:6767 --json codex >/dev/null
  paseo project ls --host 127.0.0.1:6767 --json | grep -F "$REVIEW_MONOREPO_ROOT" >/dev/null
  for skill_name in \
    codex-self-review \
    pr-reviewer \
    pr-decision-review
  do
    test -f "/opt/data/.agents/skills/$skill_name/SKILL.md"
  done
  for skill_name in \
    auto-pr-workflow \
    linear-ticket-selection \
    merge-pr-and-clean-worktree \
    prepare-branch-for-pr \
    publish-ready-pr \
    ticket-openspec-planning
  do
    skill_path="/opt/data/.agents/skills/$skill_name"
    test ! -e "$skill_path"
    test ! -L "$skill_path"
  done
  for skill_name in openspec-propose openspec-apply-change
  do
    skill_file="$REVIEW_MONOREPO_ROOT/.agents/skills/$skill_name/SKILL.md"
    if [ ! -f "$skill_file" ]; then
      skill_file="$REVIEW_MONOREPO_ROOT/.codex/skills/$skill_name/SKILL.md"
    fi
    test -f "$skill_file"
    grep -F "generatedBy: \"$OPENSPEC_VERSION\"" "$skill_file" >/dev/null
  done
  codex mcp get linear | grep -F "https://mcp.linear.app/mcp/readonly" >/dev/null
  linear_status="$(codex mcp list | awk '\''$1 == "linear" { print }'\'')"
  test -n "$linear_status"
  ! printf "%s\n" "$linear_status" | grep -F "Not logged in" >/dev/null
'

echo "Hermes orchestration, Codex review skills, Paseo, GitHub verification, review history, digest cron, plugin, and workspace are ready."
