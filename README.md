# Hermes Self-Hosted Assistant

Reproducible Docker Compose deployment of Hermes Agent as a GitHub pull-request
review assistant. It uses the Hermes agent runtime with the `openai-codex`
provider and interactive ChatGPT/Codex OAuth; it does not require an
`OPENAI_API_KEY`.

The repository owns its Codex workflow skills, three Hermes orchestration skills,
the pinned Compound Engineering plugin configuration, the persisted
review-history schema, the daily digest definition, and the Slack review-only
policy. Every installation supplies its own credentials and Slack identifiers
through ignored runtime files.

## Included boundaries

- OpenAI Codex provider authenticated through ChatGPT OAuth
- Pinned standalone Codex CLI with its own persistent ChatGPT OAuth
- Pinned Paseo daemon and web UI for using that Codex CLI remotely
- Hermes-to-Paseo delegation of exact PR review requests
- GitHub CLI OAuth for read-only proposal analysis and explicitly confirmed
  `APPROVE` or `COMMENT` actions
- SQLite schema v3 history for requests, private proposals, decisions, delivery
  receipts, reminders, and GitHub-verified publications
- Linear issue snapshots and normalized findings for later analysis
- Private Slack PR threads, bounded reminders, and a daily DM digest at 17:00
  in `America/Mexico_City`
- Pinned OpenSpec CLI for strict validation of specification changes
- Compound Engineering `3.24.0` installed into the persistent Codex profile
- Vendored `writing-for-agents` and explicit-only experimental `retro` skills
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
| Paseo daemon identity, pairings, and projects | `/opt/data/.paseo` | Never |
| GitHub CLI OAuth | `/opt/data/.config/gh/hosts.yml` | Never |
| Native Git credential configuration | `/opt/data/.gitconfig` | Never |
| Hermes configuration and integration secrets | `/opt/data/config.yaml`, `/opt/data/.env` | Never |
| Sessions and pairings | `/opt/data/sessions` and Hermes runtime state | Never |
| Review workspace | `/opt/data/repos/reserhub-revenue-full` | Never |
| Verified review history | `/opt/data/review-history/reviews.sqlite3` | Never |
| Managed Hermes cron IDs | `/opt/data/cron/repository-managed-jobs.json` | Never |
| Repository-managed Codex skills | `skills/{codex-self-review,pr-reviewer,pr-decision-review,writing-for-agents,retro}` | Yes |
| Compound Engineering plugin cache and registration | `/opt/data/.codex` | Never |
| Hermes orchestration skills | `skills/{codex-pr-review,review-digest,review-reminder}` | Yes |
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
SLACK_REVIEW_MAX_URLS_PER_MESSAGE=5
SLACK_REVIEW_MAX_ACTIVE_PER_REQUESTER=5
SLACK_REVIEW_MAX_QUEUED=50
SLACK_REVIEW_PROPOSAL_CONCURRENCY=3
TZ=America/Mexico_City
```

`SLACK_REVIEW_DIGEST_USER_ID` may be left blank when exactly one owner is
configured; that single owner becomes both the private decision owner and the
digest recipient. If it is set, it must name one member of
`SLACK_REVIEW_OWNER_USER_IDS`. Policy application, cron synchronization, and
deployment verification fail closed for a missing, ambiguous, or non-owner
decision owner.

The four queue values bound URLs per Slack message, active requests per sender,
all queued-plus-running proposals, and simultaneous Codex analyses. They must be
positive integers. Repeated work for the same repository and PR is coalesced by
the persisted workflow and does not create another private conversation.

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
make sync-codex-plugins
make sync-crons
```

The derived image installs pinned standalone Codex (`0.149.1` by default), its
Linux `bubblewrap` sandbox prerequisite, OpenSpec (`1.10.0`), and Paseo (`0.5.2`).
Override `CODEX_VERSION`, `OPENSPEC_VERSION`, or `PASEO_VERSION` only after
validating the new version.

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
- An accepted request has a reaction-only pending state. Hermes sends no
  automatic public acknowledgement or final response.
- Each requested PR gets one top-level DM summary for the decision owner; its
  questions, proposal changes, reminders, re-reviews, and action stay in that
  message thread.
- After the first terminal outcome, the original request thread gets one
  compact verdict message. The gate edits that message as sibling PRs finish
  instead of posting another message.

## Private review confirmation

Hermes does not publish a Codex review directly. `pr-reviewer` is mounted only
in Codex's user skill directory inside Paseo and always returns a read-only,
head-bound proposal. The path for a Slack request is:

```text
Slack request
  -> reaction-only pending state
  -> SQLite request and PR conversation
  -> Paseo / Codex $pr-reviewer read-only proposal
  -> one top-level DM per PR
  -> exact owner command in that DM thread
  -> current-head guard and deterministic GitHub action
  -> one compact verdict in the original request thread
```

The proposal identifies the repository and PR, exact head SHA, objective,
suggested decision, and material candidate comments with stable IDs. Assertion
placement, assertion constants, one-use helper extraction, and speculative
abstraction advice are withheld. Ask ordinary questions in the DM thread;
ordinary language is read-only. Only these exact, revision-bound commands
mutate a proposal or authorize a GitHub action:

```text
approve Pn
publish Pn Cn [Cn ...]
skip Pn
edit Pn Cn: replacement text
dismiss Pn Cn [Cn ...]
```

Replace `Pn` and `Cn` with the visible revision and candidate IDs. A missing,
stale, or inactive revision is rejected. `edit` and `dismiss` change only the
private draft. `approve` and `publish` re-read the PR identity and head before
writing. Approval is never offered for a self-authored PR, and it is disabled
unless branch protection proves that stale approvals are dismissed; this keeps
a head race from satisfying a merge requirement with an obsolete approval.

If a new commit arrives, every command for the old revision becomes stale. The
same DM conversation receives a re-review from the exact prior head to the new
head, with addressed, still-open, and new findings separated. A force-push that
removes the baseline produces a full current-head proposal labeled
`delta unavailable`; it still requires a new command.

An unanswered proposal gets a private thread reminder after two working hours,
counted Monday-Friday from 09:00 to 18:00 in `TZ`. It gets one final reminder at
09:00 on the next working day and then appears only in the daily private digest.
No reminder timeout can approve, publish, skip, create another top-level DM, or
post a public reminder. The recovery sweep may create the original top-level DM
only when analysis finished but its first summary was never sent.

### Recovery and privacy boundary

SQLite is authoritative; Slack messages and reactions are projections. A lost
Slack receipt is searched only in the exact DM/thread using its workflow key.
If the send cannot be proven present or absent, the delivery becomes
`operator-blocked`: inspect that exact destination and the Hermes logs, then
resolve the stored receipt deliberately. Do not replay the request, delete the
row, or post the private proposal in the review channel. A verdict edit failure
also never falls back to a second public verdict.

If a restart strands completed analysis before its first Slack summary, the
reminder sweep resumes that proposal and sends the summary once to the
configured decision owner. Its receipt establishes the same stable PR thread
that normal intake would have created; it never uses the source channel or cron
delivery target.

GitHub actions are commit-bound and reconciled by their publication receipts.
When a private result says `recovery_required`, fix the reported GitHub/auth
problem and send the same exact revision command again; idempotency and verified
receipts prevent already-confirmed comments from being duplicated. A head
mismatch starts re-review instead of recovery. The legacy run-recovery commands
remain available for older publish-first records:

```bash
make review-recover RUN_ID=REVIEW_RUN_UUID
make review-recover RUN_ID=REVIEW_RUN_UUID FORCE=1
make review-cleanup
make review-cleanup RUN_ID=REVIEW_RUN_UUID
```

Private objective, evidence, candidate text, questions, edits, reminders, and
errors stay in the owner's DM thread and SQLite. The review channel receives
only the pending reaction and, after a terminal outcome exists, the single
compact verdict containing PR identity, outcome, reviewed head, and published
comment count. The database lives in `hermes-data`, so normal volume backup and
restore includes the workflow audit trail.

Preview the daily digest input with:

```bash
make digest-preview
```

### Quality and smoke verification

Run the local policy/state-machine suite first, then the deployed integration
check after `make restart` and `make sync-crons`:

```bash
make test
make verify
```

The labeled audit boundary is committed in
`skills/pr-reviewer/evals/materiality-corpus.json`. Deployment verification
checks that the mounted corpus still contains both `withhold` and `retain`
examples and that the eval harness consumes it. Run the full model-backed replay
when changing reviewer policy:

```bash
cd skills/pr-reviewer
python3 scripts/eval.py --runs 5
```

Manual Slack/GitHub smoke test on allowlisted test PRs:

1. Send one channel request containing two PR URLs. Confirm only the pending
   reaction is public and two separate DM roots arrive.
2. Ask a question in one DM thread, then run `edit Pn Cn: replacement text` and
   `publish Pn Cn`. Confirm GitHub contains only that edited current-head
   comment.
3. Push a commit to the other PR, try its old command, and confirm rejection
   plus a delta summary in the existing thread. Decide using the new revision.
4. Confirm the source thread contains one compact verdict that was edited as
   the two PRs completed. Confirm no private analysis or reminder appeared in
   the channel.

## Repository-managed cron jobs

All schedules live in the single committed file
[`config/crons.json`](config/crons.json). It stores the cron expression together
with the Hermes skill, prompt, delivery target, and working directory. The
private reminder sweep runs every 15 minutes and returns `NO_REPLY` so the cron
delivery target never receives a fallback message. The daily digest is
`0 17 * * *`; with `TZ=America/Mexico_City`, it runs at 17:00 Mexico City local
time throughout the year and includes proposals that exhausted both reminders.

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
Pull or copy these files, recreate the services so the new read-only skill
mounts are applied, and synchronize the pinned plugin without deleting the
volume:

```bash
make init
make build
make up
make sync-skills
make sync-codex-plugins
make apply-review-policy
make restart
make sync-crons
make paseo-register-workspace
make paseo-provider-status
# Run make paseo-pair only if this installation is not paired yet.
make verify
```

`make sync-skills` also prunes the six retired repository-owned Codex workflow
skills from `/opt/data/.agents/skills`; unrelated skills in that persistent
directory are left untouched.

`make sync-codex-plugins` migrates the repository's former `self-assistant`
marketplace registration, then installs Compound Engineering from
`EveryInc/compound-engineering-plugin` at the exact
`compound-engineering-v3.24.0` tag. It recreates only that managed marketplace;
other plugins and marketplaces are preserved.

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
make sync-codex-plugins   # install Compound Engineering 3.24.0
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

The repository copies are canonical. They include `codex-self-review`,
`pr-reviewer`, the explicit-only `pr-decision-review` workflow vendored from
`reservamos/skills@94c241ed26e6d6cc04cbbc8333232dcfd00a7c51`, and Matt
Pocock's `writing-for-agents` and `retro` skills vendored from
`mattpocock/skills@3cca18b368ae95cdbdebbff572ccafa662551015`. To install
them as the current user's global Codex skills:

```bash
make install-global-skill
```

For every workflow skill, the installer preserves an existing non-matching
global installation with a timestamped backup before creating the symlink.
It also removes retired workflow symlinks previously created from this checkout,
while leaving independently managed entries with the same names untouched.
Restart Codex afterward so it refreshes the discovered skill catalog.

The same repository-managed skills are bind-mounted read-only into Paseo's
Codex skill root on the VPS. `retro` is an upstream in-progress stub and remains
explicit-only; invoke it manually when you intentionally want to trial it:

```text
Use $retro for this coding session.
```

Invoke the decision workflow explicitly:

```text
Use $pr-decision-review on PR 123.
```

It is intended for PRs authored by someone other than the authenticated GitHub
user and always requires an explicit human action before publishing comments
or a review decision.

After changing the OpenSpec pin or any image-installed tool, rebuild before
restarting:

```bash
git pull --ff-only origin main
make build
make restart
make verify
```

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
docker compose exec -T --user hermes paseo codex plugin list --json
docker compose exec -T --user hermes paseo codex plugin marketplace list --json
make sync-skills
make sync-codex-plugins
make sync-crons
make paseo-register-workspace
make paseo-provider-status
make verify
```

The restore command creates the configured volume if necessary and refuses to
overwrite a non-empty volume. The plugin list commands are diagnostic; the sync
target performs the pinned installation and migrates the repository's old
marketplace entry. Do not restart the old installation after the VPS starts
using the migrated OAuth and messaging state.

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
## References

- [Hermes providers](https://hermes-agent.nousresearch.com/docs/integrations/providers)
- [Hermes Docker guide](https://hermes-agent.nousresearch.com/docs/user-guide/docker)
- [Hermes Slack guide](https://hermes-agent.nousresearch.com/docs/user-guide/messaging/slack)
- [OpenAI Codex CLI](https://developers.openai.com/codex/cli/)
- [OpenAI Codex authentication](https://developers.openai.com/codex/auth/)
- [OpenAI Codex app-server](https://developers.openai.com/codex/app-server/)
- [Paseo documentation](https://paseo.sh/docs)
- [Paseo Docker deployment](https://paseo.sh/docs/docker)
- [Paseo connectivity and relay](https://paseo.sh/docs/connectivity)
- [Paseo security](https://paseo.sh/docs/security)
- [Linear MCP server](https://linear.app/docs/mcp)
- [GitHub CLI authentication](https://cli.github.com/manual/gh_auth_login)
