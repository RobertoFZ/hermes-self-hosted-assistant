import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
VERIFY = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
PASEO_ENTRYPOINT = (ROOT / "scripts" / "paseo-entrypoint.sh").read_text(
    encoding="utf-8"
)
PASEO_CONFIG = (ROOT / "scripts" / "paseo-config.json").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")
UPDATE_CHECK = (ROOT / "scripts" / "check-tool-updates.sh").read_text(
    encoding="utf-8"
)
APPLY_REVIEW_POLICY = (ROOT / "scripts" / "apply-review-policy.sh").read_text(
    encoding="utf-8"
)
SYNC_SKILLS = (ROOT / "scripts" / "sync-skills.sh").read_text(encoding="utf-8")
CRON_CONFIG = (ROOT / "config" / "crons.json").read_text(encoding="utf-8")


class DeploymentToolingPolicyTests(unittest.TestCase):
    def test_codex_cli_is_pinned_in_the_image(self):
        self.assertIn("ARG CODEX_VERSION=0.149.1", DOCKERFILE)
        self.assertIn(
            "apt-get install -y --no-install-recommends bubblewrap", DOCKERFILE
        )
        self.assertIn('@openai/codex@${CODEX_VERSION}', DOCKERFILE)
        self.assertIn("--ignore-scripts", DOCKERFILE)
        self.assertIn('CODEX_VERSION: "${CODEX_VERSION:-0.149.1}"', COMPOSE)

    def test_runtime_verification_checks_codex_version_and_auth(self):
        self.assertIn(
            'test "$(codex --version)" = "codex-cli $CODEX_VERSION"', VERIFY
        )
        self.assertIn("command -v bwrap", VERIFY)
        self.assertIn("codex login status", VERIFY)

    def test_codex_make_target_uses_the_configured_monorepo_root(self):
        self.assertIn("codex: ## Open Codex CLI", MAKEFILE)
        self.assertIn('cd "$$REVIEW_MONOREPO_ROOT"; exec codex', MAKEFILE)

    def test_tool_update_check_is_read_only_and_checks_both_npm_packages(self):
        self.assertIn("check-tool-updates: ##", MAKEFILE)
        self.assertIn('npm view --silent "@openai/codex" dist-tags.latest', UPDATE_CHECK)
        self.assertIn(
            'npm view --silent "@getpaseo/cli" dist-tags.latest', UPDATE_CHECK
        )
        self.assertIn("codex --version", UPDATE_CHECK)
        self.assertIn("paseo --version", UPDATE_CHECK)
        self.assertNotIn("npm install", UPDATE_CHECK)

    def test_openspec_is_pinned_in_the_image(self):
        self.assertIn("ARG OPENSPEC_VERSION=1.6.0", DOCKERFILE)
        self.assertIn('@fission-ai/openspec@${OPENSPEC_VERSION}', DOCKERFILE)
        self.assertIn("--ignore-scripts", DOCKERFILE)
        self.assertIn('OPENSPEC_VERSION: "${OPENSPEC_VERSION:-1.6.0}"', COMPOSE)

    def test_runtime_verification_checks_the_openspec_version(self):
        self.assertIn('test "$(openspec --version)" = "$OPENSPEC_VERSION"', VERIFY)

    def test_paseo_is_pinned_in_the_image(self):
        self.assertIn("ARG PASEO_VERSION=0.5.2", DOCKERFILE)
        self.assertIn('@getpaseo/cli@${PASEO_VERSION}', DOCKERFILE)
        self.assertIn('PASEO_VERSION: "${PASEO_VERSION:-0.5.2}"', COMPOSE)
        self.assertIn("!scripts/paseo-entrypoint.sh", DOCKERIGNORE)
        self.assertIn("!scripts/paseo-config.json", DOCKERIGNORE)

    def test_paseo_service_is_loopback_only_and_shares_persistent_state(self):
        self.assertIn('"127.0.0.1:${PASEO_HOST_PORT:-6767}:6767"', COMPOSE)
        self.assertIn('PASEO_PASSWORD: "${PASEO_PASSWORD:?set it in .env}"', COMPOSE)
        self.assertIn('PASEO_HOSTNAMES: "paseo"', COMPOSE)
        self.assertIn("- hermes-data:/opt/data", COMPOSE)
        self.assertIn("--reuid=\"$HERMES_UID\"", PASEO_ENTRYPOINT)
        self.assertNotIn("chown -R", PASEO_ENTRYPOINT)
        self.assertIn('"dictation": {', PASEO_CONFIG)
        self.assertIn('"voiceMode": {', PASEO_CONFIG)
        self.assertGreaterEqual(PASEO_CONFIG.count('"enabled": false'), 2)

    def test_pr_reviewer_is_codex_only_and_hermes_has_orchestration_skills(self):
        self.assertIn("target: /opt/data/.agents/skills/pr-reviewer", COMPOSE)
        self.assertNotIn("target: /opt/global-skills/pr-reviewer", COMPOSE)
        self.assertIn("target: /opt/global-skills/codex-pr-review", COMPOSE)
        self.assertIn("target: /opt/global-skills/review-digest", COMPOSE)
        self.assertIn("/opt/data/skills/custom/pr-reviewer", SYNC_SKILLS)
        self.assertIn('\\"skill\\": \\"codex-pr-review\\"', APPLY_REVIEW_POLICY)

    def test_daily_digest_uses_single_repository_config_at_1700_mexico_time(self):
        self.assertIn('"schedule": "0 17 * * *"', CRON_CONFIG)
        self.assertIn('"timezone": "${TZ}"', CRON_CONFIG)
        self.assertIn("America/Mexico_City", (ROOT / ".review.env.example").read_text(encoding="utf-8"))
        self.assertIn("sync-crons: ##", MAKEFILE)
        self.assertIn("/opt/review-config/crons.json", COMPOSE)

    def test_linear_context_uses_read_only_mcp_oauth(self):
        linear_setup = (ROOT / "scripts" / "auth-linear.sh").read_text(encoding="utf-8")
        self.assertIn("https://mcp.linear.app/mcp/readonly", linear_setup)
        self.assertIn("mcp_oauth_callback_port=5555", linear_setup)
        self.assertIn('127.0.0.1:${LINEAR_OAUTH_CALLBACK_HOST_PORT:-5555}:5555', COMPOSE)
        self.assertNotIn("LINEAR_API_KEY", COMPOSE)
        self.assertIn('grep -F "Not logged in"', VERIFY)

    def test_paseo_uses_an_isolated_tls_docker_daemon(self):
        self.assertIn("docker-compose", DOCKERFILE)
        self.assertIn("docker compose version", DOCKERFILE)
        self.assertIn('image: "${PASEO_DOCKER_IMAGE:-docker:29.7.2-dind}"', COMPOSE)
        self.assertIn("privileged: true", COMPOSE)
        self.assertIn('DOCKER_HOST: "tcp://paseo-docker:2376"', COMPOSE)
        self.assertIn('DOCKER_TLS_VERIFY: "1"', COMPOSE)
        self.assertIn("paseo-docker-data:/var/lib/docker", COMPOSE)
        self.assertIn("paseo-docker-certs:/certs/client", COMPOSE)
        self.assertNotIn("source: /var/run/docker.sock", COMPOSE)
        self.assertIn('PASEO_DOCKER_CERT_SOURCE:=/run/paseo-docker-certs', PASEO_ENTRYPOINT)
        self.assertIn('install -m 0400 -o "$HERMES_UID"', PASEO_ENTRYPOINT)
        self.assertIn("--clear-groups", PASEO_ENTRYPOINT)
        self.assertNotIn("DOCKER_SOCKET_GID", PASEO_ENTRYPOINT)
        self.assertIn("test ! -S /var/run/docker.sock", VERIFY)
        self.assertIn("docker info", VERIFY)
        self.assertIn("docker compose version", VERIFY)

    def test_bootstrap_backfills_a_paseo_password(self):
        self.assertIn(
            'set_if_empty .env PASEO_PASSWORD "$(openssl rand -hex 32)"',
            BOOTSTRAP,
        )

    def test_paseo_make_targets_cover_initial_setup(self):
        self.assertIn("paseo-register-workspace: ##", MAKEFILE)
        self.assertIn("paseo daemon pair --relay", MAKEFILE)
        self.assertIn("paseo provider diagnostic --host 127.0.0.1:6767", MAKEFILE)

    def test_runtime_verification_checks_paseo_and_registered_workspace(self):
        self.assertIn('test "$(paseo --version)" = "$PASEO_VERSION"', VERIFY)
        self.assertIn("http://127.0.0.1:6767/api/health", VERIFY)
        self.assertIn(
            "paseo provider diagnostic --host 127.0.0.1:6767 --json codex",
            VERIFY,
        )
        self.assertIn("paseo project ls --host 127.0.0.1:6767 --json", VERIFY)
        self.assertIn('paseo project ls --host "$PASEO_HOST" --json', VERIFY)

    def test_slack_policy_separates_owner_and_reviewer_slash_commands(self):
        self.assertIn(
            "gateway.platforms.slack.extra.allow_admin_from", APPLY_REVIEW_POLICY
        )
        self.assertIn(
            "gateway.platforms.slack.extra.group_allow_admin_from",
            APPLY_REVIEW_POLICY,
        )
        self.assertIn(
            'gateway.platforms.slack.extra.user_allowed_commands "[]"',
            APPLY_REVIEW_POLICY,
        )
        self.assertIn(
            'gateway.platforms.slack.extra.group_user_allowed_commands "[]"',
            APPLY_REVIEW_POLICY,
        )
        self.assertIn(
            "Slack slash-command access policy is not applied", VERIFY
        )


if __name__ == "__main__":
    unittest.main()
