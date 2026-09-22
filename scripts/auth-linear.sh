#!/bin/sh
set -eu

# Codex binds its OAuth callback to container loopback. Bridge a separate
# published container port to that listener only while authentication runs.
docker compose exec --user hermes paseo /bin/sh -eu -c '
  socat TCP-LISTEN:5556,bind=0.0.0.0,reuseaddr,fork TCP:127.0.0.1:5555 &
  oauth_proxy_pid=$!
  trap "kill $oauth_proxy_pid 2>/dev/null || true" EXIT HUP INT TERM
  kill -0 "$oauth_proxy_pid"

  codex mcp remove linear >/dev/null 2>&1 || true
  codex \
    -c mcp_oauth_callback_port=5555 \
    mcp add linear --url https://mcp.linear.app/mcp
  linear_status="$(codex mcp list | awk '\''$1 == "linear" { print }'\'')"
  if printf "%s\n" "$linear_status" | grep -F "Not logged in" >/dev/null; then
    codex \
      -c mcp_oauth_callback_port=5555 \
      mcp login linear
  fi
'
