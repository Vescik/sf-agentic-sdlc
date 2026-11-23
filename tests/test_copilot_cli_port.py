"""Copilot CLI port: the hooks and agent files must hold on the CLI as well as in VS Code.

Contract: docs/copilot-cli-port.md. Regressions covered here:
- an agent with target: vscode or a VS Code-qualified tool name loads in the CLI without its
  editor or shell, and nothing fails loudly;
- the CLI sends camelCase payloads (toolName/toolArgs) for camelCase registrations;
- the CLI's write_bash/write_powershell tools send raw keystrokes to a running shell, which
  no command rule can review;
- the CLI names its new-file tool `create`, which no editor token matched;
- the CLI documents top-level permissionDecision, VS Code reads hookSpecificOutput.
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from scripts import copilot_role_guard as roles
from scripts import copilot_safety_hook as safety
from scripts import validate_harness
from tests.test_validate_harness import GithubCopyBase

ROOT = Path(__file__).resolve().parents[1]


def decision(result: dict) -> str | None:
    return result.get("hookSpecificOutput", {}).get("permissionDecision")


class HookOutputShape(unittest.TestCase):
    def test_decision_is_emitted_for_both_hosts(self) -> None:
        for build in (safety.hook_response, roles.response):
            result = build("deny", "because")
            self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
            self.assertEqual("deny", result["permissionDecision"])
            self.assertEqual("because", result["permissionDecisionReason"])
            self.assertNotIn("hookEventName", {key for key in result if key != "hookSpecificOutput"})

    def test_no_decision_stays_default(self) -> None:
        self.assertEqual({"continue": True}, safety.hook_response())
        self.assertEqual({"continue": True}, roles.response())


class CamelCasePayload(unittest.TestCase):
    def test_tool_args_json_string_is_parsed(self) -> None:
        for module in (safety, roles):
            event = module.normalize_event(
                {"toolName": "bash", "toolArgs": json.dumps({"command": "ls"}), "cwd": "/x"}
            )
            self.assertEqual("bash", event["tool_name"])
            self.assertEqual({"command": "ls"}, event["tool_input"])
            self.assertEqual("/x", event["cwd"])

    def test_snake_case_payload_is_unchanged(self) -> None:
        event = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "toolName": "ignored"}
        self.assertIs(event, safety.normalize_event(event))
        self.assertIs(event, roles.normalize_event(event))

    def test_camel_case_deploy_reaches_the_same_rules(self) -> None:
        payload = json.dumps({
            "toolName": "bash",
            "toolArgs": json.dumps({"command": "sf project deploy start -o prod"}),
            "cwd": str(ROOT),
        })
        for script, extra in (("copilot_safety_hook.py", []), ("copilot_role_guard.py", ["--role", "reviewer"])):
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script), *extra],
                input=payload, capture_output=True, text=True, cwd=ROOT, timeout=30, check=True,
            )
            self.assertEqual("deny", json.loads(completed.stdout)["permissionDecision"], script)


class InteractiveShellInput(unittest.TestCase):
    def test_write_shell_tools_are_denied_for_every_role(self) -> None:
        for tool in ("write_bash", "write_powershell"):
            event = {"tool_name": tool, "tool_input": {"shellId": "1", "input": "y"}, "cwd": str(ROOT)}
            self.assertEqual("deny", decision(safety.evaluate_event(event)), tool)
            for role in sorted(roles.ROLES):
                self.assertEqual("deny", decision(roles.evaluate_event(event, role)), f"{tool} {role}")


class CliCreateTool(unittest.TestCase):
    def test_create_is_an_edit_tool(self) -> None:
        self.assertTrue(roles.is_edit_tool("create"))
        # Exact match only: MCP tools that merely contain the word stay out of path checks.
        self.assertFalse(roles.is_edit_tool("salesforce/review_create_summary"))

    def test_reviewer_cannot_create_files(self) -> None:
        event = {
            "tool_name": "create",
            "tool_input": {"path": str(ROOT / ".github/hooks/extra.json"), "file_text": "{}"},
            "cwd": str(ROOT),
        }
        self.assertEqual("deny", decision(roles.evaluate_event(event, "reviewer")))


class PortableAgentFrontmatter(GithubCopyBase):
    def test_target_vscode_is_rejected(self) -> None:
        self.rewrite_frontmatter(".github/agents/designer.agent.md", lambda data: data.update(target="vscode"))
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(any("target must be unset" in message for message in audit.errors), audit.errors)

    def test_vscode_only_tool_name_is_rejected(self) -> None:
        self.rewrite_frontmatter(
            ".github/agents/designer.agent.md",
            lambda data: data["tools"].append("execute/runInTerminal"),
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(any("execute/runInTerminal" in message for message in audit.errors), audit.errors)

    def test_repository_agents_are_portable(self) -> None:
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertEqual([], [m for m in audit.errors if "target" in m or "legacy tools" in m])


class PromptsAreThinAliases(GithubCopyBase):
    """Copilot CLI does not read .github/prompts; the logic must live in the skill."""

    def append_to_prompt(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

    def test_every_prompt_skill_has_a_matching_contract(self) -> None:
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertEqual([], [m for m in audit.errors if "alias" in m or "Invocation contract" in m])

    def test_logic_in_a_prompt_body_is_rejected(self) -> None:
        self.append_to_prompt(
            ".github/prompts/search-ado.prompt.md",
            "\nRequire `query`; default `target=both`. " + "Every call carries the project. " * 8,
        )
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(any("must stay a thin alias" in m for m in audit.errors), audit.errors)

    def test_contract_role_must_match_the_prompt_agent(self) -> None:
        self.rewrite_frontmatter(".github/prompts/search-ado.prompt.md", lambda data: data.update(agent="reviewer"))
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(any("Invocation contract role must be `reviewer`" in m for m in audit.errors), audit.errors)

    def test_vscode_tool_syntax_in_a_skill_is_rejected(self) -> None:
        self.append_to_prompt(".github/skills/search-ado/SKILL.md", "\nAsk with `#tool:vscode/askQuestions`.\n")
        audit = self.run_audit(validate_harness.check_customizations, root=self.root)
        self.assertTrue(any("host-neutral wording" in m for m in audit.errors), audit.errors)


class CliConfigFiles(unittest.TestCase):
    def test_safety_hook_file_uses_cli_version_and_windows_commands(self) -> None:
        hooks = json.loads((ROOT / ".github/hooks/safety.json").read_text(encoding="utf-8"))
        self.assertEqual(1, hooks["version"])
        entry = hooks["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["windows"], entry["powershell"])

    def test_cli_mcp_servers_are_the_read_only_launchers(self) -> None:
        servers = json.loads((ROOT / ".github/mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        self.assertEqual(validate_harness.CLI_MCP_SERVERS, {name: server["args"] for name, server in servers.items()})

    def test_root_mcp_json_has_the_same_launchers_with_relative_paths(self) -> None:
        servers = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        expected = {name: [arg.replace("${COPILOT_SESSION_CWD}/", "") for arg in args]
                    for name, args in validate_harness.CLI_MCP_SERVERS.items()}
        self.assertEqual(expected, {name: server["args"] for name, server in servers.items()})

    def test_salesforce_launcher_rejects_ambiguous_org_source(self) -> None:
        launcher = str(ROOT / "scripts/start_salesforce_mcp.mjs")
        for args, message in (
            (["--mode", "review"], "the org alias is missing"),
            (["--mode", "review", "--org", "a", "--org-from-config"], "not both"),
        ):
            completed = subprocess.run(["node", launcher, *args], capture_output=True, text=True, timeout=30)
            self.assertEqual(2, completed.returncode, completed.stderr)
            self.assertIn(message, completed.stderr)


if __name__ == "__main__":
    unittest.main()
