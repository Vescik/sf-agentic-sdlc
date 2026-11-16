from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts import copilot_safety_hook as safety
from tests.salesforce_policy_fixture import configured_policy, ROWS


ROOT = Path(__file__).resolve().parents[1]


def hook_decision(output: dict[str, Any]) -> str:
    if output.get("continue") is True:
        return "continue"
    return str(output.get("hookSpecificOutput", {}).get("permissionDecision"))


def run_hook(script: str, event: dict[str, Any], *args: str) -> dict[str, Any]:
    # Test subprocess uses a fixed synthetic identity provider, never machine credentials.
    bootstrap = (
        "import runpy,sys; from tests.salesforce_policy_fixture import configured_policy; "
        "sys.argv=sys.argv[1:]; "
        "ctx=configured_policy(); ctx.__enter__(); runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", bootstrap, str(ROOT / "scripts" / script), *args],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


def write_local_config(root: Path) -> None:
    config = {
        "salesforce": {
            "orgs": [
                {
                    "alias": "dev-sbx",
                    "environment": "development",
                    "expectedInstanceHost": "example--dev.sandbox.my.salesforce.com",
                    "expectedOrganizationId": "00D000000000001AAA",
                },
                {
                    "alias": "qa-sbx",
                    "environment": "uat",
                    "expectedInstanceHost": "example--qa.sandbox.my.salesforce.com",
                    "expectedOrganizationId": "00D000000000002AAA",
                },
            ],
            "review": {
                "enabled": True,
                "apiVersion": "67.0",
                "allowedPackageNamespaces": ["examplepkg"],
                "allowedObjectApiNames": ["ExampleManagedObject__c"],
                "maxFieldsPerObject": 500,
                "evidenceMaxAgeMinutes": 30,
            },
        },
        "safety": {},
    }
    (root / "config").mkdir()
    (root / "config/harness.local.json").write_text(json.dumps(config), encoding="utf-8")



def role_terminal(command: str, role: str, root: Path | None = None) -> str:
    """Role-guard decision for one terminal command (plan 05, D-T1: no per-role allowlist)."""
    from scripts import copilot_role_guard as role_guard

    root = root or ROOT
    with patch.object(role_guard, "HARNESS_ROOT", root), patch.object(role_guard, "_log_decision"):
        result = role_guard.evaluate_event(
            {"cwd": str(root), "tool_name": "run_in_terminal", "tool_input": {"command": command}}, role
        )
    return "continue" if result.get("continue") else result["hookSpecificOutput"]["permissionDecision"]

class GlobalSafetyHookTests(unittest.TestCase):
    def test_data_mutation_is_allowed_for_any_target(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {
                        "command": "sf data upsert bulk --file records.csv --sobject Account --target-org qa-sbx"
                    },
                },
            )
            self.assertEqual(hook_decision(output), "continue")

    def test_real_deploy_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {
                        "command": "sf project deploy start --target-org qa-sbx"
                    },
                },
            )
            self.assertEqual(hook_decision(output), "ask")
            reason = output["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn("Salesforce org qa-sbx", reason)
            self.assertIn("Should I run this deployment?", reason)

    def _hook_decision_in_repo(self, root: Path, command: str) -> str:
        event = {
            "tool_name": "execute/runInTerminal",
            "tool_input": {"command": command},
        }
        stdout = StringIO()
        with (
            patch.object(safety, "HARNESS_ROOT", root),
            patch.object(safety.sf_policy, "local_authorizations", return_value=ROWS),
            patch.object(safety.sf_policy.os, "environ", {}),
            # Windows cannot resolve Path.home() after its environment is cleared.
            # Keep home/default discovery synthetic on every test platform.
            patch.object(safety.sf_policy.Path, "home", return_value=root),
            patch.object(safety.sf_policy, "_defaults", return_value=[]),
            patch("sys.stdin", StringIO(json.dumps(event))),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(safety.main(), 0)
        return hook_decision(json.loads(stdout.getvalue()))

    def test_project_retrieve_does_not_require_deploy_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            for alias in ("dev-sbx", "qa-sbx"):
                with self.subTest(alias=alias):
                    decision = self._hook_decision_in_repo(
                        root,
                        f"sf project retrieve start --manifest manifest/package.xml --target-org {alias}",
                    )
                    self.assertEqual(decision, "continue")

    def test_project_retrieve_uses_normal_cli_target_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            for command in (
                "sf project retrieve start --target-org unknown-org",
                "sf project retrieve start --target-org my-prod",
                "sf project retrieve start",
                "sf project retrieve start --target-org dev-sbx --target-org qa-sbx",
            ):
                with self.subTest(command=command):
                    self.assertEqual(self._hook_decision_in_repo(root, command), "deny")

    def test_project_retrieve_without_local_config_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            self.assertEqual(self._hook_decision_in_repo(Path(name), "sf project retrieve start -o dev-sbx"), "deny")

    def test_repository_paths_containing_sf_token_are_not_salesforce_commands(self) -> None:
        # Regression (Windows pilot, 2026-07-14): the repo directory name `sf-harness-brain-core`
        # matched \bsf\b, so read/list tools passing file paths — and terminal commands citing the
        # full repository path — were denied as "wrapped Salesforce commands".
        win_meta = (
            r"c:\dev\sf-harness-brain-core\force-app\main\default\approvalProcesses"
            r"\VendorNS__CreditNote__c.KC_CreditNoteApproval_v2.approvalProcess-meta.xml"
        )
        events = (
            {"tool_name": "read_file", "tool_input": {"filePath": win_meta}},
            {"tool_name": "list_dir", "tool_input": {"path": r"c:\dev\sf-harness-brain-core\force-app"}},
            {
                "tool_name": "run_in_terminal",
                "tool_input": {
                    "command": "python c:/dev/sf-harness-brain-core/scripts/validate_harness.py"
                },
            },
            {
                "tool_name": "run_in_terminal",
                "tool_input": {"command": "grep -rn sf-harness-brain-core README.md"},
            },
        )
        for event in events:
            with self.subTest(tool=event["tool_name"], input=event["tool_input"]):
                output = run_hook("copilot_safety_hook.py", event)
                self.assertEqual(hook_decision(output), "continue")

    def test_direct_sf_commands_are_allowed_and_real_deploy_asks(self) -> None:
        for command, expected in (
            ("sf org display -o dev-sbx", "continue"),
            ("sf.exe data query --query x --target-org dev-sbx", "continue"),
            ("/usr/local/bin/sf project deploy start --target-org dev-sbx", "ask"),
            ("./sf org display --target-org dev-sbx", "deny"),
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), expected)

    def test_wrapped_salesforce_command_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {
                        "command": "bash -c 'sf data query --target-org dev-sbx --query SELECT'"
                    },
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_recursive_force_rm_is_denied_regardless_of_flag_order(self) -> None:
        for command in (
            "rm -rf output",
            "rm -fr output",
            "rm -f -r output",
            "rm --recursive --force output",
            "rm -r-f output",
            "/bin/rm -Rf output",
            'rm "-rf" output',  # quote splice: shell strips quotes -> rm -rf
            "r''m -rf output",  # quote splice in the command name
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), "deny")

    def test_windows_shell_recursive_deletions_are_denied(self) -> None:
        # W-1 (audit-2026-08-09-windows-readiness): the same destruction spelled in
        # cmd.exe or PowerShell must not slip past a hook written for bash. cmd.exe
        # is available on team Windows machines; Remove-Item is defense in depth.
        for command in (
            "rd /s /q output",
            "rmdir /S build",
            "del /f /s /q force-app",
            "cmd /c rd /s /q output",
            "Remove-Item -Recurse -Force output",
            "Remove-Item output -Recurse",
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), "deny")

    def test_windows_shell_non_recursive_deletions_are_not_over_blocked(self) -> None:
        # The carve-out mirrors the bash rule: single-file del / plain rd / a
        # -Recurse belonging to a read-only cmdlet must not trip the gate.
        for command in (
            "del stale.lock",
            "rd temp",
            "Remove-Item stale.lock",
            "Get-ChildItem -Recurse force-app",
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), "continue")

    def test_benign_rm_and_chained_flags_are_not_over_blocked(self) -> None:
        # Non-recursive rm, and a force flag that belongs to a *different* command segment,
        # must not trip the destructive gate.
        for command in ("rm -i stale.lock", "rm -f a.log && grep -r TODO src", "rm -r data"):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), "continue")

    def test_quote_and_backslash_spliced_salesforce_commands_follow_same_policy(self) -> None:
        for command, expected in (
            ("s''f project deploy start --target-org dev-sbx", "ask"),
            ('s""f org limits --target-org dev-sbx', "continue"),
            ("s\\f org delete --target-org dev-sbx", "deny"),
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {
                        "tool_name": "execute/runInTerminal",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(hook_decision(output), expected)

    def test_development_mcp_real_deploy_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "salesforce-development/deploy_metadata",
                    "tool_input": {"component": "Example__c"},
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_future_quick_deploy_mcp_uses_the_explicit_deploy_prompt(self) -> None:
        output = run_hook(
            "copilot_safety_hook.py",
            {
                "tool_name": "salesforce-development/quick_deploy",
                "tool_input": {"jobId": "0Af000000000001AAA", "targetOrg": "production"},
            },
        )
        self.assertEqual(hook_decision(output), "deny")
        self.assertIn("not an available channel", output["hookSpecificOutput"]["permissionDecisionReason"])

    def test_default_target_context_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {"command": "sf data query --query 'SELECT Id FROM Account'"},
                },
            )
            self.assertEqual(hook_decision(output), "continue")

    def test_real_deploy_confirmation_is_exact_scoped_and_stateless(self) -> None:
        command = (
            "sf project deploy start --manifest manifest/release.xml "
            "--post-destructive-changes manifest/post.xml --target-org dev-sbx"
        )
        event = {
            "tool_name": "execute/runInTerminal",
            "tool_input": {"command": command},
        }
        first = run_hook("copilot_safety_hook.py", event)
        second = run_hook("copilot_safety_hook.py", event)
        for output in (first, second):
            self.assertEqual(hook_decision(output), "ask")
            reason = output["hookSpecificOutput"]["permissionDecisionReason"]
            self.assertIn("Salesforce org dev-sbx", reason)
            self.assertIn("manifest/release.xml", reason)
            self.assertIn("manifest/post.xml", reason)
            self.assertIn("exact invocation", reason)

    def test_non_deploy_salesforce_mutations_do_not_use_deploy_confirmation(self) -> None:
        for command in (
            "sf data create record --sobject Account --values Name=Test --target-org dev-sbx",
            "sf data update record --sobject Account --record-id 001x --values Name=Changed",
            "sf data delete record --sobject Account --record-id 001x --target-org dev-sbx",
            "sf org delete scratch --target-org scratch-one --no-prompt",
            "sf package install --package 04tx --target-org dev-sbx --no-prompt",
            "sfdx force:data:record:update -s Account -i 001x -v Name=Changed -u dev-sbx",
        ):
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {"tool_name": "execute/runInTerminal", "tool_input": {"command": command}},
                )
                self.assertEqual(hook_decision(output), "continue")

    def test_legacy_sfdx_deploy_has_same_real_deploy_gate(self) -> None:
        cases = (
            ("sfdx force:source:deploy -p force-app -u dev-sbx", "ask"),
            ("sfdx force:source:deploy -p force-app -u dev-sbx --checkonly", "continue"),
            ("sfdx force:source:deploy -p force-app -u dev-sbx --checkonly=false", "ask"),
            ("sfdx force:mdapi:deploy -d mdapi -u dev-sbx", "ask"),
        )
        for command, expected in cases:
            with self.subTest(command=command):
                output = run_hook(
                    "copilot_safety_hook.py",
                    {"tool_name": "execute/runInTerminal", "tool_input": {"command": command}},
                )
                self.assertEqual(hook_decision(output), expected)

    def test_explicit_false_dry_run_value_is_still_a_real_deploy(self) -> None:
        output = run_hook(
            "copilot_safety_hook.py",
            {
                "tool_name": "execute/runInTerminal",
                "tool_input": {
                    "command": "sf project deploy start --dry-run=false --target-org dev-sbx"
                },
            },
        )
        self.assertEqual(hook_decision(output), "ask")

    def test_direct_browser_tool_is_denied_even_for_allowlisted_origin(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "playwright/browser_navigate",
                    "tool_input": {
                        "url": "https://example--dev.sandbox.my.salesforce.com/lightning/page/home"
                    },
                },
            )
            self.assertEqual(hook_decision(output), "deny")

    def test_browser_lane_removed_denies_and_never_downgrades(self) -> None:
        """Removing the guarded lane must not soften the deny: an MCP-shaped browser tool
        must be deny (not the fail-closed "ask" backstop, whose reason says "Unrecognized
        tool"), and terminal browser-automation shapes must be deny (not passthrough) —
        including leftover playwright_guard.py invocations. Sandbox URLs are deliberate so
        only the browser branch can produce the deny."""
        cases = (
            (
                "playwright/browser_navigate",
                {"url": "https://example--dev.sandbox.my.salesforce.com/lightning/page/home"},
            ),
            (
                "execute/runInTerminal",
                {"command": "playwright-cli goto https://example--dev.sandbox.my.salesforce.com"},
            ),
            (
                "execute/runInTerminal",
                {
                    "command": "python3 scripts/playwright_guard.py --session sf-harness goto "
                    "https://example--dev.sandbox.my.salesforce.com"
                },
            ),
        )
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            for tool_name, tool_input in cases:
                with self.subTest(tool=tool_name, payload=tool_input):
                    output = run_hook(
                        "copilot_safety_hook.py",
                        {"cwd": str(root), "tool_name": tool_name, "tool_input": tool_input},
                    )
                    self.assertEqual(hook_decision(output), "deny")
                    self.assertIn(
                        "Direct browser tooling is disabled",
                        output["hookSpecificOutput"].get("permissionDecisionReason", ""),
                    )

    def test_simple_browser_preview_stays_allowed(self) -> None:
        """Pins the open_simple_browser carve-out so a future widening of the browser
        name tokens cannot silently deny the render-only VS Code preview."""
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "open_simple_browser",
                    "tool_input": {"url": "https://example.com"},
                },
            )
            self.assertEqual(hook_decision(output), "continue")


class RoleGuardTests(unittest.TestCase):
    def test_terminal_has_no_role_allowlist(self) -> None:
        # Plan 05, D-T1: any command for every role, except protected shell writes and
        # chained or policy-denied Salesforce commands.
        from scripts import copilot_role_guard as role_guard

        for role in role_guard.ROLES:
            for command in ("npm run lint", "python -c 'print(1)'", "curl https://example.com",
                            "sed -i s/a/b/ force-app/main/default/classes/X.cls",
                            "python scripts/check_delivery.py --work-item work-items/1-a > out.txt",
                            "cat scripts/copilot_safety_hook.py"):
                with self.subTest(role=role, command=command):
                    self.assertEqual("continue", role_terminal(command, role))
            for command in ("echo x > scripts/copilot_safety_hook.py",
                            "sed -i '' s/a/b/ .github/hooks/safety.json",
                            "python -c \"open('config/harness.local.json','w')\"",
                            "git checkout -- scripts/git_workflow_policy.py",
                            "ls && sf project deploy start --target-org dev-sbx",
                            "sf project retrieve start --target-org dev-sbx > dump.txt"):
                with self.subTest(role=role, command=command):
                    self.assertEqual("deny", role_terminal(command, role))

    def test_roles_edit_the_repository_except_protected_files(self) -> None:
        # Plan 05, D-R2: one shared protected list replaces the per-role edit allowlists.
        from scripts import copilot_role_guard as role_guard

        free = ("force-app/main/default/classes/X.cls", "work-items/1-a/design.md",
                "work-items/1-a/qa-test-plan.md", ".ai/memory/decisions-log.md",
                ".cache/ado-items/1.json", "output/investigations/r.md", "docs/org-changes/x.md",
                "tests/test_safety_hooks.py", ".github/skills/development/SKILL.md")
        protected = (".github/hooks/safety.json", ".github/agents/developer.agent.md",
                     ".github/instructions/apex.instructions.md", ".github/mcp.json",
                     ".vscode/settings.json", "config/harness.example.json", "schemas/x.json",
                     "scripts/copilot_safety_hook.py", "scripts/git_workflow_policy.py",
                     "scripts/start_salesforce_mcp.mjs", "scripts/check_delivery.py",
                     "extensions/salesforce-operations/package.json")
        for role in role_guard.ROLES:
            for path in free:
                with self.subTest(role=role, path=path):
                    self.assertEqual("continue", hook_decision(run_hook(
                        "copilot_role_guard.py",
                        {"cwd": str(ROOT), "tool_name": "edit/editFiles", "tool_input": {"path": path}},
                        "--role", role)))
            for path in protected:
                with self.subTest(role=role, path=path):
                    expected = "ask" if role == role_guard.MAINTAINER_ROLE else "deny"
                    self.assertEqual(expected, role_guard.edit_decision(path, role))
            self.assertEqual("deny", role_guard.edit_decision("config/harness.local.json", role))

    def test_every_skill_instructed_command_passes_the_role_guard(self) -> None:
        # Regression for the live "agents flail through 5-8 denied commands" incident
        # (2026-07-14): every terminal command our own skills/agents instruct the model to run
        # must pass the role guard for the roles that run those skills.
        from scripts import copilot_role_guard as role_guard

        all_roles = (
            "designer",
            "config-investigator",
            "developer",
            "test-strategist",
            "reviewer",
        )
        matrix: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("python scripts/validate_harness.py", all_roles),
            ("python scripts/run_evals.py", all_roles),
            ("python --version", all_roles),
            ("node --version", all_roles),
        )
        for command, roles in matrix:
            for role in roles:
                with self.subTest(role=role, command=command):
                    self.assertTrue(role_terminal(command, role, ROOT) == "continue")

    def test_read_only_orientation_commands_are_allowed_for_every_role(self) -> None:
        from scripts import copilot_role_guard as role_guard

        root = ROOT
        allowed = (
            "git status",
            "git diff --stat force-app",
            "git log --oneline -5",
            "git ls-files force-app",
            "git branch -a",
            "git remote -v",
            "ls -la force-app",
            "cat README.md",
            "grep -rn Account force-app",
            "find force-app -name *.xml",
            "Get-Content README.md",
            "Get-ChildItem force-app",
        )
        for role in ("designer", "config-investigator", "reviewer"):
            for command in allowed:
                with self.subTest(role=role, command=command):
                    self.assertTrue(role_terminal(command, role, root) == "continue")

    def test_ambiguous_edit_requires_approval(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"content": "no path"},
            },
            "--role",
            "test-strategist",
        )
        self.assertEqual(hook_decision(output), "ask")

    def test_strategist_terminal_metadata_write_is_denied(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "execute/runInTerminal",
                "tool_input": {
                    "command": "sed -i '' s/a/b/ .github/agents/developer.agent.md"
                },
            },
            "--role",
            "test-strategist",
        )
        self.assertEqual(hook_decision(output), "deny")

    def test_developer_metadata_edit_is_allowed(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {
                    "path": "force-app/main/default/classes/X.cls"
                },
            },
            "--role",
            "developer",
        )
        self.assertEqual(hook_decision(output), "continue")

    def test_developer_documentation_output_is_allowed(self) -> None:
        output = run_hook(
            "copilot_role_guard.py",
            {
                "cwd": str(ROOT),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": "output/documentation/example.md"},
            },
            "--role",
            "developer",
        )
        self.assertEqual(hook_decision(output), "continue")

    def test_developer_documentation_cannot_escape_through_traversal(self) -> None:
        for path in (
            "work-items/242850-approval-notifications/../../../technical-documentation.md",
            str(ROOT.parent / "technical-documentation.md"),
        ):
            with self.subTest(path=path):
                output = run_hook(
                    "copilot_role_guard.py",
                    {
                        "cwd": str(ROOT),
                        "tool_name": "edit/editFiles",
                        "tool_input": {"path": path},
                    },
                    "--role",
                    "developer",
                )
                self.assertEqual(hook_decision(output), "deny")

    def test_developer_documentation_cannot_escape_through_symlink(self) -> None:
        from scripts import copilot_role_guard as role_guard

        with tempfile.TemporaryDirectory() as name:
            base = Path(name).resolve()
            root = base / "repo"
            work_items = root / "work-items"
            work_items.mkdir(parents=True)
            outside = base / "outside"
            outside.mkdir()
            linked_folder = work_items / "242850-approval-notifications"
            try:
                linked_folder.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlinks are unavailable on this host: {exc}")
            event = {
                "cwd": str(root),
                "tool_name": "edit/editFiles",
                "tool_input": {"path": str(linked_folder / "technical-documentation.md")},
            }
            stdout = StringIO()
            with (
                patch.object(role_guard, "HARNESS_ROOT", root),
                patch("sys.argv", ["copilot_role_guard.py", "--role", "developer"]),
                patch("sys.stdin", StringIO(json.dumps(event))),
                patch("sys.stdout", stdout),
            ):
                self.assertEqual(role_guard.main(), 0)
            self.assertEqual(hook_decision(json.loads(stdout.getvalue())), "deny")

class SafetyClassificationTests(unittest.TestCase):
    def test_salesforce_review_identity_with_empty_input_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            event = {
                "tool_name": "salesforce/review_org_identity",
                "tool_input": {},
            }
            stdout = StringIO()
            with (
                patch.object(safety, "HARNESS_ROOT", root),
                patch("sys.stdin", StringIO(json.dumps(event))),
                patch("sys.stdout", stdout),
            ):
                self.assertEqual(safety.main(), 0)
            self.assertEqual(hook_decision(json.loads(stdout.getvalue())), "continue")

    def test_salesforce_review_surface_is_exact_and_model_cannot_supply_scope(self) -> None:
        config = {
            "salesforce": {
                "orgs": [
                    {
                    }
                ],
                "review": {
                    "enabled": True,
                    "allowedObjectApiNames": ["ExampleManagedObject__c"],
                },
            }
        }
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/review_org_identity",
                {},
            )
        )
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/review_object_contract",
                {"objectApiName": "ExampleManagedObject__c"},
            )
        )
        for tool, tool_input in (
            ("salesforce/run_soql_query", {"query": "SELECT Name FROM Contact"}),
            ("salesforce/list_all_orgs", {}),
            ("salesforce/review_org_identity", {"usernameOrAlias": "other"}),
            (
                "salesforce/review_object_contract",
                {"objectApiName": "Unlisted__c"},
            ),
        ):
            with self.subTest(tool=tool):
                self.assertIsNotNone(
                    safety.salesforce_review_tool_error(config, tool, tool_input)
                )

    def test_wildcard_object_allowlist_permits_any_valid_object_but_not_malformed(self) -> None:
        config = {
            "salesforce": {
                "orgs": [{"alias": "dev-sbx", "environment": "development"}],
                "review": {
                    "enabled": True,
                    "allowedObjectApiNames": ["*"],
                },
            }
        }
        # any well-formed object is allowed under "*"
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/review_object_contract",
                {"objectApiName": "AnyCustom__c"},
            )
        )
        # a malformed object name is still rejected even with "*"
        self.assertIsNotNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/review_object_contract",
                {"objectApiName": "bad name!"},
            )
        )
        # "*" does not open raw query / org enumeration
        self.assertIsNotNone(
            safety.salesforce_review_tool_error(
                config, "salesforce/run_soql_query", {"query": "SELECT Id FROM Account"}
            )
        )

    def test_composed_soql_review_tool_accepts_query_shape_only(self) -> None:
        config = {
            "salesforce": {
                "orgs": [{"alias": "dev-sbx", "environment": "development"}],
                "review": {
                    "enabled": True,
                },
            }
        }
        # shape-valid composed queries pass the hook; statement-level SOQL validation is the
        # facade server's job (exactly one validator exists)
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/review_soql_query",
                {"query": "SELECT Id FROM Account LIMIT 5"},
            )
        )
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/review_soql_query",
                {"query": "SELECT COUNT(Id) FROM Contact", "useToolingApi": False},
            )
        )
        # absent allowedObjectApiNames means all objects for the object-contract path too
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/review_object_contract",
                {"objectApiName": "AnyCustom__c"},
            )
        )
        # Length-bound mirror: the 8-4000 bounds also live in the facade's tool schema and
        # statement validator (tests/test_salesforce_review.py pins the server side). A change
        # to either bound must land in all three places.
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config, "salesforce/review_soql_query", {"query": "SELECT a"}
            )
        )
        self.assertIsNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/review_soql_query",
                {"query": "SELECT Id FROM Account".ljust(4000)},
            )
        )
        for tool_input in (
            {},
            {"query": "SELECT"},
            {"query": "SELECT "},
            {"query": "x" * 4001},
            {"query": 42},
            {"query": "SELECT Id FROM Account", "usernameOrAlias": "other"},
            {"query": "SELECT Id FROM Account", "useToolingApi": "yes"},
        ):
            with self.subTest(tool_input=tool_input):
                self.assertIsNotNone(
                    safety.salesforce_review_tool_error(
                        config,
                        "salesforce/review_soql_query",
                        tool_input,
                    )
                )
        # the raw vendor tool stays denied even though the review tool accepts a query
        self.assertIsNotNone(
            safety.salesforce_review_tool_error(
                config,
                "salesforce/run_soql_query",
                {"query": "SELECT Id FROM Account"},
            )
        )

    def test_bare_mcp_tool_names_follow_capability_policy(self) -> None:
        cases = (
            ("core_list_orgs", {}, "deny"),
            ("core_list_projects", {}, "deny"),
            ("list_all_orgs", {}, "deny"),
            ("run_soql_query", {"query": "SELECT Id FROM Account"}, "deny"),
            ("deploy_metadata", {"sourceDir": "/etc"}, "deny"),
        )
        for name, tool_input, expected in cases:
            with self.subTest(tool=name):
                output = run_hook("copilot_safety_hook.py", {"tool_name": name, "tool_input": tool_input})
                self.assertEqual(hook_decision(output), expected)

    def test_unknown_prefixed_server_tool_is_not_a_question(self) -> None:
        # Plan 05, D-R1: an unrecognized MCP tool no longer asks; known servers keep their rules.
        output = run_hook("copilot_safety_hook.py", {"tool_name": "some_server/unknown_tool", "tool_input": {}})
        self.assertEqual(hook_decision(output), "continue")

    def test_builtin_tools_including_snake_case_pass(self) -> None:
        # VS Code built-ins are snake_case; they must not be caught by the MCP fail-closed.
        for name, tool_input in (
            ("read", {"path": "x"}),
            ("search", {"query": "foo"}),
            ("edit/editFiles", {"path": "force-app/x.cls"}),
            ("web/fetch", {"url": "https://example.com"}),
            ("vscode/askQuestions", {}),
            ("list_dir", {"path": "force-app"}),
            ("read_file", {"path": "README.md"}),
            ("grep_search", {"query": "Account"}),
            ("file_search", {"query": "*.cls"}),
            ("semantic_search", {"query": "approval"}),
            ("get_errors", {}),
            ("some_unknown_bare_tool", {}),
        ):
            with self.subTest(tool=name):
                output = run_hook("copilot_safety_hook.py", {"tool_name": name, "tool_input": tool_input})
                self.assertEqual(hook_decision(output), "continue")

    def test_snake_case_edit_and_task_tools_obey_role_boundaries(self) -> None:
        # apply_patch/create_file/run_task are VS Code snake_case tools that previously bypassed
        # the role guard's edit-path and command allowlists entirely.
        for tool, tool_input, want in (
            ("apply_patch", {"path": ".github/hooks/safety.json"}, "deny"),
            ("create_file", {"path": ".github/hooks/safety.json"}, "deny"),
            ("create_file", {"path": "output/investigations/draft.md"}, "continue"),
            ("run_task", {"command": "echo x > .github/hooks/safety.json"}, "deny"),
            ("run_task", {"command": "python scripts/validate_harness.py"}, "continue"),
        ):
            with self.subTest(tool=tool, path=tool_input):
                output = run_hook(
                    "copilot_role_guard.py",
                    {"cwd": str(ROOT), "tool_name": tool, "tool_input": tool_input},
                    "--role",
                    "config-investigator",
                )
                self.assertEqual(hook_decision(output), want)

    def test_sandbox_origin_recognition_is_strict(self) -> None:
        self.assertTrue(
            safety.is_salesforce_sandbox_origin(
                "https://acme--dev.sandbox.my.salesforce.com"
            )
        )
        self.assertTrue(
            safety.is_salesforce_sandbox_origin(
                "https://mpsadev.scratch.my.salesforce.com"
            )
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin("https://acme.my.salesforce.com")
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://acme.develop.my.salesforce.com"
            )
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://acme--dev.sandbox.my.salesforce.com/unexpected-path"
            )
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://mpsadev.scratch.my.salesforce.com:443"
            )
        )
        self.assertFalse(
            safety.is_salesforce_sandbox_origin(
                "https://mpsadev.scratch.my.salesforce.com//"
            )
        )

    def test_non_production_origin_admits_developer_edition_but_never_production(self) -> None:
        """URL mentions are checked against the wider non-production set.

        A Developer Edition is a legitimate org under the read-anywhere convention; denying
        its URL blocked reads the facade itself permits.
        """
        for origin in (
            "https://acme--dev.sandbox.my.salesforce.com",
            "https://mpsadev.scratch.my.salesforce.com",
            "https://orgfarm-x-dev-ed.develop.my.salesforce.com",
        ):
            with self.subTest(origin=origin):
                self.assertTrue(safety.is_non_production_salesforce_origin(origin))

        for origin in (
            "https://acme.my.salesforce.com",
            "https://login.salesforce.com",
            "https://orgfarm-x-dev-ed.develop.my.salesforce.com:443",
            "https://orgfarm-x-dev-ed.develop.my.salesforce.com/unexpected-path",
        ):
            with self.subTest(origin=origin):
                self.assertFalse(safety.is_non_production_salesforce_origin(origin))

    def test_multiple_target_orgs_are_detected(self) -> None:
        parts = [
            "sf",
            "data",
            "query",
            "--target-org",
            "dev-sbx",
            "--target-org=qa-sbx",
        ]
        self.assertEqual(safety.target_orgs(parts), ["dev-sbx", "qa-sbx"])

    def test_salesforce_development_paths_are_bounded_inside_single_root(self) -> None:
        for path in (
            ROOT / "sfdx-project.json",
            ROOT / "force-app/main/default/classes/X.cls",
            ROOT / "manifest/package.xml",
            ROOT / "tests/e2e/example.spec.ts",
        ):
            with self.subTest(path=path):
                self.assertTrue(safety.within_salesforce_source(str(path), ROOT))
        for path in (
            ROOT,
            ROOT / ".github/copilot-instructions.md",
            ROOT / "scripts/validate_harness.py",
            ROOT / "tests/test_safety_hooks.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(safety.within_salesforce_source(str(path), ROOT))

    def test_source_dir_array_is_included_in_path_enforcement(self) -> None:
        paths = safety.collect_filesystem_paths(
            {
                "directory": str(ROOT / "force-app"),
                "sourceDir": ["/tmp/outside.cls"],
            }
        )
        self.assertEqual(
            paths,
            [str(ROOT / "force-app"), "/tmp/outside.cls"],
        )

    def test_code_analyzer_path_arrays_are_included(self) -> None:
        paths = safety.collect_filesystem_paths(
            {
                "directory": str(ROOT / "force-app"),
                "target": ["/tmp/outside.cls"],
                "configPath": "/tmp/analyzer.yml",
                "resultsFile": "/tmp/results.html",
            }
        )
        self.assertIn("/tmp/outside.cls", paths)
        self.assertIn("/tmp/analyzer.yml", paths)
        self.assertIn("/tmp/results.html", paths)

    def test_resumed_salesforce_operation_does_not_start_a_new_deploy(self) -> None:
        self.assertFalse(
            safety.is_real_deploy_tool("salesforce-development/resume_tool_operation")
        )



def _terminal_gate_decision(output: dict[str, object]) -> tuple[str, str]:
    hook = output.get("hookSpecificOutput")
    if isinstance(hook, dict):
        return str(hook.get("permissionDecision")), str(
            hook.get("permissionDecisionReason", "")
        )
    return "continue", ""


class TerminalGateCoverageTests(unittest.TestCase):
    """Command-scoped gates must be reachable through EVERY terminal tool name form.

    The work-record approval gate this module originally pinned was deleted with its lane
    (phase 5, owner decision 2026-08-08); the tool-name coverage lesson it encoded (FIND-04:
    Copilot CLI capitalises its shell tool, so substring tokens missed it and every
    command-scoped gate was unreachable while the hook looked healthy) is preserved here
    against the destructive-command gate, which stays.
    """

    def run_hook(self, tool_name: str, command: str) -> tuple[str, str]:
        event = {"tool_name": tool_name, "tool_input": {"command": command}}
        stdout = StringIO()
        with (
            patch("sys.stdin", StringIO(json.dumps(event))),
            patch("sys.stdout", stdout),
        ):
            self.assertEqual(safety.main(), 0)
        return _terminal_gate_decision(json.loads(stdout.getvalue()))

    def test_every_terminal_tool_form_denies_destructive_commands(self) -> None:
        for tool_name in (
            "execute/runInTerminal",
            "run_in_terminal",
            "shell/execute",
            "executeCommand",
            "runTask",
            # Copilot CLI names its shell tool after the binary and sends it capitalised.
            # None of the substring tokens matches it unless folded, so every command-scoped
            # gate was unreachable in the CLI while the hook itself looked healthy (FIND-04).
            "Bash",
            "bash",
            "sh",
        ):
            with self.subTest(tool_name=tool_name):
                actual, reason = self.run_hook(tool_name, "rm -rf output")
                self.assertEqual(actual, "deny")
                self.assertIn("Destructive operation", reason)

    def test_shell_binary_names_are_matched_exactly_not_by_substring(self) -> None:
        """The short shell names must never become substring tokens.

        "sh" as a substring matches publish, push and refresh, and would push non-command
        tool inputs through the command rules. The long host tokens (terminal, execute, …)
        stay substring-matched; these do not.
        """
        for tool_name in (
            "publish",
            "push_changes",
            "refresh_token",
            "run_soql_query",
            "run_tests",
            "apply_patch",
            "view",
            "ado-readonly-wit_get_work_item",
        ):
            with self.subTest(tool_name=tool_name):
                self.assertFalse(safety.is_terminal_tool(tool_name))


class StandaloneGitIsolationTests(unittest.TestCase):
    """Exercise real hook startup; commands are payloads and are never executed."""

    ROLES = (
        "config-investigator", "test-strategist", "designer",
        "developer", "reviewer", "git-agent", "workspace-maintainer",
    )
    POLICY_FILES = (
        "copilot_role_guard.py", "copilot_safety_hook.py", "git_workflow_policy.py",
        "protected_paths_policy.py", "salesforce_operation_policy.py", "verify_salesforce_org.py",
        "ado_config.py", "ado_tool_policy.py",
    )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="sf-git-isolation-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.scripts = self.root / "scripts"
        self.scripts.mkdir()
        self.cwd = self.root / "nested" / "directory"
        self.cwd.mkdir(parents=True)
        for filename in self.POLICY_FILES:
            shutil.copy2(ROOT / "scripts" / filename, self.scripts / filename)

    def invoke(self, event: dict[str, Any], role: str | None = None) -> dict[str, Any]:
        script = "copilot_role_guard.py" if role else "copilot_safety_hook.py"
        args = ["--role", role] if role else []
        bootstrap = (
            "import pathlib,runpy,sys; sys.argv=sys.argv[1:]; "
            "sys.path.insert(0,str(pathlib.Path(sys.argv[0]).parent)); "
            "runpy.run_path(sys.argv[0],run_name='__main__')"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", bootstrap, str(self.scripts / script), *args],
            input=json.dumps({"cwd": str(self.cwd), **event}),
            cwd=self.cwd, text=True, capture_output=True, timeout=10, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(result.stderr, result.stderr)
        return json.loads(result.stdout)

    def assert_decision(self, event: dict[str, Any], expected: str,
                        role: str | None = None) -> None:
        output = self.invoke(event, role)
        self.assertEqual(expected, hook_decision(output), output)

    @staticmethod
    def terminal(command: str) -> dict[str, Any]:
        return {"tool_name": "run_in_terminal", "tool_input": {"command": command}}

    def test_every_role_and_global_hook_allow_git_without_repository_preconditions(self) -> None:
        commands = (
            "git add -A",
            'git commit -m "[chore] Save all changes"',
            'git commit -m "[WI-42] Save changes AB#42"',
            'git commit -m "[FEATURE-9] Update delivery AB#9"',
            "git switch -c arbitrary/branch",
            "git -C ../another-repo checkout main",
            "git clean -fdx",
            "git pull --rebase",
            "git stash pop",
            "git log --output=history.txt",
            'git commit -m "Save changes"',
            'git add . && git commit -m "[docs] Explain sf deploy and git reset --hard"',
            "gh pr view 5 --repo owner/other-repo",
        )
        for role in (None, *self.ROLES):
            for command in commands:
                with self.subTest(role=role, command=command):
                    self.assert_decision(self.terminal(command), "continue", role)

    def test_every_role_and_global_hook_deny_publication_reserved_for_a_person(self) -> None:
        # Plan 05, boundaries B1 and B2, through real hook startup.
        for role in (None, *self.ROLES):
            for command in ("git reset --hard", "git push --force-with-lease origin main",
                            "git push origin --delete arbitrary/branch",
                            "gh api repos/owner/other-repo/issues --method POST",
                            "gh pr merge 5 --squash --admin --repo owner/other-repo"):
                with self.subTest(role=role, command=command):
                    self.assert_decision(self.terminal(command), "deny", role)

    def test_git_command_does_not_admit_unrelated_destructive_or_role_restricted_commands(self) -> None:
        self.assert_decision(self.terminal("git status && rm -rf output"), "deny")
        self.assert_decision(
            {"cwd": str(self.root), **self.terminal("git status && echo x > scripts/copilot_role_guard.py")},
            "deny", "reviewer",
        )

    def test_missing_or_broken_external_modules_do_not_block_git_or_local_reads(self) -> None:
        events = (
            self.terminal("git status"),
            self.terminal('git commit -m "[docs] Save local notes"'),
            self.terminal("gh pr view 3"),
            {"tool_name": "read_file", "tool_input": {"path": "README.md"}},
            {"cwd": str(self.root), **self.terminal("cat README.md")},
        )
        for filename in ("salesforce_operation_policy.py", "ado_config.py", "ado_tool_policy.py"):
            path = self.scripts / filename
            for failure in ("missing", "syntax-error"):
                with self.subTest(module=filename, failure=failure):
                    if failure == "missing":
                        path.unlink()
                    else:
                        path.write_text("def invalid syntax(:\n", encoding="utf-8")
                    for role in (None, "developer", "reviewer"):
                        for event in events:
                            self.assert_decision(event, "continue", role)
                    shutil.copy2(ROOT / "scripts" / filename, path)

    def test_unreadable_or_invalid_external_configuration_does_not_block_local_work(self) -> None:
        config = self.root / "config" / "harness.local.json"
        config.parent.mkdir()
        for contents in (b"\xff\xfe\x00", b"{ malformed json"):
            config.write_bytes(contents)
            for role in (None, "developer", "reviewer"):
                with self.subTest(config=contents, role=role):
                    self.assert_decision(self.terminal("git status"), "continue", role)
                    self.assert_decision(
                        {"tool_name": "read_file", "tool_input": {"path": "README.md"}},
                        "continue", role,
                    )
        config.unlink()
        config.mkdir()  # Also exercise an actual read error, not only a parse error.
        for role in (None, "developer", "reviewer"):
            self.assert_decision(self.terminal("git status"), "continue", role)
            self.assert_decision({"cwd": str(self.root), **self.terminal("cat README.md")}, "continue", role)

    def test_external_operations_still_deny_when_their_policy_cannot_load(self) -> None:
        cases = (
            ("salesforce_operation_policy.py", {"cwd": str(self.root),
                                                 **self.terminal("sf org display -o dev-sbx")}),
            ("ado_tool_policy.py", {"tool_name": "ado-readonly/wit_get_work_item",
                                    "tool_input": {"project": "Example", "id": 42}}),
            ("ado_config.py", {"tool_name": "ado-readonly/wit_get_work_item",
                              "tool_input": {"project": "Example", "id": 42}}),
        )
        for filename, event in cases:
            path = self.scripts / filename
            path.unlink()
            roles = (None,) if filename == "ado_config.py" else (None, "developer")
            for role in roles:
                with self.subTest(module=filename, role=role):
                    output = self.invoke(event, role)
                    self.assertEqual("deny", hook_decision(output), output)
                    self.assertIn(Path(filename).stem, output["hookSpecificOutput"]["permissionDecisionReason"])
            shutil.copy2(ROOT / "scripts" / filename, path)


class WorkspaceMaintainerTests(unittest.TestCase):
    """Protected control files + workspace-maintainer (plan 05, D-R2).

    Every role edits the repository except the protected control files. Other roles are denied
    those files; the maintainer gets a question for each. Local config and paths outside the
    repository are denied to every role.
    """

    ROOT_OF_TRUST = (
        ".githooks/commit-msg",
        "scripts/copilot_role_guard.py",
        "scripts/check_delivery.py",
        "scripts/git_workflow_policy.py",
        ".github/instructions/apex.instructions.md",
        "schemas/output-envelope.schema.json",
        "config/repo-map-seed.json",
        "scripts/copilot_safety_hook.py",
        "scripts/ado_config.py",
        "scripts/start_ado_mcp.mjs",
        ".github/hooks/safety.json",
        ".github/agents/developer.agent.md",
        ".github/agents/new-role.agent.md",  # creating an agent is as sensitive as editing one
        ".github/mcp.json",
        ".vscode/mcp.json",
        ".vscode/settings.json",
        "config/harness.example.json",
        "config/harness.json",
        "sf-harness.code-workspace",
    )

    def decide(self, role: str, tool_input: dict[str, Any]) -> str:
        output = run_hook(
            "copilot_role_guard.py",
            {"cwd": str(ROOT), "tool_name": "edit/editFiles", "tool_input": tool_input},
            "--role",
            role,
        )
        return hook_decision(output)

    def test_maintainer_edits_standard_control_plane(self) -> None:
        for path in (
            ".github/prompts/adhoc-fix.prompt.md",
            ".github/skills/maintain-workspace/SKILL.md",
            ".github/pull_request_template.md",
            "docs/ways-of-working.md",
            "evals/agent-scenarios.yaml",
            "tests/test_safety_hooks.py",
            "scripts/render_repo_map.py",
            ".ai/contracts/tool-capabilities.md",
            ".ai/repo-map.md",
            "README.md",
            "package.json",
        ):
            with self.subTest(path=path):
                self.assertEqual("continue", self.decide("workspace-maintainer", {"path": path}))

    def test_maintainer_asks_for_every_root_of_trust_representative(self) -> None:
        for path in self.ROOT_OF_TRUST:
            with self.subTest(path=path):
                self.assertEqual("ask", self.decide("workspace-maintainer", {"path": path}))

    def test_maintainer_edits_delivery_paths_and_only_local_config_is_denied(self) -> None:
        # Plan 05, D-R2: no per-role allowlist; only local config and outside paths are denied.
        for path in (
            "force-app/main/default/classes/X.cls",
            "manifest/package.xml",
            "work-items/242850-approval-notifications/design.md",
            ".ai/memory/decisions-log.md",
            ".cache/ado-items/1201.json",
            "output/feature-health/report.md",
        ):
            with self.subTest(path=path):
                self.assertEqual("continue", self.decide("workspace-maintainer", {"path": path}))
        for path in ("config/harness.local.json", "/etc/hosts", "../outside.md"):
            with self.subTest(path=path):
                self.assertEqual("deny", self.decide("workspace-maintainer", {"path": path}))

    def test_mixed_standard_and_root_of_trust_returns_one_ask(self) -> None:
        decision = self.decide(
            "workspace-maintainer",
            {"paths": [".github/prompts/adhoc-fix.prompt.md", ".vscode/mcp.json"]},
        )
        self.assertEqual("ask", decision)

    def test_mixed_permitted_and_denied_returns_deny(self) -> None:
        # A denied path fails the whole multi-file operation — no partial allowance, and
        # deny wins even when another path in the same call would merely ask.
        decision = self.decide(
            "workspace-maintainer",
            {
                "paths": [
                    ".github/prompts/adhoc-fix.prompt.md",
                    ".vscode/mcp.json",
                    "config/harness.local.json",
                ]
            },
        )
        self.assertEqual("deny", decision)

    def test_absolute_and_case_variant_paths_cannot_bypass(self) -> None:
        self.assertEqual(
            "ask",
            self.decide(
                "workspace-maintainer", {"path": str(ROOT / "scripts/copilot_role_guard.py")}
            ),
        )
        self.assertEqual(
            "ask", self.decide("workspace-maintainer", {"path": "SCRIPTS/COPILOT_ROLE_GUARD.PY"})
        )
        self.assertEqual(
            "deny", self.decide("workspace-maintainer", {"path": "Config/Harness.Local.JSON"})
        )
        self.assertEqual(
            "ask",
            self.decide(
                "workspace-maintainer",
                {"path": ".github/prompts/../../force-app/../.github/hooks/safety.json"},
            ),
        )

    def test_second_root_of_trust_edit_still_asks(self) -> None:
        # The guard is stateless by design: a confirmed root-of-trust edit never unlocks the
        # next one. Simulate the first edit having happened; the guard must ask again.
        first = self.decide("workspace-maintainer", {"path": ".vscode/mcp.json"})
        second = self.decide("workspace-maintainer", {"path": "scripts/copilot_safety_hook.py"})
        self.assertEqual(("ask", "ask"), (first, second))

    def test_no_other_role_writes_protected_control_files(self) -> None:
        # Plan 05, D-R2: every other role edits the repository freely except protected files.
        for role in ("designer", "developer", "test-strategist", "reviewer",
                     "config-investigator", "git-agent"):
            for path in self.ROOT_OF_TRUST:
                with self.subTest(role=role, path=path):
                    self.assertEqual("deny", self.decide(role, {"path": path}))
            for path in ("scripts/render_repo_map.py", ".github/skills/maintain-workspace/SKILL.md",
                         "force-app/main/default/classes/X.cls", "work-items/1-a/design.md"):
                with self.subTest(role=role, path=path):
                    self.assertEqual("continue", self.decide(role, {"path": path}))

class DeployValidationWrapperTests(unittest.TestCase):
    """Phase 2 boundary (2026-08-17): the guarded wrapper is the only deploy-shaped
    surface, Developer-only, and no raw deploy path opens anywhere — including raw
    commands that themselves carry --dry-run."""

    START = (
        "python scripts/validate_salesforce_deploy.py start "
        "--source-dir force-app/main/default/classes --test WidgetServiceTest"
    )
    STATUS = (
        "python scripts/validate_salesforce_deploy.py status "
        "--job-id 0Af000000000001AAA --org dev-sbx"
    )

    def test_safety_hook_asks_only_for_commands_that_start_real_deploys(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            for command, expected in (
                ("sf project deploy start --dry-run --async --target-org dev-sbx --json", "continue"),
                ("sf project deploy start --target-org dev-sbx", "ask"),
                ("sf project deploy validate --target-org dev-sbx", "continue"),
                ("sf project deploy quick --job-id 0Af000000000001AAA --target-org dev-sbx", "ask"),
                ("sf project deploy cancel --job-id 0Af000000000001AAA --target-org dev-sbx", "continue"),
                ("sf project deploy resume --job-id 0Af000000000001AAA --target-org dev-sbx", "continue"),
                ("sf project deploy report --use-most-recent --target-org dev-sbx", "deny"),
                ("sf project deploy report --job-id 0Af000000000001AAA --target-org dev-sbx", "continue"),
            ):
                with self.subTest(command=command):
                    output = run_hook(
                        "copilot_safety_hook.py",
                        {
                            "cwd": str(root),
                            "tool_name": "execute/runInTerminal",
                            "tool_input": {"command": command},
                        },
                    )
                    self.assertEqual(hook_decision(output), expected)

    def test_wrapper_command_passes_the_global_safety_hook(self) -> None:
        # The hook must not misread the wrapper as a wrapped raw `sf` command; the
        # role guard (not the hook) is what narrows it to the Developer.
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_local_config(root)
            output = run_hook(
                "copilot_safety_hook.py",
                {
                    "cwd": str(root),
                    "tool_name": "execute/runInTerminal",
                    "tool_input": {"command": self.START},
                },
            )
            self.assertEqual(hook_decision(output), "continue")


if __name__ == "__main__":
    unittest.main()


class GlobalProtectedFilesTests(unittest.TestCase):
    """Plan 05 phase 0: Copilot CLI ignores frontmatter hooks, so the global safety hook enforces
    the shared protected-file list for every agent (editor tools, apply_patch text, shell)."""

    def decide(self, tool_name: str, tool_input: Any) -> str:
        return hook_decision(run_hook("copilot_safety_hook.py", {"cwd": str(ROOT), "tool_name": tool_name, "tool_input": tool_input}))

    def test_editor_and_patch_edits_of_protected_files_need_a_person(self) -> None:
        for tool, tool_input in (
            ("edit", {"path": "scripts/copilot_role_guard.py"}),
            ("create", {"path": ".github/agents/new.agent.md"}),
            ("Edit", "*** Begin Patch\n*** Add File: schemas/probe.json\n+{}\n*** End Patch\n"),
            ("apply_patch", "*** Begin Patch\n*** Update File: force-app/a.cls\n*** Move to: config/x.json\n*** End Patch\n"),
        ):
            with self.subTest(tool=tool, tool_input=tool_input):
                self.assertEqual("ask", self.decide(tool, tool_input))

    def test_local_config_and_outside_paths_are_denied_and_delivery_paths_pass(self) -> None:
        self.assertEqual("deny", self.decide("create", {"path": "config/harness.local.json"}))
        self.assertEqual("deny", self.decide("edit", {"path": "/etc/hosts"}))
        self.assertEqual("deny", self.decide("apply_patch", "*** Begin Patch\n*** Update File: config/harness.local.json\n*** End Patch\n"))
        for tool, tool_input in (("create", {"path": "force-app/main/default/classes/X.cls"}),
                                 ("apply_patch", "*** Begin Patch\n*** Add File: work-items/1-a/requirements.md\n+x\n*** End Patch\n")):
            with self.subTest(tool=tool):
                self.assertEqual("continue", self.decide(tool, tool_input))

    def test_shell_writes_to_protected_files_are_denied_for_every_agent(self) -> None:
        self.assertEqual("deny", self.decide("Bash", {"command": "printf probe > config/spike-probe.txt"}))
        self.assertEqual("deny", self.decide("Bash", {"command": "git checkout -- scripts/git_workflow_policy.py"}))
        self.assertEqual("continue", self.decide("Bash", {"command": "cat scripts/copilot_safety_hook.py"}))


class LiveTrialFixesTests(unittest.TestCase):
    """Fixes from the first live conductor run (plan 05, 2026-11-16)."""

    def decide(self, tool_name: str, tool_input: Any, cwd: Path = ROOT) -> str:
        return hook_decision(run_hook("copilot_safety_hook.py", {"cwd": str(cwd), "tool_name": tool_name, "tool_input": tool_input}))

    def test_delivery_report_is_never_written_by_an_agent(self) -> None:
        self.assertEqual("deny", self.decide("create", {"path": "work-items/1201-routing/delivery-check.json"}))
        self.assertEqual("deny", self.decide("Bash", {"command": "echo {} > work-items/1201-routing/delivery-check.json"}))
        self.assertEqual("continue", self.decide("Bash", {"command": "cat work-items/1201-routing/delivery-check.json"}))

    def test_leading_cd_to_the_repository_root_is_not_a_compound_command(self) -> None:
        from scripts import protected_paths_policy as protected

        self.assertEqual("sf org list --json", protected.strip_root_cd(f"cd {ROOT} && sf org list --json", ROOT))
        self.assertEqual("sf org list", protected.strip_root_cd(f'cd "{ROOT}" && sf org list', ROOT))
        self.assertEqual("cd /tmp && sf org list", protected.strip_root_cd("cd /tmp && sf org list", ROOT))
        reason = run_hook("copilot_safety_hook.py", {"cwd": str(ROOT), "tool_name": "Bash",
                                                    "tool_input": {"command": "cd /tmp && sf org list"}})
        self.assertEqual("deny", hook_decision(reason))


class SubagentGateTests(unittest.TestCase):
    def test_only_station_agents_start_as_sub_agents(self) -> None:
        for agent_type, expected in (("reviewer", "continue"), ("developer", "continue"), ("git-agent", "continue"),
                                     ("task", "deny"), ("general-purpose", "deny"), ("explore", "deny"),
                                     ("workspace-maintainer", "deny"), ("sdlc-conductor", "deny"), ("", "deny")):
            with self.subTest(agent_type=agent_type):
                output = run_hook("copilot_safety_hook.py", {"cwd": str(ROOT), "tool_name": "task",
                                                             "tool_input": {"agent_type": agent_type, "prompt": "x"}})
                self.assertEqual(expected, hook_decision(output))
