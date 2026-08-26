.DEFAULT_GOAL := help

.PHONY: help init bootstrap build up down restart status logs chat codex auth-codex select-model auth-codex-cli codex-cli-status auth-linear check-tool-updates paseo-up paseo-status paseo-logs paseo-register-workspace paseo-pair paseo-provider-status auth-github gateway-setup sync-skills sync-crons cron-status digest-preview review-history-init install-global-skill apply-review-policy clone-workspace github-status workspace-status workspace-sync verify test volume-backup volume-restore

help: ## Show the available commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the Hermes image with GitHub CLI
	docker compose build --pull

init: ## Create ignored local configuration files without overwriting them
	./scripts/bootstrap.sh

bootstrap: init build up sync-skills sync-crons ## Build and start a fresh installation
	@printf '%s\n' "Next: authenticate Hermes, Codex CLI, and GitHub; clone the workspace; then run make paseo-register-workspace and make paseo-pair"

up: ## Start Hermes in the background
	docker compose up -d

down: ## Stop Hermes while preserving its persistent data volume
	docker compose down

restart: ## Recreate Hermes while preserving authentication and data
	docker compose down
	docker compose up -d

status: ## Show the Hermes container status
	docker compose ps

logs: ## Follow Hermes logs (Ctrl-C to stop)
	docker compose logs --tail=100 -f hermes

chat: ## Open an interactive Hermes terminal chat
	docker compose exec hermes hermes chat

codex: ## Open Codex CLI in the configured review monorepo root
	docker compose exec --user hermes hermes /bin/sh -eu -c \
		': "$${REVIEW_MONOREPO_ROOT:?set it in .review.env}"; cd "$$REVIEW_MONOREPO_ROOT"; exec codex'

auth-codex: ## Authenticate a ChatGPT/Codex subscription interactively
	docker compose exec hermes \
		hermes auth add openai-codex --type oauth --no-browser

select-model: ## Select the authenticated Hermes model interactively
	docker compose exec hermes hermes model

auth-codex-cli: ## Authenticate the standalone Codex CLI with device code
	docker compose exec --user hermes hermes codex login --device-auth

codex-cli-status: ## Verify standalone Codex CLI authentication
	docker compose exec -T --user hermes hermes codex login status

auth-linear: ## Authenticate Codex to the read-only Linear MCP endpoint
	./scripts/auth-linear.sh

check-tool-updates: ## Check npm for newer Codex and Paseo releases
	./scripts/check-tool-updates.sh

paseo-up: ## Start the Paseo daemon and bundled web UI
	docker compose up -d paseo

paseo-status: ## Show Paseo daemon status
	docker compose exec -T paseo curl --fail --silent --show-error \
		http://127.0.0.1:6767/api/health

paseo-logs: ## Follow Paseo daemon logs (Ctrl-C to stop)
	docker compose logs --tail=100 -f paseo

paseo-register-workspace: ## Register the configured monorepo with Paseo
	docker compose exec -T --user hermes paseo /bin/sh -eu -c \
		': "$${REVIEW_MONOREPO_ROOT:?set it in .review.env}"; paseo project create --host 127.0.0.1:6767 "$${REVIEW_MONOREPO_ROOT}"'

paseo-pair: ## Pair this daemon with the hosted Paseo web app
	docker compose exec -T --user hermes paseo \
		paseo daemon pair --relay --home /opt/data/.paseo

paseo-provider-status: ## Verify Paseo can launch the authenticated Codex CLI
	docker compose exec -T --user hermes paseo \
		paseo provider diagnostic --host 127.0.0.1:6767 --json codex

auth-github: ## Authenticate GitHub CLI interactively as the Hermes user
	docker compose exec --user hermes hermes \
		gh auth login --hostname github.com --git-protocol https --web
	docker compose exec -T --user hermes hermes gh auth setup-git

gateway-setup: ## Configure Slack, Telegram, or another messaging platform
	docker compose exec hermes hermes gateway setup

sync-skills: ## Sync Hermes orchestration and digest skills
	./scripts/sync-skills.sh

sync-crons: ## Reconcile Hermes jobs from the single config/crons.json file
	./scripts/sync-crons.sh

cron-status: ## List the active Hermes cron jobs
	docker compose exec -T --user hermes hermes hermes cron list

review-history-init: ## Initialize or migrate the persisted review database
	docker compose exec -T --user hermes hermes \
		python3 /opt/review-automation/review_automation.py init

digest-preview: ## Show the verified previous-24-hours digest source as JSON
	docker compose exec -T --user hermes hermes /bin/sh -eu -c \
		'python3 /opt/review-automation/review_automation.py digest-source --hours 24 --timezone "$${TZ:-America/Mexico_City}"'

install-global-skill: ## Link the repository skill into the local Codex skill directory
	./scripts/install-global-skill.sh

apply-review-policy: ## Persist the configured review-only Slack policy
	./scripts/apply-review-policy.sh

clone-workspace: ## Clone or verify the configured monorepo and submodules
	./scripts/clone-workspace.sh

github-status: ## Verify GitHub CLI authentication without printing the token
	docker compose exec -T --user hermes hermes \
		gh auth status --active --hostname github.com

workspace-status: ## Verify the review monorepo and initialized submodules
	docker compose exec -T --user hermes hermes \
		/opt/review-workspace/prepare-workspace.sh --check

workspace-sync: ## Safely refresh review refs without changing checked-out files
	docker compose exec -T --user hermes hermes \
		/opt/review-workspace/prepare-workspace.sh --fetch

verify: ## Verify provider, GitHub, skill, plugin, and workspace configuration
	./scripts/verify.sh

test: ## Run repository policy tests and validate the skill
	python -m unittest discover -s tests -v
	python scripts/validate-skill.py

volume-backup: ## Back up the stopped persistent volume (BACKUP_FILE=/absolute/file.tgz)
	@test -n "$(BACKUP_FILE)" || (echo "Set BACKUP_FILE to an absolute path" >&2; exit 2)
	./scripts/backup-volume.sh "$(BACKUP_FILE)"

volume-restore: ## Restore into an empty volume (BACKUP_FILE=/absolute/file.tgz)
	@test -n "$(BACKUP_FILE)" || (echo "Set BACKUP_FILE to an absolute path" >&2; exit 2)
	./scripts/restore-volume.sh "$(BACKUP_FILE)"
