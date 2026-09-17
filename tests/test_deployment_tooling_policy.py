import unittest
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
VERIFY = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
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
SYNC_CODEX_PLUGINS_PATH = ROOT / "scripts" / "sync-codex-plugins.sh"
CRON_CONFIG = (ROOT / "config" / "crons.json").read_text(encoding="utf-8")
REVIEW_RESULT_SCHEMA = (
    ROOT / "automation" / "review-result.schema.json"
).read_text(encoding="utf-8")
REVIEW_RESULT_SCHEMA_JSON = json.loads(REVIEW_RESULT_SCHEMA)


class DeploymentToolingPolicyTests(unittest.TestCase):
    def test_review_result_schema_uses_paseo_compatible_draft(self):
        self.assertIn("http://json-schema.org/draft-07/schema#", REVIEW_RESULT_SCHEMA)
        self.assertNotIn("draft/2020-12", REVIEW_RESULT_SCHEMA)

    def test_review_result_schema_is_a_read_only_material_proposal(self):
        schema = REVIEW_RESULT_SCHEMA_JSON
        self.assertIn("published", schema["required"])
        self.assertEqual(schema["properties"]["published"], {"const": False})
        self.assertIn("objective", schema["required"])
        self.assertIn("baseline_head_sha", schema["required"])
        self.assertIn("delta", schema["required"])

        finding = schema["properties"]["findings"]["items"]
        self.assertEqual(
            set(finding["properties"]["category"]["enum"]),
            {
                "correctness",
                "security",
                "data_layer",
                "migration_safety",
                "architecture",
                "test_coverage",
                "error_handling",
                "scraper",
            },
        )
        self.assertEqual(
            set(finding["properties"]["severity"]["enum"]),
            {"blocker", "major", "minor", "nit"},
        )

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

    def test_gstack_integrations_are_not_managed(self):
        obsolete_paths = (
            ROOT / ".agents" / "plugins" / "marketplace.json",
            ROOT / "scripts" / "remove_gstack.py",
            ROOT / "scripts" / "uninstall-gstack.sh",
        )
        for path in obsolete_paths:
            self.assertFalse(path.exists(), path)

        for content in (MAKEFILE, COMPOSE):
            self.assertNotIn("gstack", content.lower())

        self.assertNotIn("gstack", VERIFY.lower())

    def test_compound_engineering_is_installed_from_a_pinned_remote_marketplace(self):
        self.assertTrue(SYNC_CODEX_PLUGINS_PATH.is_file())
        sync_codex_plugins = SYNC_CODEX_PLUGINS_PATH.read_text(encoding="utf-8")

        self.assertIn("compound-engineering-v3.24.0", sync_codex_plugins)
        self.assertIn(
            "compound-engineering@compound-engineering-plugin", sync_codex_plugins
        )
        self.assertIn(
            "codex plugin marketplace add EveryInc/compound-engineering-plugin",
            sync_codex_plugins,
        )
        self.assertIn('--ref "$expected_ref" --json', sync_codex_plugins)
        self.assertIn('codex plugin add "$plugin_id" --json', sync_codex_plugins)
        self.assertNotIn("/opt/self-assistant-marketplace", sync_codex_plugins)
        self.assertNotIn("compound-engineering", DOCKERFILE.lower())
        self.assertNotIn("self-assistant-marketplace", COMPOSE)
        self.assertIn("sync-codex-plugins: ##", MAKEFILE)
        self.assertIn(
            "sync-codex-plugins",
            MAKEFILE.split("bootstrap:", 1)[1].splitlines()[0],
        )
        self.assertGreaterEqual(
            VERIFY.count("compound-engineering@compound-engineering-plugin"), 2
        )

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

    def test_repo_managed_codex_skills_are_mounted_only_in_paseo(self):
        for skill_name in (
            "codex-self-review",
            "pr-reviewer",
            "pr-decision-review",
            "writing-for-agents",
            "retro",
        ):
            self.assertIn(
                f"target: /opt/data/.agents/skills/{skill_name}", COMPOSE
            )
            self.assertIn(
                'skill_path="/opt/data/.agents/skills/$skill_name"', VERIFY
            )
        self.assertIn('findmnt -n -o OPTIONS --target "$skill_path"', VERIFY)
        self.assertIn('*,ro,*)', VERIFY)
        self.assertNotIn("target: /opt/global-skills/pr-reviewer", COMPOSE)
        self.assertIn("target: /opt/global-skills/codex-pr-review", COMPOSE)
        self.assertIn("target: /opt/global-skills/review-digest", COMPOSE)
        self.assertIn("/opt/data/skills/custom/pr-reviewer", SYNC_SKILLS)
        self.assertIn('\\"skill\\": \\"codex-pr-review\\"', APPLY_REVIEW_POLICY)

    def test_matt_pocock_skills_are_vendored_at_the_reviewed_revision(self):
        revision = "3cca18b368ae95cdbdebbff572ccafa662551015"
        for skill_name in ("writing-for-agents", "retro"):
            skill_root = ROOT / "skills" / skill_name
            self.assertTrue((skill_root / "SKILL.md").is_file())
            self.assertTrue((skill_root / "agents" / "openai.yaml").is_file())
            provenance = (skill_root / "UPSTREAM.md").read_text(encoding="utf-8")
            self.assertIn(revision, provenance)
            self.assertIn("Copyright (c) 2026 Matt Pocock", provenance)

        retro = (ROOT / "skills" / "retro" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("disable-model-invocation: true", retro)
        self.assertIn("writing-for-agents", retro)
        self.assertNotIn("Call the Skill tool", retro)

        retro_openai = (
            ROOT / "skills" / "retro" / "agents" / "openai.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("allow_implicit_invocation: false", retro_openai)

    def test_retired_codex_workflow_skills_are_removed_from_persistent_state(self):
        for skill_name in (
            "auto-pr-workflow",
            "linear-ticket-selection",
            "merge-pr-and-clean-worktree",
            "prepare-branch-for-pr",
            "publish-ready-pr",
            "ticket-openspec-planning",
        ):
            self.assertFalse((ROOT / "skills" / skill_name).exists())
            self.assertNotIn(f"source: ./skills/{skill_name}", COMPOSE)
            self.assertNotIn(
                f"target: /opt/data/.agents/skills/{skill_name}", COMPOSE
            )
            self.assertIn(skill_name, SYNC_SKILLS)
            self.assertIn(skill_name, VERIFY)

        self.assertIn(
            'skill_path="/opt/data/.agents/skills/$skill_name"', SYNC_SKILLS
        )
        self.assertIn(
            'if [ -L "$skill_path" ] || [ -e "$skill_path" ]; then',
            SYNC_SKILLS,
        )
        self.assertIn('rm -rf -- "$skill_path"', SYNC_SKILLS)
        self.assertIn(
            'skill_path="/opt/data/.agents/skills/$skill_name"', VERIFY
        )
        self.assertIn('test ! -e "$skill_path"', VERIFY)
        self.assertIn('test ! -L "$skill_path"', VERIFY)

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
