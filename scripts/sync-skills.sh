#!/bin/sh
set -eu

docker compose exec -T hermes /bin/sh -eu -c '
  chown "$HERMES_UID:$HERMES_GID" /opt/data/skills

  # Remove retired repository-owned Codex workflow skills from the persistent
  # volume. Check -L separately so dangling symlinks are removed as well.
  retired_codex_skills="
    auto-pr-workflow
    linear-ticket-selection
    merge-pr-and-clean-worktree
    prepare-branch-for-pr
    publish-ready-pr
    ticket-openspec-planning
  "
  for skill_name in $retired_codex_skills; do
    skill_path="/opt/data/.agents/skills/$skill_name"
    if [ -L "$skill_path" ] || [ -e "$skill_path" ]; then
      rm -rf -- "$skill_path"
    fi
  done

  # Remove obsolete Hermes-owned review skills. Codex discovers pr-reviewer
  # through Paseo at /opt/data/.agents/skills/pr-reviewer instead.
  if [ -f /opt/data/skills/custom/code-review/SKILL.md ]; then
    rm /opt/data/skills/custom/code-review/SKILL.md
    rmdir /opt/data/skills/custom/code-review 2>/dev/null || true
  fi
  if [ -d /opt/data/skills/custom/pr-reviewer ]; then
    rm -rf /opt/data/skills/custom/pr-reviewer
  fi

  install -d -o "$HERMES_UID" -g "$HERMES_GID" \
    /opt/data/skills/custom/codex-pr-review \
    /opt/data/skills/custom/review-digest \
    /opt/data/skills/custom/review-reminder \
    /opt/data/review-history
  cp -a /opt/global-skills/codex-pr-review/. \
    /opt/data/skills/custom/codex-pr-review/
  cp -a /opt/global-skills/review-digest/. \
    /opt/data/skills/custom/review-digest/
  cp -a /opt/global-skills/review-reminder/. \
    /opt/data/skills/custom/review-reminder/

  python3 /opt/review-automation/review_automation.py init >/dev/null
  chown -R "$HERMES_UID:$HERMES_GID" \
    /opt/data/skills/custom/codex-pr-review \
    /opt/data/skills/custom/review-digest \
    /opt/data/skills/custom/review-reminder \
    /opt/data/review-history
'

echo "Synced Hermes orchestration skills and initialized review history."
