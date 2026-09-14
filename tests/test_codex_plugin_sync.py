import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
SYNC_SCRIPT = ROOT / "scripts" / "sync-codex-plugins.sh"
DESIRED_ID = "compound-engineering@compound-engineering-plugin"
LEGACY_ID = "compound-engineering@self-assistant"


class CodexPluginSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.state_path = self.root / "state.json"
        self.log_path = self.root / "commands.jsonl"

        self._write_executable(
            "docker",
            """
            #!/bin/sh
            while [ "$#" -gt 0 ] && [ "$1" != /bin/sh ]; do
              shift
            done
            exec "$@"
            """,
        )
        self._write_executable(
            "codex",
            """
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            state_path = Path(os.environ["FAKE_CODEX_STATE"])
            log_path = Path(os.environ["FAKE_CODEX_LOG"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            args = sys.argv[1:]
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps(args) + "\\n")

            def save():
                state_path.write_text(json.dumps(state), encoding="utf-8")

            if args[:3] == ["plugin", "list", "--json"]:
                if state.pop("fail_list_once", False):
                    save()
                    print(state.get("list_error", "self-assistant marketplace is invalid"), file=sys.stderr)
                    raise SystemExit(1)
                print(json.dumps({"installed": state["installed"], "available": []}))
            elif args[:3] == ["plugin", "marketplace", "list"]:
                print(
                    json.dumps(
                        {
                            "marketplaces": [
                                {"name": name, **details}
                                for name, details in state["marketplaces"].items()
                            ]
                        }
                    )
                )
            elif args[:3] == ["plugin", "marketplace", "remove"]:
                marketplace_name = args[3]
                state["marketplaces"].pop(marketplace_name, None)
                state["installed"] = [
                    item
                    for item in state["installed"]
                    if item["pluginId"].split("@", 1)[-1] != marketplace_name
                ]
                save()
                print("{}")
            elif args[:3] == ["plugin", "marketplace", "add"]:
                if state.get("fail_marketplace_add"):
                    raise SystemExit(1)
                state["marketplaces"]["compound-engineering-plugin"] = {
                    "source": args[3],
                    "ref": args[args.index("--ref") + 1],
                }
                save()
                print("{}")
            elif args[:2] == ["plugin", "remove"]:
                plugin_id = args[2]
                state["installed"] = [
                    item for item in state["installed"] if item["pluginId"] != plugin_id
                ]
                save()
                print("{}")
            elif args[:2] == ["plugin", "add"]:
                plugin_id = args[2]
                state["installed"] = [
                    item for item in state["installed"] if item["pluginId"] != plugin_id
                ]
                state["installed"].append(
                    {
                        "pluginId": plugin_id,
                        "name": "compound-engineering",
                        "version": "3.24.0",
                        "enabled": True,
                    }
                )
                save()
                print("{}")
            else:
                raise SystemExit(f"unsupported fake codex invocation: {args}")
            """,
        )

    def _write_executable(self, name, contents):
        path = self.bin_dir / name
        path.write_text(textwrap.dedent(contents).lstrip(), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def _run(self, state):
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env['PATH']}"
        env["FAKE_CODEX_STATE"] = str(self.state_path)
        env["FAKE_CODEX_LOG"] = str(self.log_path)
        result = subprocess.run(
            [str(SYNC_SCRIPT)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        final_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        commands = [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
        ]
        return result, final_state, commands

    @staticmethod
    def _plugin(plugin_id, name, version="1.0.0"):
        return {
            "pluginId": plugin_id,
            "name": name,
            "version": version,
            "enabled": True,
        }

    def test_fresh_install_preserves_unrelated_plugin_and_marketplace(self):
        unrelated = self._plugin("example@other", "example")
        result, state, _ = self._run(
            {
                "installed": [unrelated],
                "marketplaces": {"other": {"source": "example/other"}},
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(unrelated, state["installed"])
        self.assertIn("other", state["marketplaces"])
        desired = [item for item in state["installed"] if item["pluginId"] == DESIRED_ID]
        self.assertEqual(len(desired), 1)
        self.assertEqual(desired[0]["version"], "3.24.0")

    def test_legacy_install_is_removed_only_after_replacement_is_added(self):
        result, state, commands = self._run(
            {
                "installed": [
                    self._plugin(LEGACY_ID, "compound-engineering", "3.23.0")
                ],
                "marketplaces": {"self-assistant": {"source": "local"}},
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(LEGACY_ID, {item["pluginId"] for item in state["installed"]})
        self.assertLess(
            commands.index(["plugin", "add", DESIRED_ID, "--json"]),
            commands.index(["plugin", "remove", LEGACY_ID, "--json"]),
        )

    def test_exact_install_is_not_removed_or_refetched(self):
        desired = self._plugin(DESIRED_ID, "compound-engineering", "3.24.0")
        result, state, commands = self._run(
            {
                "installed": [desired],
                "marketplaces": {
                    "compound-engineering-plugin": {
                        "source": "EveryInc/compound-engineering-plugin",
                        "ref": "compound-engineering-v3.24.0",
                    }
                },
                "fail_marketplace_add": True,
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(desired, state["installed"])
        self.assertNotIn(
            ["plugin", "marketplace", "remove", "compound-engineering-plugin", "--json"],
            commands,
        )
        self.assertNotIn(["plugin", "add", DESIRED_ID, "--json"], commands)
        self.assertEqual(
            commands,
            [
                ["plugin", "list", "--json"],
                ["plugin", "marketplace", "list", "--json"],
            ],
        )

    def test_failed_replacement_fetch_keeps_working_legacy_plugin(self):
        result, state, commands = self._run(
            {
                "installed": [
                    self._plugin(LEGACY_ID, "compound-engineering", "3.23.0")
                ],
                "marketplaces": {"self-assistant": {"source": "local"}},
                "fail_marketplace_add": True,
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(LEGACY_ID, {item["pluginId"] for item in state["installed"]})
        self.assertNotIn(["plugin", "remove", LEGACY_ID, "--json"], commands)

    def test_unmanaged_compound_plugin_aborts_before_mutation(self):
        conflict = self._plugin("compound-engineering@third-party", "compound-engineering")
        result, state, commands = self._run(
            {"installed": [conflict], "marketplaces": {"third-party": {}}}
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(state["installed"], [conflict])
        self.assertEqual(commands, [["plugin", "list", "--json"]])

    def test_broken_legacy_marketplace_is_removed_then_retried(self):
        result, state, commands = self._run(
            {
                "installed": [],
                "marketplaces": {"self-assistant": {"source": "broken-local"}},
                "fail_list_once": True,
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("self-assistant", state["marketplaces"])
        self.assertEqual(
            commands[1],
            ["plugin", "marketplace", "remove", "self-assistant", "--json"],
        )
        self.assertEqual(commands[2], ["plugin", "list", "--json"])

    def test_unrelated_inventory_failure_aborts_without_mutation(self):
        result, state, commands = self._run(
            {
                "installed": [],
                "marketplaces": {"other": {"source": "broken"}},
                "fail_list_once": True,
                "list_error": "other marketplace is invalid",
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("other marketplace is invalid", result.stderr)
        self.assertEqual(state["marketplaces"], {"other": {"source": "broken"}})
        self.assertEqual(commands, [["plugin", "list", "--json"]])


if __name__ == "__main__":
    unittest.main()
