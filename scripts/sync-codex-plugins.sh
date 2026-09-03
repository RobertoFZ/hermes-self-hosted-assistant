#!/bin/sh
set -eu

docker compose exec -T --user hermes paseo /bin/sh -eu -c '
  marketplace_root=/opt/self-assistant-marketplace
  plugin_id=compound-engineering@self-assistant
  expected_version=3.24.0

  test -f "$marketplace_root/.agents/plugins/marketplace.json"
  codex plugin marketplace add "$marketplace_root" --json >/dev/null

  plugin_state="$(codex plugin list --json | python3 -c "import json,sys; items=json.load(sys.stdin).get(\"installed\", []); conflicts=[x.get(\"pluginId\") for x in items if x.get(\"name\") == \"compound-engineering\" and x.get(\"pluginId\") != sys.argv[1] and x.get(\"enabled\") is True]; item=next((x for x in items if x.get(\"pluginId\") == sys.argv[1]), None); print(\"conflict:\" + \",\".join(conflicts) if conflicts else \"missing\" if item is None else \"ready\" if item.get(\"enabled\") and item.get(\"version\") == sys.argv[2] else \"disabled\" if not item.get(\"enabled\") else \"version:\" + str(item.get(\"version\")))" "$plugin_id" "$expected_version")"

  case "$plugin_state" in
    ready)
      echo "$plugin_id $expected_version is already installed and enabled."
      ;;
    missing)
      codex plugin add "$plugin_id" --json >/dev/null
      ;;
    disabled)
      echo "$plugin_id is installed but disabled; enable it before synchronizing." >&2
      exit 1
      ;;
    version:*)
      echo "$plugin_id has ${plugin_state#version:}; expected $expected_version. Remove the stale plugin explicitly, then synchronize again." >&2
      exit 1
      ;;
    conflict:*)
      echo "Another Compound Engineering plugin is enabled (${plugin_state#conflict:}). Remove or disable it before installing $plugin_id." >&2
      exit 1
      ;;
    *)
      echo "Unexpected plugin state: $plugin_state" >&2
      exit 1
      ;;
  esac

  codex plugin list --json | python3 -c "import json,sys; items=json.load(sys.stdin).get(\"installed\", []); desired=[x for x in items if x.get(\"pluginId\") == sys.argv[1] and x.get(\"version\") == sys.argv[2] and x.get(\"enabled\") is True]; conflicts=[x for x in items if x.get(\"name\") == \"compound-engineering\" and x.get(\"pluginId\") != sys.argv[1] and x.get(\"enabled\") is True]; sys.exit(0 if len(desired) == 1 and not conflicts else \"Compound Engineering installation verification failed\")" "$plugin_id" "$expected_version"
'

echo "Compound Engineering 3.24.0 is installed in the persistent container Codex profile."
