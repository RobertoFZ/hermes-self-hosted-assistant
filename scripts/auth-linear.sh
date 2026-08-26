#!/bin/sh
set -eu

# The browser runs on the operator's computer while Codex listens inside the
# Paseo container. Before running this target on a VPS, forward local port 5555
# to the VPS loopback port configured by LINEAR_OAUTH_CALLBACK_HOST_PORT.
docker compose exec --user hermes paseo /bin/sh -eu -c '
  codex mcp remove linear >/dev/null 2>&1 || true
  codex \
    -c mcp_oauth_callback_port=5555 \
    mcp add linear --url https://mcp.linear.app/mcp/readonly
  linear_status="$(codex mcp list | awk '\''$1 == "linear" { print }'\'')"
  if printf "%s\n" "$linear_status" | grep -F "Not logged in" >/dev/null; then
    exec codex \
      -c mcp_oauth_callback_port=5555 \
      mcp login linear --scopes read
  fi
'
