# Hermes Self-Hosted Assistant

Reproducible Docker Compose deployment of Hermes Agent as a GitHub pull-request
review assistant. It uses the Hermes agent runtime with the `openai-codex`
provider and interactive ChatGPT/Codex OAuth; it does not require an
`OPENAI_API_KEY`.

The repository owns the Codex `pr-reviewer`, a pinned Compound Engineering
plugin declaration, two Hermes orchestration skills, the persisted
review-history schema, the daily digest definition, and the Slack review-only
policy. Every installation supplies its own credentials and Slack identifiers
through ignored runtime files.

## Included boundaries

- OpenAI Codex provider authenticated through ChatGPT OAuth
- Pinned standalone Codex CLI with its own persistent ChatGPT OAuth
- Repository-managed Compound Engineering plugin pinned to version `3.24.0`
- No gstack skill registrations in the container Codex profile
- Pinned Paseo daemon and web UI for using that Codex CLI remotely
- Hermes-to-Paseo delegation of exact PR review requests
- GitHub CLI OAuth for reading PRs and publishing `APPROVE` or `COMMENT`
- SQLite history containing only Hermes-initiated, GitHub-verified reviews
- Linear issue snapshots and normalized findings for later analysis
- Daily Slack DM digest at 17:00 in `America/Mexico_City`
- Pinned OpenSpec CLI for strict validation of specification changes
- Persistent Hermes state, credentials, sessions, skills, and review checkout
- Review-only Slack channel and delegated-reviewer DMs
- Optional Telegram or other Hermes gateway integrations
- Loopback-only authenticated Hermes and Paseo web interfaces
- Paseo-controlled isolated Docker for development and test workloads
- No GitHub merging, `REQUEST_CHANGES`, or directly exposed Codex app-server
  endpoint

ChatGPT/Codex usage limits are account-managed and outside this repository.

## Persistent state

Compose mounts the named volume `self-assistant-hermes-data` at `/opt/data`.
The name is deliberately stable even when the repository is cloned into a new
directory, so adopting this standardized checkout does not create a new empty
Hermes profile.

Paseo's nested Docker daemon uses two additional stable volumes:
`self-assistant-paseo-docker-data` for its images, containers, and volumes, and
`self-assistant-paseo-docker-certs` for mutual TLS credentials. The nested daemon
also mounts `hermes-data` at `/opt/data`, allowing worktree bind mounts to resolve
without exposing the VPS Docker socket.

Never run `docker compose down -v` unless you intend to erase the installation.

Important runtime locations:

| Data | Container path | Committed? |
|---|---|---|
| Hermes Codex OAuth | `/opt/data/auth.json` | Never |
| Standalone Codex CLI OAuth | `/opt/data/.codex/auth.json` | Never |
| Installed Codex plugin cache and state | `/opt/data/.codex/plugins` and `/opt/data/.codex/config.toml` | Never |
| Paseo daemon identity, pairings, and projects | `/opt/data/.paseo` | Never |
| GitHub CLI OAuth | `/opt/data/.config/gh/hosts.yml` | Never |
| Native Git credential configuration | `/opt/data/.gitconfig` | Never |
| Hermes configuration and integration secrets | `/opt/data/config.yaml`, `/opt/data/.env` | Never |
| Sessions and pairings | `/opt/data/sessions` and Hermes runtime state | Never |
| Review workspace | `/opt/data/repos/reserhub-revenue-full` | Never |
| Verified review history | `/opt/data/review-history/reviews.sqlite3` | Never |
| Managed Hermes cron IDs | `/opt/data/cron/repository-managed-jobs.json` | Never |
| Codex review skill | `skills/pr-reviewer` | Yes |
| Codex plugin marketplace | `.agents/plugins/marketplace.json` | Yes |
| Hermes orchestration skills | `skills/codex-pr-review`, `skills/review-digest` | Yes |
| Cron source of truth | `config/crons.json` | Yes |

The OAuth stores are independent. Hermes uses `/opt/data/auth.json`; the
standalone Codex CLI uses `/opt/data/.codex/auth.json`. Authenticating one does
not authenticate the other. Both locations live in the persistent named volume.

## First-time setup

Requirements: Docker Engine with Compose, Make, Python 3, and OpenSSL.

Create the ignored local configuration files:

```bash
make init
```

`make init` copies the examples when the ignored files are absent and fills only
missing generated credentials, including `PASEO_PASSWORD`. Existing values are
never overwritten.

Fill in these deployment-specific values in `.review.env`:

```dotenv
SLACK_ALLOWED_USERS=OWNER_ID,REVIEWER_ID,TRUSTED_REVIEW_BOT_ID
SLACK_REVIEW_OWNER_USER_IDS=OWNER_ID
SLACK_REVIEWER_USER_IDS=REVIEWER_ID
SLACK_REVIEW_BOT_USER_IDS=TRUSTED_REVIEW_BOT_ID
SLACK_REVIEW_COMPETING_BOT_USER_IDS=NACHO_BOT_ID
SLACK_REVIEW_CHANNEL_ID=CHANNEL_ID
SLACK_REVIEW_DIGEST_USER_ID=OWNER_ID
TZ=America/Mexico_City
```

`SLACK_REVIEW_DIGEST_USER_ID` may be left blank when exactly one owner is
configured; cron synchronization uses that owner as the digest recipient.

The repository and submodule defaults are already declared in the example.
`SLACK_ALLOWED_USERS` must contain the owner, every delegated reviewer, and
every trusted review bot because the Hermes Slack adapter authorizes senders
before the review policy runs. Human owner/reviewer messages trigger from an
exact allowlisted PR URL. Trusted bot messages are accepted only in the review
channel and additionally require review-request intent such as `Solicitud de
revisión` or `ready for review`; URLs may be present in Slack Block Kit or
attachments. Other bots and bot status messages remain ignored.
`SLACK_REVIEW_COMPETING_BOT_USER_IDS` lists bots such as a second review agent:
when a human explicitly addresses one of them without also mentioning Hermes,
Hermes ignores that message even if Slack supplies PR context from the thread.

Build and start:

```bash
make build
make up
make sync-skills
make uninstall-gstack
make sync-codex-plugins
make sync-crons
```

The derived image installs pinned standalone Codex (`0.149.1` by default), its
Linux `bubblewrap` sandbox prerequisite, OpenSpec (`1.6.0`), and Paseo (`0.5.2`).
Override `CODEX_VERSION`, `OPENSPEC_VERSION`, or `PASEO_VERSION` only after
validating the new version.

`make sync-codex-plugins` registers the repository marketplace inside the
container's persistent Codex profile and installs Compound Engineering from the
immutable Git commit declared in `.agents/plugins/marketplace.json`. The
marketplace definition is bind-mounted read-only; downloaded plugin files and
enabled state remain under `/opt/data/.codex`, shared by Hermes and Paseo. This
does not modify the host user's Codex configuration. Synchronization stops if a
Compound Engineering copy from another marketplace is already enabled, avoiding
duplicate skill registrations and leaving removal or migration explicit.

`make uninstall-gstack` removes only entries named `gstack` or `gstack-*` from
the persistent container's `.codex/skills` and `.agents/skills` directories. It
does not touch the host Codex profile, unrelated skills, or a retained gstack
source checkout outside those registration directories.

Authenticate the ChatGPT/Codex subscription interactively:

```bash
make auth-codex
make select-model
```

Open the device-code URL yourself and authenticate the intended ChatGPT account.
Do not automate the browser step. Choose the OpenAI Codex subscription provider
and one of the models offered by the live Hermes picker.

Authenticate the standalone Codex CLI separately using its headless device-code
flow, then verify its persisted session:

```bash
make auth-codex-cli
make codex-cli-status
```

The CLI writes its secret-bearing session under `/opt/data/.codex`; do not copy
that directory into the repository or expose it through a bind mount.

Linear authentication is intentionally completed after deployment on the VPS.
The repository exposes Codex's fixed OAuth callback only on VPS loopback. From
your computer, open an SSH tunnel and keep it running:

```bash
ssh -N -L 5555:127.0.0.1:5555 USER@VPS
```

In a second VPS shell, start the one-time OAuth flow, then open the printed URL
in your local browser:

```bash
make auth-linear
```

Codex registers the official read-only Linear MCP endpoint and persists its
OAuth credentials under `/opt/data/.codex`. No Linear API key is needed. If the
host port `5555` is occupied, change `LINEAR_OAUTH_CALLBACK_HOST_PORT` in `.env`
and forward that host port to local port `5555`. Reviews requested before OAuth
is completed still run, but their Linear snapshot is marked unavailable.

Authenticate GitHub CLI as the same non-root user that runs Hermes:

```bash
make auth-github
make github-status
```

`make auth-github` also configures native Git to use the persisted GitHub CLI
credential. Compose fixes `GIT_CONFIG_GLOBAL` at `/opt/data/.gitconfig` so both
interactive commands and Hermes tool subprocesses can authenticate even though
they use different `HOME` directories.

GitHub may require organization approval or SSO authorization. The authenticated
account needs repository read access and Pull requests write permission to
publish reviews.

Clone or validate the persistent monorepo and its submodules:

```bash
make clone-workspace
make workspace-sync
```

`workspace-sync` updates only remote-tracking refs. It does not pull, check out,
reset, merge, or update working files.

Register that monorepo with Paseo, verify its Codex provider, and pair the
daemon with the hosted Paseo web app:

```bash
make paseo-register-workspace
make paseo-provider-status
make paseo-pair
```

Open the private pairing link printed by the last command. It enables Paseo's
outbound, end-to-end encrypted relay connection; no public inbound port is
needed. Treat the link and QR code as credentials and do not paste them into
issues, logs, or chat channels.

Configure Slack, Telegram, or another supported gateway when needed:

```bash
make gateway-setup
```

For Slack, finish the interactive token setup, then apply the standardized
review-only policy and restart:

```bash
make apply-review-policy
make restart
make sync-crons
make verify
```

If `make verify` reports that native Git cannot authenticate, refresh its
credential helper without changing the existing OAuth login:

```bash
docker compose exec -T --user hermes hermes gh auth setup-git
```

The Slack policy behaves as follows:

- The configured owner keeps normal assistant access outside the review channel.
- The configured owner is the only Slack slash-command administrator in both
  direct messages and channels.
- Delegated reviewers can use only Hermes' always-available `/help` and
  `/whoami` slash commands. PR reviews remain explicit messages containing
  approved GitHub PR URLs; the generic `/review` and direct `/pr-reviewer`
  command surfaces are not delegated.
- Delegated reviewers can submit review requests only in the configured channel
  or one-to-one DMs.
- Delegated messages must contain one or more allowed GitHub PR URLs.
- Only the current Slack message supplies URLs; inherited thread context cannot
  turn a reply into a review request.
- A message explicitly addressed to a configured competing bot is ignored
  unless it also mentions Hermes. Messages with no bot mention keep the natural
  URL-only trigger.
- Allowed PR URLs trigger reviews regardless of surrounding wording. A PR
  authored by the authenticated GitHub reviewer is the exception: it is
  reviewed only when a configured Slack owner mentions the Hermes bot in the
  same message. Other PRs in a mixed message continue normally.
- Unsupported URLs or unrelated instructions are discarded before inference.
- Accepted requests get one immediate validation acknowledgement; tool progress
  remains hidden and Hermes posts exactly one final result.

## Review delegation and persistence

Hermes does not discover or execute `pr-reviewer`. The skill is mounted only in
Codex's user skill directory inside the Paseo service. The path for a Slack
review is:

```text
Slack request
  -> Hermes codex-pr-review
  -> deterministic review automation
  -> Paseo run
  -> Codex $pr-reviewer
  -> GitHub APPROVE or COMMENT
  -> GitHub reconciliation
  -> SQLite verified history
```

This leaves the existing `pr-reviewer` instructions unchanged. You can still
invoke `$pr-reviewer` manually in Codex for a local, pre-PR review; it is not
automatically attached to `ship` or PR creation. Those direct Codex reviews are
not imported into the Hermes digest.

For a Hermes request, the automation validates the exact URL and repository
allowlist, records the PR head SHA, checks for an existing current-head review,
launches one structured Codex run per PR, and then checks GitHub again. A Codex
response is persisted as successful only when a new review or inline comment by
the authenticated reviewer exists on the same head SHA. An atomic SQLite claim
allows only one in-progress run per PR head and reviewer; duplicate Slack
requests reuse that run instead of launching another Codex agent. Each delegated
review agent receives a unique automation-run label and is hard-deleted after
GitHub reconciliation, whether the review succeeds or fails. Cleanup validates
Paseo's deleted agent ID and count, then confirms the label no longer resolves.
Its outcome and error are persisted independently from the review result, so a
successful GitHub publication remains successful even when session deletion
must be retried. Duplicate requests and the daily digest retry pending cleanup.

If Hermes is interrupted after GitHub publication but before persistence, a
later duplicate request recovers terminal structured output from the labeled
Paseo agent, verifies the publication, persists the original run, and removes
the agent. An operator can recover a known interrupted run immediately with:

```bash
make review-recover RUN_ID=REVIEW_RUN_UUID
```

The recovery falls back to GitHub publication data only when the structured
Paseo result is unavailable and records that limitation in review history. If
the agent has finished but recovery continues to report `in_progress`, retry
with `FORCE=1`; this explicitly permits fallback recovery and deletion of an
agent Paseo still reports as active.

Reconcile every pending terminal session, or one known run, without changing
review outcomes:

```bash
make review-cleanup
make review-cleanup RUN_ID=REVIEW_RUN_UUID
```

Each successful record includes the review result and summary, normalized
findings and severities, a snapshot of the related Linear issue when available,
and the verified GitHub publication IDs. Preview the raw digest input with:

```bash
make digest-preview
```

The SQLite database is part of `hermes-data`, so the existing volume backup and
restore commands include it automatically.

## Repository-managed cron jobs

All schedules live in the single committed file
[`config/crons.json`](config/crons.json). It stores the cron expression together
with the Hermes skill, prompt, delivery target, and working directory. The
default daily digest is `0 17 * * *`; with `TZ=America/Mexico_City`, it runs at
17:00 Mexico City local time throughout the year.

After editing the file or changing its environment variables, recreate Hermes
when the timezone changed and reconcile the definitions:

```bash
make restart       # required only after changing TZ
make sync-crons
make cron-status
```

Synchronization uses `hermes cron create/edit/remove`; it never edits Hermes'
internal jobs file. Its small state map tracks only jobs owned by this
repository, so unrelated cron jobs created by a VPS operator are preserved.
Removing a job from `config/crons.json` removes only its previously managed
Hermes counterpart on the next synchronization.

## Existing installations

This repository keeps the existing `self-assistant-hermes-data` volume name.
After pulling or copying these files, switch Hermes to the repository-owned
skill and configurable plugin without touching the volume:

```bash
make init
make build
make up
make sync-skills
make uninstall-gstack
make sync-codex-plugins
make apply-review-policy
make restart
make sync-crons
make paseo-register-workspace
make paseo-provider-status
# Run make paseo-pair only if this installation is not paired yet.
make verify
```

The container is recreated, but `/opt/data` and all OAuth, sessions, pairings,
configuration, Paseo state, and repository data remain in the named volume.

## Common commands

```bash
make help                 # list targets
make up                   # start Hermes and Paseo
make down                 # stop without deleting data
make restart              # recreate while preserving the volume
make status               # container status
make logs                 # follow gateway logs
make chat                 # interactive terminal chat
make codex                # open Codex in the configured monorepo root
make auth-codex-cli       # authenticate the standalone Codex CLI
make codex-cli-status     # verify standalone Codex authentication
make auth-linear          # one-time read-only Linear MCP OAuth login
make check-tool-updates   # check npm for newer Codex and Paseo releases
make paseo-status         # show Paseo daemon status
make paseo-logs           # follow Paseo daemon logs
make paseo-register-workspace # register the review monorepo
make paseo-provider-status # verify Paseo can launch Codex
make paseo-pair           # pair with the hosted Paseo web app
make sync-skills          # copy Hermes orchestration skills into persistent state
make uninstall-gstack     # remove gstack from the container Codex profile
make sync-codex-plugins   # install the pinned Compound Engineering plugin
make sync-crons           # reconcile jobs from config/crons.json
make cron-status          # list active Hermes cron jobs
make digest-preview       # inspect verified 24-hour digest data
make review-history-init  # migrate the SQLite review history
make review-recover RUN_ID=UUID # recover an interrupted published review
make review-cleanup        # retry terminal Paseo session cleanup
make workspace-status     # validate root and initialized submodules
make workspace-sync       # safely fetch review refs
make apply-review-policy  # persist Slack review-only configuration
make verify               # verify auth, skill, plugin, and workspace
make test                 # local policy and skill tests
```

The repository copy is canonical. To use it as the current user's global Codex
skill as well:

```bash
make install-global-skill
```

If a global `pr-reviewer` directory already exists, the installer preserves it
with a timestamped backup before creating the symlink.

## Web dashboard

The dashboard is published only on host loopback:

```text
http://127.0.0.1:9119/chat
```

On a VPS, use an SSH tunnel rather than exposing port 9119 publicly:

```bash
ssh -N -L 9119:127.0.0.1:9119 USER@VPS
```

Then open the same loopback URL on the local computer. Dashboard credentials are
in the ignored `.env` file.

## Paseo web UI

Paseo runs as a separate non-root Compose service while sharing `/opt/data` with
Hermes. Codex sessions launched from Paseo therefore use the same standalone
Codex login, GitHub CLI login, Git configuration, tools, and persistent
monorepo. Hermes and Paseo still have independent process lifecycles.

Paseo includes Docker Compose but does not mount `/var/run/docker.sock`. It
connects over mutual TLS to a dedicated `paseo-docker` Docker-in-Docker sidecar.
Codex sessions can build, start, inspect, and remove nested containers without
seeing or modifying the VPS host daemon's containers, images, networks, or
volumes. Both services mount `hermes-data` at `/opt/data`, so nested containers
can bind-mount the persistent worktrees at their existing absolute paths.

The sidecar is privileged because rootful Docker-in-Docker requires elevated
kernel capabilities. This is a smaller trust boundary than exposing the host
Docker API, but it is not equivalent to a separate VM. For the strongest
isolation, run the development Docker daemon on a dedicated worker VM.

For the hosted web app, use `make paseo-pair` and open the private link it
prints. This is the recommended way to reach a remote VPS because the daemon
connects outbound through Paseo's encrypted relay.

The bundled direct UI is also available on host loopback:

```text
http://127.0.0.1:PASEO_HOST_PORT
```

The default `PASEO_HOST_PORT` is `6767`; change it in `.env` if that port is
already occupied. The UI requires the `PASEO_PASSWORD` stored in the same
ignored file. On a VPS, reach it only through an SSH tunnel (replace both port
values if you changed the default):

```bash
ssh -N -L 6767:127.0.0.1:6767 USER@VPS
```

Do not publish port 6767 directly. Use `make paseo-status` and
`make paseo-provider-status` to diagnose daemon or Codex availability.

### Migrate an existing host-socket installation

Preserve `hermes-data` and recreate the services without deleting volumes:

```bash
git pull --ff-only origin main
make down
make volume-backup BACKUP_FILE=/absolute/secure/path/hermes-data-before-dind.tgz
make build
docker compose up -d
make paseo-status
make paseo-provider-status
docker compose exec -T --user hermes paseo docker info
```

Confirm that `docker info` reports `Name: paseo-docker` and that
`/var/run/docker.sock` is absent inside Paseo. Existing Paseo sessions, Git
commits, and worktrees remain in `hermes-data`; send the paused agent its resume
message after these checks pass. Do not run `docker compose down -v`.

To roll back, revert the migration commit, rebuild, and recreate Paseo without
the `-v` flag. Keep the `paseo-docker-data` and `paseo-docker-certs` volumes until
the migration has been stable long enough that rollback is no longer needed.

## Move the complete installation to a VPS

The preferred migration preserves the complete volume. Stop the source first so
OAuth refresh state, sessions, and messaging connections cannot diverge:

```bash
make down
make volume-backup BACKUP_FILE=/absolute/secure/path/hermes-data.tgz
```

The archive contains live credentials and must be transferred through a secure
channel. Transfer these separately:

1. This Git repository (after a remote is configured).
2. The ignored `.env` and `.review.env`, or recreate them on the VPS.
3. The encrypted/securely handled `hermes-data.tgz` archive.

The backup intentionally excludes `paseo-docker-data` and
`paseo-docker-certs`. Nested Docker images, containers, networks, and TLS
certificates are disposable and are recreated on the destination. Git commits,
Paseo sessions, and worktrees remain in `hermes-data` and are preserved.

On the VPS, install Docker and Make, clone this repository, create the local
configuration files, and restore before starting Hermes:

```bash
git clone REMOTE_URL hermes-self-hosted-assistant
cd hermes-self-hosted-assistant
make init
# Securely place or edit .env and .review.env now.
make volume-restore BACKUP_FILE=/absolute/secure/path/hermes-data.tgz
make build
make up
make sync-skills
make uninstall-gstack
make sync-codex-plugins
make sync-crons
make paseo-register-workspace
make paseo-provider-status
make verify
```

The restore command creates the configured volume if necessary and refuses to
overwrite a non-empty volume. Do not restart the old installation after the VPS
starts using the migrated OAuth and messaging state.

If credentials are intentionally not migrated, omit the restore and follow the
first-time authentication steps instead. Pair Slack/Telegram identities again
for a completely fresh profile.

After validation, remove the plaintext migration archive or retain it only in
encrypted, access-controlled backup storage.

## Security rules

- Keep this repository private because the skill contains organization-specific
  review policy, even though it contains no credentials.
- Never commit `.env`, `.review.env`, `.codex`, `.paseo`, `auth.json`,
  `hosts.yml`, volume archives, sessions, or repository checkouts.
- Keep `GITHUB_TOKEN` blank when using persisted `gh` OAuth; an environment token
  takes precedence.
- Do not expose the Hermes dashboard or Paseo port directly to the internet.
- Treat Paseo pairing URLs, QR codes, and `PASEO_PASSWORD` as credentials.
- Never mount `/var/run/docker.sock` into Paseo. Keep its Docker API on the
  Compose-only TLS network and never publish port 2376 on the VPS.
- Treat Paseo users as administrators of the nested Docker daemon and the shared
  `/opt/data` workspace. They cannot control the host daemon through this setup.
- Review all dependency/image upgrades before deployment. The current Dockerfile
  tracks the upstream Hermes `latest` image; pin a tested release or digest for
  production reproducibility.
- Review Compound Engineering upgrades before changing its pinned commit.
  Codex exposes this plugin's skills under the `compound-engineering:`
  namespace.

## References

- [Hermes providers](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Hermes Docker guide](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Hermes Slack guide](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/slack)
- [OpenAI Codex CLI](https://developers.openai.com/codex/cli/)
- [OpenAI Codex authentication](https://developers.openai.com/codex/auth/)
- [OpenAI Codex app-server](https://developers.openai.com/codex/app-server/)
- [OpenAI plugin development](https://developers.openai.com/plugins/build/plugins)
- [Compound Engineering plugin](https://github.com/EveryInc/compound-engineering-plugin)
- [Paseo documentation](https://paseo.sh/docs)
- [Paseo Docker deployment](https://paseo.sh/docs/docker)
- [Paseo connectivity and relay](https://paseo.sh/docs/connectivity)
- [Paseo security](https://paseo.sh/docs/security)
- [Linear MCP server](https://linear.app/docs/mcp)
- [GitHub CLI authentication](https://cli.github.com/manual/gh_auth_login)
