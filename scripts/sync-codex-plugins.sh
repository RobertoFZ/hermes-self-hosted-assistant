#!/bin/sh
set -eu

docker compose exec -T --user hermes paseo /bin/sh -eu -c '
  marketplace_name=compound-engineering-plugin
  expected_ref=compound-engineering-v3.24.0
  plugin_id=compound-engineering@compound-engineering-plugin
  legacy_plugin_id=compound-engineering@self-assistant
  expected_version=3.24.0

  verify_pinned_plugin() {
    codex plugin list --json | python3 -c "import json,sys; items=json.load(sys.stdin).get(\"installed\", []); desired_id,version,legacy_id,allow_legacy=sys.argv[1:]; desired=[x for x in items if x.get(\"pluginId\") == desired_id and x.get(\"version\") == version and x.get(\"enabled\") is True]; allowed={desired_id} | ({legacy_id} if allow_legacy == \"true\" else set()); conflicts=[x.get(\"pluginId\") for x in items if x.get(\"name\") == \"compound-engineering\" and x.get(\"pluginId\") not in allowed and x.get(\"enabled\") is True]; sys.exit(0 if len(desired) == 1 and not conflicts else \"Compound Engineering installation verification failed\")" "$plugin_id" "$expected_version" "$legacy_plugin_id" "$1"
  }

  # Reject third-party Compound Engineering installations before changing the
  # persistent profile. A broken retired marketplace can prevent even listing
  # plugins, so remove only that known registration and retry once.
  if ! plugin_inventory="$(codex plugin list --json 2>&1)"; then
    case "$plugin_inventory" in
      *self-assistant*)
        codex plugin marketplace remove self-assistant --json >/dev/null
        plugin_inventory="$(codex plugin list --json)"
        ;;
      *)
        printf "%s\n" "$plugin_inventory" >&2
        exit 1
        ;;
    esac
  fi
  plugin_state="$(printf "%s\n" "$plugin_inventory" | python3 -c "import json,sys; items=json.load(sys.stdin).get(\"installed\", []); desired_id,legacy_id,version=sys.argv[1:]; allowed={desired_id,legacy_id}; conflicts=[x.get(\"pluginId\") for x in items if x.get(\"name\") == \"compound-engineering\" and x.get(\"pluginId\") not in allowed and x.get(\"enabled\") is True]; conflicts and sys.exit(\"Unexpected enabled Compound Engineering plugin(s): \" + \", \".join(conflicts)); ready=sum(x.get(\"pluginId\") == desired_id and x.get(\"version\") == version and x.get(\"enabled\") is True for x in items) == 1; legacy=any(x.get(\"pluginId\") == legacy_id for x in items); print((\"ready\" if ready else \"install\") + \" \" + (\"legacy\" if legacy else \"clean\"))" "$plugin_id" "$legacy_plugin_id" "$expected_version")"
  set -- $plugin_state
  desired_state=$1
  legacy_state=$2

  marketplace_inventory="$(codex plugin marketplace list --json)"
  legacy_marketplace="$(printf "%s\n" "$marketplace_inventory" | python3 -c "import json,sys; items=json.load(sys.stdin).get(\"marketplaces\", []); print(\"legacy\" if any(x.get(\"name\") == \"self-assistant\" for x in items) else \"clean\")")"
  changed=false

  if [ "$desired_state" = install ]; then
    # Recreate the managed marketplace when the installed version differs from
    # the repository pin. A healthy exact installation remains untouched.
    codex plugin marketplace remove "$marketplace_name" --json >/dev/null 2>&1 || true
    codex plugin marketplace add EveryInc/compound-engineering-plugin \
      --ref "$expected_ref" --json >/dev/null
    codex plugin add "$plugin_id" --json >/dev/null
    changed=true
  fi

  # Preserve the last working legacy install until its replacement is known
  # to be present and enabled at the pinned version.
  if [ "$desired_state" = install ] && [ "$legacy_state" = legacy ]; then
    verify_pinned_plugin true
  fi

  if [ "$legacy_state" = legacy ]; then
    codex plugin remove "$legacy_plugin_id" --json >/dev/null
    changed=true
  fi
  if [ "$legacy_marketplace" = legacy ]; then
    codex plugin marketplace remove self-assistant --json >/dev/null
    changed=true
  fi

  if [ "$changed" = true ]; then
    verify_pinned_plugin false
  fi
'

echo "Compound Engineering 3.24.0 is installed in the persistent Codex profile."
