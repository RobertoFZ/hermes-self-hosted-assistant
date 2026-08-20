.DEFAULT_GOAL := help

.PHONY: help init bootstrap build up down restart status logs chat auth-codex select-model auth-github gateway-setup sync-skills install-global-skill apply-review-policy clone-workspace github-status workspace-status workspace-sync verify test volume-backup volume-restore

help: ## Show the available commands
	@awk 'BEGIN {FS = ":.*## "; printf "Usage: make <target>\n\nTargets:\n"} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the Hermes image with GitHub CLI
	docker compose build --pull

init: ## Create ignored local configuration files without overwriting them
	./scripts/bootstrap.sh

bootstrap: init build up sync-skills ## Build and start a fresh installation
	@printf '%s\n' "Next: make auth-codex, make select-model, make auth-github, and make clone-workspace"

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

auth-codex: ## Authenticate a ChatGPT/Codex subscription interactively
	docker compose exec hermes \
		hermes auth add openai-codex --type oauth --no-browser

select-model: ## Select the authenticated Hermes model interactively
	docker compose exec hermes hermes model

auth-github: ## Authenticate GitHub CLI interactively as the Hermes user
	docker compose exec --user hermes hermes \
		gh auth login --hostname github.com --git-protocol https --web
	docker compose exec -T --user hermes hermes gh auth setup-git

gateway-setup: ## Configure Slack, Telegram, or another messaging platform
	docker compose exec hermes hermes gateway setup

sync-skills: ## Sync the repository-owned pr-reviewer skill into Hermes
	./scripts/sync-skills.sh

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
		/opt/data/skills/custom/pr-reviewer/scripts/prepare-workspace.sh --check

workspace-sync: ## Safely refresh review refs without changing checked-out files
	docker compose exec -T --user hermes hermes \
		/opt/data/skills/custom/pr-reviewer/scripts/prepare-workspace.sh --fetch

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
