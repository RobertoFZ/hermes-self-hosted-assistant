# Hermes Self-Hosted Assistant

Reproducible Docker Compose deployment of Hermes Agent as a GitHub pull-request
review assistant. It uses the Hermes agent runtime with the `openai-codex`
provider and interactive ChatGPT/Codex OAuth; it does not require an
`OPENAI_API_KEY`.

The repository owns the `pr-reviewer` skill and Slack review-only policy. Every
installation supplies its own credentials and Slack identifiers through ignored
runtime files.

## Included boundaries

- OpenAI Codex provider authenticated through ChatGPT OAuth
- GitHub CLI OAuth for reading PRs and publishing `APPROVE` or `COMMENT`
- Persistent Hermes state, credentials, sessions, skills, and review checkout
- Review-only Slack channel and delegated-reviewer DMs
- Optional Telegram or other Hermes gateway integrations
- Loopback-only authenticated web dashboard
- No Docker socket, PR code execution, GitHub merging, `REQUEST_CHANGES`, or
  Codex App-Server Runtime

ChatGPT/Codex usage limits are account-managed and outside this repository.

## Persistent state

Compose mounts the named volume `self-assistant-hermes-data` at `/opt/data`.
The name is deliberately stable even when the repository is cloned into a new
directory, so adopting this standardized checkout does not create a new empty
Hermes profile.

Never run `docker compose down -v` unless you intend to erase the installation.

Important runtime locations:

| Data | Container path | Committed? |
|---|---|---|
| Hermes Codex OAuth | `/opt/data/auth.json` | Never |
| GitHub CLI OAuth | `/opt/data/.config/gh/hosts.yml` | Never |
| Native Git credential configuration | `/opt/data/.gitconfig` | Never |
| Hermes configuration and integration secrets | `/opt/data/config.yaml`, `/opt/data/.env` | Never |
| Sessions and pairings | `/opt/data/sessions` and Hermes runtime state | Never |
| Review workspace | `/opt/data/repos/reserhub-revenue-full` | Never |
| Canonical skill source | `skills/pr-reviewer` | Yes |

The OAuth stores are independent. Codex CLI credentials from `~/.codex` are
not mounted and are not required.

## First-time setup

Requirements: Docker Engine with Compose, Make, Python 3, and OpenSSL.

Create the ignored local configuration files:

```bash
make init
```

`make init` generates dashboard credentials in `.env` when the file is absent
and copies `.review.env.example` to `.review.env`. It never overwrites existing
files.

Fill in these deployment-specific values in `.review.env`:

```dotenv
SLACK_ALLOWED_USERS=OWNER_ID,REVIEWER_ID
SLACK_REVIEW_OWNER_USER_IDS=OWNER_ID
SLACK_REVIEWER_USER_IDS=REVIEWER_ID
SLACK_REVIEW_CHANNEL_ID=CHANNEL_ID
```

The repository and submodule defaults are already declared in the example.
`SLACK_ALLOWED_USERS` must contain the owner plus every delegated reviewer
because the Hermes Slack adapter authorizes users before the review policy runs.

Build and start:

```bash
make build
make up
make sync-skills
```

Authenticate the ChatGPT/Codex subscription interactively:

```bash
make auth-codex
make select-model
```

Open the device-code URL yourself and authenticate the intended ChatGPT account.
Do not automate the browser step. Choose the OpenAI Codex subscription provider
and one of the models offered by the live Hermes picker.

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

Configure Slack, Telegram, or another supported gateway when needed:

```bash
make gateway-setup
```

For Slack, finish the interactive token setup, then apply the standardized
review-only policy and restart:

```bash
make apply-review-policy
make restart
make verify
```

If `make verify` reports that native Git cannot authenticate, refresh its
credential helper without changing the existing OAuth login:

```bash
docker compose exec -T --user hermes hermes gh auth setup-git
```

The Slack policy behaves as follows:

- The configured owner keeps normal assistant access outside the review channel.
- Delegated reviewers can submit review requests only in the configured channel
  or one-to-one DMs.
- Delegated messages must contain one or more allowed GitHub PR URLs.
- Unsupported URLs or unrelated instructions are discarded before inference.
- Accepted requests get one immediate threaded acknowledgement; tool progress
  remains hidden until Hermes posts the result.

## Existing installations

This repository keeps the existing `self-assistant-hermes-data` volume name.
After pulling or copying these files, switch Hermes to the repository-owned
skill and configurable plugin without touching the volume:

```bash
make init
make sync-skills
make apply-review-policy
make restart
make verify
```

The container is recreated, but `/opt/data` and all OAuth, sessions, pairings,
configuration, and repository data remain in the named volume.

## Common commands

```bash
make help                 # list targets
make up                   # start Hermes
make down                 # stop without deleting data
make restart              # recreate while preserving the volume
make status               # container status
make logs                 # follow gateway logs
make chat                 # interactive terminal chat
make sync-skills          # copy the repository skill into Hermes state
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
- Never commit `.env`, `.review.env`, `auth.json`, `hosts.yml`, volume archives,
  sessions, or repository checkouts.
- Keep `GITHUB_TOKEN` blank when using persisted `gh` OAuth; an environment token
  takes precedence.
- Do not expose the dashboard directly to the internet.
- Do not mount `/var/run/docker.sock`.
- Review all dependency/image upgrades before deployment. The current Dockerfile
  tracks the upstream Hermes `latest` image; pin a tested release or digest for
  production reproducibility.

## References

- [Hermes providers](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Hermes Docker guide](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Hermes Slack guide](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/slack)
- [GitHub CLI authentication](https://cli.github.com/manual/gh_auth_login)
