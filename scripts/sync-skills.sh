#!/bin/sh
set -eu

docker compose exec -T hermes /bin/sh -eu -c '
  chown "$HERMES_UID:$HERMES_GID" /opt/data/skills

  # Remove the Milestone 1 placeholder skill if it was installed previously.
  if [ -f /opt/data/skills/custom/code-review/SKILL.md ]; then
    rm /opt/data/skills/custom/code-review/SKILL.md
    rmdir /opt/data/skills/custom/code-review 2>/dev/null || true
  fi

  install -d -o "$HERMES_UID" -g "$HERMES_GID" \
    /opt/data/skills/custom/pr-reviewer
  cp -a /opt/global-skills/pr-reviewer/. \
    /opt/data/skills/custom/pr-reviewer/
  chown -R "$HERMES_UID:$HERMES_GID" \
    /opt/data/skills/custom/pr-reviewer
'

echo "Synced the repository-owned pr-reviewer into persistent Hermes state."
