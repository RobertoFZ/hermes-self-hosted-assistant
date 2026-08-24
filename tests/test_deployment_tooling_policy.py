import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "compose.yaml").read_text(encoding="utf-8")
VERIFY = (ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")


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

    def test_openspec_is_pinned_in_the_image(self):
        self.assertIn("ARG OPENSPEC_VERSION=1.6.0", DOCKERFILE)
        self.assertIn('@fission-ai/openspec@${OPENSPEC_VERSION}', DOCKERFILE)
        self.assertIn("--ignore-scripts", DOCKERFILE)
        self.assertIn('OPENSPEC_VERSION: "${OPENSPEC_VERSION:-1.6.0}"', COMPOSE)

    def test_runtime_verification_checks_the_openspec_version(self):
        self.assertIn('test "$(openspec --version)" = "$OPENSPEC_VERSION"', VERIFY)


if __name__ == "__main__":
    unittest.main()
