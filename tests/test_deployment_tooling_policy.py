import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
PASEO_DOCKERFILE = (ROOT / "Dockerfile.paseo").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
VERIFY = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
BOOTSTRAP = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")
PASEO_ENTRYPOINT = (ROOT / "scripts" / "paseo-entrypoint.sh").read_text(
    encoding="utf-8"
)
PASEO_CONFIG = (ROOT / "scripts" / "paseo-config.json").read_text(encoding="utf-8")
LINEAR_CAPABILITY_CHECK = (
    ROOT / "scripts" / "check-linear-mcp-capabilities.py"
).read_text(encoding="utf-8")
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
REVIEW_ENV_EXAMPLE = (ROOT / ".review.env.example").read_text(encoding="utf-8")
REVIEW_RESULT_SCHEMA = (
    ROOT / "automation" / "review-result.schema.json"
).read_text(encoding="utf-8")
REVIEW_RESULT_SCHEMA_JSON = json.loads(REVIEW_RESULT_SCHEMA)


class DeploymentToolingPolicyTests(unittest.TestCase):
    def test_setup_menu_selects_each_bootstrap_target(self):
        targets = {
            "1\n": ("bootstrap-hermes", 0),
            "2\n": ("bootstrap-paseo", 0),
            "3\n": ("bootstrap", 0),
            "4\n": ("", 2),
            "": ("", 2),
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_make = Path(temporary_directory) / "make"
            fake_make.write_text("#!/bin/sh\nprintf '%s\\n' \"$1\"\n")
            fake_make.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{temporary_directory}{os.pathsep}{environment['PATH']}"

            for selection, (expected_output, expected_status) in targets.items():
                with self.subTest(selection=selection):
                    result = subprocess.run(
                        [str(ROOT / "scripts" / "setup.sh")],
                        input=selection,
                        text=True,
                        capture_output=True,
                        env=environment,
                        check=False,
                    )
                    self.assertEqual(result.returncode, expected_status)
                    if expected_output:
                        self.assertTrue(result.stdout.rstrip().endswith(expected_output))

    def test_compose_profiles_select_the_expected_services(self):
        self.assertRegex(
            COMPOSE,
            r"(?ms)^  hermes:\n    profiles: \[\"hermes-only\", \"full\"\]",
        )
        self.assertRegex(
            COMPOSE,
            r"(?ms)^  paseo-docker:\n    profiles: \[\"codex-paseo\", \"full\"\]",
        )
        self.assertRegex(
            COMPOSE,
            r"(?ms)^  paseo:\n    profiles: \[\"codex-paseo\", \"full\"\]",
        )

    def test_restart_recreates_only_services_from_the_installed_profiles(self):
        restart = MAKEFILE.split("restart:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("ps --all -q hermes", restart)
        self.assertIn("--profile hermes-only up -d --force-recreate hermes", restart)
        self.assertIn("ps --all -q paseo paseo-docker", restart)
        self.assertIn("--profile codex-paseo up -d --force-recreate paseo", restart)
        self.assertNotIn("--profile full down", restart)

    def test_hermes_only_switch_is_blocked_for_configured_pr_review(self):
        self.assertRegex(REVIEW_ENV_EXAMPLE, r"(?m)^REVIEW_MONOREPO_ROOT=$")
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            review_env = temporary_path / ".review.env"
            fake_bin = temporary_path / "bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                r"""#!/bin/sh
case "$1" in
  compose)
    printf '%s\n' "{\"services\":{\"hermes\":{\"image\":\"hermes-self-hosted-assistant:local\",\"volumes\":[{\"source\":\"hermes-data\",\"target\":\"/opt/data\"}]}},\"volumes\":{\"hermes-data\":{\"name\":\"${MOCK_VOLUME_NAME:-self-assistant-hermes-data}\"}}}"
    exit 0
    ;;
  info) exit "${MOCK_DOCKER_INFO_STATUS:-0}" ;;
  volume)
    [ "$2" = ls ] || exit 2
    [ "${MOCK_VOLUME_LIST_STATUS:-0}" = 0 ] || exit "$MOCK_VOLUME_LIST_STATUS"
    [ "${MOCK_VOLUME_PRESENT:-1}" = 1 ] && printf '%s\n' "${MOCK_VOLUME_NAME:-self-assistant-hermes-data}"
    exit 0
    ;;
  run) exit "${MOCK_CRON_STATE_STATUS:-1}" ;;
esac
exit 2
"""
            )
            fake_docker.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

            review_env.write_text("REVIEW_MONOREPO_ROOT=/opt/review-workspace\n")
            blocked = subprocess.run(
                [str(ROOT / "scripts" / "guard-hermes-only.sh")],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(blocked.returncode, 1, blocked.stderr)
            self.assertIn("review jobs and reminders require the Paseo service", blocked.stderr)

            review_env.write_text("REVIEW_MONOREPO_ROOT=\n")
            environment["MOCK_CRON_STATE_STATUS"] = "0"
            blocked = subprocess.run(
                [str(ROOT / "scripts" / "guard-hermes-only.sh")],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(blocked.returncode, 1, blocked.stderr)
            self.assertIn("managed Hermes cron jobs are persisted", blocked.stderr)

            environment["MOCK_CRON_STATE_STATUS"] = "1"
            allowed = subprocess.run(
                [str(ROOT / "scripts" / "guard-hermes-only.sh")],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(allowed.returncode, 0)

            environment["MOCK_VOLUME_PRESENT"] = "0"
            missing_volume = subprocess.run(
                [str(ROOT / "scripts" / "guard-hermes-only.sh")],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(missing_volume.returncode, 0)

            environment["MOCK_VOLUME_PRESENT"] = "1"
            environment["MOCK_DOCKER_INFO_STATUS"] = "1"
            docker_error = subprocess.run(
                [str(ROOT / "scripts" / "guard-hermes-only.sh")],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(docker_error.returncode, 2)
            self.assertIn("Could not reach Docker", docker_error.stderr)

            environment["MOCK_DOCKER_INFO_STATUS"] = "0"
            environment["MOCK_VOLUME_LIST_STATUS"] = "2"
            volume_list_error = subprocess.run(
                [str(ROOT / "scripts" / "guard-hermes-only.sh")],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(volume_list_error.returncode, 2)
            self.assertIn("Could not list Docker volumes", volume_list_error.stderr)

            environment["MOCK_VOLUME_LIST_STATUS"] = "0"
            environment["MOCK_VOLUME_PRESENT"] = "1"
            environment["MOCK_CRON_STATE_STATUS"] = "125"
            inspect_error = subprocess.run(
                [str(ROOT / "scripts" / "guard-hermes-only.sh")],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(inspect_error.returncode, 2)
            self.assertIn("Could not inspect the persisted Hermes cron state", inspect_error.stderr)

            review_env.write_text("REVIEW_MONOREPO_ROOT=\n")
            (temporary_path / ".env").write_text('HERMES_DATA_VOLUME="quoted-hermes-data"\n')
            environment["MOCK_VOLUME_NAME"] = "quoted-hermes-data"
            environment["MOCK_CRON_STATE_STATUS"] = "0"
            quoted_volume = subprocess.run(
                [str(ROOT / "scripts" / "guard-hermes-only.sh")],
                cwd=temporary_path,
                text=True,
                capture_output=True,
                env=environment,
                check=False,
            )
            self.assertEqual(quoted_volume.returncode, 1)
            self.assertIn("managed Hermes cron jobs are persisted", quoted_volume.stderr)

    def test_review_result_schema_uses_paseo_compatible_draft(self):
        self.assertIn("http://json-schema.org/draft-07/schema#", REVIEW_RESULT_SCHEMA)
        self.assertNotIn("draft/2020-12", REVIEW_RESULT_SCHEMA)

    def test_review_result_schema_is_a_read_only_material_proposal(self):
        schema = REVIEW_RESULT_SCHEMA_JSON
        self.assertIn("published", schema["required"])
        self.assertEqual(
            schema["properties"]["published"],
            {"type": "boolean", "const": False},
        )
        self.assertIn("objective", schema["required"])
        self.assertIn("product_context", schema["required"])
        self.assertIn("baseline_head_sha", schema["required"])
        self.assertIn("delta", schema["required"])

        def nodes(value):
            if isinstance(value, dict):
                yield value
                for nested in value.values():
                    yield from nodes(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from nodes(nested)

        for node in nodes(schema):
            self.assertTrue({"allOf", "uniqueItems"}.isdisjoint(node), node)
            if "const" in node:
                self.assertIn("type", node, node)

        finding = schema["properties"]["findings"]["items"]
        self.assertNotIn("allOf", finding)
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
        self.assertIn("ARG CODEX_VERSION=0.156.0", PASEO_DOCKERFILE)
        self.assertIn(
            "bubblewrap", PASEO_DOCKERFILE
        )
        self.assertIn('@openai/codex@${CODEX_VERSION}', PASEO_DOCKERFILE)
        self.assertIn("--ignore-scripts", PASEO_DOCKERFILE)
        self.assertIn('CODEX_VERSION: "${CODEX_VERSION:-0.156.0}"', COMPOSE)

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
        self.assertIn("ARG OPENSPEC_VERSION=1.10.0", PASEO_DOCKERFILE)
        self.assertIn('@fission-ai/openspec@${OPENSPEC_VERSION}', PASEO_DOCKERFILE)
        self.assertIn("--ignore-scripts", PASEO_DOCKERFILE)
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
            "setup-company-brain-retros",
            "publish-company-brain-retro",
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
        self.assertIn("target: /opt/global-skills/review-reminder", COMPOSE)
        self.assertIn("/opt/data/skills/custom/pr-reviewer", SYNC_SKILLS)
        self.assertIn("/opt/data/skills/custom/review-reminder", SYNC_SKILLS)
        self.assertIn("/opt/global-skills/review-reminder/.", SYNC_SKILLS)
        self.assertIn('\\"skill\\": \\"codex-pr-review\\"', APPLY_REVIEW_POLICY)

    def test_private_confirmation_policy_fails_closed_and_stays_quiet(self):
        self.assertIn("SLACK_REVIEW_DIGEST_USER_ID", APPLY_REVIEW_POLICY)
        self.assertIn("exactly one decision owner", APPLY_REVIEW_POLICY.lower())
        self.assertIn("decision owner must be present", APPLY_REVIEW_POLICY.lower())
        self.assertIn("Slack user ID", APPLY_REVIEW_POLICY)
        self.assertIn(r"[UW][A-Z0-9_]+", APPLY_REVIEW_POLICY)
        self.assertIn("reconcile-owner", APPLY_REVIEW_POLICY)
        self.assertLess(
            APPLY_REVIEW_POLICY.index("reconcile-owner"),
            APPLY_REVIEW_POLICY.index("hermes config set"),
        )
        self.assertIn("reaction-only", APPLY_REVIEW_POLICY)
        self.assertIn("no automatic final response", APPLY_REVIEW_POLICY)
        self.assertNotIn("send exactly one final response", APPLY_REVIEW_POLICY)

    def test_review_queue_bounds_are_configured_and_validated(self):
        expected = {
            "SLACK_REVIEW_MAX_URLS_PER_MESSAGE=5",
            "SLACK_REVIEW_MAX_ACTIVE_PER_REQUESTER=5",
            "SLACK_REVIEW_MAX_QUEUED=50",
            "SLACK_REVIEW_PROPOSAL_CONCURRENCY=3",
        }
        for setting in expected:
            name = setting.split("=", 1)[0]
            self.assertIn(setting, REVIEW_ENV_EXAMPLE)
            self.assertIn(name, APPLY_REVIEW_POLICY)
            self.assertIn(name, VERIFY)

    def test_runtime_verification_checks_private_workflow_contract(self):
        self.assertIn("review-reminder", VERIFY)
        self.assertIn("schema_version", VERIFY)
        self.assertIn("== 5", VERIFY)
        self.assertIn("review-result.schema.json", VERIFY)
        self.assertIn("workflow_pr_conversations", VERIFY)
        self.assertIn("slack-pr-review-gate", VERIFY)
        self.assertIn("Private PR review reminders", VERIFY)
        self.assertIn("Daily PR review digest", VERIFY)
        self.assertIn("materiality-corpus.json", VERIFY)

    def test_readme_documents_private_confirmation_operations(self):
        required = (
            "approve Pn",
            "publish Pn Cn [Cn ...]",
            "skip Pn",
            "edit Pn Cn: replacement text",
            "dismiss Pn Cn [Cn ...]",
            "one top-level DM",
            "one compact verdict",
            "two working hours",
            "delta unavailable",
            "Repository rules decide",
            "operator-blocked",
            "Manual Slack/GitHub smoke test",
            "materiality-corpus.json",
        )
        for phrase in required:
            self.assertIn(phrase, README)

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

    def test_linear_context_uses_read_write_mcp_oauth(self):
        linear_setup = (ROOT / "scripts" / "auth-linear.sh").read_text(encoding="utf-8")
        self.assertIn("mcp add linear --url https://mcp.linear.app/mcp", linear_setup)
        self.assertNotIn("https://mcp.linear.app/mcp/readonly", linear_setup)
        self.assertNotIn("--scopes read", linear_setup)
        self.assertIn("mcp_oauth_callback_port=5555", linear_setup)
        self.assertIn("docker compose exec --user hermes paseo", linear_setup)
        self.assertIn(
            "TCP-LISTEN:5556,bind=0.0.0.0,reuseaddr,fork", linear_setup
        )
        self.assertIn("TCP:127.0.0.1:5555", linear_setup)
        self.assertIn("socat", PASEO_DOCKERFILE)
        self.assertIn(
            '127.0.0.1:${LINEAR_OAUTH_CALLBACK_HOST_PORT:-5555}:5556', COMPOSE
        )
        self.assertNotIn("network_mode: host", COMPOSE)
        self.assertNotIn("LINEAR_API_KEY", COMPOSE)
        self.assertIn('grep -F "Not logged in"', VERIFY)
        self.assertIn("check-linear-mcp-capabilities", VERIFY)
        self.assertIn('"mcpServerStatus/list"', LINEAR_CAPABILITY_CHECK)
        self.assertIn('"toolsAndAuthOnly"', LINEAR_CAPABILITY_CHECK)
        self.assertIn('tools.get("save_issue")', LINEAR_CAPABILITY_CHECK)
        self.assertIn('{"id", "description", "state"}', LINEAR_CAPABILITY_CHECK)
        self.assertIn("check-linear-mcp-capabilities.py", PASEO_DOCKERFILE)
        self.assertIn("!scripts/check-linear-mcp-capabilities.py", DOCKERIGNORE)

    def test_unattended_reviews_force_the_read_only_linear_endpoint(self):
        paseo_config = json.loads(PASEO_CONFIG)
        review_provider = paseo_config["agents"]["providers"]["codex-review"]
        self.assertEqual(review_provider["extends"], "codex")
        self.assertEqual(
            review_provider["command"],
            [
                "codex",
                "-c",
                'mcp_servers.linear.url="https://mcp.linear.app/mcp/readonly"',
            ],
        )
        self.assertIn("sync-paseo-config.py", PASEO_ENTRYPOINT)
        self.assertIn("sync-paseo-config.py", PASEO_DOCKERFILE)
        self.assertIn("!scripts/sync-paseo-config.py", DOCKERIGNORE)

    def test_paseo_config_sync_preserves_unmanaged_settings(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            defaults_path = temporary_path / "defaults.json"
            current_path = temporary_path / "current.json"
            defaults_path.write_text(PASEO_CONFIG, encoding="utf-8")
            current = {
                "version": 1,
                "daemon": {"listen": "127.0.0.1:9999"},
                "agents": {
                    "providers": {
                        "local-provider": {
                            "extends": "codex",
                            "label": "Local provider",
                        }
                    }
                },
            }
            current_path.write_text(json.dumps(current), encoding="utf-8")

            subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts" / "sync-paseo-config.py"),
                    str(defaults_path),
                    str(current_path),
                ],
                check=True,
            )

            synced = json.loads(current_path.read_text(encoding="utf-8"))
            self.assertEqual(synced["daemon"], current["daemon"])
            self.assertEqual(
                synced["agents"]["providers"]["local-provider"],
                current["agents"]["providers"]["local-provider"],
            )
            self.assertEqual(
                synced["agents"]["providers"]["codex-review"],
                json.loads(PASEO_CONFIG)["agents"]["providers"]["codex-review"],
            )

            synced_inode = current_path.stat().st_ino
            subprocess.run(
                [
                    "python3",
                    str(ROOT / "scripts" / "sync-paseo-config.py"),
                    str(defaults_path),
                    str(current_path),
                ],
                check=True,
            )
            self.assertEqual(current_path.stat().st_ino, synced_inode)

    def test_paseo_uses_an_isolated_tls_docker_daemon(self):
        self.assertIn("docker-compose-plugin", PASEO_DOCKERFILE)
        self.assertIn("docker-ce-cli", PASEO_DOCKERFILE)
        self.assertIn("docker compose version", PASEO_DOCKERFILE)
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
