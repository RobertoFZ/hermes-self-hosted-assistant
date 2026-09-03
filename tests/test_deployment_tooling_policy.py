import json
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
SYNC_CODEX_PLUGINS = (ROOT / "scripts" / "sync-codex-plugins.sh").read_text(
    encoding="utf-8"
)
REMOVE_GSTACK = (ROOT / "scripts" / "remove_gstack.py").read_text(
    encoding="utf-8"
)
UNINSTALL_GSTACK = (ROOT / "scripts" / "uninstall-gstack.sh").read_text(
    encoding="utf-8"
)
CODEX_PLUGIN_MARKETPLACE = json.loads(
    (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
)
CRON_CONFIG = (ROOT / "config" / "crons.json").read_text(encoding="utf-8")
REVIEW_RESULT_SCHEMA = (
    ROOT / "automation" / "review-result.schema.json"
).read_text(encoding="utf-8")


class DeploymentToolingPolicyTests(unittest.TestCase):
    def test_review_result_schema_uses_paseo_compatible_draft(self):
        self.assertIn("http://json-schema.org/draft-07/schema#", REVIEW_RESULT_SCHEMA)
        self.assertNotIn("draft/2020-12", REVIEW_RESULT_SCHEMA)

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

    def test_compound_engineering_is_repo_managed_and_pinned(self):
        self.assertEqual(CODEX_PLUGIN_MARKETPLACE["name"], "self-assistant")
        plugin = CODEX_PLUGIN_MARKETPLACE["plugins"][0]
        self.assertEqual(plugin["name"], "compound-engineering")
        self.assertEqual(
            plugin["source"]["url"],
            "https://github.com/EveryInc/compound-engineering-plugin.git",
        )
        self.assertEqual(
            plugin["source"]["sha"],
            "3ad9b51bceecf0158e590c882034d0398dbb9c5c",
        )
        self.assertEqual(
            COMPOSE.count("target: /opt/self-assistant-marketplace/.agents"), 2
        )
        self.assertIn("sync-codex-plugins: ##", MAKEFILE)
        self.assertIn(
            "sync-codex-plugins",
            MAKEFILE.split("bootstrap:", 1)[1].splitlines()[0],
        )
        self.assertIn(
            'codex plugin marketplace add "$marketplace_root" --json',
            SYNC_CODEX_PLUGINS,
        )
        self.assertIn(
            'codex plugin add "$plugin_id" --json', SYNC_CODEX_PLUGINS
        )
        self.assertIn(
            "Another Compound Engineering plugin is enabled", SYNC_CODEX_PLUGINS
        )
        self.assertGreaterEqual(
            VERIFY.count("compound-engineering@self-assistant"), 2
        )

    def test_gstack_is_removed_only_from_container_skill_roots(self):
        self.assertIn("uninstall-gstack: ##", MAKEFILE)
        self.assertIn(
            "uninstall-gstack", MAKEFILE.split("bootstrap:", 1)[1].splitlines()[0]
        )
        self.assertIn("/opt/review-tooling/remove_gstack.py", UNINSTALL_GSTACK)
        self.assertIn('Path("/opt/data/.codex/skills")', REMOVE_GSTACK)
        self.assertIn('Path("/opt/data/.agents/skills")', REMOVE_GSTACK)
        self.assertIn('path.name == "gstack"', REMOVE_GSTACK)
        self.assertIn('path.name.startswith("gstack-")', REMOVE_GSTACK)
        self.assertIn("remove_gstack.py --check", VERIFY)

    def test_tool_update_check_is_read_only_and_checks_all_npm_packages(self):
        self.assertIn("check-tool-updates: ##", MAKEFILE)
        self.assertIn('npm view --silent "@openai/codex" dist-tags.latest', UPDATE_CHECK)
        self.assertIn(
            'npm view --silent "@getpaseo/cli" dist-tags.latest', UPDATE_CHECK
        )
        self.assertIn(
            'npm view --silent "@fission-ai/openspec" dist-tags.latest', UPDATE_CHECK
        )
        self.assertIn("codex --version", UPDATE_CHECK)
        self.assertIn("openspec --version", UPDATE_CHECK)
        self.assertIn("paseo --version", UPDATE_CHECK)
        self.assertNotIn("npm install", UPDATE_CHECK)

    def test_openspec_is_pinned_in_the_image(self):
        self.assertIn("ARG OPENSPEC_VERSION=1.10.0", DOCKERFILE)
        self.assertIn('@fission-ai/openspec@${OPENSPEC_VERSION}', DOCKERFILE)
        self.assertIn("--ignore-scripts", DOCKERFILE)
        self.assertIn('OPENSPEC_VERSION: "${OPENSPEC_VERSION:-1.10.0}"', COMPOSE)

    def test_runtime_verification_checks_the_openspec_version(self):
        self.assertIn('test "$(openspec --version)" = "$OPENSPEC_VERSION"', VERIFY)
        self.assertIn(
            '(cd "$REVIEW_MONOREPO_ROOT" && openspec context --json >/dev/null)',
            VERIFY,
        )
        self.assertIn("openspec-propose openspec-apply-change", VERIFY)
        self.assertIn('generatedBy: \\"$OPENSPEC_VERSION\\"', VERIFY)

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

    def test_auto_pr_bundle_is_codex_only_and_hermes_has_orchestration_skills(self):
        for skill_name in (
            "auto-pr-workflow",
            "linear-ticket-selection",
            "ticket-openspec-planning",
            "prepare-branch-for-pr",
            "publish-ready-pr",
            "merge-pr-and-clean-worktree",
            "codex-self-review",
            "pr-reviewer",
        ):
            self.assertIn(
                f"target: /opt/data/.agents/skills/{skill_name}", COMPOSE
            )
            self.assertIn(
                f'\"/opt/data/.agents/skills/$skill_name/SKILL.md\"', VERIFY
            )
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

    def test_review_recovery_has_an_explicit_make_target(self):
        self.assertIn("review-recover: ##", MAKEFILE)
        self.assertIn("review_automation.py recover", MAKEFILE)
        self.assertIn("review-cleanup: ##", MAKEFILE)
        self.assertIn("review_automation.py cleanup", MAKEFILE)

    def test_slack_policy_separates_owner_and_reviewer_slash_commands(self):
        self.assertIn(
            "gateway.platforms.slack.extra.allow_bots all", APPLY_REVIEW_POLICY
        )
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
            "Slack review or slash-command access policy is not applied", VERIFY
        )


if __name__ == "__main__":
    unittest.main()
