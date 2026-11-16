"""Plan 03a: JSON authority and retained project/URL isolation, without ADO access."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.ado_config import ado_config_error
from scripts import copilot_safety_hook as safety
from scripts import validate_harness


CONFIG = {"ado": {
    "organization": "example-org", "project": "Example Project",
    "allowedHttpsOrigins": ["https://dev.azure.com/example-org"],
}}
ROOT = Path(__file__).resolve().parents[1]


class AdoConfigTests(unittest.TestCase):
    def test_valid_configuration_and_nonado_prefix_remain_usable(self):
        config = deepcopy(CONFIG)
        config["ado"]["allowedHttpsOrigins"].append("https://docs.example.com/reference")
        self.assertIsNone(ado_config_error(config))
        config["ado"]["project"] = "Zespół Projektowy"
        self.assertIsNone(ado_config_error(config))

    def test_malformed_config_and_scope_values_fail_closed_without_echoing_values(self):
        for config in (None, [], {}, {"ado": None}, {"ado": []}):
            with self.subTest(config=config):
                self.assertIsNotNone(ado_config_error(config))
        for key in ("organization", "project"):
            for value in (None, 42, False, [], {}, "", " ", " prefix", "suffix ",
                          "a\nb", "<placeholder>", "TODO", "TBD", "CHANGEme", "REPLACE_ME",
                          "your-org-slug", "your-project-name", "https://secret.invalid/x"):
                config = deepcopy(CONFIG)
                config["ado"][key] = value
                with self.subTest(key=key, value=value):
                    error = ado_config_error(config)
                    self.assertIsNotNone(error)
                    self.assertIn(f"ado.{key}", error)
                    self.assertNotIn("secret.invalid", error)

    def test_stale_broad_or_malformed_origins_are_not_scope_authority(self):
        for origin in ("https://dev.azure.com", "https://dev.azure.com/other-org",
                       "https://almsearch.dev.azure.com/example-org",
                       "https://example-org.visualstudio.com", "http://example.com",
                       "https://user:secret@example.com", "https://example.com:443",
                       "https://example.com:", "HTTPS://example.com",
                       "https://example.com?", "https://example.com#", "https://example.com/a b"):
            config = deepcopy(CONFIG)
            config["ado"]["allowedHttpsOrigins"].append(origin)
            with self.subTest(origin=origin):
                self.assertIsNotNone(ado_config_error(config))
        for origins in (None, [], [False], [CONFIG["ado"]["allowedHttpsOrigins"][0]] * 2):
            config = deepcopy(CONFIG)
            config["ado"]["allowedHttpsOrigins"] = origins
            self.assertIsNotNone(ado_config_error(config))


class AdoHookTests(unittest.TestCase):
    def invoke(self, root, payload, tool_name="ado-readonly/search_wiki"):
        event = {"tool_name": tool_name, "tool_input": payload}
        output = StringIO()
        with patch.object(safety, "HARNESS_ROOT", root), \
                patch("sys.stdin", StringIO(json.dumps(event))), redirect_stdout(output):
            self.assertEqual(0, safety.main())
        result = json.loads(output.getvalue())
        return "allow" if result.get("continue") else result["hookSpecificOutput"]["permissionDecision"]

    def test_project_scope_is_not_a_hard_stop(self):
        # Plan 05, D-R1: the hook no longer blocks ADO reads for a missing config or for a
        # project outside the configured one; the ADO tool capability rules stay.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual("allow", self.invoke(root, {"project": ["Other Project"]}))
            (root / "config").mkdir()
            (root / "config/harness.local.json").write_text(json.dumps(CONFIG))
            self.assertEqual("allow", self.invoke(root, {"project": ["Other Project"]}))

    def test_pinned_vendor_project_id_target_is_denied_by_the_full_hook(self):
        payload = {
            "project": "Example Project", "projectId": "OTHER-PROJECT-GUID",
            "repositoryId": "REPO-GUID", "pullRequestId": 1, "workItemId": 2,
        }
        # Exercise the installed schema and callback with a recording API. This
        # imports tools only, never the server entrypoint or its authentication.
        program = r"""
import { readFileSync } from 'node:fs';
import { z } from 'zod';
const manifest = JSON.parse(readFileSync('node_modules/@azure-devops/mcp/package.json', 'utf8'));
if (manifest.version !== '2.8.1') throw new Error('Expected the pinned vendor version');
globalThis.fetch = async () => { throw new Error('Network forbidden in scope contract test'); };
const { configureWorkItemTools } = await import('./node_modules/@azure-devops/mcp/dist/tools/work-items.js');
const tools = new Map();
const calls = [];
configureWorkItemTools(
  { tool(name, description, schema, callback) { tools.set(name, { schema, callback }); } },
  async () => { throw new Error('Authentication forbidden in scope contract test'); },
  async () => ({ getWorkItemTrackingApi: async () => ({
    updateWorkItem: async (customHeaders, document, id, project) => {
      calls.push({ id, project });
      return { id };
    },
  }) }),
  () => 'offline-scope-contract',
);
const tool = tools.get('wit_link_work_item_to_pull_request');
const parsed = z.object(tool.schema).parse(JSON.parse(process.argv[1]));
await tool.callback(parsed);
console.log(JSON.stringify({ parsed, calls }));
"""
        result = subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", program, json.dumps(payload)],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        observed = json.loads(result.stdout)
        self.assertNotIn("project", observed["parsed"])
        self.assertEqual([{"id": 2, "project": "OTHER-PROJECT-GUID"}], observed["calls"])
        with patch.object(safety, "load_config", return_value=deepcopy(CONFIG)):
            self.assertEqual("deny", self.invoke(
                ROOT, payload, "ado-readonly/wit_link_work_item_to_pull_request",
            ))

class AdoWiringTests(unittest.TestCase):
    def audit_with(self, relative, mutate):
        original = validate_harness.load_json
        def changed(path, audit):
            data = original(path, audit)
            if path == validate_harness.ROOT / relative:
                data = deepcopy(data)
                mutate(data)
            return data
        audit = validate_harness.Audit()
        with patch.object(validate_harness, "load_json", changed):
            validate_harness.check_settings_and_mcp(audit)
        return audit.errors

    def test_current_wiring_passes_and_direct_vendor_or_env_cannot_return(self):
        self.assertEqual([], self.audit_with(".vscode/mcp.json", lambda data: None))
        for args in (["node_modules/@azure-devops/mcp/dist/index.js", "${env:ADO_ORGANIZATION}"],
                     ["scripts/start_ado_mcp.mjs", "other-org"]):
            errors = self.audit_with(".vscode/mcp.json", lambda data:
                data["servers"]["ado-readonly"].update(args=args))
            self.assertTrue(any("local-config launcher" in error for error in errors), errors)
        errors = self.audit_with("package.json", lambda data:
            data["dependencies"].update({"@azure-devops/mcp": "latest"}))
        self.assertTrue(any("pinned to 2.8.1" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
