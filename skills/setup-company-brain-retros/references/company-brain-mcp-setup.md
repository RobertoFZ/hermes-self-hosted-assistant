# Company Brain MCP connection setup

Use this reference only when the current agent does not already expose Company Brain operations equivalent to `whoami`, `get_page`, and `put_page`.

## Canonical server

- **Name:** `company-brain`
- **Transport:** remote Streamable HTTP
- **Authentication:** OAuth 2.1 with browser consent
- **Endpoint:** `https://company-brain.reservamos.com/mcp`

Do not use undocumented endpoint aliases. Do not call the endpoint with raw HTTP, create a bearer-token fallback, or place OAuth credentials in chat, repository files, shell history, or the retro profile.

## Installation contract

1. Identify the current host from its actual runtime or ask the author which host they use. Do not run commands for a different agent.
2. Show the exact user-level configuration change or command before executing it.
3. Obtain confirmation before changing host configuration.
4. Let the host open and complete its own browser OAuth flow. OAuth consent is a human action; never automate approval.
5. Restart or reload the host if it does not expose newly registered MCP tools in the current session.
6. Verify the connection with the setup skill's live `whoami` and policy checks. A successful registration alone is not `READY`.

## Claude Code

Register the remote server for the user:

```bash
claude mcp add --transport http --scope user company-brain \
  https://company-brain.reservamos.com/mcp
```

Open `/mcp` inside Claude Code, choose `company-brain`, and complete **Authenticate** in the browser. Then run `claude mcp list` or start a new session and invoke the setup skill again.

## Codex

Register and authenticate the remote server:

```bash
codex mcp add company-brain --url https://company-brain.reservamos.com/mcp
codex mcp login company-brain
codex mcp get company-brain
```

The login command owns the browser OAuth flow and local token storage. Do not ask the author to paste the resulting token.

## Cursor

Add a user-level remote MCP entry through **Settings → Tools & MCP**, or merge this entry into `~/.cursor/mcp.json` after showing the complete proposed file change:

```json
{
  "mcpServers": {
    "company-brain": {
      "url": "https://company-brain.reservamos.com/mcp"
    }
  }
}
```

Enable the server in Cursor and complete the browser OAuth prompt. Restart Cursor if the tools do not appear.

## OpenCode

Merge this entry into the user's `~/.config/opencode/opencode.json` or `opencode.jsonc` after showing the complete proposed change:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "company-brain": {
      "type": "remote",
      "url": "https://company-brain.reservamos.com/mcp",
      "enabled": true
    }
  }
}
```

OAuth discovery is enabled for remote servers unless explicitly disabled. Authenticate and inspect status with:

```bash
opencode mcp auth company-brain
opencode mcp list
opencode mcp debug company-brain
```

Do not set `oauth: false` and do not add an Authorization header for this write-capable workflow.

## Kimi Code

Register, authorize, and test the server with Kimi's native MCP commands:

```bash
kimi mcp add --transport http --auth oauth company-brain \
  https://company-brain.reservamos.com/mcp
kimi mcp auth company-brain
kimi mcp test company-brain
```

Kimi stores its OAuth state through its own MCP subsystem. Do not copy that state into the retro profile.

## Pi

Pi does not use generic MCP registration for this workflow. Reservamos Pi setups expose Company Brain through the maintained Pi integration, which owns the endpoint, OAuth callback, credential storage, and `company_brain_*` tools.

- If Company Brain tools are already present, do not install or rewrite anything; continue with live verification.
- If they are absent, report `NOT READY` and state that the maintained Reservamos Pi integration must be enabled in this Pi installation. Do not run `claude mcp`, `codex mcp`, edit another host's config, or copy another person's Pi extension or OAuth state.

## Other MCP hosts

Proceed only when the host supports installed Agent Skills, local file access for the mode-`0600` profile, remote Streamable HTTP, and OAuth 2.1. Browser-only chat surfaces do not satisfy this workflow. Use the host's documented user-level setup with the canonical endpoint and OAuth enabled. If any capability is missing, report `NOT READY`; do not downgrade publication to a shared bearer token or personal-brain target.

## Verification after installation

A connected host is only ready when the setup skill observes all of the following in the new or reloaded session:

- operations equivalent to `whoami`, `get_page`, and `put_page`;
- OAuth transport and effective `read` plus `write` scopes;
- exactly one direct-write prefix shaped `retros/people/<person-slug>/`;
- readable canonical `resolver` and `_excluded-people` policy pages.

If OAuth finishes but these checks fail, preserve the host configuration, perform zero Company Brain writes, and report the exact missing scope, operation, prefix, or policy access. Never invent or broaden a grant locally.
