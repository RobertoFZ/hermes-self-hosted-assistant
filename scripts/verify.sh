#!/bin/sh
set -eu

docker compose --profile full config --quiet
docker compose exec -T --user hermes hermes /bin/sh -eu -c '
  : "${REVIEW_MONOREPO_ROOT:?set it in .review.env}"
  : "${SLACK_REVIEW_CHANNEL_ID:?set it in .review.env}"
  : "${PASEO_HOST:?PASEO_HOST is not configured}"

  python -c "import os,sys; values=lambda name: {item.strip() for item in os.environ.get(name, \"\").split(\",\") if item.strip()}; allowed=values(\"SLACK_ALLOWED_USERS\"); required=values(\"SLACK_REVIEW_OWNER_USER_IDS\") | values(\"SLACK_REVIEWER_USER_IDS\") | values(\"SLACK_REVIEW_BOT_USER_IDS\"); sys.exit(0 if required <= allowed else \"Slack policy users or bots are missing from SLACK_ALLOWED_USERS\")"
  python -c "import os,re,sys; owners={item.strip() for item in os.environ.get(\"SLACK_REVIEW_OWNER_USER_IDS\", \"\").split(\",\") if item.strip()}; explicit=os.environ.get(\"SLACK_REVIEW_DIGEST_USER_ID\", \"\").strip(); decision=explicit or (next(iter(owners)) if len(owners) == 1 else \"\"); valid=bool(decision and decision in owners and re.fullmatch(r\"[UW][A-Z0-9_]+\", decision)); sys.exit(0 if valid else \"Exactly one Slack user ID decision owner must be configured and present in SLACK_REVIEW_OWNER_USER_IDS\")"
  python -c "import os,sys; defaults={\"SLACK_REVIEW_MAX_URLS_PER_MESSAGE\":5,\"SLACK_REVIEW_MAX_ACTIVE_PER_REQUESTER\":5,\"SLACK_REVIEW_MAX_QUEUED\":50,\"SLACK_REVIEW_PROPOSAL_CONCURRENCY\":3}; invalid=[]; [(invalid.append(name)) for name,default in defaults.items() if not os.environ.get(name, str(default)).isdigit() or int(os.environ.get(name, str(default))) < 1]; sys.exit(0 if not invalid else \"Review queue settings must be positive integers: \" + \", \".join(invalid))"

  hermes auth status openai-codex
  gh auth status --active --hostname github.com
  git config --global --get-regexp "^credential\\.https://github\\.com\\.helper$" | grep -F "gh auth git-credential" >/dev/null
  GIT_TERMINAL_PROMPT=0 git -C "$REVIEW_MONOREPO_ROOT" ls-remote --exit-code origin HEAD >/dev/null
  # Exercise the same authenticated cross-container WebSocket path used by
  # codex-pr-review. A localhost-only check would miss hostname rejections.
  paseo project ls --host "$PASEO_HOST" --json | grep -F "$REVIEW_MONOREPO_ROOT" >/dev/null
  test "$(paseo --version)" = "$PASEO_VERSION"
  hermes skills list | grep -F codex-pr-review >/dev/null
  hermes skills list | grep -F review-digest >/dev/null
  hermes skills list | grep -F review-reminder >/dev/null
  test ! -e /opt/data/skills/custom/pr-reviewer
  test -f /opt/data/plugins/slack-pr-review-gate/__init__.py
  hermes plugins list | grep -F slack-pr-review-gate >/dev/null
  python -c "import os,subprocess,sys,yaml; get=lambda key: yaml.safe_load(subprocess.check_output([\"hermes\", \"config\", \"get\", key], text=True)); expected={value.strip() for value in os.environ[\"SLACK_REVIEW_OWNER_USER_IDS\"].split(\",\") if value.strip()}; prompts=get(\"slack.channel_prompts\") or {}; prompt=str(prompts.get(os.environ[\"SLACK_REVIEW_CHANNEL_ID\"], \"\")); valid=get(\"gateway.platforms.slack.extra.allow_bots\") == \"all\" and set(get(\"gateway.platforms.slack.extra.allow_admin_from\") or []) == expected and get(\"gateway.platforms.slack.extra.user_allowed_commands\") == [] and set(get(\"gateway.platforms.slack.extra.group_allow_admin_from\") or []) == expected and get(\"gateway.platforms.slack.extra.group_user_allowed_commands\") == [] and \"reaction-only\" in prompt and \"no automatic final response\" in prompt; sys.exit(0 if valid else \"Slack review or slash-command access policy is not applied\")"
  /opt/review-workspace/prepare-workspace.sh --check
  test -f /opt/review-automation/review-result.schema.json
  python3 -c "import json,sys; schema=json.load(open(\"/opt/review-automation/review-result.schema.json\", encoding=\"utf-8\")); valid=schema.get(\"properties\", {}).get(\"published\") == {\"type\": \"boolean\", \"const\": False} and {\"objective\", \"product_context\", \"baseline_head_sha\", \"delta\"} <= set(schema.get(\"required\", [])); sys.exit(0 if valid else \"The deployed review-result.schema.json is not the read-only proposal contract\")"
  python3 /opt/review-automation/review_automation.py init | python3 -c "import json,sys; payload=json.load(sys.stdin); sys.exit(0 if payload.get(\"schema_version\") == 5 else \"Review database schema v5 is not ready\")"
  python3 -c "import os,sqlite3,sys; db=sqlite3.connect(os.environ[\"REVIEW_HISTORY_DB\"]); tables={row[0] for row in db.execute(\"SELECT name FROM sqlite_master WHERE type=\\\"table\\\"\")}; required={\"workflow_pr_conversations\",\"proposal_revisions\",\"proposal_decisions\",\"slack_deliveries\",\"proposal_reminders\",\"analysis_attempts\"}; sys.exit(0 if required <= tables else \"Private review workflow tables are missing\")"
  python3 /opt/review-tooling/sync_crons.py --check
  python3 -c "import json,os,sys; state=json.load(open(os.environ[\"REVIEW_CRON_STATE\"], encoding=\"utf-8\")); sys.exit(0 if set(state) == {\"daily-review-digest\", \"pr-review-reminders\"} else \"Both managed cron jobs must be synchronized\")"
  hermes cron list | grep -F "Daily PR review digest" >/dev/null
  hermes cron list | grep -F "Private PR review reminders" >/dev/null
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
  command -v bwrap >/dev/null
  test "$(codex --version)" = "codex-cli $CODEX_VERSION"
  codex login status
  codex plugin list --json | python3 -c "import json,sys; items=json.load(sys.stdin).get(\"installed\", []); desired=[x for x in items if x.get(\"pluginId\") == \"compound-engineering@compound-engineering-plugin\" and x.get(\"version\") == \"3.24.0\" and x.get(\"enabled\") is True]; conflicts=[x for x in items if x.get(\"name\") == \"compound-engineering\" and x.get(\"pluginId\") != \"compound-engineering@compound-engineering-plugin\" and x.get(\"enabled\") is True]; sys.exit(0 if len(desired) == 1 and not conflicts else \"Pinned Compound Engineering plugin is not ready\")"
  test "$(openspec --version)" = "$OPENSPEC_VERSION"
  test "$(paseo --version)" = "$PASEO_VERSION"
  (cd "$REVIEW_MONOREPO_ROOT" && openspec context --json >/dev/null)
  curl --fail --silent --show-error http://127.0.0.1:6767/api/health >/dev/null
  paseo provider diagnostic --host 127.0.0.1:6767 --json codex >/dev/null
  paseo project ls --host 127.0.0.1:6767 --json | grep -F "$REVIEW_MONOREPO_ROOT" >/dev/null
  for skill_name in \
    codex-self-review \
    pr-reviewer \
    pr-decision-review \
    writing-for-agents \
    retro \
    setup-company-brain-retros \
    publish-company-brain-retro
  do
    skill_path="/opt/data/.agents/skills/$skill_name"
    test -f "$skill_path/SKILL.md"
    mount_options="$(findmnt -n -o OPTIONS --target "$skill_path")"
    case ",$mount_options," in
      *,ro,*) ;;
      *) echo "$skill_path is not mounted read-only." >&2; exit 1 ;;
    esac
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
  python3 -c "import json,sys; corpus=json.load(open(\"/opt/data/.agents/skills/pr-reviewer/evals/materiality-corpus.json\", encoding=\"utf-8\")); labels={item.get(\"label\") for item in corpus}; sys.exit(0 if labels == {\"withhold\", \"retain\"} else \"materiality-corpus.json must cover both withheld and retained findings\")"
  grep -F "materiality-corpus.json" /opt/data/.agents/skills/pr-reviewer/scripts/eval.py >/dev/null
  codex mcp get linear | grep -Fx "  url: https://mcp.linear.app/mcp" >/dev/null
  linear_status="$(codex mcp list | awk '\''$1 == "linear" { print }'\'')"
  test -n "$linear_status"
  ! printf "%s\n" "$linear_status" | grep -F "Not logged in" >/dev/null
  check-linear-mcp-capabilities >/dev/null
'

echo "Hermes private PR confirmation, schema v5, proposal quality policy, both managed cron jobs, Codex skills and plugins, Paseo, GitHub verification, and workspace are ready."
